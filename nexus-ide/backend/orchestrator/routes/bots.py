"""Authenticated bot profiles. Chat itself uses the existing PRIMARY runtime."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.llm.model_catalog import PROVIDER_SPECS
from backend.middleware.auth import require_auth
from backend.persistence import bots

router = APIRouter(prefix="/bots", tags=["bots"])


class BotCapabilities(BaseModel):
    """Tool gates enforced on every backend tool execution, not just planned.

    ``memory`` scopes memory writes to the bot's own isolated session;
    ``write`` upgrades the tools to the full tier (files at the chat root,
    matching ordinary chat). Shell/delegation/MCP are NOT part of this model:
    confirmations cannot be approved inside bot panels, so those tools stay
    off-limits for bots regardless of these flags.
    """

    model_config = ConfigDict(extra="forbid")

    read: bool = True
    research: bool = True
    tasks: bool = True
    memory: bool = True
    write: bool = False


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


def _owner(user: dict[str, Any]) -> str:
    owner = str(user.get("user_id") or "").strip()
    if not owner:
        raise HTTPException(status_code=401, detail="Authenticated user is missing an id")
    return owner


@router.get("")
async def list_bot_profiles(user: dict = Depends(require_auth)) -> dict[str, Any]:
    return {"bots": bots.list_bots(_owner(user))}


@router.post("", status_code=201)
async def create_bot_profile(body: BotFields, user: dict = Depends(require_auth)) -> dict[str, Any]:
    return bots.create_bot(_owner(user), body.model_dump())


@router.get("/{bot_id}")
async def get_bot_profile(bot_id: str, user: dict = Depends(require_auth)) -> dict[str, Any]:
    bot = bots.get_bot(_owner(user), bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail="Bot não encontrado")
    return bot


@router.patch("/{bot_id}")
async def update_bot_profile(
    bot_id: str, body: BotUpdate, user: dict = Depends(require_auth),
) -> dict[str, Any]:
    bot = bots.update_bot(_owner(user), bot_id, body.model_dump(exclude_unset=True, exclude_none=True))
    if bot is None:
        raise HTTPException(status_code=404, detail="Bot não encontrado")
    return bot


@router.delete("/{bot_id}", status_code=204)
async def remove_bot_profile(bot_id: str, user: dict = Depends(require_auth)) -> None:
    if not bots.remove_bot(_owner(user), bot_id):
        raise HTTPException(status_code=404, detail="Bot não encontrado")
