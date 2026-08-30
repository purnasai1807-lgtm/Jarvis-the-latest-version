"""
Phase 5 — Google Nest Audio / Chromecast speaker control.

Announcements: edge-tts generates MP3 → local HTTP server serves it → cast URL to speaker.
Also supports volume control and playback control on the speaker.

Tools: speaker_announce, speaker_volume, speaker_control
"""

import socket
import time

from loguru import logger

_CAST_HOST = ""             # set via init_chromecast(config), or auto-discovered if blank
_CAST_PORT = 8009
_SERVE_PORT = 9877          # local HTTP port for serving TTS audio
_cast = None                # persistent Chromecast connection


def init_chromecast(config: dict) -> None:
    global _CAST_HOST
    _CAST_HOST = config.get("smart_home", {}).get("nest_ip", "")


def _get_cast():
    global _cast
    if _cast is None or not _cast.socket_client.is_alive():
        import pychromecast
        if _CAST_HOST:
            _cast = pychromecast.get_chromecast_from_host(
                (_CAST_HOST, _CAST_PORT, None, None, None)
            )
        else:
            chromecasts, _ = pychromecast.get_chromecasts()
            if not chromecasts:
                raise RuntimeError("No Chromecast/Nest devices found on the network.")
            _cast = chromecasts[0]
        _cast.wait(timeout=10)
        logger.info(f"Chromecast connected — vol={_cast.status.volume_level:.0%}")
    return _cast


def _local_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    finally:
        s.close()


def _make_handler(filepath: str):
    """HTTP handler that serves a single file."""
    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "audio/mpeg")
            self.end_headers()
            with open(filepath, "rb") as f:
                self.wfile.write(f.read())
        def log_message(self, *args):
            pass  # silence HTTP logs
    return _Handler


def _generate_tts_mp3(text: str, lang: str = "en") -> bytes:
    """Generate TTS MP3 bytes using edge-tts."""
    import edge_tts

    voice = "ro-RO-EmilNeural" if lang == "ro" else "en-US-GuyNeural"

    async def _gen():
        communicate = edge_tts.Communicate(text, voice)
        buf = io.BytesIO()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                buf.write(chunk["data"])
        return buf.getvalue()

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_gen())
    finally:
        loop.close()


def _cast_audio_url(url: str) -> None:
    """Cast a media URL to the speaker and wait for playback to finish."""
    cast = _get_cast()
    mc = cast.media_controller
    mc.play_media(url, "audio/mpeg")
    mc.block_until_active(timeout=10)

    # Wait for playback to complete (max 60s)
    deadline = time.time() + 60
    while time.time() < deadline:
        mc.update_status()
        if mc.status.player_state in ("IDLE", "UNKNOWN", None):
            break
        time.sleep(0.5)


# ── Handlers ─────────────────────────────────────────────────────

def speaker_announce(message: str, lang: str = "en") -> str:
    """Make a spoken announcement through the Google Nest Audio."""
    try:
        import urllib.parse

        logger.info(f"speaker_announce: '{message[:60]}'")

        # Use Google TTS URL — Nest Audio fetches directly from Google,
        # no local HTTP server needed, no firewall issues.
        lang_code = "ro" if lang == "ro" else "en"
        encoded = urllib.parse.quote(message)
        url = (
            f"https://translate.google.com/translate_tts"
            f"?ie=UTF-8&q={encoded}&tl={lang_code}&client=tw-ob"
        )

        _cast_audio_url(url)
        logger.info(f"speaker_announce: done")
        return f"Announced on speaker: '{message}'"

    except Exception as exc:
        logger.error(f"speaker_announce failed: {exc}")
        return f"Could not announce on speaker: {exc}"


def speaker_volume(level: int) -> str:
    """Set the speaker volume (0-100)."""
    try:
        cast = _get_cast()
        vol = max(0.0, min(1.0, level / 100))
        cast.set_volume(vol)
        logger.info(f"speaker_volume: set to {level}%")
        return f"Speaker volume set to {level}%."
    except Exception as exc:
        logger.error(f"speaker_volume failed: {exc}")
        return f"Could not set speaker volume: {exc}"


def speaker_control(action: str) -> str:
    """Control speaker playback — pause, resume, or stop."""
    try:
        cast = _get_cast()
        mc = cast.media_controller
        action_lower = action.lower()

        if action_lower in ("pause", "stop"):
            mc.pause()
            logger.info("speaker_control: paused")
            return "Speaker paused."
        elif action_lower in ("resume", "play", "continue"):
            mc.play()
            logger.info("speaker_control: resumed")
            return "Speaker resumed."
        elif action_lower in ("skip", "next"):
            mc.skip()
            return "Skipped to next track."
        else:
            return f"Unknown action '{action}'. Use: pause, resume, stop, skip."

    except Exception as exc:
        logger.error(f"speaker_control failed: {exc}")
        return f"Could not control speaker: {exc}"


# ── Tool definitions ──────────────────────────────────────────────

TOOLS = [
    {
        "name": "speaker_announce",
        "description": (
            "Make a spoken announcement through the Google Nest Audio speaker. "
            "Use when the user says 'announce X on the speaker', 'say X on the speaker', "
            "'tell the speaker to say X', or asks to broadcast a message. "
            "The message is converted to speech and played on the physical speaker."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "The message to announce out loud on the speaker",
                },
                "lang": {
                    "type": "string",
                    "description": "'en' for English (default) or 'ro' for Romanian",
                },
            },
            "required": ["message"],
        },
    },
    {
        "name": "speaker_volume",
        "description": (
            "Set the volume of the Google Nest Audio speaker (0-100). "
            "Use when the user says 'turn up/down the speaker', 'set speaker volume to X%', etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "level": {
                    "type": "integer",
                    "description": "Volume level 0-100",
                },
            },
            "required": ["level"],
        },
    },
    {
        "name": "speaker_control",
        "description": (
            "Control playback on the Google Nest Audio — pause, resume, or skip. "
            "Use when the user says 'pause the speaker', 'resume', 'stop the speaker', etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "'pause', 'resume', 'stop', or 'skip'",
                },
            },
            "required": ["action"],
        },
    },
]

HANDLERS = {
    "speaker_announce": speaker_announce,
    "speaker_volume": speaker_volume,
    "speaker_control": speaker_control,
}
