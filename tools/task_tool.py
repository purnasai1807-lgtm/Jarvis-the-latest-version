"""
`start_task` tool — lets the brain dispatch long-running work to the async
task manager instead of trying to answer in one tool-call round.

When the user says things like "find me the best 4K monitor under 2000 lei",
"compare X vs Y", "research the new EU AI Act", the brain should call
start_task(prompt=..., kind="research") and respond with one short sentence
acknowledging the work. The task notifies the user when it finishes via
core.router (HUD/TTS/push as appropriate).
"""

from __future__ import annotations

from loguru import logger

from core import tasks


# Importing tools.research has the side-effect of registering the runner.
from tools import research  # noqa: F401


def start_task(prompt: str, kind: str = "research") -> str:
    """Spawn a background task and return a short status message."""
    if not prompt or not prompt.strip():
        return "Refused — empty prompt."
    try:
        task_id = tasks.spawn(prompt.strip(), kind=kind)
    except Exception as exc:
        logger.error(f"start_task failed: {exc}")
        return f"Couldn't start the task: {exc}"
    return (f"Started background task #{task_id} ({kind}). "
            "I'll let you know when it's done.")


def list_tasks(limit: int = 5) -> str:
    """Return a one-line summary per recent task — quick "what's running?" peek."""
    rows = tasks.list_recent(limit=max(1, min(limit, 20)))
    if not rows:
        return "No tasks yet."
    lines = []
    for r in rows:
        prompt = r["prompt"][:60] + ("…" if len(r["prompt"]) > 60 else "")
        lines.append(f"#{r['id']} [{r['status']}] {r['kind']}: {prompt}")
    return "\n".join(lines)


def task_status(task_id: int = 0) -> str:
    """Return detailed status + recent log for one task. Defaults to the most
    recent running/pending task — convenient for 'how's it going?'."""
    if task_id and task_id > 0:
        row = tasks.get(int(task_id))
        if not row:
            return f"No task #{task_id}."
    else:
        rows = tasks.list_recent(limit=10)
        active = [r for r in rows if r["status"] in ("running", "pending")]
        if not active and not rows:
            return "No tasks yet."
        row = active[0] if active else rows[0]

    log_tail = row.get("log", "").strip().splitlines()[-10:]
    log_block = "\n  ".join(log_tail) if log_tail else "(no log entries)"
    result_preview = (row.get("result") or "")[:300]

    parts = [
        f"Task #{row['id']} [{row['status']}] kind={row['kind']}",
        f"prompt: {row['prompt'][:120]}",
        f"updated: {row['updated_at']}",
        "",
        "Last log lines:",
        f"  {log_block}",
    ]
    if row["status"] in ("done", "failed", "cancelled") and result_preview:
        parts.append("")
        parts.append(f"Result preview: {result_preview}")
    return "\n".join(parts)


TOOLS = [
    {
        "name": "start_task",
        "description": (
            "Dispatch a long-running research / comparison / monitoring task to "
            "the background. Use this when the user asks for anything that "
            "needs multi-page web research, product comparisons, in-depth "
            "investigation, or anything that would take more than ~30 seconds. "
            "Examples: 'find me the best 4K monitor under 2000 lei', "
            "'compare Notion vs Obsidian for academic notes', "
            "'research the latest EU AI Act news'. "
            "Don't use it for quick lookups — those should use web_search/get_weather."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "The full research / comparison prompt, in the user's words.",
                },
                "kind": {
                    "type": "string",
                    "description": "Task type. Default 'research'.",
                    "enum": ["research"],
                },
            },
            "required": ["prompt"],
        },
    },
    {
        "name": "list_tasks",
        "description": (
            "List the most recent background tasks the user has dispatched, "
            "with their status (pending/running/done/failed). Use when the user "
            "asks 'what's running?', 'how's the research going?', etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "How many recent tasks to list (1-20). Default 5.",
                },
            },
        },
    },
    {
        "name": "task_status",
        "description": (
            "Get detailed status + last 10 log lines for a specific task — "
            "or the most-recent running task if no id given. Use when the "
            "user asks 'how's it going?', 'what's it doing right now?', "
            "'is it done yet?', 'what did the research find?', or wants "
            "Jarvis to read back the last task's progress without opening "
            "the dashboard."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "integer",
                    "description": "Task id. If omitted, uses the most recent running/pending task.",
                },
            },
        },
    },
]

HANDLERS = {
    "start_task": start_task,
    "list_tasks": list_tasks,
    "task_status": task_status,
}
