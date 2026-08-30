"""
Phase 4 — Screen Awareness (Vision)

Captures screenshots with mss, sends them to GPT-4.1 mini (vision) for analysis.
No local OCR model needed — the vision model handles everything.

Tools: see_screen, see_all_screens, find_on_screen, read_screen_text
"""

import base64
import io

from loguru import logger

_api_key: str = ""
_model: str = "gpt-4.1-mini"
_MAX_WIDTH = 1920   # resize wide monitors before sending


def init_vision(config: dict) -> None:
    global _api_key, _model
    oai_cfg = config.get("apis", {}).get("openai", {})
    _api_key = oai_cfg.get("api_key", "")
    _model = oai_cfg.get("model", "gpt-4.1-mini")


# ── Internal helpers ──────────────────────────────────────────────

def _capture_b64(monitor: int = 0, region: dict | None = None) -> tuple[str, tuple[int, int]]:
    """Capture a monitor (or region) and return (base64_png, (width, height))."""
    import mss
    from PIL import Image

    with mss.mss() as sct:
        available = len(sct.monitors) - 1
        if region:
            raw = sct.grab(region)
        else:
            idx = min(monitor, available) if monitor > 0 else 0
            raw = sct.grab(sct.monitors[idx])

    pil = Image.frombytes("RGB", raw.size, raw.rgb)

    # Resize if wider than _MAX_WIDTH (saves API tokens, stays sharp enough)
    if pil.width > _MAX_WIDTH:
        ratio = _MAX_WIDTH / pil.width
        pil = pil.resize((int(pil.width * ratio), int(pil.height * ratio)), Image.LANCZOS)

    buf = io.BytesIO()
    pil.save(buf, format="PNG", optimize=True)
    b64 = base64.standard_b64encode(buf.getvalue()).decode()
    return b64, pil.size


def analyze_image_bytes(image_bytes: bytes, prompt: str,
                        max_tokens: int = 1024) -> str:
    """Public helper — accept raw image bytes (PNG/JPG), resize, ask vision."""
    from PIL import Image
    pil = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    if pil.width > _MAX_WIDTH:
        ratio = _MAX_WIDTH / pil.width
        pil = pil.resize((int(pil.width * ratio), int(pil.height * ratio)),
                         Image.LANCZOS)
    buf = io.BytesIO()
    pil.save(buf, format="PNG", optimize=True)
    b64 = base64.standard_b64encode(buf.getvalue()).decode()
    return _ask_vision(b64, prompt, max_tokens=max_tokens)


def _ask_vision(img_b64: str, prompt: str, max_tokens: int = 1024) -> str:
    """Send an image to GPT-4.1 mini vision and return the text response."""
    from openai import OpenAI
    client = OpenAI(api_key=_api_key)
    response = client.chat.completions.create(
        model=_model,
        max_tokens=max_tokens,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{img_b64}",
                    },
                },
                {"type": "text", "text": prompt},
            ],
        }]
    )
    return response.choices[0].message.content


# ── Tool handlers ─────────────────────────────────────────────────

def see_screen(monitor: int = 1) -> str:
    """Capture a monitor and describe what's on it."""
    try:
        b64, size = _capture_b64(monitor)
        logger.info(f"see_screen(monitor={monitor}): captured {size[0]}x{size[1]}")
        prompt = (
            "Describe what you see on this screen in 2-4 sentences. "
            "Focus on what the user is currently doing — open apps, active windows, "
            "visible content. Be specific and concise."
        )
        result = _ask_vision(b64, prompt)
        logger.info(f"see_screen: {result[:80]}…")
        return result
    except Exception as exc:
        logger.error(f"see_screen failed: {exc}")
        return f"Could not capture monitor {monitor}: {exc}"


