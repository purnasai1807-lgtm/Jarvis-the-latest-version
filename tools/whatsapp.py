"""
Phase 6 — WhatsApp Desktop automation via keyboard shortcuts.

Uses the installed WhatsApp Desktop app (UWP) — no browser, no session management.
Ctrl+N → search contact → Enter → paste message → Enter.

Tools: whatsapp_send, whatsapp_read
"""

import subprocess
import time

import pyautogui
import pyperclip
from loguru import logger

_WA_UWP = r"shell:AppsFolder\5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App"
_WA_EXE_NAMES = ["whatsapp"]   # window title fragments to match


def _focus_whatsapp() -> bool:
    """Bring WhatsApp Desktop to foreground. Opens it if not running."""
    import win32gui
    import win32con

    def _find_hwnd():
        result = []
        def cb(hwnd, _):
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd).lower()
                if any(n in title for n in _WA_EXE_NAMES):
                    result.append(hwnd)
        win32gui.EnumWindows(cb, None)
        return result[0] if result else None

    hwnd = _find_hwnd()
    if not hwnd:
        subprocess.Popen(["explorer.exe", _WA_UWP])
        time.sleep(4)
        hwnd = _find_hwnd()

    if not hwnd:
        return False

    try:
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
        time.sleep(0.5)
        return True
    except Exception as exc:
        logger.warning(f"WhatsApp focus warning: {exc}")
        return False


def _type_text(text: str) -> None:
    """Type text using clipboard to handle unicode (Romanian chars etc.)."""
    old = ""
    try:
        old = pyperclip.paste()
    except Exception:
        pass
    pyperclip.copy(text)
    pyautogui.hotkey("ctrl", "v")
    time.sleep(0.2)
    try:
        pyperclip.copy(old)
    except Exception:
        pass


# ── Handlers ─────────────────────────────────────────────────────

def whatsapp_send(contact: str, message: str) -> str:
    """Send a WhatsApp message via the desktop app."""
    try:
        if not _focus_whatsapp():
            return "Could not open WhatsApp Desktop."

        time.sleep(0.3)

        # Ctrl+N opens the New Chat dialog with a search field
        pyautogui.hotkey("ctrl", "n")
        time.sleep(1.0)

        # Type contact name to search
        _type_text(contact)
        time.sleep(1.5)

        # Press Enter to open the first matching chat
        pyautogui.press("enter")
        time.sleep(0.8)

        # Type message (via clipboard for unicode support)
        _type_text(message)
        time.sleep(0.2)

        # Send
        pyautogui.press("enter")
        time.sleep(0.3)

        logger.info(f"whatsapp_send: sent to '{contact}': {message[:60]}")
        return f"WhatsApp message sent to {contact}."

    except Exception as exc:
        logger.error(f"whatsapp_send failed: {exc}")
        return f"Could not send WhatsApp message: {exc}"


def whatsapp_read(contact: str, limit: int = 5) -> str:
    """Open a WhatsApp chat and take a screenshot for vision to read."""
    try:
        if not _focus_whatsapp():
            return "Could not open WhatsApp Desktop."

        time.sleep(0.3)

        # Open search and navigate to the contact
        pyautogui.hotkey("ctrl", "n")
        time.sleep(1.0)
        _type_text(contact)
        time.sleep(1.5)
        pyautogui.press("enter")
        time.sleep(1.0)

        # Take a screenshot of the chat window and return it for vision
        import mss, base64, io
        from PIL import Image
        with mss.mss() as sct:
            img = sct.grab(sct.monitors[1])
        pil = Image.frombytes("RGB", img.size, img.rgb)
        buf = io.BytesIO()
        pil.save(buf, format="PNG")
        b64 = base64.standard_b64encode(buf.getvalue()).decode()

        # Ask Claude Vision to read the messages
        from tools.vision import _ask_vision
        result = _ask_vision(b64, f"Read the last {limit} messages in this WhatsApp chat. List them as: ContactName: message text")
        logger.info(f"whatsapp_read: {contact}")
        return result

    except Exception as exc:
        logger.error(f"whatsapp_read failed: {exc}")
        return f"Could not read WhatsApp messages: {exc}"


# ── Tool definitions ──────────────────────────────────────────────

TOOLS = [
    {
        "name": "whatsapp_send",
        "description": (
            "Send a WhatsApp message to a contact using the WhatsApp Desktop app. "
            "Use when the user says 'WhatsApp X saying Y', 'trimite pe WhatsApp lui X mesajul Y', "
            "'text X on WhatsApp', etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "contact": {"type": "string", "description": "Contact name as it appears in WhatsApp"},
                "message": {"type": "string", "description": "Message text to send"},
            },
            "required": ["contact", "message"],
        },
    },
    {
        "name": "whatsapp_read",
        "description": (
            "Read recent WhatsApp messages from a contact using the desktop app. "
            "Use when the user says 'read my WhatsApp from X', 'what did X say on WhatsApp'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "contact": {"type": "string", "description": "Contact name to read messages from"},
                "limit": {"type": "integer", "description": "Number of messages to read (default 5)"},
            },
            "required": ["contact"],
        },
    },
]

HANDLERS = {
    "whatsapp_send": whatsapp_send,
    "whatsapp_read": whatsapp_read,
}
