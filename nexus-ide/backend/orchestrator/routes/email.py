"""Email REST API — IMAP account management and LLM-powered triage."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import re
from typing import Any

from cryptography.fernet import Fernet
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from backend.config.settings import get_settings
from backend.middleware.auth import get_current_user, require_auth
from backend.persistence.db import (
    create_email_account,
    delete_email_account,
    get_email_account,
    get_email_account_with_password,
    list_email_accounts,
)
from backend.tools.email_client import (
    connect_imap,
    fetch_emails,
    mark_as_read,
)
from backend.tools.email_client import (
    search_emails as imap_search_emails,
)

logger = logging.getLogger(__name__)
router = APIRouter()


_fernet_instance: Fernet | None = None


def _get_fernet() -> Fernet:
    """Get or create a Fernet instance derived from the application secret key.

    The secret key is hashed with SHA-256 to produce 32 bytes, then
    base64-encoded to satisfy Fernet's key format requirement.
    """
    global _fernet_instance
    if _fernet_instance is None:
        settings = get_settings()
        secret = (
            settings.secret_key.get_secret_value()
            if hasattr(settings.secret_key, "get_secret_value")
            else str(settings.secret_key)
        )
        key_bytes = hashlib.sha256(secret.encode("utf-8")).digest()
        key_b64 = base64.urlsafe_b64encode(key_bytes)
        _fernet_instance = Fernet(key_b64)
    return _fernet_instance


def _encrypt_password(password: str) -> str:
    """Encrypt a password using Fernet (symmetric encryption).

    The encryption key is derived from the application's secret_key setting,
    making it deterministic per deployment but not reversible without access
    to the server's configuration.
    """
    fernet = _get_fernet()
    return fernet.encrypt(password.encode("utf-8")).decode("utf-8")


def _decrypt_password(encrypted: str) -> str:
    """Decrypt a Fernet-encrypted password."""
    fernet = _get_fernet()
    return fernet.decrypt(encrypted.encode("utf-8")).decode("utf-8")


def _account_to_config(account: dict) -> dict[str, Any]:
    """Convert an email account dict to a config dict for the IMAP client."""
    return {
        "host": account["host"],
        "port": account["port"],
        "username": account["username"],
        "password": _decrypt_password(account["password_encrypted"]),
        "use_ssl": bool(account.get("use_ssl", 1)),
    }


@router.get("/email/accounts")
async def get_accounts(
    request: Request,
    user: dict = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """List email accounts for the current user."""
    user_id = user.get("user_id") if user else None
    return list_email_accounts(user_id=user_id, active_only=False)


@router.post("/email/accounts")
async def create_account(
    request: Request,
    payload: dict[str, Any],
    user: dict = Depends(require_auth),
) -> dict[str, Any]:
    """Create a new email account configuration."""
    user_id = user.get("user_id")
    label = payload.get("label", "Email")
    host = payload.get("host")
    port = payload.get("port", 993)
    username = payload.get("username")
    password = payload.get("password")
    use_ssl = payload.get("use_ssl", True)

    if not host or not username or not password:
        raise HTTPException(status_code=400, detail="host, username, and password are required")

    try:
        conn = await asyncio.to_thread(connect_imap, host, port, username, password, use_ssl)
        conn.logout()
    except ConnectionError as e:
        raise HTTPException(status_code=400, detail=f"Could not connect to IMAP: {e}") from e

    account = create_email_account(
        user_id=user_id,
        label=label,
        host=host,
        port=port,
        username=username,
        password_encrypted=_encrypt_password(password),
        use_ssl=use_ssl,
    )
    return account


@router.delete("/email/accounts/{account_id}")
async def delete_account(
    request: Request,
    account_id: str,
    user: dict = Depends(require_auth),
) -> dict[str, Any]:
    """Delete an email account."""
    account = get_email_account(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    if account.get("user_id") != user.get("user_id"):
        raise HTTPException(status_code=403, detail="Not authorized")
    delete_email_account(account_id)
    return {"success": True, "deleted": account_id}


@router.get("/email/inbox")
async def get_inbox(
    request: Request,
    account_id: str = Query(...),
    limit: int = Query(20, ge=1, le=100),
    unread_only: bool = Query(False),
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Fetch inbox for a given account."""
    account = get_email_account_with_password(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    if user and account.get("user_id") != user.get("user_id"):
        raise HTTPException(status_code=403, detail="Not authorized")

    config = _account_to_config(account)
    try:
        emails = await asyncio.to_thread(
            fetch_emails,
            folder="INBOX",
            limit=limit,
            unread_only=unread_only,
            **config,
        )
    except ConnectionError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

    return {"account_id": account_id, "count": len(emails), "emails": emails}


@router.get("/email/search")
async def search_email_endpoint(
    request: Request,
    q: str = Query(..., min_length=1),
    account_id: str = Query(...),
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Search emails by query."""
    account = get_email_account_with_password(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    if user and account.get("user_id") != user.get("user_id"):
        raise HTTPException(status_code=403, detail="Not authorized")

    config = _account_to_config(account)
    try:
        results = await asyncio.to_thread(
            imap_search_emails,
            query=q,
            folder="INBOX",
            limit=20,
            **config,
        )
    except ConnectionError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

    return {"account_id": account_id, "query": q, "count": len(results), "emails": results}


@router.post("/email/{email_id}/read")
async def mark_email_read(
    request: Request,
    email_id: str,
    account_id: str = Query(...),
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Mark an email as read."""
    account = get_email_account_with_password(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    if user and account.get("user_id") != user.get("user_id"):
        raise HTTPException(status_code=403, detail="Not authorized")

    config = _account_to_config(account)
    success = await asyncio.to_thread(mark_as_read, email_id, **config)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to mark email as read")
    return {"success": True, "email_id": email_id}


@router.post("/email/triage")
async def triage_emails(
    request: Request,
    payload: dict[str, Any],
    user: dict = Depends(require_auth),
) -> dict[str, Any]:
    """Fetch unread emails and classify them using the LLM.

    Returns a triaged list with suggested actions.
    """
    account_id = payload.get("account_id")
    if not account_id:
        raise HTTPException(status_code=400, detail="account_id is required")

    account = get_email_account_with_password(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    if account.get("user_id") != user.get("user_id"):
        raise HTTPException(status_code=403, detail="Not authorized")

    config = _account_to_config(account)
    try:
        emails = await asyncio.to_thread(
            fetch_emails,
            folder="INBOX",
            limit=20,
            unread_only=True,
            **config,
        )
    except ConnectionError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

    if not emails:
        return {"account_id": account_id, "triaged": [], "count": 0}

    llm_client = request.app.state.llm_client
    triaged: list[dict[str, Any]] = []

    # Determine a suitable model name based on provider
    settings = get_settings()
    provider = settings.llm_provider.lower()
    if provider in ("ollama", "local"):
        model = "llama3.1:8b"
    elif provider == "openai":
        model = "gpt-3.5-turbo"
    elif provider == "deepseek":
        model = "deepseek-chat"
    elif provider == "kimi":
        model = "moonshot-v1-8k"
    elif provider == "groq":
        model = "llama3-8b-8192"
    else:
        model = ""

    for email_item in emails:
        prompt_messages = [
            {
                "role": "system",
                "content": (
                    "You are an email triage assistant. Classify the email into exactly one of: "
                    "urgent, important, normal, spam. "
                    "Respond with a JSON object containing keys: classification, reason, suggested_action. "
                    "No extra text outside the JSON."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Subject: {email_item['subject']}\n"
                    f"From: {email_item['from']}\n"
                    f"Preview: {email_item['body_preview']}\n"
                ),
            },
        ]
        try:
            response = await llm_client.chat_complete(
                model=model,
                messages=prompt_messages,
                temperature=0.3,
            )
            json_match = re.search(r"\{.*\}", response, re.DOTALL)
            if json_match:
                classification_data = json.loads(json_match.group())
            else:
                classification_data = {
                    "classification": "normal",
                    "reason": "Could not parse LLM response",
                    "suggested_action": "review manually",
                }
        except Exception as e:
            logger.warning("LLM triage failed for email %s: %s", email_item["id"], e)
            classification_data = {
                "classification": "normal",
                "reason": f"LLM error: {e}",
                "suggested_action": "review manually",
            }

        triaged.append(
            {
                "email": email_item,
                "classification": classification_data.get("classification", "normal"),
                "reason": classification_data.get("reason", ""),
                "suggested_action": classification_data.get("suggested_action", ""),
            }
        )

    # Sort by priority: urgent > important > normal > spam
    priority_order = {"urgent": 0, "important": 1, "normal": 2, "spam": 3}
    triaged.sort(key=lambda x: priority_order.get(x["classification"], 2))

    return {"account_id": account_id, "triaged": triaged, "count": len(triaged)}
