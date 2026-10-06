"""Notification tools — webhooks, email alerts, desktop notifications.

Provides three notification channels:
- ``send_webhook`` — POST a JSON payload to a webhook URL (Slack/Discord/Teams compatible)
- ``send_email_notification`` — send a simple email via SMTP (requires email config)
- ``show_desktop_notification`` — show a native desktop notification (cross-platform via plyer)

``send_webhook`` takes a model-supplied URL, so it carries an SSRF barrier: the
URL is normalised with :func:`backend.tools.safe_http.normalize_public_http_url`
and dispatched over a :class:`~backend.tools.safe_http.PublicAddressHTTPTransport`
that re-checks every resolved address at connect time, for every redirect hop.
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
from email.message import EmailMessage
from typing import Any

import httpx

from backend.tools.registry import ToolSpec, register_tool
from backend.tools.safe_http import PublicAddressHTTPTransport, normalize_public_http_url

logger = logging.getLogger(__name__)

#: Only a short success/failure snippet of the webhook response is returned, so
#: the read is bounded. An endpoint that streams indefinitely must not be able
#: to exhaust this process's memory.
_MAX_WEBHOOK_RESPONSE_BYTES = 64 * 1024

#: Snippet length actually handed back to the caller (unchanged public contract).
_WEBHOOK_SNIPPET_CHARS = 1000


def _build_client(timeout: float) -> httpx.AsyncClient:
    """Guarded HTTP client: every connect resolves the host and re-checks it."""
    return httpx.AsyncClient(
        timeout=httpx.Timeout(timeout),
        follow_redirects=True,
        trust_env=False,
        transport=PublicAddressHTTPTransport(),
    )


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

    SSRF barrier: the URL must be an absolute http/https URL on the standard
    port that resolves to a public IP address. Redirect hops are re-checked at
    connect time, so a webhook host that redirects into loopback or the cloud
    metadata address never gets a socket.

    Args:
        url: Webhook URL.
        payload: Optional dict payload (sent as JSON body).
        message: Convenience field for plain-text messages.
        title: Optional title (for Slack/Discord/Teams).
        timeout: Request timeout in seconds (1-30).
    """
    timeout = min(max(timeout, 1), 30)

    # Screen the URL before anything else: no DNS, no socket, no payload work.
    # ``normalize_public_http_url`` is what restricts the scheme to http/https,
    # rejects credentials in the URL, rejects non-standard ports, rejects
    # local/reserved hostnames, and rejects literal non-public IP addresses.
    try:
        target_url = normalize_public_http_url(url)
    except ValueError as exc:
        return {"error": f"Blocked webhook URL: {exc}", "url": str(url)[:2000]}

    # Build payload if message/title provided
    body: dict[str, Any]
    body = dict(payload) if payload is not None else {}

    if message is not None or title is not None:
        # Auto-format based on URL
        url_lower = target_url.lower()
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

    try:
        async with _build_client(timeout) as client, client.stream(
            "POST", target_url, json=body
        ) as resp:
            status = resp.status_code
            chunks: list[bytes] = []
            total = 0
            async for chunk in resp.aiter_bytes():
                chunks.append(chunk)
                total += len(chunk)
                if total >= _MAX_WEBHOOK_RESPONSE_BYTES:
                    break
            text = b"".join(chunks).decode(errors="replace")
    except httpx.TimeoutException:
        return {"error": f"Webhook timeout after {timeout}s", "url": url}
    except httpx.HTTPError as e:
        return {"error": f"Webhook HTTP error: {e}", "url": url}
    except TimeoutError:
        return {"error": f"Webhook timeout after {timeout}s", "url": url}
    except Exception as e:  # noqa: BLE001
        logger.exception("webhook send failed")
        return {"error": str(e), "url": url}

    return {
        "status": status,
        "ok": 200 <= status < 300,
        "response": text[:_WEBHOOK_SNIPPET_CHARS],
    }


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
            "or `message`+`title` for convenience. The URL must be an absolute "
            "http/https URL on the standard port resolving to a public IP address; "
            "private, loopback and link-local targets (and redirect hops to them) "
            "are refused."
        ),
        schema={
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "maxLength": 2000,
                    "description": (
                        "Webhook URL. Absolute http or https, standard port, public "
                        "IP address only."
                    ),
                },
                "payload": {"type": "object", "description": "JSON payload (dict)"},
                "message": {"type": "string", "description": "Plain text message"},
                "title": {"type": "string", "description": "Optional title"},
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (1-30)",
                    "default": 10,
                    "minimum": 1,
                    "maximum": 30,
                },
            },
            "required": ["url"],
        },
        handler=send_webhook,
        # An outbound POST with a caller-supplied body and an attacker-chosen
        # destination is not a low-risk read. "medium" is the truthful floor;
        # raising it to "high" would additionally require human confirmation,
        # which is a deliberate product decision (see registry._CONFIRMATION_TOOLS).
        risk_level="medium",
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
