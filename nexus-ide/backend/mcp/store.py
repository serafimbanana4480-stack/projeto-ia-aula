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
import shutil
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

    def to_public_dict(self) -> dict[str, Any]:
        """Serialize with secrets masked — safe to send to the frontend."""
        d = asdict(self)
        d["env"] = {k: (_SECRET_MASK if _looks_secret(k) and v else v) for k, v in self.env.items()}
        if self.url and any(_looks_secret(k) for k in ("url",)):
            pass  # URLs themselves aren't treated as secret
        return d


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
        )
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
        if not connector.command:
            result = {"status": "error", "detail": "Comando não definido"}
        elif shutil.which(connector.command) is None:
            result = {
                "status": "warning",
                "detail": f"Executável '{connector.command}' não encontrado no PATH do servidor. "
                "Vai ser instalado/resolvido no primeiro arranque (normal para npx/uvx).",
            }
        else:
            result = {"status": "ok", "detail": f"Executável '{connector.command}' resolvido com sucesso."}

        self._record_test_result(connector, result)
        return result

    def _record_test_result(self, connector: MCPConnector, result: dict[str, Any]) -> None:
        connector.last_test_status = result["status"]
        connector.last_test_detail = result["detail"]
        connector.last_tested_at = time.time()
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
        return {
            "total": len(connectors),
            "enabled": sum(1 for c in connectors if c.enabled),
            "healthy": sum(1 for c in connectors if c.last_test_status == "ok"),
            "warning": sum(1 for c in connectors if c.last_test_status == "warning"),
            "error": sum(1 for c in connectors if c.last_test_status == "error"),
            "untested": sum(1 for c in connectors if c.last_test_status == "untested"),
        }


# Singleton instance, following the SkillsStore convention.
mcp_store = MCPConnectorStore.get_instance()
