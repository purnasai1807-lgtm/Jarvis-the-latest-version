"""System control tools: open/close apps, open URLs, volume control."""

import glob
import os
import subprocess
import webbrowser

from loguru import logger

# ── App name → launch command mapping (regular desktop apps) ─────
_APP_MAP = {
    # Browsers
    "chrome": "chrome", "google chrome": "chrome",
    "firefox": "firefox", "edge": "msedge", "microsoft edge": "msedge",
    # Microsoft Office
    "word": "winword", "excel": "excel", "powerpoint": "powerpnt",
    "outlook": "outlook", "onenote": "onenote",
    # Dev tools
    "vscode": "code", "visual studio code": "code",
    "terminal": "wt", "windows terminal": "wt",
    "cmd": "cmd", "command prompt": "cmd",
    "powershell": "powershell",
    # System
    "explorer": "explorer", "file explorer": "explorer",
    "task manager": "taskmgr", "settings": "ms-settings:",
    "calculator": "calc", "notepad": "notepad",
    "paint": "mspaint", "snipping tool": "snippingtool",
    "control panel": "control",
    # Apps (non-UWP)
    "spotify": "spotify",
    "steam": "steam", "obs": "obs64",
    "vlc": "vlc",
    "slack": "slack",
}

# ── Apps that need special launch commands ────────────────────────
# Discord uses Squirrel installer (%LOCALAPPDATA%\Discord\Update.exe)
_DISCORD_EXE = os.path.join(
    os.environ.get("LOCALAPPDATA", ""), "Discord", "Update.exe"
)

# UWP / Windows Store apps → launch via explorer shell:AppsFolder
# Find these with: powershell Get-AppxPackage | Where { $_.Name -like "*name*" }
_UWP_MAP = {
    "whatsapp": "5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App",
    "telegram": "TelegramMessengerLLP.TelegramDesktop_t4vj0pshhgkwm!App",
}

# ── Friendly name → process name mapping ─────────────────────────
_PROCESS_MAP = {
    "chrome": "chrome.exe", "google chrome": "chrome.exe",
    "firefox": "firefox.exe", "edge": "msedge.exe",
    "word": "WINWORD.EXE", "excel": "EXCEL.EXE",
    "powerpoint": "POWERPNT.EXE", "outlook": "OUTLOOK.EXE",
    "vscode": "Code.exe", "visual studio code": "Code.exe",
    "terminal": "WindowsTerminal.exe", "windows terminal": "WindowsTerminal.exe",
    "explorer": "explorer.exe", "file explorer": "explorer.exe",
    "task manager": "Taskmgr.exe",
    "notepad": "notepad.exe", "calculator": "Calculator.exe",
    "spotify": "Spotify.exe", "discord": "Discord.exe", "whatsapp": "WhatsApp.exe",
    "steam": "steam.exe", "obs": "obs64.exe",
    "vlc": "vlc.exe", "telegram": "Telegram.exe",
    "slack": "slack.exe", "paint": "mspaint.exe",
}

_START_MENU_DIRS = [
    os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs"),
    r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs",
]


# ── Handlers ─────────────────────────────────────────────────────

def open_app(name: str) -> str:
    """Launch an application by name."""
    key = name.lower().strip()

    # 1) Discord — special Squirrel launcher
    if key in ("discord",):
        if os.path.isfile(_DISCORD_EXE):
            subprocess.Popen([_DISCORD_EXE, "--processStart", "Discord.exe"])
            logger.info(f"Opened app: Discord (Update.exe --processStart)")
            return f"Opened Discord."

    # 2) Known UWP / Store apps
    uwp_id = _UWP_MAP.get(key)
    if uwp_id:
        return _launch_uwp(name, uwp_id)

    # 3) Known desktop apps
    cmd = _APP_MAP.get(key)
    if cmd:
        try:
            subprocess.Popen(f'start "" "{cmd}"', shell=True)
            logger.info(f"Opened app: {name} (cmd={cmd})")
            return f"Opened {name}."
        except Exception as exc:
            logger.error(f"open_app({name}) via map failed: {exc}")

    # 4) Search Start Menu shortcuts
    for start_dir in _START_MENU_DIRS:
        if not os.path.isdir(start_dir):
            continue
        for lnk in glob.glob(os.path.join(start_dir, "**", "*.lnk"), recursive=True):
            if key in os.path.basename(lnk).lower():
                try:
                    os.startfile(lnk)
                    logger.info(f"Opened app: {name} (shortcut={lnk})")
                    return f"Opened {name}."
                except Exception as exc:
                    logger.error(f"open_app({name}) via shortcut failed: {exc}")

    # 5) Search installed UWP apps dynamically
    uwp_result = _find_and_launch_uwp(key)
    if uwp_result:
        return uwp_result

    # 6) Hail Mary — let Windows figure it out
    try:
        subprocess.Popen(f'start "" "{name}"', shell=True)
        return f"Attempted to open {name}."
    except Exception:
        return f"Could not find application: {name}"


def _launch_uwp(name: str, app_id: str) -> str:
    """Launch a UWP app via shell:AppsFolder."""
    try:
        subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{app_id}"])
        logger.info(f"Opened UWP app: {name} ({app_id})")
        return f"Opened {name}."
    except Exception as exc:
        logger.error(f"UWP launch failed for {name}: {exc}")
        return f"Failed to open {name}: {exc}"


