"""
Phase 9 — Web Dashboard + Claude Code Terminal
FastAPI backend serving dashboard data + WebSocket for Claude terminal.

Token-efficient architecture: uses a single persistent Claude Code subprocess
(via --input-format stream-json) instead of spawning a new process per message.
System prompt loaded once, prompt caching optimal across all turns.
"""

import asyncio
import http.client
import json
import re
import subprocess
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

_ANSI_RE = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]|\x1b\].*?\x07')


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub('', text)

import psutil
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

_STATIC = Path(__file__).parent / "static"
_PROJECT = Path(__file__).resolve().parent.parent
_config: dict = {}
_claude_history: list[dict] = []  # shared conversation log
_rate_limit_info: dict = {}  # cached Claude session usage limits


def _fetch_rate_limit_utilization() -> dict | None:
    """Query Anthropic API to get real plan usage utilization from response headers."""
    try:
        creds_path = Path.home() / ".claude" / ".credentials.json"
        if not creds_path.exists():
            return None
        creds = json.loads(creds_path.read_text())
        token = creds.get("claudeAiOauth", {}).get("accessToken")
        if not token:
            return None

        conn = http.client.HTTPSConnection("api.anthropic.com", timeout=10)
        body = json.dumps({
            "model": "claude-haiku-4-5-20251001",
            "max_tokens": 1,
            "messages": [{"role": "user", "content": "hi"}],
        })
        conn.request("POST", "/v1/messages", body, {
            "Content-Type": "application/json",
            "x-api-key": token,
            "anthropic-version": "2023-06-01",
        })
        resp = conn.getresponse()
        resp.read()  # drain body
        if resp.status != 200:
            conn.close()
            return None

        headers = {k.lower(): v for k, v in resp.getheaders()}
        conn.close()

        result = {}
        for key, field in [
            ("anthropic-ratelimit-unified-5h-utilization", "five_hour_utilization"),
            ("anthropic-ratelimit-unified-7d-utilization", "seven_day_utilization"),
            ("anthropic-ratelimit-unified-5h-reset", "five_hour_reset"),
            ("anthropic-ratelimit-unified-7d-reset", "seven_day_reset"),
        ]:
            if key in headers:
                result[field] = float(headers[key])
        return result if result else None
    except Exception as exc:
        logger.debug("Rate limit utilization fetch failed: {}", exc)
        return None
_session_stats: dict = {  # accumulated session usage stats
    "model": "",
    "claude_code_version": "",
    "session_id": "",
    "total_cost_usd": 0.0,
    "total_input_tokens": 0,
    "total_output_tokens": 0,
    "total_cache_read_tokens": 0,
    "total_cache_creation_tokens": 0,
    "num_messages": 0,
    "context_messages": 0,
    "fast_mode": "off",
}

from ui.routes import brain, briefing, projects, ide, settings, mobile
from ui.db_managers import voice_db

app = FastAPI(title="J.A.R.V.I.S. Dashboard")
app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")

# CORS — phone client connects from Tailscale IP / app webview / local dev.
# Origins narrowed via config.mobile.cors_origins; default "*" for first run.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include the modular routers
app.include_router(brain.router)
app.include_router(briefing.router)
app.include_router(projects.router)
app.include_router(ide.router)
app.include_router(settings.router)
app.include_router(mobile.router)


def init_dashboard(config: dict, brain_instance=None, tts_instance=None,
                    stt_instance=None) -> None:
    global _config, _rate_limit_info
    _config = config
    mobile.set_runtime(brain=brain_instance, tts=tts_instance, stt=stt_instance)
    cors_origins = config.get("mobile", {}).get("cors_origins")
    if cors_origins:
        for mw in app.user_middleware:
            if mw.cls is CORSMiddleware:
                mw.kwargs["allow_origins"] = cors_origins
                break
    # Fetch plan usage utilization at startup so the home page island has data immediately
    def _initial_fetch():
        global _rate_limit_info
        util = _fetch_rate_limit_utilization()
        if util:
            _rate_limit_info.update(util)
            logger.info("Plan usage: 5h={:.0f}%, 7d={:.0f}%",
                        util.get("five_hour_utilization", 0) * 100,
                        util.get("seven_day_utilization", 0) * 100)
    threading.Thread(target=_initial_fetch, daemon=True).start()


# ── Dashboard data endpoints ─────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    return (_STATIC / "index.html").read_text(encoding="utf-8")

