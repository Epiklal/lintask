"""'Always on top' that also works on Wayland.

Qt's WindowStaysOnTopHint only reaches the window manager on X11; Wayland has no
protocol for it, so the flag is silently ignored. On KDE Plasma (Wayland) KWin can
be asked instead: a small KWin script sets `keepAbove` on every window of this
process, including ones opened later. Other Wayland desktops offer no such hook."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication

_KWIN = ("org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting")
_SCRIPT = """\
const pid = {pid};
const keep = {keep};
const apply = (w) => {{ if (w.pid === pid) w.keepAbove = keep; }};
const windows = workspace.windowList ? workspace.windowList() : workspace.clientList();
windows.forEach(apply);
if (keep) (workspace.windowAdded || workspace.clientAdded).connect(apply);
"""


def _uses_kwin_wayland() -> bool:
    return (QGuiApplication.platformName() == "wayland"
            and "KDE" in os.environ.get("XDG_CURRENT_DESKTOP", "").upper())


def _plugin_name() -> str:
    return f"lintask-keep-above-{os.getpid()}"


def _script_path() -> Path:
    folder = os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()
    return Path(folder) / f"{_plugin_name()}.js"


def _gdbus(object_path: str, method: str, *args: str) -> str | None:
    gdbus = shutil.which("gdbus")
    if gdbus is None:
        return None
    try:
        result = subprocess.run(
            [gdbus, "call", "--session", "--dest", _KWIN[0], "--object-path", object_path,
             "--method", method, *args],
            capture_output=True, text=True, timeout=3, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout if result.returncode == 0 else None


def _set_keep_above_kwin(enabled: bool) -> bool:
    _gdbus(_KWIN[1], f"{_KWIN[2]}.unloadScript", _plugin_name())
    path = _script_path()
    try:
        path.write_text(_SCRIPT.format(pid=os.getpid(), keep="true" if enabled else "false"),
                        encoding="utf-8")
    except OSError:
        return False
    reply = _gdbus(_KWIN[1], f"{_KWIN[2]}.loadScript", str(path), _plugin_name())
    match = re.search(r"-?\d+", reply or "")
    if match is None or int(match.group()) < 0:
        return False
    # KWin 6 runs a loaded script through its own object; KWin 5 through start().
    if _gdbus(f"/Scripting/Script{match.group()}", "org.kde.kwin.Script.run") is None:
        _gdbus(_KWIN[1], f"{_KWIN[2]}.start")
    return True


def set_always_on_top(window, enabled: bool) -> None:
    if _uses_kwin_wayland():
        _set_keep_above_kwin(enabled)
        return
    if bool(window.windowFlags() & Qt.WindowStaysOnTopHint) == enabled:
        return
    visible = window.isVisible()
    window.setWindowFlag(Qt.WindowStaysOnTopHint, enabled)
    if visible:
        window.show()  # changing window flags hides the window


def release() -> None:
    """Drops the KWin script again when the app closes."""
    if not _uses_kwin_wayland():
        return
    _gdbus(_KWIN[1], f"{_KWIN[2]}.unloadScript", _plugin_name())
    try:
        _script_path().unlink()
    except OSError:
        pass
