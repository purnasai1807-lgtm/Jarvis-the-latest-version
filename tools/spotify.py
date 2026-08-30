"""Spotify control — spotipy API (if credentials) + media-key fallback."""

import pyautogui
from loguru import logger

_sp = None
_sp_config = None


def init_spotify(config: dict) -> None:
    global _sp_config
    _sp_config = config.get("apis", {}).get("spotify", {})


def _get_spotify():
    """Lazy-init authenticated Spotify client. Returns None if no creds."""
    global _sp
    if _sp is not None:
        return _sp

    if not _sp_config or not _sp_config.get("client_id"):
        return None

    try:
        import spotipy
        from spotipy.oauth2 import SpotifyOAuth

        _sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
            client_id=_sp_config["client_id"],
            client_secret=_sp_config["client_secret"],
            redirect_uri=_sp_config.get("redirect_uri", "http://localhost:8888/callback"),
            scope=(
                "user-modify-playback-state "
                "user-read-playback-state "
                "user-read-currently-playing "
                "playlist-read-private"
            ),
            cache_path="data/.spotify_cache",
        ))
        logger.info("Spotify API authenticated")
        return _sp
    except Exception as exc:
        logger.warning(f"Spotify API auth failed: {exc}")
        return None


# ── Tool handlers ─────────────────────────────────────────────────

def spotify_control(action: str, query: str = "") -> str:
    """Play, pause, skip, previous, or search+play."""
    action = action.lower().strip()

    if action == "pause":
        sp = _get_spotify()
        if sp:
            try:
                sp.pause_playback()
                return "Paused playback."
            except Exception:
                pass
        pyautogui.press("playpause")
        return "Paused playback."

    if action == "play" and not query:
        sp = _get_spotify()
        if sp:
            try:
                sp.start_playback()
                return "Resumed playback."
            except Exception:
                pass
        pyautogui.press("playpause")
        return "Resumed playback."

    if action == "next":
        sp = _get_spotify()
        if sp:
            try:
                sp.next_track()
                return "Skipped to next track."
            except Exception:
                pass
        pyautogui.press("nexttrack")
        return "Skipped to next track."

    if action == "previous":
        sp = _get_spotify()
        if sp:
            try:
                sp.previous_track()
                return "Playing previous track."
            except Exception:
                pass
        pyautogui.press("prevtrack")
        return "Playing previous track."

    if action in ("play", "search") and query:
        sp = _get_spotify()
        if sp:
            return _search_and_play(sp, query)
        return _search_and_play_fallback(query)

    return f"Unknown Spotify action: {action}"


def spotify_now_playing() -> str:
    """Get info about the currently playing track."""
    sp = _get_spotify()
    if not sp:
        return "Spotify API not configured — can't check current track."

    try:
        current = sp.current_playback()
        if not current or not current.get("item"):
            return "Nothing is currently playing on Spotify."

        track = current["item"]
        name = track["name"]
        artists = ", ".join(a["name"] for a in track["artists"])
        album = track["album"]["name"]
        progress = current.get("progress_ms", 0) // 1000
        duration = track.get("duration_ms", 0) // 1000
        is_playing = current.get("is_playing", False)
        state = "Playing" if is_playing else "Paused"

        mins_p, secs_p = divmod(progress, 60)
        mins_d, secs_d = divmod(duration, 60)

        return (
            f"{state}: {name} by {artists} "
            f"(album: {album}) — {mins_p}:{secs_p:02d}/{mins_d}:{secs_d:02d}"
        )
    except Exception as exc:
        logger.error(f"spotify_now_playing failed: {exc}")
        return f"Error checking current track: {exc}"


def spotify_volume(level: int) -> str:
    """Set Spotify volume (0-100)."""
    sp = _get_spotify()
    if not sp:
        return "Spotify API not configured — can't set volume."

    level = max(0, min(100, level))
    try:
        sp.volume(level)
        return f"Spotify volume set to {level}%."
    except Exception as exc:
        logger.error(f"spotify_volume failed: {exc}")
        return f"Error setting volume: {exc}"


