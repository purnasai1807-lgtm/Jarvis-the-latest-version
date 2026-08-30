"""
Mobile API — endpoints consumed by the Flutter phone client.

Phase 1 surface:
    GET  /api/mobile/health             liveness check (no auth — used to detect PC online)
    GET  /api/mobile/dashboard          slim dashboard payload
    POST /api/mobile/ask                stream brain reply via SSE; optional PC TTS playback

All non-health routes require Bearer token in Authorization header.
"""

import asyncio
import json
import threading
from datetime import datetime
from typing import Any

import psutil
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response, StreamingResponse
from loguru import logger
from pydantic import BaseModel, Field

from ui.routes.auth import require_api_key


router = APIRouter(prefix="/api/mobile", tags=["mobile"])

# Shared singletons set by ui.dashboard.init_dashboard()
_brain = None
_tts = None
_stt = None


def set_runtime(brain=None, tts=None, stt=None) -> None:
    """Called from ui.dashboard at startup to wire in the live Brain + TTS + STT."""
    global _brain, _tts, _stt
    _brain = brain
    _tts = tts
    _stt = stt


# ── Health ───────────────────────────────────────────────────────

_lan_meta_cache: dict | None = None


def _lan_meta() -> dict:
    """Discover the primary LAN interface — MAC + IP — so the phone can
    later send Wake-on-LAN packets. Cached after first call."""
    global _lan_meta_cache
    if _lan_meta_cache is not None:
        return _lan_meta_cache
    out = {"mac": "", "ip": "", "broadcast": "255.255.255.255"}
    try:
        import psutil
        addrs = psutil.net_if_addrs()
        stats = psutil.net_if_stats()
        for name, ifaces in addrs.items():
            if name.lower().startswith(("lo", "loopback", "vethernet",
                                        "vmware", "vbox", "virtual")):
                continue
            if name not in stats or not stats[name].isup:
                continue
            ipv4 = ""
            mac = ""
            for a in ifaces:
                fam = getattr(a.family, "name", str(a.family))
                if fam == "AF_INET" and not a.address.startswith("127."):
                    ipv4 = a.address
                elif fam in ("AF_LINK", "AF_PACKET"):
                    if a.address and a.address != "00:00:00:00:00:00":
                        mac = a.address
            if ipv4 and mac:
                out["mac"] = mac.upper().replace("-", ":")
                out["ip"] = ipv4
                # Broadcast: assume /24 — good enough for LAN WoL
                octets = ipv4.split(".")
                if len(octets) == 4:
                    out["broadcast"] = ".".join(octets[:3] + ["255"])
                break
    except Exception:
        pass
    _lan_meta_cache = out
    return out


@router.get("/health")
async def health() -> dict:
    """Cheap heartbeat used by the phone to detect PC reachability.
    Also exposes the PC's MAC + LAN IP so the phone can send Wake-on-LAN."""
    meta = _lan_meta()
    return {
        "ok": True,
        "time": datetime.now().isoformat(timespec="seconds"),
        "brain_ready": _brain is not None,
        "tts_ready": _tts is not None,
        "mac": meta["mac"],
        "lan_ip": meta["ip"],
        "broadcast": meta["broadcast"],
    }


# ── Presence heartbeat (phone says "I'm here") ───────────────────

@router.post("/heartbeat", dependencies=[Depends(require_api_key)])
async def heartbeat() -> dict:
    """Phone pings this every ~30s while alive so PC knows where the user is."""
    from core import presence
    p = presence.get()
    if p is not None:
        p.mark_mobile_alive()
        snap = p.snapshot()
        return {
            "ok": True,
            "presence": snap.state,
            "quiet_hours": snap.quiet_hours,
            "pc_idle_seconds": int(snap.pc_idle_seconds),
        }
    return {"ok": True, "presence": "unknown"}


@router.get("/presence", dependencies=[Depends(require_api_key)])
async def presence_get() -> dict:
    from core import presence
    p = presence.get()
    if p is None:
        return {"state": "unknown"}
    snap = p.snapshot()
    return {
        "state": snap.state,
        "pc_idle_seconds": int(snap.pc_idle_seconds),
        "mobile_alive": snap.mobile_alive,
        "quiet_hours": snap.quiet_hours,
        "ts": snap.ts,
    }


