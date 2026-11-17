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


def _available_capabilities(bot: dict[str, Any]) -> list[str]:
    """Capability families whose tools are actually available to the model.

    A flag is only reported as available when the live registry can serve at
    least one tool of that family. This keeps the UI honest: a capability the
    user enabled but whose tools are missing (for example the browser family
    without Playwright) is not advertised as active.
    """
    from backend.orchestrator.routes.chat_primary import _BOT_CAPABILITY_TOOLS
    from backend.tools.registry import list_tools

    try:
        available = {
            spec.name
            for spec in list_tools(enabled_only=True)
            if spec.available and spec.enabled and spec.handler is not None
        }
    except Exception:
        return []
    capabilities = bot.get("capabilities") or {}
    return sorted(
        flag
        for flag, tools in _BOT_CAPABILITY_TOOLS.items()
        if capabilities.get(flag) and (tools & available)
    )


def _with_availability(bot: dict[str, Any]) -> dict[str, Any]:
    return {**bot, "available_capabilities": _available_capabilities(bot)}


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
