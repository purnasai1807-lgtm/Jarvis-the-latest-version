"""Screenshot tool: capture specific monitors or all monitors."""

import os
from datetime import datetime
from pathlib import Path

from loguru import logger

_SCREENSHOT_DIR = Path("data/screenshots")


def screenshot(monitor: int = 0) -> str:
    """Capture a screenshot. monitor=0 for all, 1-4 for specific monitor."""
    import mss
    import mss.tools

    _SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    with mss.mss() as sct:
        available = len(sct.monitors) - 1  # monitors[0] is the combined virtual screen

        if monitor < 0 or monitor > available:
            return f"Invalid monitor {monitor}. Available: 0 (all) or 1-{available}."

        # monitor=0 → capture all (virtual screen), else specific monitor
        target = sct.monitors[monitor]
        img = sct.grab(target)

        label = "all" if monitor == 0 else f"mon{monitor}"
        filename = f"screenshot_{label}_{timestamp}.png"
        filepath = str(_SCREENSHOT_DIR / filename)

        mss.tools.to_png(img.rgb, img.size, output=filepath)
        abs_path = os.path.abspath(filepath)
        logger.info(f"Screenshot saved: {abs_path}")
        return f"Screenshot saved to {abs_path}"


# ── Tool definitions ─────────────────────────────────────────────

TOOLS = [
    {
        "name": "screenshot",
        "description": "Take a screenshot of a specific monitor or all monitors. The user has 4 monitors. Use monitor=0 for all monitors combined, or 1-4 for a specific one.",
        "input_schema": {
            "type": "object",
            "properties": {
                "monitor": {
                    "type": "integer",
                    "description": "Monitor number: 0 = all monitors, 1-4 = specific monitor",
                },
            },
            "required": ["monitor"],
        },
    },
]

HANDLERS = {
    "screenshot": screenshot,
}