def _find_and_launch_uwp(query: str) -> str | None:
    """Search installed UWP apps by name and launch the first match."""
    try:
        ps_cmd = (
            f'Get-AppxPackage | Where-Object {{ $_.Name -like "*{query}*" }} '
            f'| Select-Object -First 1 -ExpandProperty PackageFamilyName'
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True, text=True, timeout=5,
        )
        pfn = result.stdout.strip()
        if pfn:
            app_id = f"{pfn}!App"
            subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{app_id}"])
            logger.info(f"Opened UWP app: {query} (auto-found: {app_id})")
            return f"Opened {query}."
    except Exception as exc:
        logger.debug(f"UWP search for {query} failed: {exc}")
    return None


_URL_ALIASES = {
    "dashboard": "http://127.0.0.1:9000",
    "jarvis dashboard": "http://127.0.0.1:9000",
    "jarvis": "http://127.0.0.1:9000",
}


def open_url(url: str) -> str:
    """Open a URL in the default browser."""
    # Check for known aliases first
    alias = _URL_ALIASES.get(url.lower().strip())
    if alias:
        url = alias
    # Add scheme if not provided — use http:// for local addresses
    elif not url.startswith(("http://", "https://", "file://")):
        if url.startswith(("localhost", "127.0.0.1", "0.0.0.0", "192.168.")):
            url = "http://" + url
        else:
            url = "https://" + url
    webbrowser.open(url)
    logger.info(f"Opened URL: {url}")
    return f"Opened {url} in browser."


def close_app(name: str) -> str:
    """Kill a running application by name."""
    key = name.lower().strip()
    process = _PROCESS_MAP.get(key, f"{name}.exe")

    result = subprocess.run(
        ["taskkill", "/F", "/IM", process],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        logger.info(f"Closed app: {name} (process={process})")
        return f"Closed {name}."
    return f"Could not close {name}: {result.stderr.strip()}"


def volume_control(action: str, level: int = None) -> str:
    """Control system volume. Actions: set, up, down, mute, unmute."""
    action = action.lower().strip()

    if action == "set" and level is not None:
        try:
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
            from comtypes import CLSCTX_ALL

            devices = AudioUtilities.GetSpeakers()
            interface = devices.Activate(
                IAudioEndpointVolume._iid_, CLSCTX_ALL, None
            )
            vol = interface.QueryInterface(IAudioEndpointVolume)
            vol.SetMute(0, None)
            vol.SetMasterVolumeLevelScalar(max(0, min(100, level)) / 100.0, None)
            logger.info(f"Volume set to {level}%")
            return f"Volume set to {level}%."
        except ImportError:
            logger.warning("pycaw not available, falling back to media keys")
            return _volume_media_keys(action, level)

    return _volume_media_keys(action, level)


def _volume_media_keys(action: str, level: int = None) -> str:
    """Fallback volume control via media keys."""
    import pyautogui

    if action == "mute" or action == "unmute":
        pyautogui.press("volumemute")
        return "Toggled mute."
    elif action == "up":
        for _ in range(5):
            pyautogui.press("volumeup")
        return "Volume increased."
    elif action == "down":
        for _ in range(5):
            pyautogui.press("volumedown")
        return "Volume decreased."
    elif action == "set" and level is not None:
        # Approximate: mute then raise to level
        # Each volumeup press ≈ 2%, so level/2 presses
        pyautogui.press("volumemute")  # mute first
        pyautogui.press("volumemute")  # unmute at 0
        presses = max(0, level) // 2
        for _ in range(presses):
            pyautogui.press("volumeup")
        return f"Volume set to approximately {level}%."
    return f"Unknown volume action: {action}"


# ── Tool definitions (Claude API format) ─────────────────────────

TOOLS = [
    {
        "name": "open_app",
        "description": "Launch/open a desktop application by name on Windows. Examples: 'Chrome', 'Spotify', 'File Explorer', 'VS Code', 'Calculator'. Do NOT use this for opening websites or URLs — use open_url instead.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Application name to open",
                },
            },
            "required": ["name"],
        },
    },
    {
        "name": "open_url",
        "description": "Open a URL or website in the default browser. Use this for ANY request to open a website, navigate to a page, or search the web. Examples: 'youtube.com', 'https://google.com', 'reddit.com/r/programming'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "URL to open (e.g. 'youtube.com', 'https://google.com/search?q=weather')",
                },
            },
            "required": ["url"],
        },
    },
    {
        "name": "close_app",
        "description": "Close/kill a running application by name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Application name to close",
                },
            },
            "required": ["name"],
        },
    },
    {
        "name": "volume_control",
        "description": "Control system audio volume. Use 'set' with a level (0-100), or 'up'/'down'/'mute'/'unmute'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["set", "up", "down", "mute", "unmute"],
                    "description": "Volume action to perform",
                },
                "level": {
                    "type": "integer",
                    "description": "Volume level 0-100 (only used with 'set' action)",
                },
            },
            "required": ["action"],
        },
    },
]

HANDLERS = {
    "open_app": open_app,
    "open_url": open_url,
    "close_app": close_app,
    "volume_control": volume_control,
}
