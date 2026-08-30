"""
Plan tools — let the brain stage multi-action requests for confirmation
before firing anything destructive or visible.

Use case (the 'compose mode' the user asked for):

  USER  "reply to Andrei on WhatsApp that I'll be 20 min late, and move
         the meeting with Maria to 16:00"
  BRAIN propose_plan(summary, [
          {tool: "whatsapp_send", args: {...}, summary: "WhatsApp Andrei…"},
          {tool: "create_event", args: {...}, summary: "Move Maria meeting…"},
        ])
       → "Plan #5: I will A then B. Say 'confirm' or 'cancel'."
  USER  "confirm"
  BRAIN confirm_last_plan()
       → both fire in order, summary returned

The brain's persona is updated to use propose_plan whenever 2+ destructive
or externally-visible actions are requested in one turn.
"""

from __future__ import annotations

from loguru import logger

from core import plans


def propose_plan(summary: str, steps: list[dict]) -> str:
    if not summary or not summary.strip():
        return "Refused — empty summary."
    if not steps or not isinstance(steps, list):
        return "Refused — no steps provided."
    try:
        pid = plans.create(summary.strip(), steps)
    except Exception as exc:
        logger.error(f"propose_plan failed: {exc}")
        return f"Couldn't stage plan: {exc}"
    bullets = "\n".join(
        f"  {i+1}. {s.get('summary') or s.get('tool')}"
        for i, s in enumerate(steps)
    )
    return (f"Plan #{pid} staged: {summary.strip()}\n{bullets}\n"
            "Say 'confirm' to proceed, or 'cancel' to drop it.")


def confirm_last_plan() -> str:
    pending = plans.most_recent_pending()
    if not pending:
        return "No pending plan to confirm."
    result = plans.execute(pending["id"])
    if not result.get("ok"):
        first_err = next(
            (r for r in result.get("results", []) if not r.get("ok")), None,
        )
        err = first_err.get("error", "unknown") if first_err else "unknown"
        return (f"Plan #{pending['id']} failed at step "
                f"{first_err.get('step', '?') if first_err else '?'}: {err}")
    n = len(result["results"])
    return f"Plan #{pending['id']} done — {n} step(s) executed successfully."


def cancel_last_plan() -> str:
    pid = plans.cancel_pending()
    if pid is None:
        return "No pending plan to cancel."
    return f"Plan #{pid} cancelled."


TOOLS = [
    {
        "name": "propose_plan",
        "description": (
            "Stage a multi-step plan for the user to confirm BEFORE anything "
            "fires. ALWAYS use this when the user asks for 2+ destructive or "
            "visible actions in one turn — e.g. 'reply to X and move my "
            "meeting', 'send email A and create calendar event B', 'delete "
            "these files and archive that folder'. Do NOT use for read-only "
            "lookups or for a single action — those run directly. The user "
            "will then say 'confirm' or 'cancel' to control execution."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "One sentence summary of what the plan does.",
                },
                "steps": {
                    "type": "array",
                    "description": ("Ordered list of steps. Each item: "
                                    '{"tool": <tool_name>, "args": {...}, '
                                    '"summary": <human description>}.'),
                    "items": {
                        "type": "object",
                        "properties": {
                            "tool": {"type": "string"},
                            "args": {"type": "object"},
                            "summary": {"type": "string"},
                        },
                        "required": ["tool", "summary"],
                    },
                },
            },
            "required": ["summary", "steps"],
        },
    },
    {
        "name": "confirm_last_plan",
        "description": (
            "Execute the most recently proposed plan. Use when the user says "
            "'confirm', 'yes', 'go ahead', 'do it', 'da', 'sigur' AND there "
            "is a pending plan. Returns a summary of what executed."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "cancel_last_plan",
        "description": (
            "Cancel the most recently proposed plan without running it. Use "
            "when the user says 'cancel', 'no', 'never mind', 'stop', 'nu', "
            "'lasă' AND there is a pending plan."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
]

HANDLERS = {
    "propose_plan": propose_plan,
    "confirm_last_plan": confirm_last_plan,
    "cancel_last_plan": cancel_last_plan,
}
