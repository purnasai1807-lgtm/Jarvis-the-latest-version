"""
Continue-from-last-session — short brief Jarvis speaks at boot to remind the
user where they left off.

Pulls together: yesterday's git activity, any tasks still running/pending,
any pending plans, and the last user/assistant turns from the cross-device
conversation. Returns a 2-4 sentence string ready for TTS, or empty string
if nothing interesting to report.

Use it once at startup, AFTER the greeting:

    from core import continue_session
    brief = continue_session.compose_brief()
    if brief:
        tts.speak(brief)
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from loguru import logger


def _yesterday_git_lines() -> list[str]:
    """Compact summary of yesterday's commits across known repos."""
    try:
        from core import context
        # context.git_summary returns multi-line per repo; squash to top hits
        raw = context.git_summary(since="1 day ago")
        if not raw or "No commits" in raw:
            return []
        # Pull only commit lines (start with "  •")
        commit_lines: list[str] = []
        repo_for_line = ""
        for line in raw.splitlines():
            if line.startswith("📁"):
                repo_for_line = line.split()[1] if len(line.split()) > 1 else ""
            elif line.lstrip().startswith("•"):
                msg = line.lstrip("• ").strip()
                # strip the leading short-hash to make it speakable
                parts = msg.split(" ", 1)
                if len(parts) == 2 and len(parts[0]) < 12:
                    msg = parts[1]
                commit_lines.append(f"{repo_for_line}: {msg}" if repo_for_line else msg)
        return commit_lines[:3]
    except Exception as exc:
        logger.debug(f"yesterday git: {exc}")
        return []


def _running_tasks() -> list[dict]:
    try:
        from core import tasks
        rows = tasks.list_recent(limit=10)
        return [r for r in rows if r["status"] in ("running", "pending")]
    except Exception:
        return []


def _last_done_task() -> dict | None:
    try:
        from core import tasks
        rows = tasks.list_recent(limit=10)
        # most recent that's done in the last 24h
        cutoff = datetime.now() - timedelta(hours=24)
        for r in rows:
            if r["status"] != "done":
                continue
            try:
                ts = datetime.fromisoformat(r["updated_at"])
                if ts >= cutoff:
                    return r
            except Exception:
                continue
        return None
    except Exception:
        return None


def _pending_plan() -> dict | None:
    try:
        from core import plans
        return plans.most_recent_pending()
    except Exception:
        return None


def _last_conversation_turn() -> dict | None:
    try:
        from core import conversation
        turns = conversation.recent(2)
        return turns[-1] if turns else None
    except Exception:
        return None


def _greeting_part() -> str:
    h = datetime.now().hour
    if h < 5:
        return "Welcome back, sir"
    if h < 12:
        return "Good morning, sir"
    if h < 18:
        return "Good afternoon, sir"
    return "Good evening, sir"


def compose_brief() -> str:
    """Build a short spoken brief, or '' if nothing worth saying."""
    parts: list[str] = []

    # Pending plans take priority — user may have walked away mid-confirm
    plan = _pending_plan()
    if plan:
        parts.append(f"There's still a pending plan from earlier — "
                     f"#{plan['id']}: {plan['summary'][:80]}. "
                     "Say 'confirm' or 'cancel' to clear it.")

    # Active background tasks
    running = _running_tasks()
    if running:
        names = ", ".join(f"#{r['id']}" for r in running[:3])
        parts.append(f"You have {len(running)} background task(s) "
                     f"still running: {names}.")

    # Most recent completed task (if recent)
    if not running:
        done = _last_done_task()
        if done:
            prompt = done["prompt"][:80]
            parts.append(f"Your last task — '{prompt}' — finished. "
                         "Tap the dashboard for the result.")

    # Yesterday's git activity (only if user is at PC)
    git_lines = _yesterday_git_lines()
    if git_lines:
        first = git_lines[0]
        if len(git_lines) == 1:
            parts.append(f"Yesterday you committed: {first[:120]}.")
        else:
            parts.append(f"Yesterday you committed across "
                         f"{len(git_lines)} item(s); the latest was {first[:100]}.")

    if not parts:
        return ""

    head = _greeting_part()
    body = " ".join(parts)
    # Cap so TTS doesn't run forever
    return f"{head}. {body}"[:600]
