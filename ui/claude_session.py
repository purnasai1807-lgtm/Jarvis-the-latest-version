"""
Persistent Claude Code subprocess — single process, streaming I/O, optimal caching.

Instead of spawning `claude -p <prompt> --continue` per message (which
regenerates the system prompt, reloads git status, and re-sends the full
session each time — busting the prompt cache), this keeps ONE long-lived
process alive using --input-format stream-json.

Result: system prompt loaded once, prompt caching works across all turns,
~3-5x fewer input tokens compared to per-message spawning.
"""

import json
import os
import re
import subprocess
import threading
from pathlib import Path
from typing import Callable, Optional

from loguru import logger

_ANSI_RE = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]|\x1b\].*?\x07')
_PROJECT = Path(__file__).resolve().parent.parent


class PersistentClaude:
    """Single long-lived Claude Code subprocess with streaming I/O.

    - Starts one `claude -p --input-format stream-json` process
    - Sends user messages as NDJSON on stdin
    - Reads streaming events from stdout via background reader thread
    - Reuses the process across all dashboard + voice interactions
    - On stop(): kills process, resumes session on next send()
    - On clear(): kills process, starts fresh on next send()
    """

    def __init__(self, cwd: str = None, model: str = None):
        self._cwd = cwd or str(_PROJECT)
        self._model: Optional[str] = model     # e.g. "sonnet", "opus"
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()          # serializes send() calls
        self._reader_thread: Optional[threading.Thread] = None
        self._on_event: Optional[Callable] = None
        self._response_done = threading.Event()
        self._session_id: Optional[str] = None
        self._resume_on_restart = False        # True after stop()

    # ── Process lifecycle ──────────────────────────────────────────

    def _start(self):
        """Start (or restart) the Claude subprocess."""
        cmd = [
            "claude", "-p",
            "--input-format", "stream-json",
            "--output-format", "stream-json",
            "--verbose",
            "--include-partial-messages",
            "--dangerously-skip-permissions",
        ]
        if self._model:
            cmd += ["--model", self._model]
        # After stop() we resume the session; after clear() we start fresh
        if self._resume_on_restart and self._session_id:
            cmd += ["--resume", self._session_id]
        self._resume_on_restart = False

        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        self._proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace",
            cwd=self._cwd, env=env,
        )
        self._reader_thread = threading.Thread(
            target=self._read_loop, daemon=True,
            name="claude-reader",
        )
        self._reader_thread.start()
        logger.info("Persistent Claude process started (PID {})", self._proc.pid)

    def _ensure_started(self):
        if self._proc is None or self._proc.poll() is not None:
            self._start()

    def _kill(self):
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.kill()
                self._proc.wait(timeout=5)
            except Exception:
                pass
        self._proc = None

    # ── Background reader ──────────────────────────────────────────

    def _read_loop(self):
        """Continuously read stdout and dispatch events to the callback."""
        proc = self._proc
        while proc and proc.poll() is None:
            try:
                line = proc.stdout.readline()
            except Exception:
                break
            if not line:
                break
            line = line.strip()
            if not line:
                continue

            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                clean = _ANSI_RE.sub('', line)
                if self._on_event:
                    self._on_event({"type": "raw_text", "content": clean})
                continue

            evt_type = event.get("type")

            # Capture session ID so we can resume after stop()
            if evt_type == "system" and event.get("subtype") == "init":
                self._session_id = event.get("session_id")

            # Dispatch to current callback
            if self._on_event:
                self._on_event(event)

            # Signal that the current request is complete
            if evt_type == "result":
                self._response_done.set()

        logger.debug("Claude reader loop ended (PID {})",
                      proc.pid if proc else "?")

    # ── Public API ─────────────────────────────────────────────────

    def send(self, prompt: str, on_event: Callable = None,
             timeout: float = 300) -> bool:
        """Send a user message and block until the response is complete.

        Args:
            prompt: The user's message text.
            on_event: Callback(event_dict) called for each streaming event.
            timeout: Max seconds to wait for the full response.

        Returns:
            True if the response completed, False on timeout.
        """
        with self._lock:
            self._ensure_started()
            self._on_event = on_event
            self._response_done.clear()

            msg = json.dumps({
                "type": "user",
                "message": {
                    "role": "user",
                    "content": prompt,
                },
            })

            try:
                self._proc.stdin.write(msg + "\n")
                self._proc.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                logger.warning("Claude stdin broken, restarting: {}", exc)
                self._kill()
                self._resume_on_restart = True
                self._start()
                try:
                    self._proc.stdin.write(msg + "\n")
                    self._proc.stdin.flush()
                except Exception as exc2:
                    logger.error("Claude restart failed: {}", exc2)
                    return False

            return self._response_done.wait(timeout=timeout)

    def send_with_image(self, prompt: str, image_base64: str,
                        media_type: str = "image/png",
                        on_event: Callable = None,
                        timeout: float = 300) -> bool:
        """Send a user message with an attached image."""
        with self._lock:
            self._ensure_started()
            self._on_event = on_event
            self._response_done.clear()

            msg = json.dumps({
                "type": "user",
                "message": {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": image_base64,
                            },
                        },
                    ],
                },
            })

            try:
                self._proc.stdin.write(msg + "\n")
                self._proc.stdin.flush()
            except (BrokenPipeError, OSError):
                self._kill()
                self._resume_on_restart = True
                self._start()
                self._proc.stdin.write(msg + "\n")
                self._proc.stdin.flush()

            return self._response_done.wait(timeout=timeout)

    def stop(self):
        """Cancel current request. Kills process; will resume session on next send()."""
        self._resume_on_restart = True
        self._kill()
        self._response_done.set()  # unblock any waiting send()

    def clear(self):
        """Clear conversation. Kills process; next send() starts a fresh session."""
        self._resume_on_restart = False
        self._session_id = None
        self._kill()

    def set_model(self, model: str):
        """Switch model (e.g. 'sonnet', 'opus'). Restarts process, resumes session."""
        self._model = model
        if self._proc and self._proc.poll() is None:
            self._resume_on_restart = True
            self._kill()
        logger.info("Claude model set to '{}'", model)

    @property
    def model(self) -> Optional[str]:
        return self._model

    @property
    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    @property
    def session_id(self) -> Optional[str]:
        return self._session_id


# ── Module-level singleton ─────────────────────────────────────────

_instance: Optional[PersistentClaude] = None
_instance_lock = threading.Lock()


def get_claude() -> PersistentClaude:
    """Get or create the shared PersistentClaude instance."""
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = PersistentClaude()
        return _instance