# ── Cross-device conversation read ───────────────────────────────

@router.get("/conversation/recent", dependencies=[Depends(require_api_key)])
async def conversation_recent(limit: int = 40) -> dict:
    """Return the shared conversation tail so the phone can mirror what was said
    on PC voice / dashboard / scheduler — and vice-versa."""
    from core import conversation
    limit = max(1, min(limit, 200))
    return {"turns": conversation.recent(limit)}


@router.delete("/conversation", dependencies=[Depends(require_api_key)])
async def conversation_clear() -> dict:
    from core import conversation
    n = conversation.clear()
    return {"ok": True, "cleared": n}


# ── Routines (declarative workflows) ─────────────────────────────

@router.get("/routines", dependencies=[Depends(require_api_key)])
async def routines_list() -> dict:
    from core import routines
    return {
        "routines": [
            {
                "name": r.name,
                "description": r.description,
                "voice_phrases": [
                    p for t in r.triggers if t.type == "voice" for p in t.phrases
                ],
                "schedule": [
                    {"time": t.time, "days": t.days}
                    for t in r.triggers if t.type == "schedule"
                ],
                "step_count": len(r.steps),
            }
            for r in routines.list_all()
        ]
    }


class RunRoutine(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)


@router.post("/routines/run", dependencies=[Depends(require_api_key)])
async def routines_run(req: RunRoutine) -> dict:
    from core import routines
    routines.run_async(req.name)
    return {"ok": True, "name": req.name}


@router.post("/routines/reload", dependencies=[Depends(require_api_key)])
async def routines_reload() -> dict:
    from core import routines
    n = routines.load()
    return {"ok": True, "loaded": n}


# ── Geofence zones + events ─────────────────────────────────────

