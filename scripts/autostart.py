"""
Auto-start manager — add/remove Jarvis from Windows Startup.

Usage:
    python scripts/autostart.py          # install auto-start
    python scripts/autostart.py remove   # remove auto-start
"""

import os
import sys
from pathlib import Path

_STARTUP = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
_VBS = _STARTUP / "jarvis_autostart.vbs"
_PROJECT = Path(__file__).resolve().parent.parent


def install() -> None:
    python = Path(sys.executable).resolve()
    vbs = (
        f'Set WshShell = CreateObject("WScript.Shell")\n'
        f'WshShell.CurrentDirectory = "{_PROJECT}"\n'
        f'WshShell.Run """{python}"" main.py", 1, False\n'
    )
    _VBS.write_text(vbs)
    print(f"Auto-start installed: {_VBS}")


def uninstall() -> None:
    if _VBS.exists():
        _VBS.unlink()
        print("Auto-start removed.")
    else:
        print("Auto-start was not installed.")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ("remove", "uninstall", "--remove"):
        uninstall()
    else:
        install()