@app.post("/api/quick-action")
async def quick_action(data: dict):
    action = data.get("action", "")
    try:
        if action == "lights off":
            from tools.hue import lights_control
            result = lights_control(action="off")
        elif action == "play music":
            from tools.spotify import spotify_control
            result = spotify_control(action="play")
        elif action == "read emails":
            from tools.gmail import read_emails
            result = read_emails(max_results=5)
        elif action == "lock pc":
            import subprocess
            subprocess.Popen(["rundll32.exe", "user32.dll,LockWorkStation"])
            result = "PC locked."
        else:
            return {"status": "error", "message": f"Unknown action: {action}"}
        return {"status": "success", "action": action, "message": str(result)[:200]}
    except Exception as e:
        return {"status": "error", "message": str(e)[:200]}

@app.get("/api/voice-log")
async def get_voice_log():
    return voice_db.get_today_logs()

@app.get("/api/dashboard")
async def dashboard_data():
    """Return all dashboard card data in one call."""
    data: dict[str, Any] = {}

    # System info
    data["system"] = {
        "cpu_percent": psutil.cpu_percent(interval=0.5),
        "ram_percent": psutil.virtual_memory().percent,
        "ram_used_gb": round(psutil.virtual_memory().used / (1024**3), 1),
        "ram_total_gb": round(psutil.virtual_memory().total / (1024**3), 1),
        "uptime_hours": round((datetime.now().timestamp() - psutil.boot_time()) / 3600, 1),
    }

    # Weather
    try:
        import requests
        resp = requests.get("https://wttr.in/Bucharest?format=j1",
                          timeout=5, headers={"User-Agent": "curl/7.68.0"})
        w = resp.json()
        cur = w["current_condition"][0]
        data["weather"] = {
            "city": "Bucharest",
            "temp_c": cur["temp_C"],
            "feels_like": cur["FeelsLikeC"],
            "description": cur["weatherDesc"][0]["value"],
            "humidity": cur["humidity"],
            "wind_kmph": cur["windspeedKmph"],
        }
    except Exception:
        data["weather"] = None

    # Calendar (today)
    try:
        from tools.calendar_tool import get_schedule
        data["calendar"] = get_schedule(date="today")
    except Exception:
        data["calendar"] = "Could not load calendar."

    # Emails (last 5)
    try:
        from tools.gmail import read_emails
        data["emails"] = read_emails(max_results=5)
    except Exception:
        data["emails"] = "Could not load emails."

    # Spotify
    try:
        from tools.spotify import spotify_now_playing
        data["spotify"] = spotify_now_playing()
    except Exception:
        data["spotify"] = "Could not check Spotify."

    # Lights
    try:
        from tools.hue import hue_status
        data["lights"] = hue_status()
    except Exception:
        data["lights"] = "Could not check lights."

    # ── Live Jarvis state (presence / tasks / watches / plans / routines) ──
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

    try:
        from core import tasks as _tasks
        recent = _tasks.list_recent(limit=10)
        data["tasks"] = {
            "running_count": len([t for t in recent
                                  if t["status"] in ("running", "pending")]),
            "recent": [
                {"id": t["id"], "kind": t["kind"], "status": t["status"],
                 "prompt": t["prompt"][:120], "updated_at": t["updated_at"],
                 "result_preview": (t.get("result") or "")[:200]}
                for t in recent[:6]
            ],
        }
    except Exception:
        pass

    try:
        from core import watches as _watches
        all_w = _watches.list_all(include_archived=False)
        data["watches"] = [
            {"id": w["id"], "label": w["label"], "url": w["url"][:80],
             "status": w["status"], "condition": w["condition"][:60],
             "interval_minutes": w["interval_seconds"] // 60,
             "hits": w["hits"], "last_message": w["last_message"]}
            for w in all_w[:8]
        ]
    except Exception:
        pass

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
                ][:6],
            }
    except Exception:
        pass

    try:
        from core import routines as _routines
        data["routines"] = [
            {
                "name": r.name,
                "description": r.description,
                "voice_phrases": [
                    p for t in r.triggers if t.type == "voice" for p in t.phrases
                ][:3],
                "schedule": [
                    {"time": t.time, "days": t.days}
                    for t in r.triggers if t.type == "schedule"
                ],
                "step_count": len(r.steps),
            }
            for r in _routines.list_all()
        ]
    except Exception:
        pass

    try:
        from core import context as _context
        data["active_brief"] = _context.active_brief()
    except Exception:
        pass

    try:
        from core import scheduler as _scheduler
        s = _scheduler.get()
        if s is not None:
            jobs = s.list_jobs()
            data["scheduler"] = [
                {"name": j["name"], "kind": j["kind"],
                 "next_fire_in": j["next_fire_in"]}
                for j in jobs
            ]
    except Exception:
        pass

    return data


