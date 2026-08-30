"""Claude Code integration — uses shared persistent process + real-time dashboard streaming."""

from loguru import logger

_SHORT_LIMIT = 400
_last_response = {"prompt": "", "summary": "", "full": ""}


def _push(msg_type: str, content, *, raw_msg: dict = None):
    """Push a message to dashboard WebSocket + history."""
    try:
        from ui.dashboard import _add_to_history, broadcast_to_clients
        if msg_type in ("user", "assistant", "error"):
            _add_to_history(msg_type, content)
        if raw_msg:
            broadcast_to_clients(raw_msg)
        else:
            broadcast_to_clients({"type": msg_type, "content": content})
    except Exception:
        pass


def run_claude_code(prompt: str, directory: str = "") -> str:
    """Run Claude Code via shared persistent process, stream to dashboard in real-time."""
    try:
        from ui.claude_session import get_claude
        from ui.dashboard import _handle_claude_event

        logger.info(f"Claude Code: {prompt[:100]}")
        _push("user", prompt)
        _push("claude_working", "true")

        output_parts = []

        def on_event(event):
            _handle_claude_event(event, output_parts)

        claude = get_claude()
        completed = claude.send(prompt, on_event=on_event, timeout=120)

        output = "".join(output_parts).strip()
        _push("claude_working", "false")

        if not completed and not output:
            error = "Claude Code timed out."
            _push("error", error)
            return error

        if not output:
            _push("assistant", "Claude Code finished but produced no output.")
            _push("claude_done", "")
            _last_response["prompt"] = prompt
            _last_response["summary"] = "Finished but produced no output."
            _last_response["full"] = ""
            return "Claude Code finished but produced no output."

        lines = output.count("\n") + 1
        logger.info(f"Claude Code: {lines} lines, {len(output)} chars")

        _push("assistant", output)
        _push("claude_done", output)

        # Store last response so Jarvis brain can reference it
        _last_response["prompt"] = prompt
        _last_response["full"] = output
        if len(output) <= _SHORT_LIMIT:
            _last_response["summary"] = output
        else:
            # Build a meaningful summary from first and last few lines
            out_lines = output.strip().split("\n")
            head = "\n".join(out_lines[:5])
            tail = "\n".join(out_lines[-3:]) if len(out_lines) > 8 else ""
            _last_response["summary"] = (
                f"{head}\n{'...\n' + tail if tail else ''}"
                f"\n[{lines} lines total]"
            )

        if len(output) <= _SHORT_LIMIT:
            return output

        first_lines = "\n".join(output.split("\n")[:3])
        return (
            f"Done. Claude Code responded with {lines} lines. "
            f"Here's the start:\n{first_lines}\n\n"
            f"Full response visible on the dashboard."
        )

    except FileNotFoundError:
        return "Claude Code CLI is not installed or not on PATH."
    except Exception as exc:
        logger.error(f"Claude Code error: {exc}")
        _push("error", str(exc))
        return f"Error running Claude Code: {exc}"


def get_last_claude_response() -> str:
    """Return Claude Code's last response summary for Jarvis to read back."""
    if not _last_response["summary"]:
        return "Claude Code hasn't responded to anything yet in this session."
    return (
        f"Last prompt sent to Claude: {_last_response['prompt'][:200]}\n\n"
        f"Claude's response:\n{_last_response['summary']}"
    )


