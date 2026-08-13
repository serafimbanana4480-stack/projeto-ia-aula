"""Persistent store for MCP connector configurations.

Mirrors the pattern used by ``backend/core/skills_store.py``: a JSON-backed
singleton store under ``data/``. Connectors are the user's configured MCP
server instances (built from a template in ``backend/mcp/templates.py`` or a
fully custom command). Secrets (API keys, tokens) are persisted to disk but
masked whenever the connector is serialized for the API/frontend.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import httpx

from backend.mcp.templates import get_template

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
MCP_STORE_FILE = DATA_DIR / "mcp_connectors.json"

_SECRET_MASK = "••••••••"


def _looks_secret(key: str) -> bool:
    lowered = key.lower()
    return any(token in lowered for token in ("token", "key", "secret", "password", "connection_string", "auth"))


@dataclass
class MCPConnector:
    """A single configured MCP server connection."""

    id: str
    name: str
    template_id: str
    description: str = ""
    transport: str = "stdio"
    command: str = ""
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    url: str = ""
    enabled: bool = True
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    last_test_status: str = "untested"  # untested | ok | warning | error
    last_test_detail: str = ""
    last_tested_at: float | None = None
    tools: list[dict[str, Any]] = field(default_factory=list)
    calls_today: int = 0
    success_rate: float | None = None
    latency_ms: float | None = None
    last_activity_tool: str = ""
    last_activity_at: float | None = None
    source_root: str = ""

    def to_public_dict(self) -> dict[str, Any]:
        """Serialize with secrets masked — safe to send to the frontend."""
        d = asdict(self)
        d["env"] = {k: (_SECRET_MASK if _looks_secret(k) and v else v) for k, v in self.env.items()}
        if self.url and any(_looks_secret(k) for k in ("url",)):
            pass  # URLs themselves aren't treated as secret
        d["tool_count"] = len(self.tools)
        d["health_score"] = self._health_score()
        d["index_stats"] = self._index_stats()
        return d

    def _health_score(self) -> int | None:
        if self.last_test_status == "error":
            return 0
        if self.last_test_status == "warning":
            return 60
        if self.last_test_status == "ok":
            return 100
        return None

    def _index_stats(self) -> dict[str, int] | None:
        if self.template_id != "projectmind" or not self.source_root:
            return None
        database = Path(self.source_root) / ".projectmind" / "projectmind.db"
        if not database.exists():
            return None
        tables = ("files", "nodes", "edges", "memories", "plans", "telemetry_events")
        try:
            with sqlite3.connect(database) as connection:
                return {table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]) for table in tables}
        except (OSError, sqlite3.Error):
            return None


class MCPConnectorStore:
    """Persistent, singleton store for MCP connectors."""

    _instance: MCPConnectorStore | None = None

    def __init__(self) -> None:
        self._connectors: dict[str, MCPConnector] = {}
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._load()

    @classmethod
    def get_instance(cls) -> MCPConnectorStore:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ── Persistence ──────────────────────────────────────────────────

    def _load(self) -> None:
        if not MCP_STORE_FILE.exists():
            return
        try:
            raw = json.loads(MCP_STORE_FILE.read_text(encoding="utf-8"))
            for item in raw.get("connectors", []):
                connector = MCPConnector(**item)
                self._connectors[connector.id] = connector
        except Exception:
            logger.exception("Failed to load MCP connector store from %s", MCP_STORE_FILE)

    def _save(self) -> None:
        try:
            payload = {"connectors": [asdict(c) for c in self._connectors.values()]}
            MCP_STORE_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception:
            logger.exception("Failed to persist MCP connector store to %s", MCP_STORE_FILE)

    # ── CRUD ─────────────────────────────────────────────────────────

    def list_connectors(self) -> list[dict[str, Any]]:
        return [c.to_public_dict() for c in sorted(self._connectors.values(), key=lambda c: c.created_at)]

    def get_connector(self, connector_id: str) -> MCPConnector | None:
        return self._connectors.get(connector_id)

    def create_connector(
        self,
        name: str,
        template_id: str,
        params: dict[str, str] | None = None,
        env_values: dict[str, str] | None = None,
    ) -> MCPConnector:
        params = params or {}
        env_values = env_values or {}
        template = get_template(template_id)
        if template is None:
            raise ValueError(f"Unknown MCP template: {template_id!r}")

        command = template.get("command", "")
        args = list(template.get("args", []))
        transport = template.get("transport", "stdio")
        url = ""

        if template_id == "custom":
            command = params.get("command", command)
            extra_args = params.get("args", "")
            args = extra_args.split() if isinstance(extra_args, str) else list(extra_args)
        elif template_id == "http-remote":
            url = params.get("url", "")
        elif template_id == "projectmind":
            root_path = params.get("root_path", "")
            command = self._projectmind_python(root_path)
            args = [a.format(root_path=root_path) if "{" in a else a for a in args]
        else:
            # Substitute {placeholder} tokens in args with user-supplied params
            args = [a.format(**params) if "{" in a else a for a in args]

        connector = MCPConnector(
            id=f"mcp_{uuid.uuid4().hex[:12]}",
            name=name or template.get("name", template_id),
            template_id=template_id,
            description=template.get("description", ""),
            transport=transport,
            command=command,
            args=args,
            env={e["key"]: env_values.get(e["key"], "") for e in template.get("env", [])} | {
                k: v for k, v in env_values.items() if k not in {e["key"] for e in template.get("env", [])}
            },
            url=url,
            source_root=params.get("root_path", "") if template_id in {"filesystem", "serena", "projectmind"} else "",
        )
        connector.tools = self._discover_tools(connector)
        self._connectors[connector.id] = connector
        self._save()
        logger.info("Created MCP connector %s (%s)", connector.id, connector.name)
        return connector

    def update_connector(self, connector_id: str, **fields: Any) -> MCPConnector | None:
        connector = self._connectors.get(connector_id)
        if not connector:
            return None
        for key, value in fields.items():
            if hasattr(connector, key) and value is not None:
                setattr(connector, key, value)
        connector.updated_at = time.time()
        self._save()
        return connector

    def delete_connector(self, connector_id: str) -> bool:
        if connector_id in self._connectors:
            del self._connectors[connector_id]
            self._save()
            return True
        return False

    # ── Health / test ────────────────────────────────────────────────

    async def test_connector(self, connector_id: str) -> dict[str, Any]:
        """Best-effort validation without fully starting the MCP session.

        For stdio servers we check the executable resolves on PATH and that
        required env vars are populated. For http servers we issue a quick
        GET. This intentionally does not spin up a full MCP handshake (slow,
        and many servers `npx`-install on first run) — it's a fast sanity
        check the wizard can run on every keystroke of the form.
        """
        connector = self._connectors.get(connector_id)
        if not connector:
            return {"status": "error", "detail": "Connector not found"}

        template = get_template(connector.template_id) or {}
        missing_env = [
            e["key"]
            for e in template.get("env", [])
            if e.get("required") and not connector.env.get(e["key"])
        ]
        if missing_env:
            result = {"status": "error", "detail": f"Variáveis em falta: {', '.join(missing_env)}"}
            self._record_test_result(connector, result)
            return result

        if connector.transport == "http":
            if not connector.url:
                result = {"status": "error", "detail": "URL do servidor não definida"}
                self._record_test_result(connector, result)
                return result
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    resp = await client.get(connector.url)
                result = {
                    "status": "ok" if resp.status_code < 500 else "warning",
                    "detail": f"HTTP {resp.status_code}",
                }
            except Exception as exc:
                result = {"status": "error", "detail": f"Inalcançável: {exc}"}
            self._record_test_result(connector, result)
            return result

        # stdio transport
        if connector.template_id == "projectmind":
            result = await self._probe_with_runtime(connector)
            self._record_test_result(connector, result)
            return result
        if not connector.command:
            result = {"status": "error", "detail": "Comando não definido"}
        elif shutil.which(connector.command) is None:
            result = {
                "status": "warning",
                "detail": f"Executável '{connector.command}' não encontrado no PATH do servidor. "
                "Vai ser instalado/resolvido no primeiro arranque (normal para npx/uvx).",
            }
        else:
            result = await self._probe_with_runtime(connector)

        self._record_test_result(connector, result)
        return result

    async def _probe_with_runtime(self, connector: MCPConnector) -> dict[str, Any]:
        """Run the same real MCP handshake used by agent calls."""
        try:
            from backend.mcp.runtime import list_connector_tools

            started = time.perf_counter()
            tools = await list_connector_tools(connector, timeout=35)
            return {
                "status": "ok",
                "detail": f"MCP handshake OK · {len(tools)} tools descobertas",
                "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                "tools": tools,
            }
        except Exception as exc:
            return {"status": "error", "detail": f"Handshake falhou: {str(exc)[:240]}"}

    @staticmethod
    def _probe_projectmind(connector: MCPConnector) -> dict[str, Any]:
        """Perform a real initialize + tools/list probe for the local server."""
        probe = (
            "import asyncio, json, sys\n"
            "from mcp import ClientSession, StdioServerParameters\n"
            "from mcp.client.stdio import stdio_client\n"
            "async def main():\n"
            "    p = StdioServerParameters(command=sys.argv[1], args=json.loads(sys.argv[2]))\n"
            "    async with stdio_client(p) as rw:\n"
            "        async with ClientSession(*rw) as s:\n"
            "            await s.initialize()\n"
            "            r = await s.list_tools()\n"
            "            print('MCP_HANDSHAKE_OK', len(r.tools))\n"
            "asyncio.run(main())"
        )
        started = time.perf_counter()
        try:
            completed = subprocess.run(
                [connector.command, "-c", probe, connector.command, json.dumps(connector.args)],
                capture_output=True,
                text=True,
                timeout=35,
                cwd=connector.source_root or None,
                check=False,
            )
            elapsed = round((time.perf_counter() - started) * 1000, 1)
            if completed.returncode == 0 and "MCP_HANDSHAKE_OK" in completed.stdout:
                count = completed.stdout.split("MCP_HANDSHAKE_OK", 1)[1].strip().split()[0]
                return {"status": "ok", "detail": f"MCP handshake OK · {count} tools descobertas", "latency_ms": elapsed}
            detail = (completed.stderr or completed.stdout or "Falha no handshake MCP").strip().splitlines()[-1]
            return {"status": "error", "detail": f"Handshake falhou: {detail[:240]}", "latency_ms": elapsed}
        except subprocess.TimeoutExpired:
            return {"status": "error", "detail": "Timeout durante o handshake MCP (35s)", "latency_ms": 35000}
        except OSError as exc:
            return {"status": "error", "detail": f"Não foi possível iniciar o ProjectMind: {exc}", "latency_ms": None}

    @staticmethod
    def _projectmind_python(root_path: str) -> str:
        """Resolve the interpreter from the user-owned ProjectMind checkout."""
        root = Path(root_path).expanduser() if root_path else Path()
        candidates = [
            root / ".venv" / "Scripts" / "python.exe",
            root / ".venv" / "bin" / "python",
            root / "_audit" / "venv312" / "Scripts" / "python.exe",
        ]
        for candidate in candidates:
            if candidate.exists():
                return str(candidate)
        return sys.executable

    @staticmethod
    def _discover_tools(connector: MCPConnector) -> list[dict[str, Any]]:
        """Discover local ProjectMind tools from its registered source symbols.

        This is deliberately read-only. Other MCPs are left with no fabricated
        tool list until a real MCP session is available.
        """
        if connector.template_id != "projectmind" or not connector.source_root:
            return []
        server_file = Path(connector.source_root) / "src" / "projectmind" / "server.py"
        if not server_file.exists():
            return []
        try:
            source = server_file.read_text(encoding="utf-8")
        except OSError:
            return []
        pattern = re.compile(
            r'@tracked_tool\(title="(?P<title>[^"]+)"[^\n]*\)\s+def (?P<name>[A-Za-z0-9_]+)\(',
            re.MULTILINE,
        )
        return [
            {"name": match.group("name"), "title": match.group("title"), "calls": 0, "success_rate": None}
            for match in pattern.finditer(source)
        ]

    def _record_test_result(self, connector: MCPConnector, result: dict[str, Any]) -> None:
        connector.last_test_status = result["status"]
        connector.last_test_detail = result["detail"]
        connector.last_tested_at = time.time()
        if result.get("latency_ms") is not None:
            connector.latency_ms = float(result["latency_ms"])
        discovered = result.get("tools")
        if isinstance(discovered, list):
            previous = {str(item.get("name")): item for item in connector.tools}
            connector.tools = [
                {
                    "name": item.get("name", ""),
                    "title": item.get("title", ""),
                    "description": item.get("description", ""),
                    "inputSchema": item.get("inputSchema", {}),
                    "calls": int(previous.get(str(item.get("name")), {}).get("calls") or 0),
                    "successes": int(previous.get(str(item.get("name")), {}).get("successes") or 0),
                    "success_rate": previous.get(str(item.get("name")), {}).get("success_rate"),
                }
                for item in discovered
                if isinstance(item, dict) and item.get("name")
            ]
        connector.tools = self._discover_tools(connector) or connector.tools
        self._save()

    def record_tool_call(
        self, connector_id: str, tool_name: str, latency_ms: float, *, success: bool
    ) -> None:
        """Persist evidence from a real MCP tool invocation."""
        connector = self._connectors.get(connector_id)
        if connector is None:
            return
        connector.calls_today += 1
        connector.last_activity_tool = tool_name
        connector.last_activity_at = time.time()
        connector.latency_ms = round(float(latency_ms), 1)
        for tool in connector.tools:
            if tool.get("name") != tool_name:
                continue
            calls = int(tool.get("calls") or 0) + 1
            successes = int(tool.get("successes") or 0) + (1 if success else 0)
            tool["calls"] = calls
            tool["successes"] = successes
            tool["success_rate"] = round(successes / calls * 100, 1)
            break
        connector.last_test_status = "ok" if success else "warning"
        connector.last_test_detail = f"Tool MCP {'executada' if success else 'falhou'}: {tool_name}"
        self._save()

    # ── Export ───────────────────────────────────────────────────────

    def export_connector(self, connector_id: str) -> dict[str, Any] | None:
        """Export one connector as an ``mcpServers`` config block."""
        connector = self._connectors.get(connector_id)
        if not connector:
            return None
        return {"mcpServers": {connector.name: self._to_mcp_json_entry(connector)}}

    def export_all(self, only_enabled: bool = True) -> dict[str, Any]:
        """Export every connector as a single ``mcpServers`` config block,
        ready to paste into a `claude_desktop_config.json`-style file."""
        entries = {
            c.name: self._to_mcp_json_entry(c)
            for c in self._connectors.values()
            if (c.enabled or not only_enabled)
        }
        return {"mcpServers": entries}

    @staticmethod
    def _to_mcp_json_entry(connector: MCPConnector) -> dict[str, Any]:
        if connector.transport == "http":
            entry: dict[str, Any] = {"url": connector.url}
        else:
            entry = {"command": connector.command, "args": connector.args}
        if connector.env:
            entry["env"] = connector.env
        return entry

    def health(self) -> dict[str, Any]:
        connectors = list(self._connectors.values())
        latencies = [c.latency_ms for c in connectors if c.latency_ms is not None]
        return {
            "total": len(connectors),
            "enabled": sum(1 for c in connectors if c.enabled),
            "healthy": sum(1 for c in connectors if c.last_test_status == "ok"),
            "warning": sum(1 for c in connectors if c.last_test_status == "warning"),
            "error": sum(1 for c in connectors if c.last_test_status == "error"),
            "untested": sum(1 for c in connectors if c.last_test_status == "untested"),
            "calls_today": sum(c.calls_today for c in connectors),
            "avg_latency_ms": round(sum(latencies) / len(latencies), 1) if latencies else None,
            "last_health_check": max((c.last_tested_at or 0 for c in connectors), default=0) or None,
        }


# Singleton instance, following the SkillsStore convention.
mcp_store = MCPConnectorStore.get_instance()
