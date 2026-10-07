"""Persistent store for MCP connector configurations.

Mirrors the pattern used by ``backend/core/skills_store.py``: a JSON-backed
singleton store under ``data/``. Connectors are the user's configured MCP
server instances (built from a template in ``backend/mcp/templates.py`` or a
fully custom command). Secrets (API keys, tokens) are persisted to disk but
masked whenever the connector is serialized for the API/frontend.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
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
MCP_ACTIVITY_FILE = DATA_DIR / "mcp_activity.jsonl"
_MAX_ACTIVITY_MEMORY = 500

_SECRET_MASK = "••••••••"
_SECRET_CIPHERTEXT_PREFIX = "nexus-fernet:v1:"


def _secret_cipher():
    """Build an at-rest cipher from the configured local NEXUS secret."""
    try:
        from cryptography.fernet import Fernet

        from backend.config.settings import get_settings

        settings = get_settings()
        material = (
            os.environ.get("NEXUS_MCP_ENCRYPTION_KEY")
            or getattr(settings, "secret_key", "")
        ).strip()
        # This public development fallback is unsuitable as an at-rest key:
        # using it would make every installation with default configuration
        # decrypt the same connector credentials.
        if not material or material == "development-secret-key-change-in-production":
            return None
        key = base64.urlsafe_b64encode(hashlib.sha256(b"nexus-mcp-store-v1:" + material.encode()).digest())
        return Fernet(key)
    except Exception:  # pragma: no cover - handled as an unavailable secure store
        logger.exception("MCP credential encryption is unavailable")
        return None


def _encrypt_secret(value: str) -> str:
    cipher = _secret_cipher()
    if cipher is None:
        raise RuntimeError("Não foi possível proteger credenciais MCP no disco")
    return _SECRET_CIPHERTEXT_PREFIX + cipher.encrypt(value.encode("utf-8")).decode("ascii")


def _decrypt_secret(value: str) -> str:
    if not value.startswith(_SECRET_CIPHERTEXT_PREFIX):
        return value
    cipher = _secret_cipher()
    if cipher is None:
        logger.error("MCP credential cannot be decrypted because the local key is unavailable")
        return ""
    try:
        token = value[len(_SECRET_CIPHERTEXT_PREFIX) :].encode("ascii")
        return cipher.decrypt(token).decode("utf-8")
    except Exception:
        logger.error("MCP credential cannot be decrypted; re-enter it in connector settings")
        return ""


def _looks_secret(key: str) -> bool:
    lowered = key.lower()
    return lowered.startswith("nexus_mcp_") or any(
        token in lowered for token in ("token", "key", "secret", "password", "connection_string", "auth")
    )


def tool_permission_fingerprint(tool: dict[str, Any]) -> str:
    """Bind a read-only grant to the exact schema and server annotations."""
    contract = {
        "name": tool.get("name", ""),
        "description": tool.get("description", ""),
        "inputSchema": tool.get("inputSchema", {}),
        "annotations": tool.get("annotations", {}),
    }
    encoded = json.dumps(contract, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


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
    last_activity_status: str = "unknown"
    source_root: str = ""
    # Only these process-level variables may be forwarded to the MCP child.
    # Connector.env remains the explicit per-connector credential/config map.
    pass_through_env: list[str] = field(default_factory=list)
    secret_arg_indexes: list[int] = field(default_factory=list)
    readonly_tool_fingerprints: dict[str, str] = field(default_factory=dict)

    def to_public_dict(self) -> dict[str, Any]:
        """Serialize with secrets masked — safe to send to the frontend."""
        d = asdict(self)
        d["env"] = {k: (_SECRET_MASK if _looks_secret(k) and v else v) for k, v in self.env.items()}
        for index in self.secret_arg_indexes:
            if 0 <= index < len(d["args"]):
                d["args"][index] = _SECRET_MASK
        d.pop("secret_arg_indexes", None)
        d["approved_readonly_tools"] = sorted(self.readonly_tool_fingerprints)
        d.pop("readonly_tool_fingerprints", None)
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
        self._activity_events: dict[str, dict[str, Any]] = {}
        self._activity_lock = threading.RLock()
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._load()
        self._load_activity()

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
            needs_migration = False
            for item in raw.get("connectors", []):
                item = dict(item)
                env_values = dict(item.get("env", {}))
                for key, value in env_values.items():
                    if _looks_secret(key) and value:
                        if str(value).startswith(_SECRET_CIPHERTEXT_PREFIX):
                            env_values[key] = _decrypt_secret(str(value))
                        else:
                            needs_migration = True
                item["env"] = env_values
                args = list(item.get("args", []))
                if not item.get("secret_arg_indexes") and item.get("template_id") == "postgres":
                    inferred_indexes = [
                        index for index, arg in enumerate(args)
                        if str(arg).lower().startswith(("postgres://", "postgresql://"))
                    ]
                    if inferred_indexes:
                        item["secret_arg_indexes"] = inferred_indexes
                        needs_migration = True
                for index in item.get("secret_arg_indexes", []):
                    if 0 <= int(index) < len(args):
                        value = str(args[int(index)])
                        if value.startswith(_SECRET_CIPHERTEXT_PREFIX):
                            args[int(index)] = _decrypt_secret(value)
                        elif value:
                            needs_migration = True
                item["args"] = args
                connector = MCPConnector(**item)
                self._connectors[connector.id] = connector
            if needs_migration:
                logger.info("Encrypting legacy MCP credentials in the local connector store")
                self._save()
        except Exception:
            logger.exception("Failed to load MCP connector store from %s", MCP_STORE_FILE)

    def _save(self) -> None:
        try:
            connectors = []
            for connector in self._connectors.values():
                item = asdict(connector)
                item["env"] = {
                    key: _encrypt_secret(value) if _looks_secret(key) and value else value
                    for key, value in connector.env.items()
                }
                for index in connector.secret_arg_indexes:
                    if 0 <= index < len(item["args"]) and item["args"][index]:
                        item["args"][index] = _encrypt_secret(str(item["args"][index]))
                connectors.append(item)
            payload = {"connectors": connectors}
            MCP_STORE_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception:
            logger.exception("Failed to persist MCP connector store to %s", MCP_STORE_FILE)

    def _load_activity(self) -> None:
        """Load the latest state for each append-only activity event."""
        if not MCP_ACTIVITY_FILE.exists():
            return
        try:
            with MCP_ACTIVITY_FILE.open("r", encoding="utf-8") as stream:
                for line in stream:
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(event, dict) and event.get("id"):
                        self._activity_events[str(event["id"])] = event
        except OSError:
            logger.exception("Failed to read MCP activity log from %s", MCP_ACTIVITY_FILE)
        self._trim_activity_memory()

    def _trim_activity_memory(self) -> None:
        if len(self._activity_events) <= _MAX_ACTIVITY_MEMORY:
            return
        oldest = sorted(
            self._activity_events.values(),
            key=lambda item: float(item.get("updated_at") or item.get("at") or 0),
        )[: len(self._activity_events) - _MAX_ACTIVITY_MEMORY]
        for event in oldest:
            self._activity_events.pop(str(event.get("id") or ""), None)

    def _append_activity_snapshot(self, event: dict[str, Any]) -> None:
        """Append a state transition without storing arguments or tool output."""
        try:
            MCP_ACTIVITY_FILE.parent.mkdir(parents=True, exist_ok=True)
            with self._activity_lock, MCP_ACTIVITY_FILE.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
                stream.flush()
        except OSError:
            logger.exception("Failed to append MCP activity to %s", MCP_ACTIVITY_FILE)

    def start_activity(
        self,
        *,
        tool: str,
        kind: str,
        source: str,
        connector_id: str = "",
        connector_name: str = "",
        phase: str = "starting",
        detail: str = "",
        argument_names: list[str] | None = None,
    ) -> str:
        connector = self._connectors.get(connector_id) if connector_id else None
        now = time.time()
        event_id = uuid.uuid4().hex
        event = {
            "id": event_id,
            "at": now,
            "updated_at": now,
            "connector_id": connector_id,
            "connector": connector.name if connector else connector_name or "NEXUS MCP",
            "tool": str(tool)[:128],
            "kind": str(kind)[:40],
            "source": str(source)[:40],
            "status": "running",
            "phase": str(phase)[:80],
            "duration_ms": None,
            "detail": str(detail)[:300],
            "argument_names": sorted({str(name)[:64] for name in (argument_names or [])})[:20],
            "result_shape": "",
        }
        with self._activity_lock:
            self._activity_events[event_id] = event
            self._trim_activity_memory()
        self._append_activity_snapshot(event)
        return event_id

    def update_activity(
        self,
        event_id: str,
        *,
        status: str | None = None,
        phase: str | None = None,
        detail: str | None = None,
        duration_ms: float | None = None,
        result_shape: str | None = None,
        connector_id: str | None = None,
        connector_name: str | None = None,
    ) -> None:
        with self._activity_lock:
            event = self._activity_events.get(event_id)
            if event is None:
                return
            if status in {"running", "ok", "warning", "error"}:
                event["status"] = status
            if phase is not None:
                event["phase"] = str(phase)[:80]
            if detail is not None:
                event["detail"] = str(detail)[:300]
            if duration_ms is not None:
                event["duration_ms"] = round(max(0.0, float(duration_ms)), 1)
            if result_shape is not None:
                event["result_shape"] = str(result_shape)[:200]
            if connector_id is not None:
                event["connector_id"] = connector_id
            if connector_name is not None:
                event["connector"] = connector_name[:120]
            event["updated_at"] = time.time()
            snapshot = dict(event)
            snapshot["argument_names"] = list(event.get("argument_names", []))
        self._append_activity_snapshot(snapshot)

    def record_activity(
        self,
        *,
        tool: str,
        kind: str,
        source: str,
        status: str,
        detail: str,
        connector_id: str = "",
        connector_name: str = "",
        result_shape: str = "",
        duration_ms: float | None = None,
    ) -> str:
        event_id = self.start_activity(
            tool=tool,
            kind=kind,
            source=source,
            connector_id=connector_id,
            connector_name=connector_name,
            phase="complete",
        )
        self.update_activity(
            event_id,
            status=status,
            phase="complete",
            detail=detail,
            result_shape=result_shape,
            duration_ms=duration_ms,
        )
        return event_id

    def list_activity(self, *, limit: int = 100, connector_id: str = "") -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 200))
        with self._activity_lock:
            events = [
                {**event, "argument_names": list(event.get("argument_names", []))}
                for event in self._activity_events.values()
                if not connector_id or event.get("connector_id") == connector_id
            ]
        events.sort(key=lambda item: float(item.get("updated_at") or item.get("at") or 0), reverse=True)
        return events[:safe_limit]

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
            try:
                parsed_url = httpx.URL(url)
            except httpx.InvalidURL as exc:
                raise ValueError("URL MCP remoto inválido: usa HTTP/S sem credenciais na URL") from exc
            if (
                parsed_url.scheme not in {"http", "https"}
                or not parsed_url.host
                or parsed_url.username
                or parsed_url.password
                or parsed_url.query
                or parsed_url.fragment
            ):
                raise ValueError("URL MCP remoto inválido: usa HTTP/S sem credenciais na URL")
        elif template_id == "projectmind":
            root_path = params.get("root_path", "")
            command = self._projectmind_python(root_path)
            args = [a.format(root_path=root_path) if "{" in a else a for a in args]
        else:
            # Substitute {placeholder} tokens in args with user-supplied params
            args = [a.format(**params) if "{" in a else a for a in args]

        secret_param_names = {
            str(param.get("key"))
            for param in template.get("params", [])
            if param.get("secret") and params.get(str(param.get("key")))
        }
        secret_arg_indexes = [
            index for index, arg in enumerate(args)
            if any(str(params[name]) in arg for name in secret_param_names)
        ]

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
            secret_arg_indexes=secret_arg_indexes,
        )
        connector.tools = self._discover_tools(connector)
        self._connectors[connector.id] = connector
        self._save()
        self.record_activity(
            connector_id=connector.id,
            connector_name=connector.name,
            tool="Configure MCP",
            kind="connector_created",
            source="control_center",
            status="warning",
            detail="Connector configurado · falta validar a ligação MCP",
        )
        logger.info("Created MCP connector %s (%s)", connector.id, connector.name)
        return connector

    def update_connector(self, connector_id: str, **fields: Any) -> MCPConnector | None:
        connector = self._connectors.get(connector_id)
        if not connector:
            return None
        for key, value in fields.items():
            if key == "env" and isinstance(value, dict):
                merged = dict(connector.env)
                for env_name, env_value in value.items():
                    if _looks_secret(str(env_name)) and env_value == _SECRET_MASK:
                        continue
                    merged[str(env_name)] = str(env_value)
                connector.env = merged
                continue
            if hasattr(connector, key) and value is not None:
                setattr(connector, key, value)
        connector.updated_at = time.time()
        self._save()
        return connector

    def set_approved_readonly_tools(self, connector_id: str, tool_names: list[str]) -> MCPConnector:
        """Grant auto-call only to user-approved, currently read-only tool contracts."""
        connector = self._connectors.get(connector_id)
        if connector is None:
            raise ValueError("Connector MCP não encontrado")
        if not connector.enabled or connector.last_test_status != "ok":
            raise ValueError("Testa e ativa o connector antes de aprovar tools read-only")
        known = {str(tool.get("name")): tool for tool in connector.tools if tool.get("name")}
        fingerprints: dict[str, str] = {}
        for raw_name in tool_names:
            name = str(raw_name)
            tool = known.get(name)
            annotations = (tool or {}).get("annotations") or {}
            if (
                tool is None
                or annotations.get("readOnlyHint") is not True
                or annotations.get("destructiveHint") is True
            ):
                raise ValueError(f"A tool '{name}' não está validada como read-only pelo último handshake")
            fingerprints[name] = tool_permission_fingerprint(tool)
        connector.readonly_tool_fingerprints = fingerprints
        connector.updated_at = time.time()
        self._save()
        self.record_activity(
            connector_id=connector.id,
            connector_name=connector.name,
            tool="Update tool permissions",
            kind="permission_change",
            source="control_center",
            status="ok",
            detail=f"{len(fingerprints)} permissões read-only aprovadas pelo utilizador",
            result_shape=", ".join(sorted(fingerprints)[:8]),
        )
        return connector

    def register_connector(self, connector: MCPConnector) -> MCPConnector:
        """Persist one connector after its caller has completed validation."""
        if connector.id in self._connectors:
            raise ValueError(f"MCP connector already exists: {connector.id}")
        self._connectors[connector.id] = connector
        self._save()
        self.record_activity(
            connector_id=connector.id,
            connector_name=connector.name,
            tool="Activate MCP",
            kind="connector_created",
            source="mcp_builder" if connector.template_id == "builder" else "control_center",
            status="ok",
            detail="Connector validado e disponibilizado ao agente",
            result_shape=f"{len(connector.tools)} tools MCP",
        )
        logger.info("Registered MCP connector %s (%s)", connector.id, connector.name)
        return connector

    def delete_connector(self, connector_id: str) -> bool:
        if connector_id in self._connectors:
            connector_name = self._connectors[connector_id].name
            del self._connectors[connector_id]
            self._save()
            self.record_activity(
                connector_id=connector_id,
                connector_name=connector_name,
                tool="Remove MCP",
                kind="connector_removed",
                source="control_center",
                status="warning",
                detail="Connector removido do registo; o histórico de atividade foi preservado",
            )
            return True
        return False

    # ── Health / test ────────────────────────────────────────────────

    async def test_connector(self, connector_id: str) -> dict[str, Any]:
        connector = self._connectors.get(connector_id)
        if not connector:
            return {"status": "error", "detail": "Connector not found"}
        started = time.perf_counter()
        activity_id = self.start_activity(
            connector_id=connector_id,
            tool="Test MCP connection",
            kind="connector_test",
            source="control_center",
            phase="mcp_handshake",
            detail="A testar o initialize e a descoberta de tools",
        )
        try:
            result = await self._test_connector_impl(connector_id)
        except BaseException as exc:  # noqa: BLE001 - record cancellation before propagating
            self.update_activity(
                activity_id,
                status="error",
                phase="cancelled" if isinstance(exc, asyncio.CancelledError) else "failed",
                detail=f"Teste interrompido ({type(exc).__name__})",
                duration_ms=(time.perf_counter() - started) * 1000,
            )
            raise
        status = result.get("status", "error")
        self.update_activity(
            activity_id,
            status=status if status in {"ok", "warning", "error"} else "error",
            phase="complete",
            detail=(
                f"Handshake MCP OK · {len(result.get('tools', []))} tools descobertas"
                if status == "ok" and isinstance(result.get("tools"), list)
                else "Executável ainda não está disponível no PATH deste servidor"
                if status == "warning"
                else "Teste falhou; consulta o detalhe do connector para diagnóstico"
            ),
            duration_ms=(time.perf_counter() - started) * 1000,
            result_shape=f"{len(result.get('tools', []))} tools encontradas" if isinstance(result.get("tools"), list) else "",
        )
        return result

    async def _test_connector_impl(self, connector_id: str) -> dict[str, Any]:
        """Best-effort validation without fully starting the MCP session.

        Tests perform a real MCP initialize + tools/list handshake. An HTTP
        status code alone is not evidence that a URL speaks the MCP protocol.
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
            result = await self._probe_with_runtime(connector)
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
                    "annotations": item.get("annotations", {}),
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
        self,
        connector_id: str,
        tool_name: str,
        latency_ms: float,
        *,
        success: bool,
        activity_id: str = "",
        detail: str = "",
        result_shape: str = "",
    ) -> None:
        """Persist evidence from a real MCP tool invocation."""
        connector = self._connectors.get(connector_id)
        if connector is None:
            if activity_id:
                self.update_activity(
                    activity_id,
                    status="ok" if success else "error",
                    phase="complete",
                    detail=detail or "Connector removido durante a chamada MCP",
                    duration_ms=latency_ms,
                    result_shape=result_shape,
                )
            return
        connector.calls_today += 1
        connector.last_activity_tool = tool_name
        connector.last_activity_at = time.time()
        connector.last_activity_status = "ok" if success else "error"
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
        if activity_id:
            self.update_activity(
                activity_id,
                status="ok" if success else "error",
                phase="complete",
                detail=detail or ("Resultado recebido" if success else "A chamada falhou"),
                duration_ms=latency_ms,
                result_shape=result_shape,
            )
        else:
            self.record_activity(
                tool=tool_name,
                kind="tool_call",
                source="agent",
                status="ok" if success else "error",
                detail=detail or ("Resultado recebido" if success else "A chamada falhou"),
                connector_id=connector_id,
                duration_ms=latency_ms,
                result_shape=result_shape,
            )
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
            args = list(connector.args)
            for index in connector.secret_arg_indexes:
                if 0 <= index < len(args):
                    args[index] = f"<set secret argument {index} in the MCP host environment>"
            entry = {"command": connector.command, "args": args}
        if connector.env:
            entry["env"] = {
                name: f"<set {name} in the MCP host environment>" if _looks_secret(name) and value else value
                for name, value in connector.env.items()
            }
        if connector.pass_through_env:
            entry.setdefault("env", {}).update(
                {name: f"<set {name} in the MCP host environment>" for name in connector.pass_through_env}
            )
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
