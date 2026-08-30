"""
Live PC context — what is the user looking at right now?

Two background pollers expose ephemeral state that the brain can use to
resolve "this", "that file", "the tab", etc:

  WindowWatcher    — foreground app, window title, parsed VS Code file,
                     meeting-app detection. Polls every 5s.
  ClipboardWatcher — keeps a deque of the last ~30 distinct clipboard
                     entries with timestamps. Polls every 2s.

Heavy / on-demand operations live as plain functions:

  active_chrome_url()    — read Chrome's active tab via UI Automation
  git_summary(since)     — git log/status across known repos
  active_brief()         — single short string ready to drop in a prompt

Designed to be Windows-first; gracefully degrades on other platforms.
"""

from __future__ import annotations

import collections
import os
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger


# ── Window watcher ───────────────────────────────────────────────
_MEETING_PROCS = {
    "teams.exe", "ms-teams.exe", "zoom.exe", "zoomus.exe",
    "discord.exe", "webex.exe",
}


class _WindowSnap(dict):
    """Convenience: dict-like snapshot of the foreground window."""


class WindowWatcher:
    def __init__(self) -> None:
        self._latest: dict[str, Any] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="jarvis-context-window", daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def latest(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._latest)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                snap = self._snap()
                with self._lock:
                    self._latest = snap
            except Exception as exc:
                logger.debug(f"window watcher: {exc}")
            self._stop.wait(5.0)

    def _snap(self) -> dict[str, Any]:
        try:
            import win32gui  # type: ignore
            import win32process  # type: ignore
        except ImportError:
            return {"app": "", "title": "", "ts": _now_iso()}

        hwnd = win32gui.GetForegroundWindow()
        title = win32gui.GetWindowText(hwnd) or ""
        proc_name = ""
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            import psutil
            proc_name = psutil.Process(pid).name()
        except Exception:
            pass

        # Parse VS Code file from title pattern: "● filename - workspace - Visual Studio Code"
        vscode_file: str | None = None
        if "Visual Studio Code" in title:
            t = title.replace("●", "").strip()
            parts = [p.strip() for p in t.split(" - ")]
            if len(parts) >= 2:
                vscode_file = parts[0]

        # Meeting detection: known process + meeting-y title
        in_meeting = False
        pn_low = proc_name.lower()
        if pn_low in _MEETING_PROCS:
            tl = title.lower()
            if any(kw in tl for kw in ("meeting", "call", "zoom",
                                       "huddle", "podcast")):
                in_meeting = True
            elif pn_low.startswith(("teams", "ms-teams")):
                # Teams call windows often just have the participant name
                in_meeting = "|" in title and len(title) > 6

        return {
            "app": proc_name,
            "app_short": _short_app(proc_name),
            "title": title,
            "vscode_file": vscode_file,
            "in_meeting": in_meeting,
            "ts": _now_iso(),
        }


# ── Clipboard watcher ────────────────────────────────────────────
class ClipboardWatcher:
    def __init__(self, max_entries: int = 30) -> None:
        self._entries: collections.deque[dict] = collections.deque(maxlen=max_entries)
        self._last = ""
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="jarvis-context-clipboard", daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def recent(self, n: int = 10) -> list[dict]:
        n = max(1, min(n, 30))
        with self._lock:
            items = list(self._entries)[-n:]
        return list(reversed(items))

    def search(self, query: str, n: int = 10) -> list[dict]:
        q = (query or "").lower().strip()
        if not q:
            return self.recent(n)
        with self._lock:
            hits = [e for e in self._entries if q in e["text"].lower()]
        return list(reversed(hits))[:n]

    def _loop(self) -> None:
        try:
            import pyperclip  # type: ignore
        except ImportError:
            logger.warning("clipboard watcher: pyperclip unavailable")
            return
        while not self._stop.is_set():
            try:
                cur = pyperclip.paste() or ""
                if cur and cur != self._last and len(cur) < 5000:
                    with self._lock:
                        self._entries.append({
                            "text": cur,
                            "ts": _now_iso(),
                        })
                    self._last = cur
            except Exception:
                pass
            self._stop.wait(2.0)


# ── Singletons ───────────────────────────────────────────────────
_window: WindowWatcher | None = None
_clipboard: ClipboardWatcher | None = None


def init() -> None:
    global _window, _clipboard
    if _window is None:
        _window = WindowWatcher()
        _window.start()
    if _clipboard is None:
        _clipboard = ClipboardWatcher()
        _clipboard.start()
    logger.info("Context watchers started (window 5s, clipboard 2s)")


def window() -> dict[str, Any]:
    return _window.latest() if _window else {}


def clipboard_recent(n: int = 10) -> list[dict]:
    return _clipboard.recent(n) if _clipboard else []


def clipboard_search(query: str, n: int = 10) -> list[dict]:
    return _clipboard.search(query, n) if _clipboard else []


