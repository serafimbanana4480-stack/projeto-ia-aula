"""Browser automation REST endpoints.

Thin wrappers around the tools in ``backend.tools.browser_automation`` so the
frontend (or external clients) can drive a headless browser via HTTP.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from backend.middleware.auth import require_auth
from backend.tools.browser_automation import (
    browser_navigate,
    browser_click,
    browser_fill,
    browser_extract_text,
    browser_screenshot,
    browser_get_links,
    browser_close,
)

router = APIRouter()


class BrowserNavigateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(min_length=1, max_length=2000)
    session_id: str = Field(default="default", min_length=1, max_length=128)


class BrowserClickRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    selector: str = Field(min_length=1, max_length=1000)
    session_id: str = Field(default="default", min_length=1, max_length=128)


class BrowserFillRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    selector: str = Field(min_length=1, max_length=1000)
    text: str = Field(min_length=0, max_length=50_000)
    session_id: str = Field(default="default", min_length=1, max_length=128)


class BrowserExtractRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    selector: str | None = Field(default=None, max_length=1000)
    session_id: str = Field(default="default", min_length=1, max_length=128)


class BrowserScreenshotRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str = Field(default="default", min_length=1, max_length=128)
    full_page: bool = False


class BrowserCloseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str = Field(default="default", min_length=1, max_length=128)


@router.post("/browser/navigate")
async def navigate(req: BrowserNavigateRequest, _user: dict = Depends(require_auth)) -> dict:
    return await browser_navigate(url=req.url, session_id=req.session_id)


@router.post("/browser/click")
async def click(req: BrowserClickRequest, _user: dict = Depends(require_auth)) -> dict:
    return await browser_click(selector=req.selector, session_id=req.session_id)


@router.post("/browser/fill")
async def fill(req: BrowserFillRequest, _user: dict = Depends(require_auth)) -> dict:
    return await browser_fill(selector=req.selector, text=req.text, session_id=req.session_id)


@router.post("/browser/extract")
async def extract(req: BrowserExtractRequest, _user: dict = Depends(require_auth)) -> dict:
    return await browser_extract_text(selector=req.selector, session_id=req.session_id)


@router.post("/browser/screenshot")
async def screenshot(req: BrowserScreenshotRequest, _user: dict = Depends(require_auth)) -> dict:
    return await browser_screenshot(session_id=req.session_id, full_page=req.full_page)


@router.post("/browser/get_links")
async def get_links(req: BrowserCloseRequest, _user: dict = Depends(require_auth)) -> dict:
    return await browser_get_links(session_id=req.session_id)


@router.post("/browser/close")
async def close(req: BrowserCloseRequest, _user: dict = Depends(require_auth)) -> dict:
    return await browser_close(session_id=req.session_id)
