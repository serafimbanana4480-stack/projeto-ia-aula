"""Authenticated bot profiles. Chat itself uses the existing PRIMARY runtime."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.llm.model_catalog import PROVIDER_SPECS
from backend.middleware.auth import require_auth
from backend.persistence import bot_room, bots

router = APIRouter(prefix="/bots", tags=["bots"])


class BotCapabilities(BaseModel):
    """Tool gates enforced on every backend tool execution, not just planned.

    All tool families (read, write, shell, research, browser, MCP, tasks, memory)
    are delivered to the model by default. In-project auto-accept is enabled by
    default and confined strictly to the selected project directory.
    """

    model_config = ConfigDict(extra="forbid")

    read: bool = True
    research: bool = True
    tasks: bool = True
    memory: bool = True
    write: bool = True
    shell: bool = True
    browser: bool = True
    mcp: bool = True
    auto_accept: bool = True


class BotFields(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=500)
    instructions: str = Field(default="", max_length=4000)
    provider: str = Field(default="", max_length=128)
    model: str = Field(default="", max_length=128)
    capabilities: BotCapabilities = Field(default_factory=BotCapabilities)

    @field_validator("provider")
    @classmethod
    def known_provider(cls, value: str) -> str:
        value = value.lower()
        if value and value not in PROVIDER_SPECS:
            raise ValueError("Provedor não suportado pelo catálogo NEXUS")
        return value


class BotUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=500)
    instructions: str | None = Field(default=None, max_length=4000)
    provider: str | None = Field(default=None, max_length=128)
    model: str | None = Field(default=None, max_length=128)
    archived: bool | None = None
    capabilities: BotCapabilities | None = None

    @field_validator("provider")
    @classmethod
    def known_provider(cls, value: str | None) -> str | None:
        return BotFields.known_provider(value) if value is not None else None


class RoomMemoryUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    pins: list[str] | None = Field(default=None, max_length=500)
    seen: dict[str, str] | None = None


def _owner(user: dict[str, Any]) -> str:
    owner = str(user.get("user_id") or "").strip()
    if not owner:
        raise HTTPException(status_code=401, detail="Authenticated user is missing an id")
    return owner


def _mcp_block_reason() -> str:
    """Why the MCP family cannot run, or empty when a server is configured."""
    try:
        from mcp import ClientSession  # noqa: F401
    except ImportError:
        return (
            "A dependência Python 'mcp' não está instalada. "
            "Instala com: uv sync (pacote mcp)."
        )
    try:
        from backend.mcp.store import MCPConnectorStore

        connectors = MCPConnectorStore.get_instance().list_connectors()
    except Exception:
        return "Não foi possível ler a configuração dos servidores MCP."
    enabled = [
        item for item in connectors
        if isinstance(item, dict) and item.get("enabled", True)
    ]
    if not enabled:
        return "Nenhum servidor MCP configurado."
    return ""


def _capability_report(bot: dict[str, Any]) -> tuple[list[str], dict[str, str]]:
    """Families the bot can use, and a specific reason for each one it cannot.

    A family is blocked only when a real dependency is missing: the tool is
    not installed, or, for MCP, no server is configured. Lack of a selected
    project is not a block — the bot uses its own folder.
    """
    from backend.orchestrator.routes.chat_primary import _BOT_CAPABILITY_TOOLS
    from backend.tools.registry import list_tools

    capabilities = bot.get("capabilities") if isinstance(bot.get("capabilities"), dict) else {}
    try:
        specs = {
            spec.name: spec
            for spec in list_tools(enabled_only=False)
        }
    except Exception:
        specs = {}
    available: list[str] = []
    blocked: dict[str, str] = {}
    for flag, tools in _BOT_CAPABILITY_TOOLS.items():
        if not capabilities.get(flag):
            continue
        live = [
            name for name in tools
            if name in specs
            and specs[name].available
            and specs[name].enabled
            and specs[name].handler is not None
        ]
        if flag == "mcp" and live:
            reason = _mcp_block_reason()
            if reason:
                blocked[flag] = reason
                continue
        if live:
            available.append(flag)
            continue
        if flag == "browser":
            blocked[flag] = "O Playwright não está instalado neste backend."
            continue
        if flag == "mcp":
            reason = _mcp_block_reason()
            if reason:
                blocked[flag] = reason
                continue
        from backend.tools.registry import unavailable_tool_reason

        dependency = next(
            (unavailable_tool_reason(name) for name in tools if unavailable_tool_reason(name)),
            "",
        )
        if dependency:
            blocked[flag] = dependency
            continue
        reasons = []
        for name in tools:
            spec = specs.get(name)
            if spec is None:
                continue
            detail = spec.unavailable_reason or spec.missing_dependency
            if detail:
                reasons.append(str(detail))
        blocked[flag] = reasons[0] if reasons else (
            "Nenhuma ferramenta desta família está registada neste processo."
        )
    return sorted(available), blocked


def _available_capabilities(bot: dict[str, Any]) -> list[str]:
    """Capability families whose tools are actually available to the model."""
    available, _blocked = _capability_report(bot)
    return available


def _with_availability(bot: dict[str, Any]) -> dict[str, Any]:
    available, blocked = _capability_report(bot)
    return {
        **bot,
        "available_capabilities": available,
        "capability_blocks": blocked,
    }


@router.get("/room-memory")
async def get_room_memory_endpoint(user: dict = Depends(require_auth)) -> dict[str, Any]:
    return bot_room.get_room_memory(_owner(user))


@router.post("/room-memory")
async def update_room_memory_endpoint(
    body: RoomMemoryUpdate, user: dict = Depends(require_auth),
) -> dict[str, Any]:
    return bot_room.update_room_memory(_owner(user), pins=body.pins, seen=body.seen)


@router.get("")
async def list_bot_profiles(user: dict = Depends(require_auth)) -> dict[str, Any]:
    return {"bots": [_with_availability(bot) for bot in bots.list_bots(_owner(user))]}


@router.post("", status_code=201)
async def create_bot_profile(body: BotFields, user: dict = Depends(require_auth)) -> dict[str, Any]:
    return _with_availability(bots.create_bot(_owner(user), body.model_dump()))


@router.get("/{bot_id}")
async def get_bot_profile(bot_id: str, user: dict = Depends(require_auth)) -> dict[str, Any]:
    bot = bots.get_bot(_owner(user), bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail="Bot não encontrado")
    return _with_availability(bot)


@router.patch("/{bot_id}")
async def update_bot_profile(
    bot_id: str, body: BotUpdate, user: dict = Depends(require_auth),
) -> dict[str, Any]:
    bot = bots.update_bot(_owner(user), bot_id, body.model_dump(exclude_unset=True, exclude_none=True))
    if bot is None:
        raise HTTPException(status_code=404, detail="Bot não encontrado")
    return _with_availability(bot)


@router.delete("/{bot_id}", status_code=204)
async def remove_bot_profile(bot_id: str, user: dict = Depends(require_auth)) -> None:
    if not bots.remove_bot(_owner(user), bot_id):
        raise HTTPException(status_code=404, detail="Bot não encontrado")
