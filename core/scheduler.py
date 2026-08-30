"""
Lightweight scheduler — daily / weekly / interval jobs.

Avoids APScheduler to keep deps lean. One daemon thread sleeps until the
next due fire-time, runs the job inline, then re-computes the next slot.

Job types:
    daily       fire at HH:MM, every day (optional weekday filter)
    interval    fire every N seconds after start

Persistence: last-fire timestamps are kept in-memory + a small JSON file
so a restart doesn't refire missed daily jobs (we skip if "fire-time has
already passed today and we already fired since then").

Job handlers must be cheap callables taking no args. Wrap your real work
in a closure that captures whatever it needs.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable

from loguru import logger

_STATE_PATH = Path(__file__).resolve().parent.parent / "data" / "scheduler_state.json"


# Weekdays bitmask helpers (Mon=0, Sun=6) — same convention as datetime.weekday()
ALL_DAYS = {0, 1, 2, 3, 4, 5, 6}
WEEKDAYS = {0, 1, 2, 3, 4}
WEEKENDS = {5, 6}


@dataclass
class Job:
    name: str
    handler: Callable[[], None]
    kind: str                                  # "daily" | "interval"
    hh: int = 0                                # daily only
    mm: int = 0                                # daily only
    weekdays: set[int] = field(default_factory=lambda: set(ALL_DAYS))
    interval_seconds: int = 0                  # interval only
    last_fired: float = 0.0                    # epoch seconds


class Scheduler:
    def __init__(self) -> None:
        self._jobs: list[Job] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._load_state()

    # ── State persistence ───────────────────────────────────────
    def _load_state(self) -> None:
        self._saved_state: dict[str, float] = {}
        if not _STATE_PATH.is_file():
            return
        try:
            data = json.loads(_STATE_PATH.read_text())
            self._saved_state = {k: float(v) for k, v in data.items()}
        except Exception as exc:
            logger.warning(f"scheduler load state failed: {exc}")

    def _save_state(self) -> None:
        try:
            _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            with self._lock:
                data = {j.name: j.last_fired for j in self._jobs}
            _STATE_PATH.write_text(json.dumps(data))
        except Exception as exc:
            logger.warning(f"scheduler save state failed: {exc}")

    # ── Registration ────────────────────────────────────────────
    def add_daily(self, name: str, handler: Callable[[], None],
                  hh: int, mm: int = 0,
                  weekdays: set[int] | None = None) -> None:
        job = Job(
            name=name, handler=handler, kind="daily",
            hh=hh, mm=mm,
            weekdays=set(weekdays) if weekdays else set(ALL_DAYS),
            last_fired=getattr(self, "_saved_state", {}).get(name, 0.0),
        )
        with self._lock:
            self._jobs.append(job)
        logger.info(f"scheduler: + daily '{name}' at {hh:02d}:{mm:02d}")

    def add_interval(self, name: str, handler: Callable[[], None],
                     seconds: int) -> None:
        job = Job(
            name=name, handler=handler, kind="interval",
            interval_seconds=max(5, int(seconds)),
            last_fired=getattr(self, "_saved_state", {}).get(name, time.time()),
        )
        with self._lock:
            self._jobs.append(job)
        logger.info(f"scheduler: + interval '{name}' every {seconds}s")

    def list_jobs(self) -> list[dict]:
        with self._lock:
            return [
                {
                    "name": j.name,
                    "kind": j.kind,
                    "next_fire_in": max(0, int(self._next_due(j) - time.time())),
                    "last_fired": j.last_fired,
                }
                for j in self._jobs
            ]

    # ── Loop ────────────────────────────────────────────────────
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="jarvis-scheduler", daemon=True,
        )
        self._thread.start()
        logger.info(f"scheduler started ({len(self._jobs)} job(s))")

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            now = time.time()
            next_due = now + 60.0  # default sleep
            with self._lock:
                jobs = list(self._jobs)

            for job in jobs:
                due = self._next_due(job)
                if due <= now:
                    self._fire(job)
                    job.last_fired = now
                    due = self._next_due(job)
                next_due = min(next_due, due)

            self._save_state()
            sleep_for = max(1.0, min(next_due - time.time(), 60.0))
            self._stop.wait(sleep_for)

    @staticmethod
    def _next_due(job: Job) -> float:
        if job.kind == "interval":
            return job.last_fired + job.interval_seconds

        # daily: today at HH:MM if we haven't fired since, else tomorrow
        now = datetime.now()
        target_today = now.replace(hour=job.hh, minute=job.mm,
                                   second=0, microsecond=0)
        target_ts = target_today.timestamp()

        last_fired_dt = (datetime.fromtimestamp(job.last_fired)
                         if job.last_fired else None)
        already_fired_today = bool(
            last_fired_dt and last_fired_dt.date() == now.date()
        )

        # If today is allowed and we still have time AND haven't fired yet → today
        if (now.weekday() in job.weekdays
                and now < target_today
                and not already_fired_today):
            return target_ts

        # Otherwise advance day-by-day to the next allowed weekday
        candidate = target_today + timedelta(days=1)
        for _ in range(8):
            if candidate.weekday() in job.weekdays:
                return candidate.timestamp()
            candidate += timedelta(days=1)
        return target_ts + 86400  # paranoid fallback

    @staticmethod
    def _fire(job: Job) -> None:
        try:
            logger.info(f"scheduler: firing '{job.name}'")
            job.handler()
        except Exception as exc:
            logger.error(f"scheduler job '{job.name}' raised: {exc}")


# ── Module singleton ────────────────────────────────────────────
_instance: Scheduler | None = None


def init() -> Scheduler:
    global _instance
    if _instance is None:
        _instance = Scheduler()
    return _instance


def get() -> Scheduler | None:
    return _instance