class CreateZone(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    radius_m: int = Field(default=200, ge=50, le=5000)


@router.get("/zones", dependencies=[Depends(require_api_key)])
async def zones_list() -> dict:
    from core import zones
    return {"zones": zones.list_all()}


@router.post("/zones", dependencies=[Depends(require_api_key)])
async def zones_create(req: CreateZone) -> dict:
    from core import zones
    zid = zones.create(req.name, req.latitude, req.longitude, req.radius_m)
    return {"ok": True, "zone_id": zid}


@router.delete("/zones/{zone_id}", dependencies=[Depends(require_api_key)])
async def zones_delete(zone_id: int) -> dict:
    from core import zones
    return {"ok": zones.delete(zone_id)}


class GeofenceEvent(BaseModel):
    event: str = Field(..., min_length=1, max_length=32)   # "enter" | "exit" | "dwell"
    zone_name: str = Field(..., min_length=1, max_length=64)
    latitude: float | None = Field(default=None)
    longitude: float | None = Field(default=None)


@router.post("/geofence-event", dependencies=[Depends(require_api_key)])
async def geofence_event(req: GeofenceEvent) -> dict:
    """Phone reports an entry/exit at a named zone. Server fires any routine
    whose trigger matches `geofence.<event>:<zone_name>`."""
    from core import routines
    event = f"geofence.{req.event.strip().lower()}"
    target = req.zone_name.strip().lower()
    fired = routines.fire_event(event, target=target)
    logger.info(
        f"geofence-event: {event} zone={target} → fired {fired or '[]'}"
    )
    return {"ok": True, "event": event, "zone": target, "fired": fired}


# ── URL watches (proactive monitoring) ──────────────────────────

class CreateWatch(BaseModel):
    url: str = Field(..., min_length=4, max_length=2000)
    condition: str = Field(default="changed", max_length=200)
    interval_minutes: int = Field(default=30, ge=1, le=10080)
    label: str = Field(default="", max_length=120)


@router.get("/watches", dependencies=[Depends(require_api_key)])
async def watches_list(include_archived: bool = False) -> dict:
    from core import watches
    return {"watches": watches.list_all(include_archived=include_archived)}


@router.get("/watches/{watch_id}", dependencies=[Depends(require_api_key)])
async def watches_get(watch_id: int) -> dict:
    from core import watches
    row = watches.get(watch_id)
    if not row:
        raise HTTPException(404, "watch not found")
    return row


@router.post("/watches", dependencies=[Depends(require_api_key)])
async def watches_create(req: CreateWatch) -> dict:
    from core import watches
    wid = watches.create(req.url, req.condition,
                         req.interval_minutes, req.label)
    return {"ok": True, "watch_id": wid}


@router.post("/watches/{watch_id}/stop", dependencies=[Depends(require_api_key)])
async def watches_stop(watch_id: int) -> dict:
    from core import watches
    return {"ok": watches.stop(watch_id)}


@router.post("/watches/{watch_id}/reactivate", dependencies=[Depends(require_api_key)])
async def watches_reactivate(watch_id: int) -> dict:
    from core import watches
    return {"ok": watches.reactivate(watch_id)}


# ── Background tasks (research / monitoring) ────────────────────

@router.get("/tasks", dependencies=[Depends(require_api_key)])
async def tasks_list(limit: int = 30) -> dict:
    from core import tasks
    rows = tasks.list_recent(limit=limit)
    # Trim heavy fields for the list view; full content via /tasks/{id}
    light = [
        {
            "id": r["id"],
            "kind": r["kind"],
            "prompt": r["prompt"],
            "status": r["status"],
            "result_preview": r["result"][:200],
            "log_lines": r["log"].count("\n"),
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
        }
        for r in rows
    ]
    return {"tasks": light}


@router.get("/tasks/{task_id}", dependencies=[Depends(require_api_key)])
async def tasks_get(task_id: int) -> dict:
    from core import tasks
    row = tasks.get(task_id)
    if not row:
        raise HTTPException(404, "task not found")
    return row


class StartTaskRequest(BaseModel):
    prompt: str = Field(..., min_length=2, max_length=2000)
    kind: str = Field(default="research", max_length=32)


@router.post("/tasks", dependencies=[Depends(require_api_key)])
async def tasks_start(req: StartTaskRequest) -> dict:
    from core import tasks
    try:
        task_id = tasks.spawn(req.prompt.strip(), kind=req.kind)
        return {"ok": True, "task_id": task_id}
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.post("/tasks/{task_id}/cancel", dependencies=[Depends(require_api_key)])
async def tasks_cancel(task_id: int) -> dict:
    from core import tasks
    tasks.cancel(task_id)
    return {"ok": True}


# ── Notification action handler ──────────────────────────────────

class NotificationAction(BaseModel):
    action_id: str = Field(..., min_length=1, max_length=64)
    kind: str = Field(default="", max_length=32)
    data: dict[str, Any] = Field(default_factory=dict)


@router.post("/notification-action", dependencies=[Depends(require_api_key)])
async def notification_action(req: NotificationAction) -> dict:
    """Phone tells the PC the user tapped an action button on a push.

    Action IDs:
        email.mark_read   — mark a Gmail message as read
        email.read_aloud  — speak the subject/sender on PC TTS
        snooze.<minutes>  — re-fire the same notification after N minutes
        calendar.dismiss  — acknowledge a meeting alert (no-op log)
    """
    aid = req.action_id.strip()
    data = req.data or {}
    logger.info(f"notification action: {aid} kind={req.kind} data_keys={list(data)}")

    # ── Snooze (re-fire after N min) ─────────────────────────
    if aid.startswith("snooze."):
        try:
            minutes = int(aid.split(".", 1)[1])
        except Exception:
            minutes = 10
        from core import notifications, scheduler as sch
        title = data.get("__title", "Reminder") if isinstance(data, dict) else "Reminder"
        body = data.get("__body", "") if isinstance(data, dict) else ""

        def _refire(_t=title, _b=body, _d=data) -> None:
            notifications.push_async(_t, _b, data=_d)

        s = sch.get()
        if s is not None:
            s.add_interval(f"snooze_{aid}_{int(__import__('time').time())}",
                           _refire, seconds=minutes * 60)
            return {"ok": True, "action": aid, "snoozed_minutes": minutes}
        return {"ok": False, "error": "scheduler not running"}

    # ── Email actions ─────────────────────────────────────────
    if aid == "email.mark_read":
        msg_id = str(data.get("message_id", ""))
        if not msg_id:
            return {"ok": False, "error": "missing message_id"}
        try:
            from tools.gmail import _get_gmail_service
            svc = _get_gmail_service()
            svc.users().messages().modify(
                userId="me", id=msg_id,
                body={"removeLabelIds": ["UNREAD"]},
            ).execute()
            return {"ok": True, "action": aid}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    if aid == "email.read_aloud":
        msg_id = str(data.get("message_id", ""))
        if not msg_id:
            return {"ok": False, "error": "missing message_id"}
        try:
            from tools.gmail import _get_gmail_service, _parse_message
            from core import router as core_router
            svc = _get_gmail_service()
            full = svc.users().messages().get(
                userId="me", id=msg_id, format="full"
            ).execute()
            parsed = _parse_message(full)
            sender = parsed["from"].split("<")[0].strip(" \"'") or "unknown"
            subj = parsed["subject"] or parsed["snippet"][:140]
            spoken = f"From {sender}. {subj}"[:400]
            core_router.speak(spoken, kind="email_readout")
            return {"ok": True, "action": aid}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    # ── Calendar actions ─────────────────────────────────────
    if aid == "calendar.dismiss":
        return {"ok": True, "action": aid}

    return {"ok": False, "error": f"unknown action: {aid}"}


# ── Slim dashboard ───────────────────────────────────────────────

@router.get("/dashboard", dependencies=[Depends(require_api_key)])
async def dashboard_mobile() -> dict:
    """Compact dashboard payload (<5KB) for phone home screen.

    Same data as /api/dashboard but stripped of HTML formatting and trimmed
    to mobile essentials.
    """
    data: dict[str, Any] = {}

    vm = psutil.virtual_memory()
    data["system"] = {
        "cpu_percent": psutil.cpu_percent(interval=0.2),
        "ram_percent": vm.percent,
        "ram_used_gb": round(vm.used / (1024 ** 3), 1),
        "ram_total_gb": round(vm.total / (1024 ** 3), 1),
        "uptime_hours": round(
            (datetime.now().timestamp() - psutil.boot_time()) / 3600, 1
        ),
    }

    try:
        import requests
        resp = requests.get(
            "https://wttr.in/Bucharest?format=j1",
            timeout=4,
            headers={"User-Agent": "curl/7.68.0"},
        )
        cur = resp.json()["current_condition"][0]
        data["weather"] = {
            "city": "Bucharest",
            "temp_c": int(cur["temp_C"]),
            "feels_like": int(cur["FeelsLikeC"]),
            "description": cur["weatherDesc"][0]["value"],
            "humidity": int(cur["humidity"]),
        }
    except Exception:
        data["weather"] = None

    try:
        from tools.calendar_tool import get_schedule
        schedule = get_schedule(date="today")
        data["calendar"] = str(schedule)[:500] if schedule else "No events today."
    except Exception:
        data["calendar"] = None

    try:
        from tools.gmail import read_emails
        emails = read_emails(max_results=3)
        data["emails"] = str(emails)[:600] if emails else "Inbox empty."
    except Exception:
        data["emails"] = None

    try:
        from tools.spotify import spotify_now_playing
        data["spotify"] = str(spotify_now_playing())[:200]
    except Exception:
        data["spotify"] = None

    try:
        from tools.hue import hue_status
        data["lights"] = str(hue_status())[:200]
    except Exception:
        data["lights"] = None

    # ── Live presence ───────────────────────────────────────────
    try:
        from core import presence as _presence
        p = _presence.get()
        if p is not None:
            snap = p.snapshot()
            data["presence"] = {
                "state": snap.state,
                "quiet_hours": snap.quiet_hours,
                "pc_idle_seconds": int(snap.pc_idle_seconds),
            }
    except Exception:
        pass

    # ── Task summary ────────────────────────────────────────────
    try:
        from core import tasks as _tasks
        recent = _tasks.list_recent(limit=10)
        running = [t for t in recent if t["status"] in ("running", "pending")]
        data["tasks"] = {
            "running_count": len(running),
            "recent": [
                {"id": t["id"], "kind": t["kind"], "status": t["status"],
                 "prompt": t["prompt"][:80], "updated_at": t["updated_at"]}
                for t in recent[:5]
            ],
        }
    except Exception:
        data["tasks"] = None

    # ── Watches summary ─────────────────────────────────────────
    try:
        from core import watches as _watches
        all_watches = _watches.list_all(include_archived=False)
        active = [w for w in all_watches if w["status"] == "active"]
        fired = [w for w in all_watches if w["status"] == "fired"]
        data["watches"] = {
            "active_count": len(active),
            "fired_count": len(fired),
            "last_fired": (fired[0] if fired else None) and {
                "id": fired[0]["id"],
                "url": fired[0]["url"][:80],
                "label": fired[0]["label"],
                "last_message": fired[0]["last_message"],
                "last_check_at": fired[0]["last_check_at"],
            },
        }
    except Exception:
        data["watches"] = None

    # ── Pending plan (top priority — phone shows a banner) ──────
    try:
        from core import plans as _plans
        pending = _plans.most_recent_pending()
        if pending:
            data["pending_plan"] = {
                "id": pending["id"],
                "summary": pending["summary"],
                "step_count": len(pending["steps"]),
                "step_summaries": [
                    s.get("summary") or s.get("tool")
                    for s in pending["steps"]
                ][:5],
                "created_at": pending["created_at"],
            }
        else:
            data["pending_plan"] = None
    except Exception:
        data["pending_plan"] = None

    # ── Quick routines (voice-triggered, for chip row) ──────────
    try:
        from core import routines as _routines
        voice_routines = _routines.voice_routines()
        data["quick_routines"] = [
            {"name": r.name, "description": r.description}
            for r in voice_routines[:6]
        ]
    except Exception:
        data["quick_routines"] = []

    # ── Active context (for "what am I doing") ──────────────────
    try:
        from core import context as _context
        brief = _context.active_brief()
        if brief:
            data["active_brief"] = brief[:200]
    except Exception:
        pass

    return data


# ── Ask (SSE streaming) ──────────────────────────────────────────

class AskRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)
    language: str = Field(default="en", pattern="^(en|ro)$")
    play_on_pc: bool = False


