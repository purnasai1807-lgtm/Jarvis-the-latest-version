"""
Instagram integration via Playwright with a persistent browser profile.

First use opens a visible Chromium window so the user can log in once —
the session (cookies) is cached in data/instagram_profile and reused after that.

Tools: instagram_send_message, instagram_read_messages
"""

import re
import time
from pathlib import Path

from loguru import logger

_PROFILE_DIR = Path("data/instagram_profile")
_playwright = None
_context = None


def _get_page():
    """Return an Instagram page from a persistent, cookie-preserving browser context."""
    global _playwright, _context

    from playwright.sync_api import sync_playwright

    if _playwright is None:
        _playwright = sync_playwright().start()

    if _context is None:
        _PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        _context = _playwright.chromium.launch_persistent_context(
            str(_PROFILE_DIR), headless=False, no_viewport=True,
        )

    page = _context.pages[0] if _context.pages else _context.new_page()
    return page


def _ensure_logged_in(page) -> bool:
    page.goto("https://www.instagram.com/direct/inbox/", wait_until="domcontentloaded")
    time.sleep(2)
    if "accounts/login" in page.url:
        logger.warning("Instagram: not logged in — waiting up to 60s for manual login")
        try:
            page.wait_for_url("**/direct/inbox/**", timeout=60000)
        except Exception:
            return False
    return True


def instagram_send_message(contact: str, message: str) -> str:
    """Send an Instagram direct message to a user."""
    try:
        page = _get_page()
        if not _ensure_logged_in(page):
            return "Instagram requires manual login — a browser window was opened, please log in and try again."

        page.get_by_role("button", name=re.compile("New message", re.I)).click()
        time.sleep(1.0)

        search = page.get_by_placeholder(re.compile("Search", re.I))
        search.fill(contact)
        time.sleep(1.5)

        page.locator("div[role='dialog'] div[role='button']").first.click()
        time.sleep(0.5)
        page.get_by_role("button", name=re.compile("^Chat$|^Next$", re.I)).click()
        time.sleep(1.0)

        box = page.get_by_role("textbox", name=re.compile("Message", re.I))
        box.click()
        box.fill(message)
        page.keyboard.press("Enter")
        time.sleep(0.5)

        logger.info(f"instagram_send_message: to '{contact}': {message[:60]}")
        return f"Instagram message sent to {contact}."
    except Exception as exc:
        logger.error(f"instagram_send_message failed: {exc}")
        return f"Could not send Instagram message: {exc}"


def instagram_read_messages(contact: str, limit: int = 5) -> str:
    """Open an Instagram DM thread and read recent messages via vision."""
    try:
        page = _get_page()
        if not _ensure_logged_in(page):
            return "Instagram requires manual login — a browser window was opened, please log in and try again."

        search = page.get_by_placeholder(re.compile("Search", re.I))
        search.click()
        search.fill(contact)
        time.sleep(1.5)
        page.keyboard.press("Enter")
        time.sleep(1.5)

        screenshot = page.screenshot()
        import base64
        b64 = base64.standard_b64encode(screenshot).decode()

        from tools.vision import _ask_vision
        result = _ask_vision(b64, f"Read the last {limit} messages in this Instagram DM thread. List them as: Name: message text")
        logger.info(f"instagram_read_messages: {contact}")
        return result
    except Exception as exc:
        logger.error(f"instagram_read_messages failed: {exc}")
        return f"Could not read Instagram messages: {exc}"


# ── Tool definitions ──────────────────────────────────────────────

TOOLS = [
    {
        "name": "instagram_send_message",
        "description": (
            "Send an Instagram direct message to a user. "
            "Use when the user says 'DM X on Instagram', 'send an Instagram message to X'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "contact": {"type": "string", "description": "Instagram username to message"},
                "message": {"type": "string", "description": "Message text to send"},
            },
            "required": ["contact", "message"],
        },
    },
    {
        "name": "instagram_read_messages",
        "description": (
            "Read recent Instagram direct messages from a user. "
            "Use when the user says 'read my Instagram DMs from X', 'what did X send me on Instagram'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "contact": {"type": "string", "description": "Instagram username to read messages from"},
                "limit": {"type": "integer", "description": "Number of messages to read (default 5)"},
            },
            "required": ["contact"],
        },
    },
]

HANDLERS = {
    "instagram_send_message": instagram_send_message,
    "instagram_read_messages": instagram_read_messages,
}
