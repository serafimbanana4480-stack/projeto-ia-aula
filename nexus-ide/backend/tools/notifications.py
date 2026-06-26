"""Notification tools — webhooks, email alerts, desktop notifications.

Provides three notification channels:
- ``send_webhook`` — POST a JSON payload to a webhook URL (Slack/Discord/Teams compatible)
- ``send_email_notification`` — send a simple email via SMTP (requires email config)
- ``show_desktop_notification`` — show a native desktop notification (cross-platform via plyer)
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
from email.message import EmailMessage
from typing import Any

import aiohttp

from backend.tools.registry import ToolSpec, register_tool

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Webhook
# ---------------------------------------------------------------------------
async def send_webhook(
    url: str,
    payload: dict[str, Any] | None = None,
    message: str | None = None,
    title: str | None = None,
    timeout: int = 10,
) -> dict:
    """Send a webhook notification.

    Compatible with Slack (incoming webhooks), Discord, MS Teams, and generic
    JSON endpoints. Auto-detects format from URL or content-type.

    Args:
        url: Webhook URL.
        payload: Optional dict payload (sent as JSON body).
        message: Convenience field for plain-text messages.
        title: Optional title (for Slack/Discord/Teams).
        timeout: Request timeout in seconds (1-30).
    """
    timeout = min(max(timeout, 1), 30)

    # Build payload if message/title provided
    body: dict[str, Any]
    body = dict(payload) if payload is not None else {}

    if message is not None or title is not None:
        # Auto-format based on URL
        url_lower = url.lower()
        if "hooks.slack.com" in url_lower:
            body.setdefault("text", message or title or "")
        elif "discord.com/api/webhooks" in url_lower or "discordapp.com/api/webhooks" in url_lower:
            body.setdefault("content", message or title or "")
            if title:
                body.setdefault("embeds", [{"title": title, "description": message or ""}])
        elif "webhook.office.com" in url_lower or "outlook.office.com" in url_lower:
            # Teams: MessageCard
            body = {
                "@type": "MessageCard",
                "@context": "https://schema.org/extensions",
                "summary": title or "Notification",
                "themeColor": "0076D7",
                "title": title or "Notification",
                "text": message or "",
            }
        else:
            # Generic JSON
            if title:
                body.setdefault("title", title)
            if message:
                body.setdefault("message", message)

    timeout_obj = aiohttp.ClientTimeout(total=timeout)
    try:
        async with aiohttp.ClientSession(timeout=timeout_obj) as session, session.post(url, json=body) as resp:
            text = await resp.text()
            return {
                "status": resp.status,
                "ok": 200 <= resp.status < 300,
                "response": text[:1000],  # cap response size
            }
    except TimeoutError:
        return {"error": f"Webhook timeout after {timeout}s", "url": url}
    except aiohttp.ClientError as e:
        return {"error": f"Webhook HTTP error: {e}", "url": url}
    except Exception as e:  # noqa: BLE001
        logger.exception("webhook send failed")
        return {"error": str(e), "url": url}


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------
async def send_email_notification(
    to: str,
    subject: str,
    body: str,
    from_addr: str | None = None,
    smtp_host: str | None = None,
    smtp_port: int | None = None,
    smtp_user: str | None = None,
    smtp_password: str | None = None,
) -> dict:
    """Send a simple email notification via SMTP.

    Args:
        to: Recipient email address.
        subject: Email subject.
        body: Email body (plain text).
        from_addr: Sender address (defaults to env NEXUS_SMTP_FROM or smtp_user).
        smtp_host: SMTP server (defaults to env NEXUS_SMTP_HOST).
        smtp_port: SMTP port (defaults to env NEXUS_SMTP_PORT or 587).
        smtp_user: SMTP username (defaults to env NEXUS_SMTP_USER).
        smtp_password: SMTP password (defaults to env NEXUS_SMTP_PASSWORD).
    """
    import os

    host = smtp_host or os.environ.get("NEXUS_SMTP_HOST")
    port = smtp_port or int(os.environ.get("NEXUS_SMTP_PORT", "587"))
    user = smtp_user or os.environ.get("NEXUS_SMTP_USER")
    password = smtp_password or os.environ.get("NEXUS_SMTP_PASSWORD")
    sender = from_addr or os.environ.get("NEXUS_SMTP_FROM") or user

    if not host:
        return {"error": "SMTP host not configured (set NEXUS_SMTP_HOST or pass smtp_host)"}
    if not sender:
        return {"error": "Sender address not configured (set NEXUS_SMTP_FROM or NEXUS_SMTP_USER)"}

    # Validate email format (basic)
    if "@" not in to or " " in to:
        return {"error": f"Invalid recipient email '{to}'"}
    if "@" not in sender:
        return {"error": f"Invalid sender email '{sender}'"}

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to
    msg.set_content(body)

    def _send() -> tuple[bool, str]:
        try:
            with smtplib.SMTP(host, port, timeout=30) as smtp:
                smtp.ehlo()
                smtp.starttls()
                smtp.ehlo()
                if user and password:
                    smtp.login(user, password)
                smtp.send_message(msg)
            return True, ""
        except Exception as e:  # noqa: BLE001
            return False, str(e)

    try:
        ok, err = await asyncio.to_thread(_send)
        if ok:
            return {"status": "sent", "to": to, "subject": subject}
        return {"error": f"SMTP error: {err}", "to": to}
    except Exception as e:  # noqa: BLE001
        logger.exception("email send failed")
        return {"error": str(e), "to": to}


# ---------------------------------------------------------------------------
# Desktop notification
# ---------------------------------------------------------------------------
async def show_desktop_notification(title: str, message: str, app_name: str = "NEXUS IDE") -> dict:
    """Show a native desktop notification.

    Cross-platform via ``plyer`` (best-effort). If plyer is not available,
    falls back to platform-specific commands.

    Args:
        title: Notification title.
        message: Notification body text.
        app_name: App name shown in the notification.
    """
    import asyncio
    import shutil
    import subprocess
    import sys

    def _show() -> tuple[bool, str]:
        try:
            from plyer import notification  # type: ignore

            notification.notify(title=title, message=message, app_name=app_name, timeout=10)
            return True, "plyer"
        except ImportError:
            pass
        # Fallback: platform-specific
        if sys.platform == "win32":
            # PowerShell BurntToast / Windows.UI.Notifications (simplest: msg.exe)
            ps_script = f"""
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.MessageBox]::Show('{message}', '{title}')
"""
            try:
                subprocess.run(
                    ["powershell", "-NoProfile", "-Command", ps_script],
                    check=True,
                    capture_output=True,
                    timeout=10,
                )
                return True, "winforms"
            except Exception as e:  # noqa: BLE001
                return False, f"Windows fallback failed: {e}"
        if sys.platform == "darwin":
            if shutil.which("osascript"):
                try:
                    subprocess.run(
                        [
                            "osascript",
                            "-e",
                            f'display notification "{message}" with title "{title}"',
                        ],
                        check=True,
                        capture_output=True,
                        timeout=10,
                    )
                    return True, "osascript"
                except Exception as e:  # noqa: BLE001
                    return False, f"macOS fallback failed: {e}"
            return False, "osascript not found"
        # Linux: notify-send
        if shutil.which("notify-send"):
            try:
                subprocess.run(
                    ["notify-send", "-a", app_name, title, message],
                    check=True,
                    capture_output=True,
                    timeout=10,
                )
                return True, "notify-send"
            except Exception as e:  # noqa: BLE001
                return False, f"Linux fallback failed: {e}"
        return False, "No notification backend available (install plyer or notify-send)"

    try:
        ok, backend = await asyncio.to_thread(_show)
        if ok:
            return {"status": "shown", "backend": backend, "title": title}
        return {"error": backend}
    except Exception as e:  # noqa: BLE001
        logger.exception("desktop notification failed")
        return {"error": str(e)}


register_tool(
    ToolSpec(
        name="send_webhook",
        description=(
            "Send a webhook notification. Auto-formats payload for Slack, Discord, "
            "MS Teams, or generic JSON endpoints. Provide either `payload` (dict) "
            "or `message`+`title` for convenience."
        ),
        schema={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Webhook URL"},
                "payload": {"type": "object", "description": "JSON payload (dict)"},
                "message": {"type": "string", "description": "Plain text message"},
                "title": {"type": "string", "description": "Optional title"},
                "timeout": {"type": "integer", "description": "Timeout in seconds", "default": 10},
            },
            "required": ["url"],
        },
        handler=send_webhook,
    )
)

register_tool(
    ToolSpec(
        name="send_email_notification",
        description=(
            "Send a plain-text email notification via SMTP. Configuration via env vars: "
            "NEXUS_SMTP_HOST, NEXUS_SMTP_PORT, NEXUS_SMTP_USER, NEXUS_SMTP_PASSWORD, "
            "NEXUS_SMTP_FROM. Always uses STARTTLS."
        ),
        schema={
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient email address"},
                "subject": {"type": "string", "description": "Email subject"},
                "body": {"type": "string", "description": "Email body (plain text)"},
                "from_addr": {"type": "string", "description": "Sender (defaults to NEXUS_SMTP_FROM)"},
                "smtp_host": {"type": "string", "description": "SMTP host (defaults to NEXUS_SMTP_HOST)"},
                "smtp_port": {"type": "integer", "description": "SMTP port (default 587)"},
                "smtp_user": {"type": "string", "description": "SMTP user (defaults to NEXUS_SMTP_USER)"},
                "smtp_password": {"type": "string", "description": "SMTP password (defaults to NEXUS_SMTP_PASSWORD)"},
            },
            "required": ["to", "subject", "body"],
        },
        handler=send_email_notification,
    )
)

register_tool(
    ToolSpec(
        name="show_desktop_notification",
        description=(
            "Show a native desktop notification. Uses plyer if available; "
            "falls back to platform-specific commands (powershell MessageBox on Windows, "
            "osascript on macOS, notify-send on Linux)."
        ),
        schema={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Notification title"},
                "message": {"type": "string", "description": "Notification body"},
                "app_name": {"type": "string", "description": "App name shown in notification", "default": "NEXUS IDE"},
            },
            "required": ["title", "message"],
        },
        handler=show_desktop_notification,
    )
)