def is_in_meeting() -> bool:
    return bool(window().get("in_meeting"))


# ── On-demand: Chrome URL ───────────────────────────────────────
def active_chrome_url() -> str | None:
    """Read Chrome's active tab URL (slow ~1s — Win UI Automation). Cached briefly."""
    try:
        from tools.browser import _get_active_tab_url
        return _get_active_tab_url()
    except Exception as exc:
        logger.debug(f"active_chrome_url: {exc}")
        return None


# ── On-demand: Git summary ───────────────────────────────────────
def _known_repos() -> list[Path]:
    """Walk a small set of known parent dirs and find git repos."""
    candidates: list[Path] = []
    for env_var in ("JARVIS_REPO_DIRS", "USERPROFILE"):
        raw = os.environ.get(env_var, "")
        for p in raw.split(os.pathsep):
            if p:
                candidates.append(Path(p))
    # Project root + Personal Projects + tmp
    candidates += [
        Path(r"c:\PersonalProjects"),
        Path(r"c:\Projects"),
    ]

    repos: list[Path] = []
    seen: set[Path] = set()
    for parent in candidates:
        if not parent.exists():
            continue
        try:
            for child in parent.iterdir():
                if not child.is_dir():
                    continue
                if (child / ".git").exists() and child not in seen:
                    repos.append(child)
                    seen.add(child)
        except Exception:
            continue
    return repos[:12]   # cap to keep things snappy


def git_summary(since: str = "1 day ago", *,
                repos: list[Path] | None = None) -> str:
    """git log + git status across known repos. Returns human-readable text."""
    repos = repos or _known_repos()
    if not repos:
        return "No git repos found under known dirs."

    chunks: list[str] = []
    for repo in repos:
        try:
            log = subprocess.run(
                ["git", "-C", str(repo), "log",
                 f"--since={since}", "--author", _git_author(),
                 "--pretty=format:%h %s",
                 "--no-merges", "-n", "8"],
                capture_output=True, text=True, timeout=8,
            ).stdout.strip()

            status = subprocess.run(
                ["git", "-C", str(repo), "status", "-s"],
                capture_output=True, text=True, timeout=4,
            ).stdout.strip()

            branch = subprocess.run(
                ["git", "-C", str(repo), "branch", "--show-current"],
                capture_output=True, text=True, timeout=4,
            ).stdout.strip() or "?"

            if not log and not status:
                continue

            block = [f"📁 {repo.name} (on {branch})"]
            if log:
                for line in log.splitlines()[:5]:
                    block.append(f"  • {line}")
            if status:
                count = len(status.splitlines())
                block.append(f"  ✎ {count} uncommitted change(s)")
            chunks.append("\n".join(block))
        except Exception as exc:
            logger.debug(f"git summary {repo.name} failed: {exc}")
            continue

    return "\n\n".join(chunks) if chunks else (
        f"No commits or changes in any tracked repo since {since}."
    )


_GIT_AUTHOR_CACHE: str | None = None


def _git_author() -> str:
    global _GIT_AUTHOR_CACHE
    if _GIT_AUTHOR_CACHE is not None:
        return _GIT_AUTHOR_CACHE
    try:
        out = subprocess.run(
            ["git", "config", "--global", "user.email"],
            capture_output=True, text=True, timeout=2,
        ).stdout.strip()
        _GIT_AUTHOR_CACHE = out or ""
    except Exception:
        _GIT_AUTHOR_CACHE = ""
    return _GIT_AUTHOR_CACHE


# ── One-line brief for system prompt injection ──────────────────
def active_brief() -> str:
    """Compact one-line description of what the user is doing right now."""
    w = window()
    parts: list[str] = []

    app = w.get("app_short") or w.get("app") or ""
    if w.get("vscode_file"):
        parts.append(f"VS Code on {w['vscode_file']}")
    elif app == "chrome":
        parts.append("Chrome")
    elif app:
        parts.append(app.replace(".exe", ""))

    if w.get("in_meeting"):
        parts.append("(in a meeting)")

    title = w.get("title") or ""
    if title and len(parts) < 2 and not w.get("vscode_file"):
        parts.append(title[:80])

    clip = clipboard_recent(1)
    if clip:
        snippet = clip[0]["text"].replace("\n", " ").strip()
        if snippet:
            parts.append(f"clipboard: '{snippet[:60]}…'"
                         if len(snippet) > 60 else f"clipboard: '{snippet}'")

    return " · ".join(parts) if parts else ""


# ── Helpers ─────────────────────────────────────────────────────
def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _short_app(proc_name: str) -> str:
    n = proc_name.lower()
    table = {
        "chrome.exe": "chrome", "msedge.exe": "edge",
        "firefox.exe": "firefox", "code.exe": "vscode",
        "windowsterminal.exe": "terminal",
        "explorer.exe": "explorer",
    }
    return table.get(n, n.replace(".exe", "") if n else "")
