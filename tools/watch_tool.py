"""
`watch_url` / `list_watches` / `stop_watch` tools — let the brain set up
periodic monitoring of a URL with a fire-when condition.

Usage examples (what the brain will route to these tools):
    "Watch this Amazon page for price drops, every 30 minutes"
    "Tell me when this PR gets approved" → watch_url(url, "is the PR approved or merged?")
    "Let me know if this page changes" → watch_url(url, "changed")
"""

from __future__ import annotations

from loguru import logger

from core import watches


def watch_url(url: str, condition: str = "changed",
              interval_minutes: int = 30, label: str = "") -> str:
    if not url or not url.strip():
        return "Refused — empty URL."
    try:
        wid = watches.create(url.strip(), condition.strip() or "changed",
                             int(interval_minutes), label.strip())
    except Exception as exc:
        logger.error(f"watch_url failed: {exc}")
        return f"Couldn't set up watch: {exc}"
    cond_desc = "changes" if condition == "changed" else f"'{condition[:60]}'"
    return (f"Watching #{wid}: {url[:60]} every {interval_minutes} min for {cond_desc}. "
            "I'll notify you when it fires.")


def list_watches(include_archived: bool = False) -> str:
    rows = watches.list_all(include_archived=include_archived)
    if not rows:
        return "No watches set."
    lines = []
    for w in rows[:20]:
        cond = w.get("condition") or "changed"
        cond_short = cond if len(cond) <= 50 else cond[:47] + "…"
        lines.append(
            f"#{w['id']} [{w['status']}] every {w['interval_seconds']//60}min — "
            f"{cond_short} → {w['url'][:70]}"
        )
    return "\n".join(lines)


def stop_watch(watch_id: int) -> str:
    if watches.stop(int(watch_id)):
        return f"Stopped watch #{watch_id}."
    return f"No active watch with id #{watch_id}."


TOOLS = [
    {
        "name": "watch_url",
        "description": (
            "Set up a periodic watch on a URL that fires a notification when a "
            "condition becomes true. Use this for: 'tell me when the price "
            "drops', 'notify me when this PR is approved', 'let me know if "
            "this page changes', 'watch the score of this match'. "
            "Use condition='changed' to fire on any text change. Otherwise "
            "phrase the condition as a yes/no question — the LLM will check "
            "the page each tick. Default interval is 30 minutes."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Full URL to watch."},
                "condition": {
                    "type": "string",
                    "description": ("'changed' to fire on any text change, OR a "
                                    "yes/no question evaluated against the page "
                                    "(e.g. 'is the PR approved?', 'is the price "
                                    "below 1500 lei?')."),
                },
                "interval_minutes": {
                    "type": "integer",
                    "description": "How often to check. Min 1. Default 30.",
                },
                "label": {
                    "type": "string",
                    "description": "Short human-readable label (e.g. 'AMD CPU on PCGarage').",
                },
            },
            "required": ["url"],
        },
    },
    {
        "name": "list_watches",
        "description": "List the user's active URL watches.",
        "input_schema": {
            "type": "object",
            "properties": {
                "include_archived": {
                    "type": "boolean",
                    "description": "Whether to include stopped/archived watches. Default false.",
                },
            },
        },
    },
    {
        "name": "stop_watch",
        "description": "Stop an active URL watch by id.",
        "input_schema": {
            "type": "object",
            "properties": {
                "watch_id": {"type": "integer", "description": "Watch id from list_watches."},
            },
            "required": ["watch_id"],
        },
    },
]

HANDLERS = {
    "watch_url": watch_url,
    "list_watches": list_watches,
    "stop_watch": stop_watch,
}