@router.post("/ask", dependencies=[Depends(require_api_key)])
async def ask(req: AskRequest):
    """Stream brain reply as Server-Sent Events.

    Each event is JSON: {"type": "chunk", "text": "..."}.
    Final event: {"type": "done"}. Errors: {"type": "error", "message": "..."}.
    """
    if _brain is None:
        raise HTTPException(503, "Brain not initialized.")

    loop = asyncio.get_event_loop()
    queue: asyncio.Queue[str | None] = asyncio.Queue()
    full_reply_chunks: list[str] = []

    def _producer() -> None:
        """Drain the brain generator on a worker thread; push chunks to the asyncio queue."""
        try:
            # Tag this turn's origin so the cross-device conversation store
            # can show it came from the phone.
            for chunk in _brain.think_stream(req.text, req.language, source="mobile"):
                full_reply_chunks.append(chunk)
                event = json.dumps({"type": "chunk", "text": chunk})
                asyncio.run_coroutine_threadsafe(queue.put(f"data: {event}\n\n"), loop)
        except Exception as exc:
            logger.exception("Mobile /ask brain stream failed")
            err = json.dumps({"type": "error", "message": str(exc)[:200]})
            asyncio.run_coroutine_threadsafe(queue.put(f"data: {err}\n\n"), loop)
        finally:
            done = json.dumps({"type": "done"})
            asyncio.run_coroutine_threadsafe(queue.put(f"data: {done}\n\n"), loop)
            asyncio.run_coroutine_threadsafe(queue.put(None), loop)

    threading.Thread(target=_producer, daemon=True).start()

    async def _event_stream():
        while True:
            item = await queue.get()
            if item is None:
                break
            yield item
        if req.play_on_pc and _tts is not None and full_reply_chunks:
            text = "".join(full_reply_chunks)
            try:
                threading.Thread(
                    target=_tts.speak,
                    args=(text,),
                    kwargs={"language": req.language},
                    daemon=True,
                ).start()
            except Exception:
                logger.exception("Mobile /ask play_on_pc failed")

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ── Voice memo (record → transcribe → LLM auto-tag → save) ──────

