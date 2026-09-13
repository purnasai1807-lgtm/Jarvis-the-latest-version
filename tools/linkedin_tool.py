"""
LinkedIn integration via Playwright with a persistent browser profile.

First use opens a visible Chromium window so the user can log in once —
the session (cookies) is cached in data/linkedin_profile and reused after that.

Tools: linkedin_post, linkedin_send_message
"""

import asyncio
import re
import threading
import time
from pathlib import Path
from typing import Any

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

    if _context is None or (not _context.pages and _context.browser is None):
        _PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        _context = _playwright.chromium.launch_persistent_context(
            str(_PROFILE_DIR), headless=False, no_viewport=True,
        )

    page = _context.pages[0] if _context.pages else _context.new_page()
    return page


def _safe_run_in_thread(fn, *args, **kwargs):
    """Run a blocking Playwright action safely even when an asyncio loop is active."""
    result_holder: dict[str, Any] = {}
    error_holder: dict[str, Exception] = {}

    def runner() -> None:
        try:
            result_holder["value"] = fn(*args, **kwargs)
        except Exception as exc:  # pragma: no cover - runtime safety guard
            error_holder["error"] = exc

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join()

    if "error" in error_holder:
        raise error_holder["error"]
    return result_holder.get("value")


def _is_login_page(page) -> bool:
    url = (page.url or "").lower()
    if "/login" in url or "checkpoint" in url or "challenge" in url or "/uas/login" in url:
        return True
    try:
        if page.locator("text=Sign in").count() > 0:
            return True
    except Exception:
        pass
    return False


def _ensure_logged_in(page) -> bool:
    page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded")
    time.sleep(2)
    if _is_login_page(page):
        logger.warning("LinkedIn: not logged in — waiting up to 60s for manual login")
        try:
            page.wait_for_url("**/feed/**", timeout=60000)
        except Exception:
            return False
    return True


def linkedin_post(text: str) -> str:
    """Publish a text update to the user's LinkedIn feed."""
    try:
        def action():
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

        return _safe_run_in_thread(action)
    except Exception as exc:
        logger.error(f"linkedin_post failed: {exc}")
        return f"Could not post to LinkedIn: {exc}"


def linkedin_send_message(contact: str, message: str) -> str:
    """Send a LinkedIn direct message to a connection."""
    try:
        def action():
            page = _get_page()
            if not _ensure_logged_in(page):
                return "LinkedIn requires manual login — a browser window was opened, please log in and try again."

            page.goto("https://www.linkedin.com/messaging/", wait_until="domcontentloaded")
            time.sleep(2)

            search = page.locator("input[placeholder*='Search'], input[type='search'], input[aria-label*='Search']").first
            if search.count() == 0:
                search = page.get_by_placeholder(re.compile("Search messages", re.I))
            if search.count() > 0:
                search.click()
                search.fill(contact)
                time.sleep(1.5)
                page.keyboard.press("Enter")
                time.sleep(1.5)

            target = page.locator("li, div").filter(has_text=re.compile(contact, re.I)).first
            if target.count() > 0:
                target.click()
            else:
                page.locator("li.msg-conversation-listitem").first.click(timeout=10000)
            time.sleep(1.0)

            box = page.locator("div[contenteditable='true'], div.msg-form__contenteditable, div[role='textbox']").last
            if box.count() == 0:
                return f"LinkedIn message target '{contact}' was not found or the message composer is unavailable."
            box.click()
            box.fill(message)
            time.sleep(0.3)
            page.keyboard.press("Enter")
            time.sleep(0.5)

            logger.info(f"linkedin_send_message: to '{contact}': {message[:60]}")
            return f"LinkedIn message sent to {contact}."

        return _safe_run_in_thread(action)
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