def spotify_queue(query: str) -> str:
    """Search for a track and add it to the queue."""
    sp = _get_spotify()
    if not sp:
        return "Spotify API not configured — can't add to queue."

    try:
        results = sp.search(q=query, limit=1, type="track")
        tracks = results.get("tracks", {}).get("items", [])
        if not tracks:
            return f"No tracks found for '{query}'."

        track = tracks[0]
        name = track["name"]
        artist = track["artists"][0]["name"]
        sp.add_to_queue(track["uri"])
        return f"Added to queue: {name} by {artist}."
    except Exception as exc:
        logger.error(f"spotify_queue failed: {exc}")
        return f"Error adding to queue: {exc}"


# ── Internal helpers ──────────────────────────────────────────────

def _search_and_play(sp, query: str) -> str:
    try:
        results = sp.search(q=query, limit=1, type="track")
        tracks = results.get("tracks", {}).get("items", [])

        if not tracks:
            return f"No tracks found for '{query}'."

        track = tracks[0]
        name = track["name"]
        artist = track["artists"][0]["name"]
        uri = track["uri"]

        try:
            sp.start_playback(uris=[uri])
        except Exception:
            try:
                sp.add_to_queue(uri)
                return f"Queued: {name} by {artist}. Press play if not already playing."
            except Exception as exc:
                return f"Found '{name}' by {artist} but couldn't start playback: {exc}"

        logger.info(f"Spotify: playing {name} by {artist}")
        return f"Playing: {name} by {artist}."

    except Exception as exc:
        logger.error(f"Spotify search failed: {exc}")
        return f"Spotify search error: {exc}"


def _search_and_play_fallback(query: str) -> str:
    import subprocess
    import time

    subprocess.Popen('start "" "spotify"', shell=True)
    time.sleep(2)
    pyautogui.hotkey("ctrl", "l")
    time.sleep(0.3)
    pyautogui.hotkey("ctrl", "a")
    import pyperclip
    pyperclip.copy(query)
    pyautogui.hotkey("ctrl", "v")
    time.sleep(2)
    pyautogui.press("enter")
    logger.info(f"Spotify fallback: searched and played '{query}'")
    return f"Playing '{query}' on Spotify."


# ── Tool definitions ─────────────────────────────────────────────

TOOLS = [
    {
        "name": "spotify_control",
        "description": (
            "Control Spotify music playback. Actions: 'play' (resume or search+play), "
            "'pause', 'next' (skip), 'previous'. "
            "To play a specific song, set action='play' and query='song name or artist'. "
            "Works with or without Spotify API credentials."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["play", "pause", "next", "previous"],
                    "description": "Playback action",
                },
                "query": {
                    "type": "string",
                    "description": "Song/artist/album to search and play (only for 'play' action)",
                },
            },
            "required": ["action"],
        },
    },
    {
        "name": "spotify_now_playing",
        "description": (
            "Get info about the currently playing track on Spotify — "
            "song name, artist, album, progress. Use when the user asks "
            "'what song is this', 'what's playing', 'ce melodie e asta', etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "spotify_volume",
        "description": (
            "Set Spotify playback volume to a specific level (0-100). "
            "Use when the user says 'set Spotify volume to 50', 'turn down the music', etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "level": {
                    "type": "integer",
                    "description": "Volume level from 0 to 100",
                },
            },
            "required": ["level"],
        },
    },
    {
        "name": "spotify_queue",
        "description": (
            "Search for a track and add it to the Spotify play queue. "
            "Use when the user says 'queue this song', 'add X to queue', "
            "'play X next', etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Song/artist to search for and add to queue",
                },
            },
            "required": ["query"],
        },
    },
]

HANDLERS = {
    "spotify_control": spotify_control,
    "spotify_now_playing": spotify_now_playing,
    "spotify_volume": spotify_volume,
    "spotify_queue": spotify_queue,
}
