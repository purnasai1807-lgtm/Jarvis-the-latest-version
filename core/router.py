"""
Smart notification router.

The router decides HOW to deliver a proactive message — not just whether
to push it. Channels:

    HUD       text bubble on the desktop overlay
    TTS       Jarvis speaks it through the local speakers
    PUSH      FCM push notification to registered phones

The decision matrix is driven by presence + urgency + quiet hours:

    state         urgency=low   urgency=normal   urgency=high
    AT_PC         HUD           HUD + TTS        HUD + TTS + PUSH
    PHONE_ONLY    PUSH          PUSH             PUSH (high prio)
    AWAY          —             PUSH             PUSH (high prio)

Quiet hours (sleeping) override TTS off, downgrade PUSH to silent unless
urgency=high.

Everything is fire-and-forget; failures are logged but never raise.
"""

from __future__ import annotations

import threading
from typing import Literal

from loguru import logger

from core import notifications, presence

Urgency = Literal["low", "normal", "high"]


# Optional surfaces wired from main.py
_hud = None
_tts = None


def wire(hud=None, tts=None) -> None:
    """Inject HUD + TTS singletons after they exist."""
    global _hud, _tts
    if hud is not None:
        _hud = hud
    if tts is not None:
        _tts = tts


def _default_actions_for(kind: str) -> list[dict]:
    """Sensible default action buttons based on the notification kind."""
    if kind == "email":
        return [
            {"id": "email.mark_read", "label": "Mark read"},
            {"id": "email.read_aloud", "label": "Read"},
            {"id": "snooze.10", "label": "Snooze 10m"},
        ]
    if kind == "calendar":
        return [
            {"id": "calendar.dismiss", "label": "Dismiss"},
            {"id": "snooze.5", "label": "Snooze 5m"},
        ]
    return []


def notify(title: str, body: str, *, urgency: Urgency = "normal",
           data: dict | None = None, kind: str = "info",
           force_tts: bool = False,
           actions: list[dict] | None = None) -> dict:
    """Route a notification through the right channel(s).

    Returns a dict describing what was actually dispatched, useful for logs.
    """
    p = presence.get()
    snap = p.snapshot() if p else None

    state = snap.state if snap else "unknown"
    quiet = bool(snap and snap.quiet_hours)

    do_hud = state == "at_pc"
    do_tts = state == "at_pc" and urgency in ("normal", "high") and not quiet
    do_push = (
        state in ("phone_only", "away", "unknown")
        or urgency == "high"
    )

    if force_tts and not quiet:
        do_tts = True

    dispatched: list[str] = []

    if do_hud and _hud is not None:
        try:
            text = f"{title}: {body}" if body else title
            _hud.set_response(text[:300])
            dispatched.append("hud")
        except Exception as exc:
            logger.warning(f"router HUD failed: {exc}")

    if do_tts and _tts is not None:
        try:
            spoken = body if body else title
            threading.Thread(
                target=_tts.speak, args=(spoken,), daemon=True,
            ).start()
            dispatched.append("tts")
        except Exception as exc:
            logger.warning(f"router TTS failed: {exc}")

    if do_push:
        try:
            payload = dict(data or {})
            payload.setdefault("kind", kind)
            payload["urgency"] = urgency
            if quiet and urgency != "high":
                payload["silent"] = "1"
            push_actions = actions if actions is not None else _default_actions_for(kind)
            notifications.push_async(title, body, data=payload,
                                     actions=push_actions or None)
            dispatched.append("push")
        except Exception as exc:
            logger.warning(f"router push failed: {exc}")

    logger.info(
        f"router[{kind}] urgency={urgency} state={state} "
        f"quiet={quiet} → {','.join(dispatched) or 'none'}"
    )
    return {
        "dispatched": dispatched,
        "state": state,
        "quiet": quiet,
    }


def speak(text: str, *, kind: str = "announcement",
          urgency: Urgency = "normal") -> dict:
    """Convenience: TTS-first announcement that also goes to HUD/push when away."""
    return notify(title="Jarvis", body=text, urgency=urgency,
                  kind=kind, force_tts=True)