# ── Direct routes for routine/task/watch operations from web UI ──

@app.post("/api/routines/run")
async def web_run_routine(payload: dict):
    from core import routines as _routines
    name = str(payload.get("name", ""))
    if not name:
        return {"ok": False, "error": "missing name"}
    _routines.run_async(name)
    return {"ok": True, "name": name}


@app.post("/api/routines/reload")
async def web_reload_routines():
    from core import routines as _routines
    n = _routines.load()
    return {"ok": True, "loaded": n}


@app.post("/api/plan/confirm")
async def web_confirm_plan():
    from tools.plan_tool import confirm_last_plan
    return {"result": confirm_last_plan()}


@app.post("/api/plan/cancel")
async def web_cancel_plan():
    from tools.plan_tool import cancel_last_plan
    return {"result": cancel_last_plan()}


@app.post("/api/watch/stop")
async def web_stop_watch(payload: dict):
    from core import watches as _watches
    wid = int(payload.get("id", 0))
    return {"ok": _watches.stop(wid)}


@app.post("/api/watch/reactivate")
async def web_reactivate_watch(payload: dict):
    from core import watches as _watches
    wid = int(payload.get("id", 0))
    return {"ok": _watches.reactivate(wid)}


@app.post("/api/task/cancel")
async def web_cancel_task(payload: dict):
    from core import tasks as _tasks
    tid = int(payload.get("id", 0))
    _tasks.cancel(tid)
    return {"ok": True}


@app.get("/api/system")
async def system_info():
    """Live system stats for auto-refresh."""
    gpu_pct = 0
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=3
        )
        if result.returncode == 0:
            gpu_pct = int(result.stdout.strip().split('\n')[0])
    except Exception:
        pass
    return {
        "cpu_percent": psutil.cpu_percent(interval=0.3),
        "ram_percent": psutil.virtual_memory().percent,
        "ram_used_gb": round(psutil.virtual_memory().used / (1024**3), 1),
        "gpu_percent": gpu_pct,
        "time": datetime.now().strftime("%H:%M:%S"),
    }


@app.get("/api/claude-limit")
async def claude_limit():
    """Return cached Claude session usage limits."""
    return _rate_limit_info


@app.get("/api/session-stats")
async def session_stats():
    """Return accumulated session usage stats."""
    return {**_session_stats, "rate_limit": _rate_limit_info}




# ── Claude Code WebSocket terminal ───────────────────────────────

_ws_clients: list[WebSocket] = []
_history_ids: set = set()  # track saved message hashes to prevent duplicates


def _add_to_history(role: str, content: str):
    """Add a message to history with deduplication."""
    msg_id = f"{role}:{hash(content)}"
    if msg_id in _history_ids:
        return
    _history_ids.add(msg_id)
    _claude_history.append({
        "role": role,
        "content": content,
        "time": datetime.now().strftime("%H:%M:%S"),
    })


async def _broadcast(msg: dict):
    """Send a message to all connected WebSocket clients."""
    dead = []
    for ws in _ws_clients:
        try:
            await ws.send_json(msg)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _ws_clients.remove(ws)


def broadcast_to_clients(msg: dict):
    """Thread-safe broadcast to all WebSocket clients. Callable from any thread."""
    if _main_loop is None:
        return
    try:
        asyncio.run_coroutine_threadsafe(_broadcast(msg), _main_loop)
    except Exception:
        pass


