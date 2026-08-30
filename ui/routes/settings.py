from fastapi import APIRouter
from pathlib import Path

router = APIRouter(prefix="/api/settings", tags=["settings"])
_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config.yaml"


def _load_config():
    if not _CONFIG_PATH.exists():
        return {}
    import yaml
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@router.get("")
async def get_settings():
    config = _load_config()
    # Return only the safe, user-facing settings
    return {
        "tts_engine": config.get("tts", {}).get("engine", "kokoro"),
        "stt_model": config.get("stt", {}).get("model_size", "small"),
        "wake_threshold": config.get("wake_word", {}).get("threshold", 0.3),
        "language": config.get("language", {}).get("default", "en"),
        "openai_model": config.get("apis", {}).get("openai", {}).get("model", "gpt-4.1-mini"),
    }


@router.put("")
async def update_settings(data: dict):
    """Update specific safe settings. Does NOT overwrite the whole config."""
    import yaml
    config = _load_config()

    # Map frontend fields to config paths (only safe fields)
    _SAFE_FIELDS = {
        "tts_engine": ("tts", "engine"),
        "wake_threshold": ("wake_word", "threshold"),
        "language": ("language", "default"),
    }

    changed = []
    for key, value in data.items():
        if key not in _SAFE_FIELDS:
            continue
        section, field = _SAFE_FIELDS[key]
        if section not in config:
            config[section] = {}
        config[section][field] = value
        changed.append(key)

    if changed:
        with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
            yaml.safe_dump(config, f, default_flow_style=False, allow_unicode=True)

    return {"status": "success", "changed": changed}


@router.get("/status")
async def get_api_status():
    config = _load_config()
    status = {}

    status["OpenAI"] = "Connected" if config.get("apis", {}).get("openai", {}).get("api_key") else "Not configured"
    status["Spotify"] = "Connected" if config.get("apis", {}).get("spotify", {}).get("client_id") else "Not configured"
    status["Hue"] = "Connected" if config.get("smart_home", {}).get("hue_bridge_ip") or Path(__file__).resolve().parent.parent.parent.joinpath(".python_hue").exists() else "Not configured"
    status["Gmail"] = "Connected" if Path(__file__).resolve().parent.parent.parent.joinpath("data/google_token.json").exists() else "Not configured"
    status["Discord"] = "Connected" if config.get("apis", {}).get("discord", {}).get("bot_token") else "Not configured"
    status["ElevenLabs"] = "Connected" if config.get("apis", {}).get("elevenlabs", {}).get("api_key") else "Not configured"

    return status