# ── Background task runner (registered with core.tasks) ──────────
def _claude_task_runner(task_id: int, prompt: str) -> str:
    """Drive Claude Code in the background, streaming its output to the task
    log so the user can watch progress on the mobile TasksScreen.

    On completion, the tasks engine fires a router notification automatically
    (HUD/TTS/push depending on presence)."""
    from core import tasks
    output_parts: list[str] = []
    last_log_at = [0.0]

    def on_event(event):
        # Re-use the dashboard handler (keeps web UI in sync)
        try:
            from ui.dashboard import _handle_claude_event
            _handle_claude_event(event, output_parts)
        except Exception:
            pass

        # Also condense to one line per significant event for the task log
        try:
            etype = event.get("type", "")
            text = (event.get("text") or event.get("content") or "")
            if isinstance(text, list):
                # message blocks → join text bits
                text = " ".join(
                    str(b.get("text", "")) for b in text if isinstance(b, dict)
                )
            if etype == "tool_use":
                tname = event.get("name") or event.get("tool_name") or "tool"
                tasks.append_log(task_id, f"⚙ {tname}")
            elif text:
                # Throttle log writes — long streams would otherwise overwhelm
                import time as _t
                now = _t.time()
                if now - last_log_at[0] >= 0.8:
                    snippet = text.strip().replace("\n", " ")[:160]
                    if snippet:
                        tasks.append_log(task_id, snippet)
                        last_log_at[0] = now
        except Exception:
            pass

    try:
        from ui.claude_session import get_claude
        claude = get_claude()
        completed = claude.send(prompt, on_event=on_event, timeout=900)
    except Exception as exc:
        return f"Claude Code error: {exc}"

    output = "".join(output_parts).strip()
    if not completed and not output:
        return "Claude Code timed out."
    if not output:
        return "Claude Code finished but produced no output."
    return output


def start_claude_task(prompt: str) -> str:
    """Spawn Claude Code as a background task. Returns immediately with task id;
    Jarvis will speak/push a notification when it's done."""
    if not prompt or not prompt.strip():
        return "Refused — empty prompt."
    try:
        from core import tasks
        task_id = tasks.spawn(prompt.strip(), kind="claude_code")
    except Exception as exc:
        logger.error(f"start_claude_task failed: {exc}")
        return f"Couldn't start Claude task: {exc}"
    return (f"Started Claude Code task #{task_id} in the background. "
            "I'll let you know when it's done.")


def _register_claude_runner() -> None:
    """Register the background runner with core.tasks. Idempotent."""
    try:
        from core import tasks
        tasks.register_runner("claude_code", _claude_task_runner)
    except Exception as exc:
        logger.warning(f"Couldn't register claude_code task runner: {exc}")


_register_claude_runner()


TOOLS = [
    {
        "name": "get_last_claude_response",
        "description": (
            "Get Claude Code's last response/answer. Use when the user asks "
            "'what did Claude say?', 'what was Claude's response?', "
            "'what did Claude do?', 'read Claude's answer', 'tell me what Claude replied', "
            "or any question about Claude Code's most recent output."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "run_claude_code",
        "description": (
            "Run a prompt through Claude Code CLI (Anthropic's coding assistant) "
            "and BLOCK until it finishes. Use ONLY for short, fast prompts "
            "(simple questions, single-file reads, quick edits). For anything "
            "that might take >30s — building a feature, multi-file refactor, "
            "long debugging — use start_claude_task instead so the voice loop "
            "stays free. Results stream live on the dashboard. "
            "IMPORTANT: The prompt must be plain natural language, NOT code."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "The instruction for Claude Code",
                },
                "directory": {
                    "type": "string",
                    "description": "Working directory (default: C:\\Projects\\jarvis)",
                },
            },
            "required": ["prompt"],
        },
    },
    {
        "name": "start_claude_task",
        "description": (
            "Dispatch a Claude Code prompt as a BACKGROUND task. Returns "
            "immediately with a task id; the task runs asynchronously and "
            "Jarvis notifies the user when it completes (HUD + TTS at PC, "
            "push to phone if away). Progress visible on the mobile Tasks "
            "screen. Use this for: 'build feature X', 'fix issue #42', "
            "'refactor the auth module', 'add tests for Y' — anything that "
            "would take more than ~30 seconds. The user can keep talking to "
            "Jarvis or walk away while Claude works."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "The instruction for Claude Code (plain natural language).",
                },
            },
            "required": ["prompt"],
        },
    },
]

HANDLERS = {
    "run_claude_code": run_claude_code,
    "get_last_claude_response": lambda: get_last_claude_response(),
    "start_claude_task": start_claude_task,
}