@router.post("/memo", dependencies=[Depends(require_api_key)])
async def voice_memo(
    audio: UploadFile = File(...),
    language: str = Form("en"),
    auto_save: str = Form("true"),
) -> dict:
    """Record on the phone, get transcript + auto-categorisation, save to memory.

    Pipeline:
      1. Whisper transcribe
      2. LLM classifies into one of {idea, todo, note, decision, reminder}
         and extracts a short key + value + tags
      3. If auto_save, persist to the long-term memory store (FTS5 + Chroma)
    """
    if _stt is None:
        raise HTTPException(503, "STT not initialised.")
    wav_bytes = await audio.read()
    if not wav_bytes:
        raise HTTPException(400, "Empty audio upload.")

    loop = asyncio.get_event_loop()
    transcript, lang = await loop.run_in_executor(
        None, _stt.transcribe, wav_bytes, language,
    )
    transcript = (transcript or "").strip()
    if not transcript:
        return {"transcript": "", "saved": False,
                "error": "empty transcript"}

    classification = await loop.run_in_executor(
        None, _classify_memo, transcript,
    )

    save_flag = auto_save.lower() in ("1", "true", "yes")
    saved = False
    if save_flag:
        try:
            from tools.memory_tool import _memory
            if _memory is not None:
                _memory.remember(
                    classification.get("key") or transcript[:40],
                    classification.get("value") or transcript[:240],
                    classification.get("category") or "note",
                )
                saved = True
        except Exception:
            logger.exception("memo save failed (non-fatal)")

    # Mirror to cross-device conversation so it shows on PC HUD too
    try:
        from core import conversation
        conversation.append("user", f"[memo] {transcript}",
                            source="mobile", lang=lang)
        if classification.get("key"):
            conversation.append(
                "assistant",
                f"Saved as {classification['category']}: {classification['key']}",
                source="mobile", lang=lang,
            )
    except Exception:
        pass

    return {
        "transcript": transcript,
        "language": lang,
        "category": classification.get("category", "note"),
        "key": classification.get("key", ""),
        "value": classification.get("value", ""),
        "tags": classification.get("tags", []),
        "urgency": classification.get("urgency", "normal"),
        "saved": saved,
    }


