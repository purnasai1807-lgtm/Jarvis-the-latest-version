"""
Phase 5 — Philips Hue smart light control.

Uses phue library (direct bridge API, no cloud).
Credentials stored in ~/.python_hue after one-time pairing.

Tools: lights_control, hue_scene
"""

from loguru import logger

_bridge_ip: str = ""
_bridge = None

# Common color names → CIE 1931 xy values
_COLORS = {
    "red":      [0.6484, 0.3309],
    "green":    [0.1700, 0.7000],
    "blue":     [0.1532, 0.0475],
    "yellow":   [0.4317, 0.4996],
    "orange":   [0.5614, 0.4156],
    "purple":   [0.2451, 0.0826],
    "violet":   [0.2451, 0.0826],
    "pink":     [0.3944, 0.1685],
    "cyan":     [0.1530, 0.2200],
    "white":    None,   # use color temp instead
    "warm":     None,
    "cool":     None,
    "daylight": None,
}

# Color name → color temperature in mireds (for white tones)
_COLOR_TEMPS = {
    "warm":     400,   # ~2500K — cosy/candlelight
    "white":    300,   # ~3300K — neutral white
    "cool":     200,   # ~5000K — cool white
    "daylight": 153,   # ~6500K — daylight
}


def init_hue(config: dict) -> None:
    global _bridge_ip
    _bridge_ip = config.get("smart_home", {}).get("hue_bridge_ip", "")


def _get_bridge():
    global _bridge
    if _bridge is None:
        from phue import Bridge
        ip = _bridge_ip or None
        _bridge = Bridge(ip)
        _bridge.connect()
        logger.info(f"Hue bridge connected — {len(_bridge.lights)} lights")
    return _bridge


def _resolve_group(bridge, room: str) -> int | None:
    """Find a group ID by fuzzy name match. Returns None to mean 'all lights'."""
    if not room or room.lower() in ("all", "everywhere", "toate"):
        return None
    groups = bridge.get_group()
    room_lower = room.lower()
    for gid, g in groups.items():
        if room_lower in g["name"].lower() or g["name"].lower() in room_lower:
            return int(gid)
    return None  # fallback: affect all


def _brightness_to_hue(pct: int) -> int:
    """Convert 0-100% to Hue brightness 1-254."""
    return max(1, min(254, int(pct / 100 * 254)))


# ── Handlers ─────────────────────────────────────────────────────

def lights_control(
    action: str = "on",
    brightness: int | None = None,
    color: str | None = None,
    room: str = "all",
) -> str:
    """Turn lights on/off, set brightness and color."""
    try:
        bridge = _get_bridge()
        group_id = _resolve_group(bridge, room)
        target = f"group '{room}'" if group_id else "all lights"

        command: dict = {}

        action_lower = action.lower()
        if action_lower in ("off", "turn off", "opreste", "stinge"):
            command["on"] = False
        elif action_lower in ("on", "turn on", "porneste", "aprinde"):
            command["on"] = True
        elif action_lower in ("toggle",):
            # get current state
            if group_id:
                state = bridge.get_group(group_id, "action")
                command["on"] = not state.get("on", True)
            else:
                command["on"] = not bridge.lights[0].on
        else:
            command["on"] = True  # default to on for brightness/color changes

        if brightness is not None:
            command["bri"] = _brightness_to_hue(max(0, min(100, brightness)))
            if brightness == 0:
                command["on"] = False

        if color:
            col = color.lower().strip()
            if col in _COLORS and _COLORS[col] is not None:
                command["xy"] = _COLORS[col]
                command["on"] = True
            elif col in _COLOR_TEMPS:
                command["ct"] = _COLOR_TEMPS[col]
                command["on"] = True
            else:
                # Try partial match
                for name, xy in _COLORS.items():
                    if name in col or col in name:
                        if xy:
                            command["xy"] = xy
                        elif name in _COLOR_TEMPS:
                            command["ct"] = _COLOR_TEMPS[name]
                        command["on"] = True
                        break

        if group_id:
            bridge.set_group(group_id, command)
        else:
            bridge.set_group(0, command)  # group 0 = all lights

        parts = []
        if "on" in command:
            parts.append("on" if command["on"] else "off")
        if "bri" in command:
            parts.append(f"{brightness}% brightness")
        if "xy" in command:
            parts.append(f"{color} color")
        elif "ct" in command:
            parts.append(f"{color} white")

        desc = ", ".join(parts) if parts else "updated"
        logger.info(f"lights_control: {target} → {desc}")
        return f"Done — {target} set to {desc}."

    except Exception as exc:
        logger.error(f"lights_control failed: {exc}")
        return f"Could not control lights: {exc}"