def see_all_screens() -> str:
    """Capture all monitors at once and describe each one."""
    try:
        import mss
        with mss.mss() as sct:
            num_monitors = len(sct.monitors) - 1

        descriptions = []
        for i in range(1, num_monitors + 1):
            b64, size = _capture_b64(i)
            logger.info(f"see_all_screens: monitor {i} captured {size[0]}x{size[1]}")
            prompt = (
                f"This is monitor {i} of {num_monitors}. "
                "Describe what's on this screen in 1-2 sentences. "
                "Focus on the active window and main content."
            )
            desc = _ask_vision(b64, prompt)
            descriptions.append(f"Monitor {i}: {desc}")

        return "\n\n".join(descriptions)
    except Exception as exc:
        logger.error(f"see_all_screens failed: {exc}")
        return f"Could not capture all screens: {exc}"


def find_on_screen(description: str, monitor: int = 0) -> str:
    """Find a UI element on screen and describe its location."""
    try:
        b64, size = _capture_b64(monitor)
        logger.info(f"find_on_screen({description!r}): captured {size[0]}x{size[1]}")
        prompt = (
            f"I'm looking for: '{description}'\n"
            "Is this element visible on the screen? "
            "If yes, describe exactly where it is (e.g. top-left area, center, "
            "inside which window, next to what). "
            "If no, say it's not visible and describe what IS on the screen."
        )
        result = _ask_vision(b64, prompt)
        logger.info(f"find_on_screen: {result[:80]}…")
        return result
    except Exception as exc:
        logger.error(f"find_on_screen failed: {exc}")
        return f"Could not search screen: {exc}"


def read_screen_text(monitor: int = 1) -> str:
    """Extract all readable text from a monitor."""
    try:
        b64, size = _capture_b64(monitor)
        logger.info(f"read_screen_text(monitor={monitor}): captured {size[0]}x{size[1]}")
        prompt = (
            "Extract and return ALL readable text visible on this screen. "
            "Preserve the layout as much as possible. "
            "Include text from windows, dialogs, notifications, taskbar, and any open documents."
        )
        result = _ask_vision(b64, prompt)
        logger.info(f"read_screen_text: {len(result)} chars")
        return result
    except Exception as exc:
        logger.error(f"read_screen_text failed: {exc}")
        return f"Could not read screen text: {exc}"


# ── Tool definitions ──────────────────────────────────────────────

TOOLS = [
    {
        "name": "see_screen",
        "description": (
            "Capture a monitor and describe what's on it using computer vision. "
            "Use when the user asks 'what's on my screen', 'what am I looking at', "
            "'what's on monitor 2', 'look at my screen', etc. "
            "The user has 4 monitors. Default to monitor=1 if unspecified."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "monitor": {
                    "type": "integer",
                    "description": "Monitor number 1-4. Use 0 to capture all monitors combined.",
                },
            },
            "required": ["monitor"],
        },
    },
    {
        "name": "see_all_screens",
        "description": (
            "Capture all monitors and describe each one individually. "
            "Use when the user asks 'what's on all my screens' or 'describe all monitors'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "find_on_screen",
        "description": (
            "Search for a specific UI element, button, text, or object on screen using vision. "
            "Use when the user asks 'find X on my screen', 'where is the X button', "
            "'can you see Y on screen', etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "description": {
                    "type": "string",
                    "description": "What to look for, e.g. 'the close button', 'a login form', 'error dialog'",
                },
                "monitor": {
                    "type": "integer",
                    "description": "Which monitor to search (0=all combined, 1-4=specific). Default 0.",
                },
            },
            "required": ["description"],
        },
    },
    {
        "name": "read_screen_text",
        "description": (
            "Extract and read all text visible on a monitor. "
            "Use when the user asks 'read what's on my screen', 'what does it say on monitor 2', "
            "'read that error message', 'what text is on screen', etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "monitor": {
                    "type": "integer",
                    "description": "Monitor number 1-4 to read text from. Default 1.",
                },
            },
            "required": ["monitor"],
        },
    },
]

HANDLERS = {
    "see_screen": see_screen,
    "see_all_screens": see_all_screens,
    "find_on_screen": find_on_screen,
    "read_screen_text": read_screen_text,
}