def _classify_memo(text: str) -> dict[str, Any]:
    """Run a single LLM call to categorise + summarise a memo. Returns dict."""
    import json as _json
    from openai import OpenAI

    from core.config import load_config
    cfg = load_config()
    oai = cfg.get("apis", {}).get("openai", {})
    client = OpenAI(api_key=oai.get("api_key", ""))

    sys = (
        "You categorise short voice memos. Reply ONLY with valid JSON "
        "matching this schema:\n"
        "{\n"
        '  "category": "idea" | "todo" | "note" | "decision" | "reminder",\n'
        '  "key":      <short title, ≤40 chars>,\n'
        '  "value":    <one-sentence summary, ≤240 chars>,\n'
        '  "tags":     [<short topic tags, lowercase, ≤5 items>],\n'
        '  "urgency":  "low" | "normal" | "high"\n'
        "}\n"
        "Pick the category that best matches the memo's intent. "
        "Use 'reminder' only if the memo refers to a future time. "
        "Default urgency is 'normal'."
    )
    try:
        resp = client.chat.completions.create(
            model=oai.get("model", "gpt-4.1-mini"),
            max_tokens=300,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": sys},
                {"role": "user", "content": text[:2000]},
            ],
        )
        raw = (resp.choices[0].message.content or "").strip()
        data = _json.loads(raw) if raw else {}
        # Sanitise
        cat = str(data.get("category", "note")).lower()
        if cat not in ("idea", "todo", "note", "decision", "reminder"):
            cat = "note"
        return {
            "category": cat,
            "key": str(data.get("key", text[:40])).strip()[:80],
            "value": str(data.get("value", text[:240])).strip()[:300],
            "tags": [str(t).lower().strip()[:24]
                     for t in (data.get("tags") or [])][:5],
            "urgency": str(data.get("urgency", "normal")).lower(),
        }
    except Exception as exc:
        logger.warning(f"memo classify fallback: {exc}")
        return {
            "category": "note",
            "key": text[:40],
            "value": text[:240],
            "tags": [],
            "urgency": "normal",
        }


# ── Vision (phone camera → vision LLM) ───────────────────────────

