"""
Async task manager — long-running work that doesn't block the voice loop.

When the user says "find me the best X", "research Y", "monitor the price of Z",
the brain dispatches a Task instead of trying to answer in one round of tool
calls. The task runs on a worker thread, streams progress to a SQLite log,
and notifies the user on completion via core.router (which picks HUD / TTS /
push automatically based on presence).

Schema:
    tasks(id, kind, prompt, status, result, log, created_at, updated_at)

status values:
    pending   created, not started yet
    running   worker thread is active
    done      finished with a result
    failed    threw an exception
    cancelled requested cancellation (best-effort — workers must check is_cancelled)

Workers are plain callables: `runner(task_id: int, prompt: str) -> str`.
They can call `tasks.append_log(task_id, line)` to stream progress and
`tasks.is_cancelled(task_id)` to honour cancel requests.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

from loguru import logger

_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "tasks.db"
_lock = threading.Lock()


def _conn() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(_DB_PATH, check_same_thread=False)


def _init() -> None:
    with _lock, _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                kind        TEXT NOT NULL,
                prompt      TEXT NOT NULL,
                status      TEXT NOT NULL DEFAULT 'pending',
                result      TEXT NOT NULL DEFAULT '',
                log         TEXT NOT NULL DEFAULT '',
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)")
        c.commit()


_init()

_runners: dict[str, Callable[[int, str], str]] = {}
_cancelled: set[int] = set()


# ── Runner registration ──────────────────────────────────────────
def register_runner(kind: str, runner: Callable[[int, str], str]) -> None:
    _runners[kind] = runner
    logger.info(f"tasks: registered runner for kind={kind}")


# ── Spawn ────────────────────────────────────────────────────────
def spawn(prompt: str, kind: str = "research") -> int:
    """Create a task row and start the worker thread. Returns the task id."""
    if kind not in _runners:
        raise ValueError(f"no runner registered for kind '{kind}'")

    now = datetime.now().isoformat(timespec="seconds")
    with _lock, _conn() as c:
        cur = c.execute(
            "INSERT INTO tasks (kind, prompt, status, created_at, updated_at) "
            "VALUES (?, ?, 'pending', ?, ?)",
            (kind, prompt, now, now),
        )
        task_id = int(cur.lastrowid or 0)
        c.commit()

    threading.Thread(
        target=_run, args=(task_id, kind, prompt),
        name=f"task-{task_id}", daemon=True,
    ).start()
    logger.info(f"task[{task_id}] spawned kind={kind} prompt={prompt[:80]}")
    return task_id


def _run(task_id: int, kind: str, prompt: str) -> None:
    runner = _runners.get(kind)
    if runner is None:
        _set_status(task_id, "failed", result=f"No runner for kind '{kind}'")
        return

    _set_status(task_id, "running")
    t0 = time.time()
    try:
        result = runner(task_id, prompt)
        if is_cancelled(task_id):
            _set_status(task_id, "cancelled", result=str(result)[:8000])
            _notify_done(task_id, kind, prompt, result, cancelled=True)
            return
        _set_status(task_id, "done", result=str(result)[:8000])
        elapsed = time.time() - t0
        logger.info(f"task[{task_id}] done in {elapsed:.1f}s")
        _notify_done(task_id, kind, prompt, result)
    except Exception as exc:
        logger.exception(f"task[{task_id}] failed")
        _set_status(task_id, "failed", result=f"{exc}")
        _notify_done(task_id, kind, prompt, f"{exc}", failed=True)
    finally:
        _cancelled.discard(task_id)


def _notify_done(task_id: int, kind: str, prompt: str, result: object,
                 *, failed: bool = False, cancelled: bool = False) -> None:
    """Push completion to the user via core.router."""
    try:
        from core import router
        head = "Task failed" if failed else "Task cancelled" if cancelled else "Task done"
        prompt_short = (prompt[:60] + "…") if len(prompt) > 60 else prompt
        body_preview = str(result)[:240]
        router.notify(
            title=f"✓ {head}: {prompt_short}",
            body=body_preview,
            urgency="normal" if not failed else "low",
            kind="task",
            data={"task_id": str(task_id), "kind": kind},
        )
    except Exception as exc:
        logger.warning(f"task notify failed: {exc}")


# ── Status / log mutators ────────────────────────────────────────
def _set_status(task_id: int, status: str, *, result: str | None = None) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with _lock, _conn() as c:
        if result is None:
            c.execute(
                "UPDATE tasks SET status=?, updated_at=? WHERE id=?",
                (status, now, task_id),
            )
        else:
            c.execute(
                "UPDATE tasks SET status=?, result=?, updated_at=? WHERE id=?",
                (status, result, now, task_id),
            )
        c.commit()


def append_log(task_id: int, line: str) -> None:
    """Append a progress line to a task's log (visible in the mobile UI)."""
    line = line.strip()
    if not line:
        return
    stamp = datetime.now().strftime("%H:%M:%S")
    entry = f"[{stamp}] {line}\n"
    with _lock, _conn() as c:
        c.execute(
            "UPDATE tasks SET log = log || ?, updated_at=? WHERE id=?",
            (entry, datetime.now().isoformat(timespec="seconds"), task_id),
        )
        c.commit()


def cancel(task_id: int) -> bool:
    """Mark a task as cancellation-requested. Workers must check `is_cancelled`."""
    _cancelled.add(task_id)
    return True


def is_cancelled(task_id: int) -> bool:
    return task_id in _cancelled


# ── Read accessors ───────────────────────────────────────────────
def get(task_id: int) -> dict | None:
    with _conn() as c:
        row = c.execute(
            "SELECT id, kind, prompt, status, result, log, created_at, updated_at "
            "FROM tasks WHERE id = ?",
            (task_id,),
        ).fetchone()
    if not row:
        return None
    return _row_to_dict(row)


def list_recent(limit: int = 30) -> list[dict]:
    limit = max(1, min(limit, 200))
    with _conn() as c:
        rows = c.execute(
            "SELECT id, kind, prompt, status, result, log, created_at, updated_at "
            "FROM tasks ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def _row_to_dict(r: tuple) -> dict:
    return {
        "id": r[0],
        "kind": r[1],
        "prompt": r[2],
        "status": r[3],
        "result": r[4],
        "log": r[5],
        "created_at": r[6],
        "updated_at": r[7],
    }
