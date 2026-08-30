"""Input tools: type text, press hotkeys, clipboard access."""

import time

import pyautogui
import pyperclip
from loguru import logger

# Disable pyautogui fail-safe (mouse to corner pauses) for assistant use
pyautogui.FAILSAFE = False


def type_text(text: str) -> str:
    """Type text at the current cursor position (uses clipboard paste for Unicode support)."""
    pyperclip.copy(text)
    pyautogui.hotkey("ctrl", "v")
    time.sleep(0.05)
    logger.info(f"Typed text: {text[:60]}{'…' if len(text) > 60 else ''}")
    return f"Typed: {text[:80]}"


def hotkey(keys: str) -> str:
    """Press a keyboard shortcut like 'ctrl+c', 'alt+tab', 'win+d'."""
    _KEY_MAP = {
        "win": "winleft", "windows": "winleft",
        "control": "ctrl", "escape": "esc",
        "return": "enter", "del": "delete",
    }
    parts = [k.strip().lower() for k in keys.split("+")]
    mapped = [_KEY_MAP.get(k, k) for k in parts]
    pyautogui.hotkey(*mapped)
    logger.info(f"Hotkey pressed: {keys}")
    return f"Pressed {keys}."


def clipboard_read() -> str:
    """Read current clipboard text content."""
    content = pyperclip.paste()
    logger.info(f"Clipboard read: {len(content)} chars")
    if not content:
        return "Clipboard is empty."
    return f"Clipboard contents:\n{content[:2000]}"


def clipboard_write(text: str) -> str:
    """Write text to the clipboard."""
    pyperclip.copy(text)
    logger.info(f"Clipboard write: {len(text)} chars")
    return f"Copied to clipboard: {text[:80]}"


# ── Tool definitions ─────────────────────────────────────────────

TOOLS = [
    {
        "name": "type_text",
        "description": "Type text at the current cursor position. Uses clipboard paste for full Unicode support.",
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "The text to type",
                },
            },
            "required": ["text"],
        },
    },
    {
        "name": "hotkey",
        "description": "Press a keyboard shortcut. Format: keys separated by '+'. Examples: 'ctrl+c', 'alt+tab', 'win+d', 'ctrl+shift+esc', 'alt+f4'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "keys": {
                    "type": "string",
                    "description": "Key combination, e.g. 'ctrl+c', 'alt+tab', 'win+d'",
                },
            },
            "required": ["keys"],
        },
    },
    {
        "name": "clipboard_read",
        "description": "Read the current text contents of the clipboard.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "clipboard_write",
        "description": "Write/copy text to the clipboard.",
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Text to copy to clipboard",
                },
            },
            "required": ["text"],
        },
    },
]

HANDLERS = {
    "type_text": type_text,
    "hotkey": hotkey,
    "clipboard_read": clipboard_read,
    "clipboard_write": clipboard_write,
}