def _handle_claude_event(event: dict, full_text_parts: list):
    """Process a single streaming event from the persistent Claude process."""
    global _rate_limit_info, _session_stats
    evt_type = event.get("type")

    if evt_type == "raw_text":
        text = event.get("content", "")
        broadcast_to_clients({"type": "claude_stream", "content": text + "\n"})
        full_text_parts.append(text + "\n")

    elif evt_type == "system" and event.get("subtype") == "init":
        _session_stats["model"] = event.get("model", "")
        _session_stats["claude_code_version"] = event.get("claude_code_version", "")
        _session_stats["session_id"] = event.get("session_id", "")
        _session_stats["fast_mode"] = event.get("fast_mode_state", "off")
        broadcast_to_clients({"type": "session_info", "stats": _session_stats})

    elif evt_type == "stream_event":
        inner = event.get("event", {})
        inner_type = inner.get("type", "")

        if inner_type == "content_block_delta":
            delta = inner.get("delta", {})
            if delta.get("type") == "text_delta":
                text = delta.get("text", "")
                if text:
                    broadcast_to_clients({"type": "claude_stream", "content": text})
                    full_text_parts.append(text)

        elif inner_type == "content_block_start":
            cb = inner.get("content_block", {})
            if cb.get("type") == "tool_use":
                tool_name = cb.get("name", "unknown")
                tool_msg = f"\n🔧 **{tool_name}**\n"
                broadcast_to_clients({"type": "claude_stream", "content": tool_msg})
                full_text_parts.append(tool_msg)

    elif evt_type == "tool_use_event":
        tool_result = event.get("tool_result", "")
        if tool_result:
            result_preview = str(tool_result)[:300]
            result_msg = f"```\n{result_preview}\n```\n"
            broadcast_to_clients({"type": "claude_stream", "content": result_msg})
            full_text_parts.append(result_msg)

    elif evt_type == "rate_limit_event":
        info = event.get("rate_limit_info", {})
        if info:
            # Enrich with real utilization from API headers (background)
            def _enrich_rate_limit():
                global _rate_limit_info
                util = _fetch_rate_limit_utilization()
                if util:
                    _rate_limit_info.update(util)
                    broadcast_to_clients({"type": "rate_limit", "info": _rate_limit_info})
            _rate_limit_info = info
            broadcast_to_clients({"type": "rate_limit", "info": info})
            threading.Thread(target=_enrich_rate_limit, daemon=True).start()

    elif evt_type == "result":
        if not full_text_parts and event.get("result"):
            full_text_parts.append(event["result"])
            broadcast_to_clients({"type": "claude_stream", "content": event["result"]})

        cost = event.get("total_cost_usd", 0)
        usage = event.get("usage", {})
        _session_stats["total_cost_usd"] += cost
        _session_stats["total_input_tokens"] += usage.get("input_tokens", 0)
        _session_stats["total_output_tokens"] += usage.get("output_tokens", 0)
        _session_stats["total_cache_read_tokens"] += usage.get("cache_read_input_tokens", 0)
        _session_stats["total_cache_creation_tokens"] += usage.get("cache_creation_input_tokens", 0)
        _session_stats["num_messages"] += 1
        _session_stats["fast_mode"] = event.get("fast_mode_state", _session_stats.get("fast_mode", "off"))
        model_usage = event.get("modelUsage", {})
        if model_usage:
            _session_stats["model_usage"] = model_usage
        broadcast_to_clients({"type": "session_stats", "stats": _session_stats})


def _run_claude_streaming(prompt: str, image_data: str = None):
    """Send prompt to the persistent Claude process and stream to WebSocket clients."""
    from ui.claude_session import get_claude

    _add_to_history("user", prompt)
    broadcast_to_clients({"type": "user", "content": prompt})
    broadcast_to_clients({"type": "claude_working", "content": "true"})

    full_text_parts = []

    def on_event(event):
        _handle_claude_event(event, full_text_parts)

    try:
        claude = get_claude()

        if image_data:
            # Strip data URL prefix if present
            raw = image_data.split(",", 1)[1] if "," in image_data else image_data
            completed = claude.send_with_image(
                prompt, raw, on_event=on_event, timeout=300,
            )
        else:
            completed = claude.send(prompt, on_event=on_event, timeout=300)

        full_output = "".join(full_text_parts).strip()
        broadcast_to_clients({"type": "claude_working", "content": "false"})
        _add_to_history("assistant", full_output)
        _session_stats["context_messages"] = len(_claude_history)
        broadcast_to_clients({"type": "session_stats", "stats": _session_stats})
        broadcast_to_clients({"type": "claude_done", "content": full_output})
        # Phase 3 — also push to registered phones so the user gets pinged
        # even when the dashboard isn't open.
        try:
            from core import notifications
            preview = (full_output[:80] + "…") if len(full_output) > 80 else full_output
            notifications.push_async(
                "🤖 Claude Code finished",
                preview or "Task complete.",
                data={"kind": "claude_done"},
            )
        except Exception:
            logger.debug("claude_done push notification failed", exc_info=True)

        if not completed:
            broadcast_to_clients({"type": "claude_error", "content": "Response timed out."})

    except Exception as exc:
        error_msg = f"Error: {exc}"
        broadcast_to_clients({"type": "claude_working", "content": "false"})
        broadcast_to_clients({"type": "claude_error", "content": error_msg})
        _add_to_history("error", error_msg)
        _session_stats["context_messages"] = len(_claude_history)
        broadcast_to_clients({"type": "session_stats", "stats": _session_stats})


