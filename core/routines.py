"""
Routines — declarative, composable workflows.

A routine is a named sequence of steps that fires when one of its triggers
matches. Triggers can be voice phrases, schedule entries, or external events
(e.g. mobile geofence later). Steps are tool calls, spoken announcements,
short waits, or nested routines.

YAML lives in data/routines.yaml (user-editable). Reload at runtime by
calling `load(...)` again.

Schema (illustrative):

    routines:
      - name: good_morning
        description: "Daily wake-up sequence"
        triggers:
          - type: voice
            phrases: ["good morning", "morning jarvis", "buna dimineata"]
          - type: schedule
            time: "07:30"
            days: weekdays
        steps:
          - tool: hue_scene
            args: {scene: "Energize"}
          - speak: "Good morning, sir."
          - tool: morning_briefing
          - wait: 1.0

Step kinds:
    tool      — call a registered tool with kwargs
    speak     — route a TTS announcement through core.router
    wait      — sleep N seconds
    routine   — run another routine by name (no infinite loops — depth-limited)
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from loguru import logger

from core import router


_DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "routines.yaml"
_MAX_DEPTH = 4


@dataclass
class Trigger:
    type: str                                  # "voice" | "schedule" | "event"
    phrases: list[str] = field(default_factory=list)
    time: str = ""                             # "HH:MM"
    days: str = "daily"                        # "weekdays" | "weekends" | "daily"
    event: str = ""                            # e.g. "presence_change"


@dataclass
class Step:
    kind: str                                  # "tool" | "speak" | "wait" | "routine"
    tool_name: str = ""
    args: dict = field(default_factory=dict)
    speak_text: str = ""
    wait_seconds: float = 0.0
    routine_name: str = ""


@dataclass
class Routine:
    name: str
    description: str
    triggers: list[Trigger]
    steps: list[Step]


# ── Module state ─────────────────────────────────────────────────
_routines: dict[str, Routine] = {}
_brain = None
_lock = threading.Lock()


def set_brain(brain) -> None:
    """Inject the brain so routines can call its registered tools."""
    global _brain
    _brain = brain


# ── Loading ──────────────────────────────────────────────────────
def load(path: Path | None = None) -> int:
    """(Re)load routines from YAML. Returns the count loaded."""
    p = path or _DEFAULT_PATH
    if not p.is_file():
        logger.info(f"routines: {p} not found — none loaded")
        with _lock:
            _routines.clear()
        return 0

    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        logger.error(f"routines: YAML parse error in {p}: {exc}")
        return 0

    parsed: dict[str, Routine] = {}
    for entry in (raw.get("routines") or []):
        try:
            r = _parse_routine(entry)
            parsed[r.name.lower()] = r
        except Exception as exc:
            logger.warning(f"routines: skipped invalid entry: {exc}")

    with _lock:
        _routines.clear()
        _routines.update(parsed)

    logger.info(f"routines: loaded {len(parsed)} — {list(parsed.keys())}")
    return len(parsed)


def _parse_routine(entry: dict) -> Routine:
    name = str(entry.get("name", "")).strip()
    if not name:
        raise ValueError("routine missing 'name'")
    description = str(entry.get("description", ""))

    triggers = [_parse_trigger(t) for t in (entry.get("triggers") or [])]
    steps = [_parse_step(s) for s in (entry.get("steps") or [])]
    if not steps:
        raise ValueError(f"routine '{name}' has no steps")
    return Routine(name=name, description=description,
                   triggers=triggers, steps=steps)


def _parse_trigger(t: dict) -> Trigger:
    kind = str(t.get("type", "")).lower()
    return Trigger(
        type=kind,
        phrases=[str(p).lower().strip() for p in (t.get("phrases") or [])],
        time=str(t.get("time", "")),
        days=str(t.get("days", "daily")).lower(),
        event=str(t.get("event", "")),
    )


def _parse_step(s: dict) -> Step:
    if "tool" in s:
        return Step(kind="tool", tool_name=str(s["tool"]),
                    args=dict(s.get("args") or {}))
    if "speak" in s:
        return Step(kind="speak", speak_text=str(s["speak"]))
    if "wait" in s:
        return Step(kind="wait", wait_seconds=float(s["wait"]))
    if "routine" in s:
        return Step(kind="routine", routine_name=str(s["routine"]))
    raise ValueError(f"unrecognised step: {s}")


# ── Lookup / iteration ───────────────────────────────────────────
def get(name: str) -> Routine | None:
    with _lock:
        return _routines.get(name.lower())


def list_all() -> list[Routine]:
    with _lock:
        return list(_routines.values())


def voice_routines() -> list[Routine]:
    return [r for r in list_all() if any(t.type == "voice" for t in r.triggers)]


def schedule_routines() -> list[Routine]:
    return [r for r in list_all() if any(t.type == "schedule" for t in r.triggers)]


def event_routines() -> list[Routine]:
    return [r for r in list_all() if any(t.type == "event" for t in r.triggers)]


def match_event(event: str, target: str | None = None) -> list[Routine]:
    """Find routines whose event-trigger matches (case-insensitive)."""
    ev = (event or "").lower().strip()
    tgt = (target or "").lower().strip()
    out: list[Routine] = []
    for r in list_all():
        for trig in r.triggers:
            if trig.type != "event":
                continue
            te = (trig.event or "").lower().strip()
            # event field uses dot notation: "geofence.enter:home"  or  just "geofence.enter"
            ev_part, _, tgt_part = te.partition(":")
            if ev_part != ev:
                continue
            if tgt_part and tgt and tgt_part != tgt:
                continue
            out.append(r)
            break
    return out


def fire_event(event: str, target: str | None = None) -> list[str]:
    """Run every routine whose event-trigger matches. Returns names that ran."""
    matched = match_event(event, target)
    fired: list[str] = []
    for r in matched:
        run_async(r.name)
        fired.append(r.name)
    if fired:
        logger.info(f"event '{event}' (target='{target or ''}') fired: {fired}")
    return fired


# ── Voice matcher ────────────────────────────────────────────────
def match_voice(text: str) -> Routine | None:
    """Find the first routine whose voice-trigger phrases match the text.
    Matching is case-insensitive substring; any phrase wins."""
    if not text:
        return None
    lowered = text.lower().strip()
    for r in list_all():
        for trig in r.triggers:
            if trig.type != "voice":
                continue
            for phrase in trig.phrases:
                if phrase and phrase in lowered:
                    return r
    return None


# ── Execution ────────────────────────────────────────────────────
def run(name: str, *, depth: int = 0, skip_first_speak: bool = False) -> dict:
    """Execute a routine by name. Safe against deep recursion.

    `skip_first_speak` lets the brain's voice pipeline speak the opening
    line itself (so the user hears one cohesive reply) while this function
    drops it to avoid double-speaking.
    """
    if depth >= _MAX_DEPTH:
        logger.warning(f"routines: depth limit reached at '{name}'")
        return {"ok": False, "error": "max depth"}

    r = get(name)
    if r is None:
        return {"ok": False, "error": f"unknown routine: {name}"}

    logger.info(f"routine[{r.name}] starting ({len(r.steps)} step(s))")
    results: list[dict] = []
    skipped_speak = False
    for i, step in enumerate(r.steps):
        if (not skipped_speak and skip_first_speak
                and step.kind == "speak"):
            skipped_speak = True
            continue
        try:
            res = _run_step(step, depth=depth)
        except Exception as exc:
            logger.error(f"routine[{r.name}] step {i} ({step.kind}) failed: {exc}")
            res = {"ok": False, "error": str(exc)}
        results.append(res)

    logger.info(f"routine[{r.name}] done")
    return {"ok": True, "name": r.name, "steps": results}


def run_async(name: str, *, skip_first_speak: bool = False) -> threading.Thread:
    """Fire-and-forget routine execution on a worker thread."""
    t = threading.Thread(
        target=run, args=(name,),
        kwargs={"skip_first_speak": skip_first_speak},
        daemon=True, name=f"routine-{name}",
    )
    t.start()
    return t


def first_speak_text(routine: Routine) -> str | None:
    """Return the first 'speak' step's text, or None if no speak step."""
    for step in routine.steps:
        if step.kind == "speak" and step.speak_text:
            return step.speak_text
    return None


def _run_step(step: Step, *, depth: int) -> dict:
    if step.kind == "tool":
        return _step_tool(step.tool_name, step.args)
    if step.kind == "speak":
        router.speak(step.speak_text)
        return {"ok": True, "kind": "speak"}
    if step.kind == "wait":
        time.sleep(max(0.0, step.wait_seconds))
        return {"ok": True, "kind": "wait", "seconds": step.wait_seconds}
    if step.kind == "routine":
        return run(step.routine_name, depth=depth + 1)
    return {"ok": False, "error": f"unknown step kind: {step.kind}"}


def _step_tool(name: str, args: dict) -> dict:
    if _brain is None:
        return {"ok": False, "error": "brain not wired"}
    handler = _brain._tool_handlers.get(name)  # type: ignore[attr-defined]
    if handler is None:
        return {"ok": False, "error": f"unknown tool: {name}"}
    try:
        result = handler(**args) if args else handler()
        return {"ok": True, "tool": name, "result": str(result)[:300]}
    except Exception as exc:
        return {"ok": False, "tool": name, "error": str(exc)}
