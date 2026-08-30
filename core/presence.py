"""
Presence detector — figures out where the user is so the router can pick
the right channel for proactive messages.

States:
    AT_PC        keyboard/mouse activity in the last `pc_idle_threshold` seconds
    PHONE_ONLY   no PC activity, but mobile heartbeat in the last `mobile_window` seconds
    AWAY         neither

Quiet hours (config) force a SILENT override regardless of state — the router
decides what that means for each channel.

Mobile heartbeat:
    The phone calls POST /api/mobile/heartbeat every ~30s while the app is
    in foreground or has wake-permission. Each call refreshes the last-seen
    timestamp via mark_mobile_alive().
"""

from __future__ import annotations

import ctypes
import threading
import time
from dataclasses import dataclass
from datetime import datetime, time as _time

from loguru import logger


AT_PC = "at_pc"
PHONE_ONLY = "phone_only"
AWAY = "away"


@dataclass
class PresenceSnapshot:
    state: str               # AT_PC | PHONE_ONLY | AWAY
    pc_idle_seconds: float   # 0 if active, larger if idle
    mobile_alive: bool       # phone heartbeat seen recently
    quiet_hours: bool        # true if inside the user's quiet window
    ts: str                  # ISO timestamp of the snapshot


class PresenceDetector:
    def __init__(self, config: dict) -> None:
        cfg = config.get("presence", {}) or {}
        self._pc_idle_threshold: int = int(cfg.get("pc_idle_threshold_seconds", 120))
        self._mobile_window: int = int(cfg.get("mobile_alive_window_seconds", 90))

        # Quiet hours — disables audible TTS broadcasts; pushes still go to phone
        # but with a "silent" hint so the router can lower priority.
        qh = cfg.get("quiet_hours", {}) or {}
        self._quiet_enabled: bool = bool(qh.get("enabled", True))
        self._quiet_start = _parse_time(qh.get("start", "23:00"))
        self._quiet_end = _parse_time(qh.get("end", "07:00"))

        self._mobile_last_seen: float = 0.0
        self._lock = threading.Lock()

    # ── Mobile heartbeat ─────────────────────────────────────────
    def mark_mobile_alive(self) -> None:
        with self._lock:
            self._mobile_last_seen = time.time()

    def mobile_alive(self) -> bool:
        with self._lock:
            return (time.time() - self._mobile_last_seen) < self._mobile_window

    # ── PC idle (Windows GetLastInputInfo) ───────────────────────
    @staticmethod
    def pc_idle_seconds() -> float:
        """Seconds since the last keyboard or mouse event (Windows-specific)."""
        try:
            class LASTINPUTINFO(ctypes.Structure):
                _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

            lii = LASTINPUTINFO()
            lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
            if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
                return 0.0
            millis_since = ctypes.windll.kernel32.GetTickCount() - lii.dwTime
            return max(0.0, millis_since / 1000.0)
        except Exception:
            # Non-Windows or failure — assume always active
            return 0.0

    # ── Quiet hours ──────────────────────────────────────────────
    def is_quiet_now(self) -> bool:
        if not self._quiet_enabled:
            return False
        now = datetime.now().time()
        if self._quiet_start <= self._quiet_end:
            return self._quiet_start <= now < self._quiet_end
        # crosses midnight
        return now >= self._quiet_start or now < self._quiet_end

    # ── Snapshot ─────────────────────────────────────────────────
    def snapshot(self) -> PresenceSnapshot:
        idle = self.pc_idle_seconds()
        mobile = self.mobile_alive()

        if idle < self._pc_idle_threshold:
            state = AT_PC
        elif mobile:
            state = PHONE_ONLY
        else:
            state = AWAY

        return PresenceSnapshot(
            state=state,
            pc_idle_seconds=idle,
            mobile_alive=mobile,
            quiet_hours=self.is_quiet_now(),
            ts=datetime.now().isoformat(timespec="seconds"),
        )


def _parse_time(s: str) -> _time:
    try:
        h, m = s.split(":", 1)
        return _time(int(h), int(m))
    except Exception:
        return _time(23, 0)


# ── Singleton wiring ────────────────────────────────────────────
_instance: PresenceDetector | None = None


def init(config: dict) -> PresenceDetector:
    global _instance
    if _instance is None:
        _instance = PresenceDetector(config)
        snap = _instance.snapshot()
        logger.info(
            f"Presence: state={snap.state} idle={snap.pc_idle_seconds:.0f}s "
            f"mobile={snap.mobile_alive} quiet={snap.quiet_hours}"
        )
    return _instance


def get() -> PresenceDetector | None:
    return _instance
