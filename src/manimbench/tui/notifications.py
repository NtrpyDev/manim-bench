from __future__ import annotations

import shutil
import subprocess
import sys


def os_notify(title: str, message: str) -> None:
    try:
        if sys.platform == "darwin" and shutil.which("osascript"):
            script = f'display notification "{_escape_applescript(message)}" with title "{_escape_applescript(title)}"'
            subprocess.run(["osascript", "-e", script], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
            return
        if sys.platform.startswith("linux") and shutil.which("notify-send"):
            subprocess.run(["notify-send", title, message], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
            return
        if sys.platform.startswith("win") and shutil.which("powershell"):
            subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    f"New-BurntToastNotification -Text '{_escape_powershell(title)}','{_escape_powershell(message)}'",
                ],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=2,
            )
    except Exception:
        return


def _escape_applescript(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _escape_powershell(value: str) -> str:
    return value.replace("'", "''")
