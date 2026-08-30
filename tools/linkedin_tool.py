"""
LinkedIn integration via Playwright with a persistent browser profile.

First use opens a visible Chromium window so the user can log in once —
the session (cookies) is cached in data/linkedin_profile and reused after that.

Tools: linkedin_post, linkedin_send_message
"""

import re
import time
from pathlib import Path

from loguru import logger

_PROFILE_DIR = Path("data/linkedin_profile")
_playwright = None
_context = None


def _get_page():
    """Return a LinkedIn page from a persistent, cookie-preserving browser context."""
    global _playwright, _context

    from playwright.sync_api import sync_playwright

    if _playwright is None:
        _playwright = sync_playwright().start()

    if _context is None or not _context.pages and _context.browser is None:
        _PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        _context = _playwright.chromium.launch_persistent_context(
            str(_PROFILE_DIR), headless=False, no_viewport=True,
        )

    page = _context.pages[0] if _context.pages else _context.new_page()
    return page


def _ensure_logged_in(page) -> bool:
    page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded")
    time.sleep(2)
    if "login" in page.url or "checkpoint" in page.url:
        logger.warning("LinkedIn: not logged in — waiting up to 60s for manual login")
        try:
            page.wait_for_url("**/feed/**", timeout=60000)
        except Exception:
            return False
    return True


def linkedin_post(text: str) -> str:
    """Publish a text update to the user's LinkedIn feed."""
    try:
        page = _get_page()
        if not _ensure_logged_in(page):
            return "LinkedIn requires manual login — a browser window was opened, please log in and try again."

        page.get_by_role("button", name=re.compile("Start a post", re.I)).click()
        time.sleep(1.5)
        page.locator("div.ql-editor").fill(text)
        time.sleep(0.5)
        page.get_by_role("button", name=re.compile("^Post$", re.I)).click()
        time.sleep(1.5)

        logger.info(f"linkedin_post: {text[:60]}")
        return "Posted to LinkedIn."
    except Exception as exc:
        logger.error(f"linkedin_post failed: {exc}")
        return f"Could not post to LinkedIn: {exc}"


def linkedin_send_message(contact: str, message: str) -> str:
    """Send a LinkedIn direct message to a connection."""
    try:
        page = _get_page()
        if not _ensure_logged_in(page):
            return "LinkedIn requires manual login — a browser window was opened, please log in and try again."

        page.goto("https://www.linkedin.com/messaging/", wait_until="domcontentloaded")
        time.sleep(2)

        search = page.get_by_placeholder(re.compile("Search messages", re.I))
        search.click()
        search.fill(contact)
        time.sleep(1.5)
        page.keyboard.press("Enter")
        time.sleep(1.5)

        # First matching conversation result
        page.locator("li.msg-conversation-listitem").first.click()
        time.sleep(1.0)

        box = page.locator("div.msg-form__contenteditable")
        box.click()
        box.fill(message)
        time.sleep(0.3)
        page.keyboard.press("Enter")
        time.sleep(0.5)

        logger.info(f"linkedin_send_message: to '{contact}': {message[:60]}")
        return f"LinkedIn message sent to {contact}."
    except Exception as exc:
        logger.error(f"linkedin_send_message failed: {exc}")
        return f"Could not send LinkedIn message: {exc}"


# ── Tool definitions ──────────────────────────────────────────────

TOOLS = [
    {
        "name": "linkedin_post",
        "description": (
            "Publish a text update to the user's LinkedIn feed. "
            "Use when the user says 'post on LinkedIn', 'share an update on LinkedIn'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "The post content"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "linkedin_send_message",
        "description": (
            "Send a LinkedIn direct message to a connection. "
            "Use when the user says 'message X on LinkedIn', 'send a LinkedIn DM to X'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "contact": {"type": "string", "description": "Connection's name as it appears on LinkedIn"},
                "message": {"type": "string", "description": "Message text to send"},
            },
            "required": ["contact", "message"],
        },
    },
]

HANDLERS = {
    "linkedin_post": linkedin_post,
    "linkedin_send_message": linkedin_send_message,
}