_main_loop: asyncio.AbstractEventLoop = None


@app.websocket("/ws/claude")
async def claude_terminal(ws: WebSocket):
    await ws.accept()
    _ws_clients.append(ws)

    # Send full history in order on connect
    await ws.send_json({"type": "history", "messages": [
        {"role": m["role"], "content": m["content"], "time": m.get("time", "")}
        for m in _claude_history
    ]})
    # Send current session stats and rate limit info
    await ws.send_json({"type": "session_info", "stats": _session_stats})
    await ws.send_json({"type": "session_stats", "stats": _session_stats})
    if _rate_limit_info:
        await ws.send_json({"type": "rate_limit", "info": _rate_limit_info})

    try:
        while True:
            data = await ws.receive_text()
            msg = json.loads(data)
            if msg.get("type") == "stop":
                from ui.claude_session import get_claude
                get_claude().stop()
                broadcast_to_clients({"type": "claude_working", "content": "false"})
                broadcast_to_clients({"type": "claude_error", "content": "Task cancelled."})
            elif msg.get("type") == "command":
                cmd = msg.get("name", "")
                if cmd == "clear":
                    from ui.claude_session import get_claude
                    get_claude().clear()
                    _claude_history.clear()
                    _history_ids.clear()
                    # Reset session stats for new conversation
                    _session_stats["total_cost_usd"] = 0.0
                    _session_stats["total_input_tokens"] = 0
                    _session_stats["total_output_tokens"] = 0
                    _session_stats["total_cache_read_tokens"] = 0
                    _session_stats["total_cache_creation_tokens"] = 0
                    _session_stats["num_messages"] = 0
                    _session_stats["context_messages"] = 0
                    _session_stats.pop("model_usage", None)
                    broadcast_to_clients({"type": "cleared"})
                    broadcast_to_clients({"type": "session_stats", "stats": _session_stats})
                elif cmd == "set_model":
                    from ui.claude_session import get_claude
                    new_model = msg.get("value", "").strip()
                    if new_model:
                        get_claude().set_model(new_model)
                        _session_stats["model"] = new_model
                        await ws.send_json({"type": "session_info", "stats": _session_stats})
                        broadcast_to_clients({"type": "session_stats", "stats": _session_stats})
                elif cmd == "get_stats":
                    await ws.send_json({"type": "session_stats", "stats": _session_stats})
                    if _rate_limit_info:
                        await ws.send_json({"type": "rate_limit", "info": _rate_limit_info})
            elif msg.get("type") == "prompt":
                prompt = msg["content"]
                image = msg.get("image")
                threading.Thread(
                    target=_run_claude_streaming,
                    args=(prompt, image),
                    daemon=True,
                ).start()
    except WebSocketDisconnect:
        _ws_clients.remove(ws)


# ── Server startup ───────────────────────────────────────────────

def start_dashboard(config: dict, port: int = 9000, brain=None, tts=None, stt=None):
    """Start the dashboard server in a background thread."""
    global _main_loop
    init_dashboard(config, brain_instance=brain, tts_instance=tts, stt_instance=stt)

    # Proactive checks are now driven by core.scheduler (initialised in main.py)
    # — no per-poller threads here.

    # Ensure static dir exists
    _STATIC.mkdir(parents=True, exist_ok=True)

    import uvicorn

    def _run():
        global _main_loop
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            _main_loop = loop

            config_uv = uvicorn.Config(
                app, host="0.0.0.0", port=port,
                log_level="warning", loop="asyncio",
            )
            server = uvicorn.Server(config_uv)
            loop.run_until_complete(server.serve())
        except Exception as exc:
            logger.error(f"Dashboard server crashed: {exc}")

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    # Wait briefly to confirm server actually starts
    import time
    time.sleep(1)
    import socket
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=2):
            logger.info(f"Dashboard server started on http://localhost:{port}")
    except OSError:
        logger.warning(f"Dashboard server may have failed to start on port {port}")
