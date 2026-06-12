"""IMAP email client using Python's built-in imaplib and email modules."""

from __future__ import annotations

import email
import email.header
import email.message
import imaplib
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


def _decode_header_value(value: str) -> str:
    """Decode an email header value that may contain encoded-word sequences."""
    if not value:
        return ""
    try:
        decoded_parts = email.header.decode_header(value)
        result: list[str] = []
        for part, charset in decoded_parts:
            if isinstance(part, bytes):
                try:
                    result.append(part.decode(charset or "utf-8", errors="replace"))
                except Exception:
                    result.append(part.decode("utf-8", errors="replace"))
            else:
                result.append(part)
        return "".join(result)
    except Exception:
        return value


def _get_body_preview(msg: email.message.Message, max_length: int = 500) -> str:
    """Extract a plain-text preview from an email message."""
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type == "text/plain":
                try:
                    payload = part.get_payload(decode=True)
                    if payload:
                        body = payload.decode("utf-8", errors="replace")
                        break
                except Exception:
                    continue
            elif content_type == "text/html" and not body:
                try:
                    payload = part.get_payload(decode=True)
                    if payload:
                        html = payload.decode("utf-8", errors="replace")
                        body = re.sub(r"<[^>]+>", " ", html)
                        body = re.sub(r"\s+", " ", body).strip()
                except Exception:
                    continue
    else:
        try:
            payload = msg.get_payload(decode=True)
            if payload:
                body = payload.decode("utf-8", errors="replace")
        except Exception:
            pass
    return body[:max_length] if body else ""


def _get_full_body(msg: email.message.Message) -> str:
    """Extract the full text body from an email message."""
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type == "text/plain":
                try:
                    payload = part.get_payload(decode=True)
                    if payload:
                        body = payload.decode("utf-8", errors="replace")
                        break
                except Exception:
                    continue
            elif content_type == "text/html" and not body:
                try:
                    payload = part.get_payload(decode=True)
                    if payload:
                        body = payload.decode("utf-8", errors="replace")
                except Exception:
                    continue
    else:
        try:
            payload = msg.get_payload(decode=True)
            if payload:
                body = payload.decode("utf-8", errors="replace")
        except Exception:
            pass
    return body


def connect_imap(
    host: str,
    port: int,
    username: str,
    password: str,
    use_ssl: bool = True,
) -> imaplib.IMAP4_SSL | imaplib.IMAP4:
    """Connect to an IMAP server and return the authenticated connection.

    Args:
        host: IMAP server hostname.
        port: IMAP server port.
        username: Email account username.
        password: Email account password.
        use_ssl: Whether to use SSL/TLS connection.

    Returns:
        An authenticated IMAP connection object.

    Raises:
        ConnectionError: If connection or login fails.
    """
    try:
        if use_ssl:
            conn = imaplib.IMAP4_SSL(host, port)
        else:
            conn = imaplib.IMAP4(host, port)
        conn.login(username, password)
        logger.info("Connected to IMAP server %s:%s as %s", host, port, username)
        return conn
    except imaplib.IMAP4.error as e:
        logger.error("IMAP login failed for %s: %s", username, e)
        raise ConnectionError(f"IMAP login failed: {e}") from e
    except Exception as e:
        logger.error("IMAP connection failed to %s:%s: %s", host, port, e)
        raise ConnectionError(f"IMAP connection failed: {e}") from e


def _ensure_conn(
    conn: imaplib.IMAP4_SSL | imaplib.IMAP4 | None,
    host: str | None,
    port: int | None,
    username: str | None,
    password: str | None,
    use_ssl: bool,
) -> tuple[imaplib.IMAP4_SSL | imaplib.IMAP4, bool]:
    """Return a connection and a flag indicating whether we should close it."""
    if conn is not None:
        return conn, False
    if not all([host, port is not None, username, password]):
        raise ValueError("Connection or full credentials (host, port, username, password) are required")
    return connect_imap(host, port, username, password, use_ssl), True


