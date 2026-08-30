"""
Watches — periodic monitoring of URLs with fire-when conditions.

Two modes:
    "changed"            fires when the rendered page text changes (hash diff)
    free-form question   LLM evaluates the page each tick; fires on no→yes

Examples the user might set:
    watch_url("https://emag.ro/...", condition="changed", interval_minutes=60)
    watch_url("https://github.com/owner/repo/pull/42",
              condition="has the PR been approved or merged?",
              interval_minutes=15)
    watch_url("https://shop.example.com/item",
              condition="is the price under 1500 lei?",
              interval_minutes=30)

A scheduler tick (every 60s) calls `tick()` which checks any watch whose
next-due time has elapsed. When a check fires, the watch is auto-paused
(status='fired'); the user reactivates manually via the API or `re-watch`.
This avoids notification spam if the condition stays true.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger


_DB = Path(__file__).resolve().parent.parent / "data" / "watches.db"
_lock = threading.Lock()


def _conn() -> sqlite3.Connection:
    _DB.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(_DB, check_same_thread=False)


def _init() -> None:
    with _lock, _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS watches (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                url             TEXT NOT NULL,
                condition       TEXT NOT NULL DEFAULT 'changed',
                label           TEXT NOT NULL DEFAULT '',
                interval_seconds INTEGER NOT NULL DEFAULT 1800,
                status          TEXT NOT NULL DEFAULT 'active',
                hits            INTEGER NOT NULL DEFAULT 0,
                state_json      TEXT NOT NULL DEFAULT '{}',
                last_check_at   TEXT,
                last_message    TEXT NOT NULL DEFAULT '',
                created_at      TEXT NOT NULL
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_watches_status ON watches(status)")
        c.commit()


_init()


# ── CRUD ────────────────────────────────────────────────────────
def create(url: str, condition: str = "changed",
           interval_minutes: int = 30, label: str = "") -> int:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    interval = max(60, int(interval_minutes) * 60)
    now = datetime.now().isoformat(timespec="seconds")

    with _lock, _conn() as c:
        cur = c.execute(
            """INSERT INTO watches (url, condition, label, interval_seconds,
                                    status, state_json, created_at)
               VALUES (?, ?, ?, ?, 'active', '{}', ?)""",
            (url, condition, label, interval, now),
        )
        wid = int(cur.lastrowid or 0)
        c.commit()
    logger.info(f"watch[{wid}] created url={url[:60]} cond={condition[:40]}")
    return wid


def stop(watch_id: int) -> bool:
    with _lock, _conn() as c:
        cur = c.execute(
            "UPDATE watches SET status='archived' WHERE id=? AND status!='archived'",
            (watch_id,),
        )
        c.commit()
        return (cur.rowcount or 0) > 0


def reactivate(watch_id: int) -> bool:
    """Re-arm a watch that previously fired."""
    with _lock, _conn() as c:
        cur = c.execute(
            "UPDATE watches SET status='active' WHERE id=?",
            (watch_id,),
        )
        c.commit()
        return (cur.rowcount or 0) > 0


def get(watch_id: int) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM watches WHERE id=?",
                        (watch_id,)).fetchone()
        cols = [d[1] for d in c.execute("PRAGMA table_info(watches)").fetchall()]
    return dict(zip(cols, row)) if row else None


def list_all(include_archived: bool = False) -> list[dict]:
    q = "SELECT * FROM watches"
    if not include_archived:
        q += " WHERE status != 'archived'"
    q += " ORDER BY id DESC"
    with _conn() as c:
        rows = c.execute(q).fetchall()
        cols = [d[1] for d in c.execute("PRAGMA table_info(watches)").fetchall()]
    return [dict(zip(cols, r)) for r in rows]


# ── Tick (scheduler-driven) ─────────────────────────────────────
def tick() -> int:
    """Run any active watches whose next-check time has passed.
    Returns the count of watches actually checked."""
    now = datetime.now().timestamp()
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM watches WHERE status='active'"
        ).fetchall()
        cols = [d[1] for d in c.execute("PRAGMA table_info(watches)").fetchall()]

    checked = 0
    for r in rows:
        watch = dict(zip(cols, r))
        last = watch.get("last_check_at")
        last_ts = 0.0
        if last:
            try:
                last_ts = datetime.fromisoformat(last).timestamp()
            except Exception:
                last_ts = 0.0
        if last_ts and (now - last_ts) < watch["interval_seconds"]:
            continue  # not due yet

        try:
            fired, message, new_state = _check_one(watch)
        except Exception as exc:
            logger.warning(f"watch[{watch['id']}] check failed: {exc}")
            _record_check(watch["id"], watch.get("state_json", "{}"),
                          fired=False, message=f"error: {exc}")
            continue

        _record_check(watch["id"], json.dumps(new_state),
                      fired=fired, message=message)
        if fired:
            _notify_fire(watch, message)
        checked += 1

    return checked


def _record_check(watch_id: int, state_json: str, *,
                  fired: bool, message: str) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with _lock, _conn() as c:
        if fired:
            c.execute(
                """UPDATE watches
                      SET state_json=?, last_check_at=?, last_message=?,
                          hits=hits+1, status='fired'
                    WHERE id=?""",
                (state_json, now, message[:300], watch_id),
            )
        else:
            c.execute(
                """UPDATE watches
                      SET state_json=?, last_check_at=?, last_message=?
                    WHERE id=?""",
                (state_json, now, message[:300], watch_id),
            )
        c.commit()


# ── Condition checkers ──────────────────────────────────────────
def _check_one(watch: dict) -> tuple[bool, str, dict]:
    """Run the appropriate checker for this watch.

    Returns (fired?, message, new_state_dict).
    """
    url = watch["url"]
    cond = (watch.get("condition") or "changed").strip()
    try:
        prev = json.loads(watch.get("state_json") or "{}")
    except Exception:
        prev = {}

    from tools.browser import read_page
    text = (read_page(url) or "").strip()
    if not text or text.startswith("Failed to read"):
        return (False, "page unreadable", prev)

    # ── Mode: changed ────────────────────────────────────────
    if cond.lower() in ("changed", "change", "any change"):
        digest = hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()
        old_hash = prev.get("hash")
        new_state = {"hash": digest, "excerpt": text[:300]}
        if old_hash is None:
            return (False, "seeded", new_state)  # first observation → seed only
        if old_hash != digest:
            label = watch.get("label") or url[:60]
            return (True, f"Changed: {label}", new_state)
        return (False, "no change", new_state)

    # ── Mode: free-form LLM question ─────────────────────────
    answer = _llm_yes_no(cond, text[:4000])
    new_state = {"was_yes": answer, "excerpt": text[:300]}
    if answer and not prev.get("was_yes"):
        label = watch.get("label") or url[:60]
        return (True, f"Condition met for {label}: {cond[:80]}", new_state)
    return (False, "condition not met" if not answer else "still true",
            new_state)


def _llm_yes_no(question: str, page_text: str) -> bool:
    """Ask the LLM yes/no whether the condition holds given the page text."""
    try:
        from core.config import load_config
        from openai import OpenAI

        cfg = load_config()
        oai = cfg.get("apis", {}).get("openai", {})
        client = OpenAI(api_key=oai.get("api_key", ""))
        resp = client.chat.completions.create(
            model=oai.get("model", "gpt-4.1-mini"),
            max_tokens=4,
            messages=[
                {"role": "system",
                 "content": ("Answer with ONLY 'yes' or 'no'. Given the web "
                             "page content and a yes/no question, decide if "
                             "the condition is currently true based ONLY on "
                             "what the page says. Default to 'no' when unclear.")},
                {"role": "user",
                 "content": f"Question: {question}\n\nPage content:\n{page_text}"},
            ],
        )
        out = (resp.choices[0].message.content or "").strip().lower()
        return out.startswith("y")
    except Exception as exc:
        logger.warning(f"watch LLM yes/no failed: {exc}")
        return False


# ── Notification ────────────────────────────────────────────────
def _notify_fire(watch: dict, message: str) -> None:
    try:
        from core import router
        title = "🔔 Watch fired"
        body = (message + " — " + watch["url"])[:240]
        router.notify(
            title=title,
            body=body,
            urgency="normal",
            kind="watch",
            data={"watch_id": str(watch["id"]), "url": watch["url"]},
        )
    except Exception as exc:
        logger.warning(f"watch notify failed: {exc}")
