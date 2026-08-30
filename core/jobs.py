"""
Scheduled jobs — wires concrete tasks (briefing, email/meeting checks)
into the scheduler.

Call `register_all(config)` once at boot, after the scheduler instance
exists, to install every default job.
"""

from __future__ import annotations

from loguru import logger

from core import health_checks, proactive, router, routines, scheduler, watches


def _do_morning_briefing() -> None:
    """Build a short briefing (weather + today + memory highlights) and route it."""
    try:
        from tools.memory_tool import morning_briefing
        text = morning_briefing()
        if not text:
            return
        # Trim — Nest Audio / TTS sounds best with short, punchy briefings.
        text = str(text).strip()
        if len(text) > 600:
            text = text[:600].rsplit(".", 1)[0] + "."

        router.notify(
            title="Briefing",
            body=text,
            urgency="normal",
            kind="briefing",
            force_tts=True,
        )
    except Exception as exc:
        logger.warning(f"morning briefing failed: {exc}")


def register_all(config: dict) -> None:
    sch = scheduler.get()
    if sch is None:
        logger.warning("scheduler not initialised — jobs not registered")
        return

    sched_cfg = (config.get("scheduler") or {})

    # ── Morning briefing ────────────────────────────────────────
    brief_cfg = (sched_cfg.get("briefing") or {})
    if brief_cfg.get("enabled", True):
        time_str = str(brief_cfg.get("time", "07:30"))
        days_str = str(brief_cfg.get("days", "weekdays")).lower()
        try:
            hh, mm = (int(x) for x in time_str.split(":", 1))
        except Exception:
            hh, mm = 7, 30
        if days_str == "weekdays":
            weekdays = scheduler.WEEKDAYS
        elif days_str == "weekends":
            weekdays = scheduler.WEEKENDS
        elif days_str in ("daily", "all", "every"):
            weekdays = scheduler.ALL_DAYS
        else:
            weekdays = scheduler.ALL_DAYS
        sch.add_daily(
            "morning_briefing", _do_morning_briefing,
            hh=hh, mm=mm, weekdays=weekdays,
        )

    # ── Calendar meeting alert (interval) ───────────────────────
    notif_cfg = (config.get("mobile", {}) or {}).get("notifications", {}) or {}
    if notif_cfg.get("enabled", True):
        cal_seconds = int(sched_cfg.get("calendar_check_seconds",
                                        notif_cfg.get("calendar_poll_seconds", 60)))
        cal_lead = int(sched_cfg.get("calendar_lead_minutes",
                                     notif_cfg.get("calendar_lead_minutes", 10)))
        sch.add_interval(
            "calendar_alerts",
            lambda: proactive.check_meetings_once(lead_minutes=cal_lead),
            seconds=cal_seconds,
        )

        # ── Email watcher (interval) ────────────────────────────
        email_seconds = int(sched_cfg.get("email_check_seconds",
                                          notif_cfg.get("email_poll_seconds", 60)))
        sch.add_interval(
            "email_watcher",
            proactive.check_emails_once,
            seconds=email_seconds,
        )

    # ── URL watches (master tick — actual due-checking happens inside) ──
    watch_tick_seconds = int(sched_cfg.get("watch_tick_seconds", 60))
    sch.add_interval("watch_tick", watches.tick, seconds=watch_tick_seconds)

    # ── Health checks ───────────────────────────────────────────
    # Idle nocturn — scan every 10 min; only fires inside its own time window
    sch.add_interval(
        "idle_nocturn", health_checks.check_idle_nocturn, seconds=600,
    )
    # System health — battery / disk / RAM, every 5 min
    sch.add_interval(
        "system_health", health_checks.check_system_health, seconds=300,
    )
    # Calendar conflicts — once a day at 08:30 weekdays
    sch.add_daily(
        "calendar_conflicts", health_checks.check_calendar_conflicts,
        hh=8, mm=30, weekdays=scheduler.WEEKDAYS,
    )

    # Disk hygiene — daily 18:00, scans Downloads/Temp for large old files
    try:
        from tools.cleanup_tool import daily_cleanup_check
        sch.add_daily(
            "disk_hygiene", daily_cleanup_check,
            hh=18, mm=0, weekdays=scheduler.ALL_DAYS,
        )
    except Exception as exc:
        logger.warning(f"disk hygiene job not registered: {exc}")

    # ── Schedule-triggered routines ─────────────────────────────
    # Any routine with a `schedule` trigger gets registered as a daily job.
    for r in routines.schedule_routines():
        for trig in r.triggers:
            if trig.type != "schedule" or not trig.time:
                continue
            try:
                hh, mm = (int(x) for x in trig.time.split(":", 1))
            except Exception:
                logger.warning(f"routine '{r.name}' bad time '{trig.time}', skipping")
                continue
            if trig.days == "weekdays":
                weekdays = scheduler.WEEKDAYS
            elif trig.days == "weekends":
                weekdays = scheduler.WEEKENDS
            else:
                weekdays = scheduler.ALL_DAYS

            # Capture name in default-arg to avoid late-binding bug
            def _fire(_name=r.name) -> None:
                routines.run(_name)

            sch.add_daily(
                f"routine_{r.name}", _fire,
                hh=hh, mm=mm, weekdays=weekdays,
            )

    logger.info(f"jobs registered: {[j['name'] for j in sch.list_jobs()]}")