def fetch_emails(
    folder: str = "INBOX",
    limit: int = 20,
    unread_only: bool = False,
    conn: imaplib.IMAP4_SSL | imaplib.IMAP4 | None = None,
    host: str | None = None,
    port: int | None = None,
    username: str | None = None,
    password: str | None = None,
    use_ssl: bool = True,
) -> list[dict[str, Any]]:
    """Fetch emails from an IMAP folder.

    Args:
        folder: IMAP folder to fetch from (default: INBOX).
        limit: Maximum number of emails to fetch.
        unread_only: If True, only fetch unread emails.
        conn: Existing IMAP connection (optional).
        host: IMAP server host (required if conn is not provided).
        port: IMAP server port (required if conn is not provided).
        username: IMAP username (required if conn is not provided).
        password: IMAP password (required if conn is not provided).
        use_ssl: Use SSL for new connections.

    Returns:
        List of email dicts with keys: id, subject, from, date, body_preview, unread.
    """
    conn, close_conn = _ensure_conn(conn, host, port, username, password, use_ssl)
    emails: list[dict[str, Any]] = []

    try:
        status, _ = conn.select(folder)
        if status != "OK":
            raise ConnectionError(f"Could not select folder {folder}")

        if unread_only:
            status, data = conn.search(None, "UNSEEN")
        else:
            status, data = conn.search(None, "ALL")

        if status != "OK" or not data or not data[0]:
            return []

        msg_ids = data[0].split()
        msg_ids = msg_ids[-limit:] if len(msg_ids) > limit else msg_ids
        msg_ids.reverse()

        # Pre-compute unread set when fetching ALL
        unread_ids: set[str | bytes] = set()
        if not unread_only:
            try:
                _, unseen_data = conn.search(None, "UNSEEN")
                if unseen_data and unseen_data[0]:
                    unread_ids = set(unseen_data[0].split())
            except Exception:
                pass

        for msg_id in msg_ids:
            status, msg_data = conn.fetch(msg_id, "(RFC822)")
            if status != "OK" or not msg_data:
                continue

            raw_msg = msg_data[0][1] if isinstance(msg_data[0], tuple) else None
            if raw_msg is None:
                continue

            msg = email.message_from_bytes(raw_msg)
            subject = _decode_header_value(msg.get("Subject", ""))
            from_addr = msg.get("From", "")
            date = msg.get("Date", "")
            body_preview = _get_body_preview(msg)

            if unread_only:
                unread = True
            else:
                unread = msg_id in unread_ids

            emails.append({
                "id": msg_id.decode("utf-8") if isinstance(msg_id, bytes) else str(msg_id),
                "subject": subject,
                "from": from_addr,
                "date": date,
                "body_preview": body_preview,
                "unread": unread,
            })

    except Exception as e:
        logger.error("Failed to fetch emails: %s", e)
        raise
    finally:
        if close_conn:
            try:
                conn.close()
                conn.logout()
            except Exception as e:
                logger.debug("Error closing IMAP connection: %s", e)

    return emails


def search_emails(
    query: str,
    folder: str = "INBOX",
    limit: int = 10,
    conn: imaplib.IMAP4_SSL | imaplib.IMAP4 | None = None,
    host: str | None = None,
    port: int | None = None,
    username: str | None = None,
    password: str | None = None,
    use_ssl: bool = True,
) -> list[dict[str, Any]]:
    """Search emails by subject or body.

    Args:
        query: Search query string.
        folder: IMAP folder to search.
        limit: Maximum results.
        conn: Existing IMAP connection (optional).
        host: IMAP server host (required if conn is not provided).
        port: IMAP server port (required if conn is not provided).
        username: IMAP username (required if conn is not provided).
        password: IMAP password (required if conn is not provided).
        use_ssl: Use SSL for new connections.

    Returns:
        List of matching email dicts.
    """
    conn, close_conn = _ensure_conn(conn, host, port, username, password, use_ssl)
    results: list[dict[str, Any]] = []

    try:
        status, _ = conn.select(folder)
        if status != "OK":
            raise ConnectionError(f"Could not select folder {folder}")

        # Try OR SUBJECT/BODY search; fallback to SUBJECT only, then ALL
        data = None
        quoted = query.replace('"', '\\"')
        for criteria in (
            f'(OR SUBJECT "{quoted}" BODY "{quoted}")',
            f'SUBJECT "{quoted}"',
        ):
            try:
                status, data = conn.search(None, criteria)
                if status == "OK" and data and data[0]:
                    break
            except Exception:
                continue

        if data is None or not data[0]:
            return []

        msg_ids = data[0].split()
        msg_ids = msg_ids[-limit:] if len(msg_ids) > limit else msg_ids
        msg_ids.reverse()

        # Pre-compute unread set
        unread_ids: set[str | bytes] = set()
        try:
            _, unseen_data = conn.search(None, "UNSEEN")
            if unseen_data and unseen_data[0]:
                unread_ids = set(unseen_data[0].split())
        except Exception:
            pass

        for msg_id in msg_ids:
            status, msg_data = conn.fetch(msg_id, "(RFC822)")
            if status != "OK" or not msg_data:
                continue

            raw_msg = msg_data[0][1] if isinstance(msg_data[0], tuple) else None
            if raw_msg is None:
                continue

            msg = email.message_from_bytes(raw_msg)
            subject = _decode_header_value(msg.get("Subject", ""))
            from_addr = msg.get("From", "")
            date = msg.get("Date", "")
            body_preview = _get_body_preview(msg)
            unread = msg_id in unread_ids

            results.append({
                "id": msg_id.decode("utf-8") if isinstance(msg_id, bytes) else str(msg_id),
                "subject": subject,
                "from": from_addr,
                "date": date,
                "body_preview": body_preview,
                "unread": unread,
            })

    except Exception as e:
        logger.error("Failed to search emails: %s", e)
        raise
    finally:
        if close_conn:
            try:
                conn.close()
                conn.logout()
            except Exception as e:
                logger.debug("Error closing IMAP connection: %s", e)

    return results


