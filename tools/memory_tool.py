"""
Phase 7 — Long-term memory tools.

5 tools: remember_fact, recall_fact, forget_fact, list_memories, morning_briefing
"""

from loguru import logger

_memory = None   # MemoryManager injected at startup


def init_memory(memory_manager) -> None:
    global _memory
    _memory = memory_manager


# ------------------------------------------------------------------
# Handlers
# ------------------------------------------------------------------

def _remember_fact(key: str, value: str, category: str = "general") -> str:
    if _memory is None:
        return "Memory system not initialised."
    return _memory.remember(key, value, category)


def _recall_fact(query: str) -> str:
    if _memory is None:
        return "Memory system not initialised."
    facts = _memory.recall(query, n=5)
    if not facts:
        return f"I don't have any memories matching '{query}'."
    lines = [f"• {f['doc']}" for f in facts]
    return "What I remember:\n" + "\n".join(lines)


def _forget_fact(key: str) -> str:
    if _memory is None:
        return "Memory system not initialised."
    return _memory.forget(key)


def _list_memories(category: str | None = None) -> str:
    if _memory is None:
        return "Memory system not initialised."
    facts = _memory.list_facts(category)
    if not facts:
        label = f" in category '{category}'" if category else ""
        return f"No memories stored{label} yet."
    lines = [f"[{f['category']}] {f['key']}: {f['value']}" for f in facts[:25]]
    header = f"I have {len(facts)} memor{'y' if len(facts) == 1 else 'ies'}:\n"
    suffix = f"\n…and {len(facts) - 25} more." if len(facts) > 25 else ""
    return header + "\n".join(lines) + suffix


def _morning_briefing() -> str:
    """Compile a morning briefing: weather + today's calendar + memory highlights."""
    import requests
    from tools.calendar_tool import get_schedule

    parts: list[str] = []

    # --- Weather (wttr.in) ---
    try:
        r = requests.get("https://wttr.in/Bucharest?format=3", timeout=6)
        if r.ok:
            parts.append(f"Weather: {r.text.strip()}")
    except Exception as exc:
        logger.warning(f"Briefing — weather error: {exc}")

    # --- Today's calendar ---
    try:
        schedule = get_schedule(date="today", days=1)
        parts.append(schedule)
    except Exception as exc:
        logger.warning(f"Briefing — calendar error: {exc}")

    # --- Memory highlights (5 most recent facts) ---
    if _memory:
        try:
            facts = _memory.list_facts()[:5]
            if facts:
                mem_lines = [f"• {f['key']}: {f['value']}" for f in facts]
                parts.append("Things I remember:\n" + "\n".join(mem_lines))
        except Exception as exc:
            logger.warning(f"Briefing — memory error: {exc}")

    if not parts:
        return "Good morning, sir. No briefing data available right now."

    return "Good morning, sir. Here is your briefing:\n\n" + "\n\n".join(parts)


# ------------------------------------------------------------------
# Tool definitions
# ------------------------------------------------------------------

TOOLS = [
    {
        "name": "remember_fact",
        "description": (
            "Store a fact or piece of information in Jarvis's long-term memory. "
            "Use when the user says 'remember that', 'note that', 'don't forget', "
            "'keep in mind', etc. Examples: 'Remember my car is a BMW X5', "
            "'Remember I prefer dark mode', 'Remember my gym is at 7am on Mondays'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": (
                        "Short identifier for this fact (e.g. 'car', 'coffee preference', "
                        "'gym schedule'). Use lowercase, descriptive labels."
                    ),
                },
                "value": {
                    "type": "string",
                    "description": "The detail or value to store.",
                },
                "category": {
                    "type": "string",
                    "description": "Category: personal, work, preferences, health, home, general",
                    "enum": ["personal", "work", "preferences", "health", "home", "general"],
                },
            },
            "required": ["key", "value"],
        },
    },
    {
        "name": "recall_fact",
        "description": (
            "Search Jarvis's long-term memory for information relevant to a query. "
            "Use when the user says 'do you remember', 'what do you know about', "
            "'remind me', 'what did I tell you about', etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The topic or question to search for in memory.",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "forget_fact",
        "description": (
            "Delete a specific fact from Jarvis's long-term memory. "
            "Use when the user says 'forget that', 'delete that memory', "
            "'that's no longer true', etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "The exact key of the fact to forget.",
                },
            },
            "required": ["key"],
        },
    },
    {
        "name": "list_memories",
        "description": (
            "List all facts stored in Jarvis's long-term memory. "
            "Use when the user says 'what do you know about me', "
            "'show me my memories', 'what have I told you', etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": (
                        "Optional filter: personal, work, preferences, health, home, general. "
                        "Omit to list all categories."
                    ),
                },
            },
        },
    },
    {
        "name": "morning_briefing",
        "description": (
            "Deliver a morning briefing: current weather in Bucharest, today's calendar events, "
            "and highlights from long-term memory. "
            "Use when the user says 'morning briefing', 'good morning', "
            "'what's on today', 'brief me', etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
]

HANDLERS = {
    "remember_fact":    _remember_fact,
    "recall_fact":      _recall_fact,
    "forget_fact":      _forget_fact,
    "list_memories":    _list_memories,
    "morning_briefing": _morning_briefing,
}