@router.post("/vision", dependencies=[Depends(require_api_key)])
async def vision(
    image: UploadFile = File(...),
    prompt: str = Form("Describe what's in this image."),
    language: str = Form("en"),
) -> dict:
    """Receive an image from the phone, run it through GPT-4 Vision, return the answer.

    The Q&A is appended to the cross-device conversation store so it shows
    up on PC HUD and other surfaces. Useful for: scanning menus/receipts,
    identifying objects, OCR, "what's this?", etc.
    """
    image_bytes = await image.read()
    if not image_bytes:
        raise HTTPException(400, "Empty image upload.")
    if len(image_bytes) > 10 * 1024 * 1024:
        raise HTTPException(413, "Image too large (10 MB max).")

    user_prompt = (prompt or "").strip() or "Describe what's in this image."
    if language == "ro":
        user_prompt += " Reply in Romanian."

    loop = asyncio.get_event_loop()
    try:
        from tools.vision import analyze_image_bytes
        answer = await loop.run_in_executor(
            None, analyze_image_bytes, image_bytes, user_prompt, 1024,
        )
    except Exception as exc:
        logger.exception("Mobile /vision failed")
        raise HTTPException(500, f"Vision failed: {exc}")

    answer = (answer or "").strip()

    # Persist to the shared conversation so the PC sees it too
    try:
        from core import conversation
        conversation.append("user", f"[image] {user_prompt}",
                            source="mobile", lang=language)
        conversation.append("assistant", answer,
                            source="mobile", lang=language)
    except Exception:
        logger.exception("conversation append failed (non-fatal)")

    return {"answer": answer, "language": language}


# ── Transcribe (phone mic → text) ────────────────────────────────

@router.post("/transcribe", dependencies=[Depends(require_api_key)])
async def transcribe(
    audio: UploadFile = File(...),
    language: str = Form("en"),
) -> dict:
    """Receive a WAV upload from the phone, return Whisper transcript."""
    if _stt is None:
        raise HTTPException(503, "STT not initialized.")
    if language not in ("en", "ro"):
        language = "en"

    wav_bytes = await audio.read()
    if not wav_bytes:
        raise HTTPException(400, "Empty audio upload.")

    loop = asyncio.get_event_loop()
    text, lang = await loop.run_in_executor(
        None, _stt.transcribe, wav_bytes, language
    )
    return {"text": text, "language": lang}


# ── Synthesize (text → audio for phone playback) ─────────────────

class SynthesizeRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)
    language: str = Field(default="en", pattern="^(en|ro)$")


@router.post("/synthesize", dependencies=[Depends(require_api_key)])
async def synthesize(req: SynthesizeRequest):
    """Render text via the configured TTS engine, return WAV bytes."""
    if _tts is None:
        raise HTTPException(503, "TTS not initialized.")

    loop = asyncio.get_event_loop()
    wav = await loop.run_in_executor(
        None, _tts.synthesize_to_wav, req.text, req.language
    )
    if not wav:
        raise HTTPException(500, "TTS produced no audio.")

    return Response(
        content=wav,
        media_type="audio/wav",
        headers={"Cache-Control": "no-store"},
    )


# ── Device registration (FCM push tokens) ────────────────────────

class DeviceRegister(BaseModel):
    token: str = Field(..., min_length=10, max_length=512)
    platform: str = Field(default="", max_length=16)
    label: str = Field(default="", max_length=64)


@router.post("/devices/register", dependencies=[Depends(require_api_key)])
async def register_device(req: DeviceRegister) -> dict:
    from ui.db_managers import device_db
    device_db.register(req.token, platform=req.platform, label=req.label)
    return {"ok": True, "registered": req.token[:12] + "…"}


@router.delete("/devices/{token}", dependencies=[Depends(require_api_key)])
async def unregister_device(token: str) -> dict:
    from ui.db_managers import device_db
    device_db.unregister(token)
    return {"ok": True}


@router.get("/devices", dependencies=[Depends(require_api_key)])
async def list_devices() -> dict:
    from ui.db_managers import device_db
    devices = device_db.list_active()
    # Hide raw token, only return prefix for verification
    return {
        "count": len(devices),
        "devices": [
            {**d, "token": d["token"][:12] + "…"}
            for d in devices
        ],
    }


class PushTest(BaseModel):
    title: str = Field(default="Jarvis")
    body: str = Field(default="Test notification from PC.")


@router.post("/push/test", dependencies=[Depends(require_api_key)])
async def push_test(req: PushTest) -> dict:
    from core import notifications
    if not notifications.is_configured():
        raise HTTPException(503, "FCM not configured (apis.fcm.*).")
    sent = notifications.push(req.title, req.body, data={"source": "test"})
    return {"sent": sent}
