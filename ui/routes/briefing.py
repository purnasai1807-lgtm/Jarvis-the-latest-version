from fastapi import APIRouter
from datetime import datetime
from loguru import logger
import threading

router = APIRouter(prefix="/api/briefing", tags=["briefing"])


@router.get("")
async def get_briefing():
    data = {
        "greeting": f"Good morning, Purna Sai. It is {datetime.now().strftime('%A, %B %d')}.",
        "weather_summary": "",
        "agenda": [],
        "news": [],
        "memory": [],
        "suggestions": [],
    }

    # Real weather from wttr.in
    try:
        import requests
        resp = requests.get(
            "https://wttr.in/Bucharest?format=j1",
            timeout=5, headers={"User-Agent": "curl/7.68.0"},
        )
        w = resp.json()
        cur = w["current_condition"][0]
        data["weather_summary"] = (
            f"{cur['temp_C']}°C, {cur['weatherDesc'][0]['value']}, "
            f"feels like {cur['FeelsLikeC']}°C"
        )
    except Exception as e:
        logger.debug(f"Briefing weather error: {e}")
        data["weather_summary"] = "Weather data unavailable."

    # Real calendar
    try:
        from tools.calendar_tool import get_schedule
        schedule_text = get_schedule(date="today")
        # Parse the text into agenda items if possible
        if schedule_text and "no events" not in schedule_text.lower():
            for line in schedule_text.strip().split("\n"):
                line = line.strip("- •").strip()
                if line:
                    data["agenda"].append({
                        "time": "",
                        "title": line,
                        "location": "",
                    })
        if not data["agenda"]:
            data["agenda"].append({"time": "", "title": "No events today.", "location": ""})
    except Exception as e:
        logger.debug(f"Briefing calendar error: {e}")
        data["agenda"].append({"time": "", "title": "Calendar unavailable.", "location": ""})

    # Real memory highlights
    try:
        from tools.memory_tool import _memory
        if _memory:
            facts = _memory.list_facts()[:5]
            data["memory"] = [f"{f['key']}: {f['value']}" for f in facts]
    except Exception as e:
        logger.debug(f"Briefing memory error: {e}")

    # Suggestions based on real state
    try:
        from tools.gmail import read_emails
        unread = read_emails(max_results=3)
        if unread and "no" not in str(unread).lower()[:20]:
            data["suggestions"].append({
                "text": "You have unread emails.",
                "action": "read_emails",
            })
    except Exception:
        pass

    return data


@router.post("/audio")
async def generate_audio_briefing():
    """Speak the briefing aloud via Jarvis TTS."""
    def _speak_briefing():
        try:
            from tools.memory_tool import _morning_briefing
            text = _morning_briefing()
            from core.tts import speak_streamed
            speak_streamed(text)
        except Exception as e:
            logger.error(f"Audio briefing error: {e}")

    threading.Thread(target=_speak_briefing, daemon=True).start()
    return {"status": "started"}


@router.get("/news")
async def get_news():
    return {"categories": []}
