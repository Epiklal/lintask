"""Start Lintask in the panel at login through an XDG autostart entry.

The entry lives in $XDG_CONFIG_HOME/autostart (usually ~/.config/autostart) and runs
Lintask with --tray, so only the panel icon and the history recorder start. Whether the
option is on is read from that file, never stored separately, so removing the file in the
Autostart tab or by hand is reflected here too."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from app.i18n import N_

FILENAME = "lintask-tray.desktop"
TRAY_ARGUMENT = "--tray"

_APP_DIR = Path(__file__).resolve().parent.parent  # the folder that holds main.py


def autostart_dir() -> Path:
    config_home = os.environ.get("XDG_CONFIG_HOME", "").strip()
    if not config_home or not os.path.isabs(config_home):
        config_home = os.path.expanduser("~/.config")
    return Path(config_home) / "autostart"


def entry_path() -> Path:
    return autostart_dir() / FILENAME


def launch_command() -> list[str]:
    """How this copy of Lintask is started, without the --tray argument."""
    appimage = os.environ.get("APPIMAGE", "")
    if appimage and os.path.isfile(appimage):
        return [appimage]  # the mount point changes on every start; the file does not
    run_script = _APP_DIR / "run.sh"
    if run_script.is_file() and os.access(run_script, os.X_OK):
        return [str(run_script)]  # a source checkout set up by install.sh
    installed = shutil.which("lintask")
    if installed:
        return [installed]  # deb, rpm, Arch package or a linked bundle
    bundle_launcher = _APP_DIR.parent / "bin" / "lintask"
    if bundle_launcher.is_file() and os.access(bundle_launcher, os.X_OK):
        return [str(bundle_launcher)]
    return [sys.executable, str(_APP_DIR / "main.py")]


def _quote_exec_argument(argument: str) -> str:
    """Quote one argument for the Exec key (Desktop Entry Specification)."""
    argument = argument.replace("%", "%%")
    if not any(ch in argument for ch in ' \t\n"\'\\><~|&;$*?#()`'):
        return argument
    for ch in ("\\", '"', "`", "$"):
        argument = argument.replace(ch, "\\" + ch)
    # Exec is also a string value, so every backslash is escaped once more.
    return '"' + argument.replace("\\", "\\\\") + '"'


def exec_line(command: list[str] | None = None) -> str:
    parts = [*(command or launch_command()), TRAY_ARGUMENT]
    return " ".join(_quote_exec_argument(part) for part in parts)


_COMMENT = N_("Start Lintask in the panel and keep recording the history")


def desktop_entry(command: list[str] | None = None) -> str:
    from app.translations_de import GERMAN
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Lintask\n"
        f"Comment={_COMMENT}\n"
        f"Comment[de]={GERMAN.get(_COMMENT, _COMMENT)}\n"
        f"Exec={exec_line(command)}\n"
        "Icon=utilities-system-monitor\n"
        "Terminal=false\n"
        "NoDisplay=true\n"
        "X-GNOME-Autostart-enabled=true\n"
        "X-KDE-autostart-after=panel\n"
    )


def is_enabled() -> bool:
    """True when our entry exists and nothing (Autostart tab, desktop settings) turned it off."""
    path = entry_path()
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    in_section = False
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("["):
            in_section = line == "[Desktop Entry]"
            continue
        if not in_section or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().lower()
        if key == "Hidden" and value == "true":
            return False
        if key == "X-GNOME-Autostart-enabled" and value == "false":
            return False
    return True


def set_enabled(enabled: bool) -> tuple[bool, str]:
    """Write or remove the autostart entry. Returns (ok, error message)."""
    path = entry_path()
    try:
        if enabled:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(path.name + ".tmp")
            temporary.write_text(desktop_entry(), encoding="utf-8")
            os.replace(temporary, path)
        else:
            path.unlink(missing_ok=True)
    except OSError as exc:
        return False, exc.strerror or str(exc) or N_("Could not change the autostart entry")
    return True, ""
