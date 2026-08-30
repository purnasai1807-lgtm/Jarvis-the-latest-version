"""
System & schedule health checks — interval jobs that fire alerts proactively.

  check_idle_nocturn()       at 23:00–02:00, if PC idle > 30 min and we
                              haven't asked yet tonight, prompts "good night?"
  check_system_health()      battery <20% on power, disk <10% on any drive,
                              RAM >90% sustained — each fires once per day
                              max
  check_calendar_conflicts() detects overlapping events for today and pushes
                              once per day if any exist

All checks dedupe via day-scoped flags persisted in data/health_state.json.
Routed through core.router so the user gets the right channel automatically.
"""

from __future__ import annotations

import json
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

from loguru import logger

from core import presence, router

_STATE_PATH = Path(__file__).resolve().parent.parent / "data" / "health_state.json"
_state: dict = {}


def _load_state() -> None:
    global _state
    if not _STATE_PATH.is_file():
        _state = {}
        return
    try:
        _state = json.loads(_STATE_PATH.read_text())
    except Exception:
        _state = {}


def _save_state() -> None:
    try:
        _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _STATE_PATH.write_text(json.dumps(_state))
    except Exception as exc:
        logger.warning(f"health save state failed: {exc}")


_load_state()


def _today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _fired_today(key: str) -> bool:
    return _state.get(key) == _today_str()


def _mark_fired(key: str) -> None:
    _state[key] = _today_str()
    _save_state()


# ── Idle nocturn ────────────────────────────────────────────────
def check_idle_nocturn() -> None:
    """At 23:00–02:00, if user hasn't touched PC for 30 min, suggest night mode."""
    if _fired_today("idle_nocturn"):
        return

    now = datetime.now()
    nt = now.time()
    in_window = nt >= time(23, 0) or nt < time(2, 0)
    if not in_window:
        return

    p = presence.get()
    if p is None:
        return
    snap = p.snapshot()
    if snap.pc_idle_seconds < 30 * 60:
        return

    logger.info("idle_nocturn: prompting good-night routine")
    _mark_fired("idle_nocturn")

    router.notify(
        title="🌙 Calling it a night?",
        body="You've been idle for a while. Say 'good night Jarvis' to wind down — "
             "or I'll stop bothering you until tomorrow.",
        urgency="low",
        kind="idle_nocturn",
    )


# ── System health (battery / disk / RAM) ────────────────────────
def check_system_health() -> None:
    try:
        import psutil
    except ImportError:
        return

    # ── Battery ───────────────────────────────────────────────
    try:
        bat = psutil.sensors_battery()
        if bat is not None and not bat.power_plugged:
            pct = int(bat.percent or 0)
            if pct < 20 and not _fired_today("battery_low"):
                _mark_fired("battery_low")
                router.notify(
                    title="🔋 Battery low",
                    body=f"{pct}% remaining on battery — plug in soon.",
                    urgency="normal",
                    kind="system",
                )
    except Exception as exc:
        logger.debug(f"battery check failed: {exc}")

    # ── Disk space ────────────────────────────────────────────
    try:
        for part in psutil.disk_partitions(all=False):
            # Skip CD/DVD/removable that report 0 free
            if "fixed" not in (part.opts or "") and "rw" not in (part.opts or ""):
                continue
            try:
                usage = psutil.disk_usage(part.mountpoint)
            except Exception:
                continue
            free_pct = 100 - usage.percent
            if free_pct < 10:
                key = f"disk_low_{part.mountpoint}"
                if _fired_today(key):
                    continue
                _mark_fired(key)
                free_gb = round(usage.free / (1024**3), 1)
                router.notify(
                    title=f"💾 Disk almost full: {part.mountpoint}",
                    body=f"Only {free_gb} GB free ({free_pct:.1f}%). "
                         f"Time to clean up.",
                    urgency="normal",
                    kind="system",
                )
    except Exception as exc:
        logger.debug(f"disk check failed: {exc}")

    # ── RAM (sustained high) ──────────────────────────────────
    try:
        vm = psutil.virtual_memory()
        if vm.percent > 92:
            # Use a streak counter so a single spike doesn't fire
            streak = int(_state.get("ram_high_streak", 0)) + 1
            _state["ram_high_streak"] = streak
            if streak >= 3 and not _fired_today("ram_high"):
                _mark_fired("ram_high")
                _state["ram_high_streak"] = 0
                router.notify(
                    title="🧠 RAM under pressure",
                    body=f"Memory at {vm.percent:.0f}% for several minutes — "
                         f"close some heavy apps.",
                    urgency="low",
                    kind="system",
                )
            _save_state()
        else:
            if _state.get("ram_high_streak"):
                _state["ram_high_streak"] = 0
                _save_state()
    except Exception as exc:
        logger.debug(f"ram check failed: {exc}")


# ── Calendar conflicts (today) ──────────────────────────────────
def check_calendar_conflicts() -> None:
    """Scan today's events; if any overlap, fire one alert listing the clashes."""
    if _fired_today("cal_conflicts"):
        return

    try:
        from tools.calendar_tool import _get_calendar_service
        service = _get_calendar_service()
    except Exception as exc:
        logger.debug(f"calendar conflict check skipped: {exc}")
        return

    try:
        now = datetime.now(timezone.utc)
        end_of_day = now.replace(hour=23, minute=59, second=59,
                                 microsecond=0)
        events = service.events().list(
            calendarId="primary",
            timeMin=now.isoformat(),
            timeMax=end_of_day.isoformat(),
            singleEvents=True,
            orderBy="startTime",
            maxResults=20,
        ).execute().get("items", []) or []

        # Build (start, end, title) tuples for events with explicit times
        intervals: list[tuple[datetime, datetime, str]] = []
        for ev in events:
            s = ev.get("start", {}).get("dateTime")
            e = ev.get("end", {}).get("dateTime")
            if not s or not e:
                continue
            try:
                ds = datetime.fromisoformat(s)
                de = datetime.fromisoformat(e)
            except Exception:
                continue
            intervals.append((ds, de, ev.get("summary", "(untitled)")))

        # Detect overlaps (O(n^2), fine for n ≤ 20)
        clashes: list[str] = []
        for i in range(len(intervals)):
            si, ei, ti = intervals[i]
            for j in range(i + 1, len(intervals)):
                sj, ej, tj = intervals[j]
                if si < ej and sj < ei:  # overlap
                    overlap_start = max(si, sj).astimezone().strftime("%H:%M")
                    overlap_end = min(ei, ej).astimezone().strftime("%H:%M")
                    clashes.append(
                        f"{ti[:30]} ↔ {tj[:30]} ({overlap_start}-{overlap_end})"
                    )

        if not clashes:
            return

        _mark_fired("cal_conflicts")
        body = " · ".join(clashes[:3])
        router.notify(
            title=f"⚠ {len(clashes)} calendar conflict(s) today",
            body=body[:240],
            urgency="normal",
            kind="calendar_conflict",
        )

    except Exception as exc:
        logger.debug(f"calendar conflict check error: {exc}")
