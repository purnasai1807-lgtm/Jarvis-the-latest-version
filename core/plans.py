"""
Proposed plans — staging area for multi-step actions that need user
confirmation before executing.

Use case: the user says "reply to Andrei on WhatsApp that I'll be 20 min late
AND move the meeting with Maria to 16:00". The brain shouldn't fire both
actions blindly — it should propose the plan, narrate it back, then wait
for "confirm" or "cancel".

Schema (SQLite):
    plans(id, summary, steps_json, status, created_at, executed_at)

status: pending | confirmed | cancelled | failed
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from loguru import logger


_DB = Path(__file__).resolve().parent.parent / "data" / "plans.db"
_lock = threading.Lock()
_brain = None  # injected at boot — used to look up tool handlers


def set_brain(brain) -> None:
    global _brain
    _brain = brain


def _conn() -> sqlite3.Connection:
    _DB.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(_DB, check_same_thread=False)


def _init() -> None:
    with _lock, _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS plans (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                summary     TEXT NOT NULL,
                steps_json  TEXT NOT NULL,
                status      TEXT NOT NULL DEFAULT 'pending',
                results     TEXT NOT NULL DEFAULT '',
                created_at  TEXT NOT NULL,
                executed_at TEXT
            )
        """)
        c.commit()


_init()


# ── CRUD ────────────────────────────────────────────────────────
def create(summary: str, steps: list[dict]) -> int:
    """Stage a new plan. Returns the plan id."""
    if not steps:
        raise ValueError("plan must have at least one step")
    cleaned: list[dict] = []
    for s in steps:
        if not isinstance(s, dict):
            continue
        tool = str(s.get("tool", "")).strip()
        if not tool:
            continue
        cleaned.append({
            "tool": tool,
            "args": dict(s.get("args") or {}),
            "summary": str(s.get("summary") or "")[:200],
        })
    if not cleaned:
        raise ValueError("no valid steps in plan")

    now = datetime.now().isoformat(timespec="seconds")
    with _lock, _conn() as c:
        cur = c.execute(
            """INSERT INTO plans (summary, steps_json, status, created_at)
               VALUES (?, ?, 'pending', ?)""",
            (summary[:300], json.dumps(cleaned), now),
        )
        pid = int(cur.lastrowid or 0)
        c.commit()
    logger.info(f"plan[{pid}] proposed: {summary[:80]} ({len(cleaned)} step(s))")
    return pid


def get(plan_id: int) -> dict | None:
    with _conn() as c:
        row = c.execute(
            "SELECT id, summary, steps_json, status, results, created_at, executed_at "
            "FROM plans WHERE id=?", (plan_id,),
        ).fetchone()
    return _row_to_dict(row) if row else None


def most_recent_pending() -> dict | None:
    with _conn() as c:
        row = c.execute(
            "SELECT id, summary, steps_json, status, results, created_at, executed_at "
            "FROM plans WHERE status='pending' "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return _row_to_dict(row) if row else None


def _row_to_dict(r) -> dict:
    return {
        "id": r[0],
        "summary": r[1],
        "steps": json.loads(r[2]),
        "status": r[3],
        "results": r[4],
        "created_at": r[5],
        "executed_at": r[6],
    }


# ── Execution ───────────────────────────────────────────────────
def execute(plan_id: int) -> dict:
    """Run every step of the plan in order. Stops on first hard failure
    (returns False from handler), but logs all results."""
    plan = get(plan_id)
    if not plan:
        return {"ok": False, "error": "plan not found"}
    if plan["status"] != "pending":
        return {"ok": False, "error": f"plan is {plan['status']}"}
    if _brain is None:
        return {"ok": False, "error": "brain not wired"}

    handlers = _brain._tool_handlers  # type: ignore[attr-defined]
    results: list[dict] = []
    failed = False
    for i, step in enumerate(plan["steps"]):
        name = step["tool"]
        args = step.get("args") or {}
        handler = handlers.get(name)
        if handler is None:
            results.append({"step": i, "tool": name, "ok": False,
                            "error": f"unknown tool: {name}"})
            failed = True
            break
        try:
            res = handler(**args) if args else handler()
            results.append({"step": i, "tool": name, "ok": True,
                            "result": str(res)[:300]})
        except Exception as exc:
            results.append({"step": i, "tool": name, "ok": False,
                            "error": str(exc)[:200]})
            failed = True
            break

    status = "failed" if failed else "confirmed"
    now = datetime.now().isoformat(timespec="seconds")
    with _lock, _conn() as c:
        c.execute(
            "UPDATE plans SET status=?, results=?, executed_at=? WHERE id=?",
            (status, json.dumps(results), now, plan_id),
        )
        c.commit()

    return {"ok": not failed, "plan_id": plan_id, "status": status,
            "results": results}


def cancel(plan_id: int) -> bool:
    with _lock, _conn() as c:
        cur = c.execute(
            "UPDATE plans SET status='cancelled' WHERE id=? AND status='pending'",
            (plan_id,),
        )
        c.commit()
        return (cur.rowcount or 0) > 0


def cancel_pending() -> int | None:
    """Cancel the most recent pending plan; returns its id or None."""
    plan = most_recent_pending()
    if not plan:
        return None
    cancel(plan["id"])
    return plan["id"]
