"""
Context-awareness tools — let the brain answer questions about *what's
on screen right now* and resolve "this", "that file", "the tab".

The tools wrap core.context, which keeps a live snapshot of:
  • foreground app + window title (5s polling)
  • parsed VS Code file
  • meeting-app detection
  • last 30 clipboard entries (2s polling)
plus on-demand:
  • Chrome's active tab URL (slow — UI Automation)
  • git log / status across known repos
"""

from __future__ import annotations

from loguru import logger

from core import context


def get_active_context() -> str:
    """One-shot snapshot of what the user is doing right now."""
    w = context.window()
    if not w:
        return "Context not available yet (watcher still warming up)."

    parts = []
    app = w.get("app") or "?"
    title = w.get("title") or "(no title)"
    parts.append(f"App: {app}")
    parts.append(f"Window: {title[:160]}")
    if w.get("vscode_file"):
        parts.append(f"VS Code file: {w['vscode_file']}")
    if w.get("in_meeting"):
        parts.append("Meeting: YES (assume the user is in a call)")

    clips = context.clipboard_recent(3)
    if clips:
        parts.append("Recent clipboard:")
        for c in clips:
            txt = c["text"].replace("\n", " ").strip()
            parts.append(f"  • [{c['ts'][11:16]}] {txt[:120]}")

    return "\n".join(parts)


def read_active_tab() -> str:
    """Resolve the URL of the active Chrome tab and fetch its readable text.
    Use when the user says 'this tab', 'this article', 'this page'."""
    url = context.active_chrome_url()
    if not url:
        return "Couldn't read the active Chrome URL (no Chrome window or UI automation blocked)."
    try:
        from tools.browser import read_page
        text = read_page(url)
        return f"Active tab: {url}\n\n{text[:6000]}"
    except Exception as exc:
        logger.warning(f"read_active_tab failed: {exc}")
        return f"Got URL ({url}) but couldn't fetch content: {exc}"


def clipboard_history(limit: int = 10) -> str:
    """List the user's recent clipboard entries (newest first, deduped)."""
    items = context.clipboard_recent(int(limit))
    if not items:
        return "Clipboard history is empty."
    lines = []
    for i, c in enumerate(items, 1):
        txt = c["text"].replace("\n", " ").strip()
        lines.append(f"{i}. [{c['ts'][11:16]}] {txt[:200]}")
    return "Recent clipboard:\n" + "\n".join(lines)


def clipboard_search(query: str, limit: int = 10) -> str:
    """Search recent clipboard entries by substring (case-insensitive).
    Use when user says 'put what I copied earlier' or 'find that link I had'."""
    items = context.clipboard_search(query, int(limit))
    if not items:
        return f"No clipboard entries matching '{query}'."
    lines = []
    for i, c in enumerate(items, 1):
        txt = c["text"].replace("\n", " ").strip()
        lines.append(f"{i}. [{c['ts'][11:16]}] {txt[:200]}")
    return f"Clipboard matches for '{query}':\n" + "\n".join(lines)


def git_summary(since: str = "1 day ago") -> str:
    """Cross-repo git log + status. Use when the user asks 'what did I do
    today/yesterday/this week?', 'what's left to commit?', etc.

    `since` accepts git's relative-time syntax: '6 hours ago', '1 day ago',
    '2 weeks ago', 'monday', etc."""
    try:
        return context.git_summary(since=since)
    except Exception as exc:
        logger.error(f"git_summary failed: {exc}")
        return f"Couldn't compute git summary: {exc}"


TOOLS = [
    {
        "name": "get_active_context",
        "description": (
            "Get a live snapshot of what's on the user's screen right now: "
            "active app, window title, parsed VS Code file, meeting state, "
            "and recent clipboard entries. Always check this BEFORE asking "
            "the user 'which file?' or 'which tab?' — the answer is usually "
            "already here."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "read_active_tab",
        "description": (
            "Fetch and return the readable text content of the user's active "
            "Chrome tab. Use when the user says 'this tab', 'this article', "
            "'this page', 'rezumă tab-ul ăsta', 'summarize this'. "
            "This is the right tool to resolve 'this' when the user is "
            "looking at a webpage."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "clipboard_history",
        "description": (
            "List the user's recent clipboard entries (deduped, newest first, "
            "with timestamps). Use when the user asks 'what did I just copy', "
            "'show clipboard history'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "How many entries to return (1-30). Default 10.",
                },
            },
        },
    },
    {
        "name": "clipboard_search",
        "description": (
            "Search recent clipboard entries by substring (case-insensitive). "
            "Use when the user says 'put what I copied earlier with X in it', "
            "'find that link I had', 'paste the JSON I copied'. After finding "
            "a match, you can use type_text() or clipboard_write() to act on it."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Substring to search for."},
                "limit": {"type": "integer", "description": "Max results. Default 10."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "git_summary",
        "description": (
            "Multi-repo git log + status summary across the user's known "
            "project directories. Use when the user asks 'what did I do "
            "today / yesterday / this week', 'what's left uncommitted', "
            "'ce am lucrat azi'. Accepts git relative-time strings."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "since": {
                    "type": "string",
                    "description": ("Git relative-time, e.g. '6 hours ago', "
                                    "'1 day ago', '2 weeks ago', 'monday'. "
                                    "Default '1 day ago'."),
                },
            },
        },
    },
]

HANDLERS = {
    "get_active_context": get_active_context,
    "read_active_tab": read_active_tab,
    "clipboard_history": clipboard_history,
    "clipboard_search": clipboard_search,
    "git_summary": git_summary,
}
