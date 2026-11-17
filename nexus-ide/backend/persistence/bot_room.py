"""Durable pins and unread signatures for bot and group conversations."""

from __future__ import annotations

from typing import Any

from backend.persistence.db import get_db

_MAX_ITEMS = 500
_MAX_SIGNATURE_LEN = 512


def get_room_memory(owner: str) -> dict[str, Any]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT item_id, pinned, seen_signature FROM bot_room_memory WHERE owner = ?",
            (owner,),
        ).fetchall()
    pins: list[str] = []
    seen: dict[str, str] = {}
    for row in rows:
        item_id = str(row["item_id"] or "").strip()
        if not item_id:
            continue
        if int(row["pinned"] or 0) == 1 and item_id not in pins:
            pins.append(item_id)
        sig = str(row["seen_signature"] or "")
        if sig:
            seen[item_id] = sig
    return {"pins": pins[:_MAX_ITEMS], "seen": seen}


def update_room_memory(
    owner: str,
    *,
    pins: list[str] | None = None,
    seen: dict[str, str] | None = None,
) -> dict[str, Any]:
    with get_db() as conn:
        if pins is not None:
            clean_pins = [str(item).strip() for item in pins if str(item).strip()][:_MAX_ITEMS]
            for item_id in clean_pins:
                conn.execute(
                    """INSERT INTO bot_room_memory (owner, item_id, pinned, seen_signature, updated_at)
                       VALUES (?, ?, 1, '', strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                       ON CONFLICT(owner, item_id) DO UPDATE SET
                           pinned = 1, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')""",
                    (owner, item_id),
                )
            for row in conn.execute(
                "SELECT item_id FROM bot_room_memory WHERE owner = ? AND pinned = 1",
                (owner,),
            ).fetchall():
                if str(row[0]) not in clean_pins:
                    conn.execute(
                        "UPDATE bot_room_memory SET pinned = 0, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE owner = ? AND item_id = ?",
                        (owner, str(row[0])),
                    )
        if seen is not None:
            for raw_id, raw_sig in seen.items():
                item_id = str(raw_id).strip()
                sig = str(raw_sig or "")[:_MAX_SIGNATURE_LEN]
                if not item_id:
                    continue
                conn.execute(
                    """INSERT INTO bot_room_memory (owner, item_id, pinned, seen_signature, updated_at)
                       VALUES (?, ?, 0, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                       ON CONFLICT(owner, item_id) DO UPDATE SET
                           seen_signature = excluded.seen_signature,
                           updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')""",
                    (owner, item_id, sig),
                )
    return get_room_memory(owner)