def mark_as_read(
    email_id: str,
    conn: imaplib.IMAP4_SSL | imaplib.IMAP4 | None = None,
    host: str | None = None,
    port: int | None = None,
    username: str | None = None,
    password: str | None = None,
    use_ssl: bool = True,
) -> bool:
    """Mark an email as read.

    Args:
        email_id: The IMAP message ID.
        conn: Existing IMAP connection (optional).
        host: IMAP server host (required if conn is not provided).
        port: IMAP server port (required if conn is not provided).
        username: IMAP username (required if conn is not provided).
        password: IMAP password (required if conn is not provided).
        use_ssl: Use SSL for new connections.

    Returns:
        True if successful, False otherwise.
    """
    conn, close_conn = _ensure_conn(conn, host, port, username, password, use_ssl)

    try:
        status, _ = conn.select("INBOX")
        if status != "OK":
            return False

        msg_id_bytes = email_id.encode("utf-8") if isinstance(email_id, str) else email_id
        conn.store(msg_id_bytes, "+FLAGS", "\\Seen")
        return True
    except Exception as e:
        logger.error("Failed to mark email %s as read: %s", email_id, e)
        return False
    finally:
        if close_conn:
            try:
                conn.close()
                conn.logout()
            except Exception as e:
                logger.debug("Error closing IMAP connection: %s", e)


def get_email_body(
    email_id: str,
    conn: imaplib.IMAP4_SSL | imaplib.IMAP4 | None = None,
    host: str | None = None,
    port: int | None = None,
    username: str | None = None,
    password: str | None = None,
    use_ssl: bool = True,
) -> str:
    """Get the full body of an email.

    Args:
        email_id: The IMAP message ID.
        conn: Existing IMAP connection (optional).
        host: IMAP server host (required if conn is not provided).
        port: IMAP server port (required if conn is not provided).
        username: IMAP username (required if conn is not provided).
        password: IMAP password (required if conn is not provided).
        use_ssl: Use SSL for new connections.

    Returns:
        The full email body text.
    """
    conn, close_conn = _ensure_conn(conn, host, port, username, password, use_ssl)

    try:
        msg_id_bytes = email_id.encode("utf-8") if isinstance(email_id, str) else email_id
        status, msg_data = conn.fetch(msg_id_bytes, "(RFC822)")
        if status != "OK" or not msg_data:
            return ""

        raw_msg = msg_data[0][1] if isinstance(msg_data[0], tuple) else None
        if raw_msg is None:
            return ""

        msg = email.message_from_bytes(raw_msg)
        return _get_full_body(msg)
    except Exception as e:
        logger.error("Failed to get email body for %s: %s", email_id, e)
        return ""
    finally:
        if close_conn:
            try:
                conn.close()
                conn.logout()
            except Exception as e:
                logger.debug("Error closing IMAP connection: %s", e)
