"""
Cross-device conversation store.

A single SQLite-backed transcript shared by every Jarvis surface
(voice on PC, mobile app, dashboard). Brain reads recent turns from here
instead of an in-memory list, so a conversation started on the phone
continues seamlessly when the user walks up to the PC.

Schema:
    turns(id, ts, role, content, source, lang)

role:    "user" | "assistant" | "system"
source:  "voice" | "mobile" | "dashboard" | "scheduler" | "system"
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime
from pathlib import Path

_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "conversation.db"
_lock = threading.Lock()


def _conn() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(_DB_PATH, check_same_thread=False)


def _init() -> None:
    with _lock, _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS turns (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                ts      TEXT NOT NULL,
                role    TEXT NOT NULL,
                content TEXT NOT NULL,
                source  TEXT NOT NULL DEFAULT 'voice',
                lang    TEXT NOT NULL DEFAULT 'en'
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_turns_ts ON turns(ts)")
        c.commit()


_init()


def append(role: str, content: str, *, source: str = "voice", lang: str = "en") -> None:
    if not content:
        return
    ts = datetime.now().isoformat(timespec="seconds")
    with _lock, _conn() as c:
        c.execute(
            "INSERT INTO turns (ts, role, content, source, lang) VALUES (?, ?, ?, ?, ?)",
            (ts, role, content, source, lang),
        )
        c.commit()


def recent(limit: int = 40) -> list[dict]:
    """Return the most recent N turns in chronological order (oldest first)."""
    with _conn() as c:
        rows = c.execute(
            "SELECT ts, role, content, source, lang FROM turns "
            "ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    rows.reverse()
    return [
        {"ts": r[0], "role": r[1], "content": r[2], "source": r[3], "lang": r[4]}
        for r in rows
    ]


def history_for_brain(limit: int = 40) -> list[dict]:
    """Format recent turns as OpenAI-style {role, content} messages."""
    return [
        {"role": t["role"], "content": t["content"]}
        for t in recent(limit)
        if t["role"] in ("user", "assistant", "system")
    ]


def clear() -> int:
    with _lock, _conn() as c:
        cur = c.execute("DELETE FROM turns")
        c.commit()
        return cur.rowcount or 0


def stats() -> dict:
    with _conn() as c:
        row = c.execute(
            "SELECT COUNT(*), MIN(ts), MAX(ts) FROM turns"
        ).fetchone()
    return {"count": row[0] or 0, "first": row[1], "last": row[2]}