def hue_scene(scene: str, room: str = "Home") -> str:
    """Activate a Hue scene by name."""
    try:
        bridge = _get_bridge()
        group_id = _resolve_group(bridge, room)

        scenes = bridge.get_scene()
        scene_lower = scene.lower()

        # Find best match — prefer scenes in the target group
        best_id = None
        best_name = None
        for sid, s in scenes.items():
            s_name = s["name"].lower()
            matches = scene_lower in s_name or s_name in scene_lower
            in_group = str(group_id) == str(s.get("group", ""))
            if matches:
                if group_id and in_group:
                    best_id, best_name = sid, s["name"]
                    break
                elif best_id is None:
                    best_id, best_name = sid, s["name"]

        if not best_id:
            available = ", ".join(sorted({s["name"] for s in scenes.values()}))
            return f"Scene '{scene}' not found. Available: {available}"

        bridge.activate_scene(str(group_id) if group_id else "1", best_id)
        logger.info(f"hue_scene: activated '{best_name}'")
        return f"Scene '{best_name}' activated."

    except Exception as exc:
        logger.error(f"hue_scene failed: {exc}")
        return f"Could not activate scene: {exc}"


def hue_status() -> str:
    """Get the current state of all lights."""
    try:
        bridge = _get_bridge()
        lines = []
        for light in bridge.lights:
            state = "on" if light.on else "off"
            bri = round(light.brightness / 254 * 100) if light.on else 0
            lines.append(f"{light.name}: {state}, {bri}% brightness")
        result = "\n".join(lines)
        logger.info(f"hue_status: {result}")
        return result
    except Exception as exc:
        logger.error(f"hue_status failed: {exc}")
        return f"Could not get light status: {exc}"


# ── Tool definitions ──────────────────────────────────────────────

TOOLS = [
    {
        "name": "lights_control",
        "description": (
            "Control Philips Hue smart lights — turn on/off, set brightness, change color. "
            "Examples: 'turn off the lights', 'dim to 30%', 'set lights to blue', "
            "'turn on warm white', 'lights off'. "
            "Supports colors: red, green, blue, yellow, orange, purple, pink, cyan, "
            "warm, white, cool, daylight."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "'on', 'off', or 'toggle'",
                },
                "brightness": {
                    "type": "integer",
                    "description": "Brightness 0-100 (percentage). Omit to keep current.",
                },
                "color": {
                    "type": "string",
                    "description": "Color name: red/green/blue/yellow/orange/purple/pink/cyan/warm/white/cool/daylight",
                },
                "room": {
                    "type": "string",
                    "description": "Room or group name (e.g. 'Home', 'Music area'). Default 'all'.",
                },
            },
            "required": ["action"],
        },
    },
    {
        "name": "hue_scene",
        "description": (
            "Activate a Philips Hue lighting scene by name. "
            "Available scenes: Relax, Read, Concentrate, Energize, Nightlight, "
            "Red light, Rosu portocaliu, Cool bright, Valley dawn, Midsummer sun, Under the tree, Rest. "
            "Use when the user asks for a mood or preset: 'movie mode', 'relax', 'reading light', etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "scene": {
                    "type": "string",
                    "description": "Scene name to activate (fuzzy matched)",
                },
                "room": {
                    "type": "string",
                    "description": "Room/group to apply scene to. Default 'Home'.",
                },
            },
            "required": ["scene"],
        },
    },
    {
        "name": "hue_status",
        "description": (
            "Get the current on/off state and brightness of all Hue lights. "
            "Use when the user asks 'are the lights on?', 'what's the light status?', etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
]

HANDLERS = {
    "lights_control": lights_control,
    "hue_scene": hue_scene,
    "hue_status": hue_status,
}
