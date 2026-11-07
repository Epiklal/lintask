"""Persisted application settings (theme + refresh rates) via QSettings (INI backend)."""
from __future__ import annotations

import json
import os

from PySide6.QtCore import QSettings

ORG = "Lintask"
APP = "TaskManager"
LEGACY_ORG = "WinTaskManager"  # Name of the settings folder before the rename

DEFAULT_THEME = "light"
DEFAULT_STYLE = "win10"  # "win10" or "win11" window layout / look
DEFAULT_LANGUAGE = "system"  # "system" follows the locale; otherwise "de" or "en"
DEFAULT_PROCESS_INTERVAL_MS = 1000
DEFAULT_PERFORMANCE_INTERVAL_MS = 500
DEFAULT_REMOTE_HOST = "127.0.0.1"
DEFAULT_REMOTE_PORT = 8765


class Settings:
    def __init__(self):
        self._store = QSettings(ORG, APP)
        self._migrate_legacy_file()
        self._store.sync()
        self._restrict_permissions()

    def _migrate_legacy_file(self) -> None:
        """Take over the settings, including the token, from before the rename. Runs
        before the new file exists; an existing new file is never overwritten."""
        path = self._store.fileName()
        folder = os.path.dirname(path)
        legacy = os.path.join(os.path.dirname(folder), LEGACY_ORG, os.path.basename(path))
        if os.path.exists(path) or not os.path.exists(legacy):
            return
        try:
            os.makedirs(folder, exist_ok=True)
            os.replace(legacy, path)
            os.chmod(path, 0o600)
            os.rmdir(os.path.dirname(legacy))
        except OSError:
            pass

    def _restrict_permissions(self) -> None:
        """The file holds the remote-server token: readable by this user only (0600).
        QSettings keeps the mode when it rewrites the file later."""
        path = self._store.fileName()
        try:
            if os.path.exists(path):
                os.chmod(path, 0o600)
            else:
                # Create it empty with 0600 now, so it is never readable by others,
                # not even right after the very first start.
                os.makedirs(os.path.dirname(path), exist_ok=True)
                os.close(os.open(path, os.O_CREAT | os.O_WRONLY, 0o600))
        except OSError:
            pass

    @property
    def theme(self) -> str:
        return self._store.value("theme", DEFAULT_THEME, type=str)

    @theme.setter
    def theme(self, value: str) -> None:
        self._store.setValue("theme", value)

    @property
    def language(self) -> str:
        value = self._store.value("language", DEFAULT_LANGUAGE, type=str)
        return value if value in ("system", "de", "en") else DEFAULT_LANGUAGE

    @language.setter
    def language(self, value: str) -> None:
        self._store.setValue("language", value)

    @property
    def style(self) -> str:
        value = self._store.value("style", DEFAULT_STYLE, type=str)
        return value if value in ("win10", "win11") else DEFAULT_STYLE

    @style.setter
    def style(self, value: str) -> None:
        self._store.setValue("style", value)

    @property
    def process_interval_ms(self) -> int:
        return self._store.value(
            "process_interval_ms", DEFAULT_PROCESS_INTERVAL_MS, type=int
        )

    @process_interval_ms.setter
    def process_interval_ms(self, value: int) -> None:
        self._store.setValue("process_interval_ms", value)

    @property
    def performance_interval_ms(self) -> int:
        return self._store.value(
            "performance_interval_ms", DEFAULT_PERFORMANCE_INTERVAL_MS, type=int
        )

    @performance_interval_ms.setter
    def performance_interval_ms(self, value: int) -> None:
        self._store.setValue("performance_interval_ms", value)

    @property
    def remote_host(self) -> str:
        return self._store.value("remote_host", DEFAULT_REMOTE_HOST, type=str)

    @remote_host.setter
    def remote_host(self, value: str) -> None:
        self._store.setValue("remote_host", value)

    @property
    def history_enabled(self) -> bool:
        return self._store.value("history_enabled", True, type=bool)

    @history_enabled.setter
    def history_enabled(self, value: bool) -> None:
        self._store.setValue("history_enabled", value)

    @property
    def always_on_top(self) -> bool:
        return self._store.value("always_on_top", False, type=bool)

    @always_on_top.setter
    def always_on_top(self, value: bool) -> None:
        self._store.setValue("always_on_top", value)

    @property
    def close_to_tray(self) -> bool:
        return self._store.value("close_to_tray", False, type=bool)

    @close_to_tray.setter
    def close_to_tray(self, value: bool) -> None:
        self._store.setValue("close_to_tray", value)

    @property
    def default_page(self) -> str:
        """Key of the page shown at start, like Windows' "Set default tab"."""
        return self._store.value("default_page", "processes", type=str)

    @default_page.setter
    def default_page(self, value: str) -> None:
        self._store.setValue("default_page", value)

    @property
    def ui_scale(self) -> int:
        """UI size in percent; 0 follows the screen resolution (see app/ui_scale.py)."""
        return self._store.value("ui_scale", 0, type=int)

    @ui_scale.setter
    def ui_scale(self, value: int) -> None:
        self._store.setValue("ui_scale", value)

    @property
    def window_geometry(self):
        return self._store.value("window_geometry")

    @window_geometry.setter
    def window_geometry(self, value) -> None:
        self._store.setValue("window_geometry", value)

    @property
    def cpu_graph(self) -> str:
        """CPU chart: "overall", "cores" (one graph per logical processor) or "ccds"
        (one per core chiplet). Older versions only stored cpu_per_core."""
        value = self._store.value("cpu_graph", "", type=str)
        if value in ("overall", "cores", "ccds"):
            return value
        return "cores" if self._store.value("cpu_per_core", False, type=bool) else "overall"

    @cpu_graph.setter
    def cpu_graph(self, value: str) -> None:
        self._store.setValue("cpu_graph", value)

    @property
    def remote_enabled(self) -> bool:
        return self._store.value("remote_enabled", False, type=bool)

    @remote_enabled.setter
    def remote_enabled(self, value: bool) -> None:
        self._store.setValue("remote_enabled", value)

    @property
    def remote_port(self) -> int:
        return self._store.value("remote_port", DEFAULT_REMOTE_PORT, type=int)

    @remote_port.setter
    def remote_port(self, value: int) -> None:
        self._store.setValue("remote_port", value)

    @property
    def remote_token(self) -> str:
        return self._store.value("remote_token", "", type=str)

    @remote_token.setter
    def remote_token(self, value: str) -> None:
        self._store.setValue("remote_token", value)
        self._store.sync()  # make sure the file exists before locking it down
        self._restrict_permissions()

    @property
    def smart_sudo_enabled(self) -> bool:
        return self._store.value("smart_sudo_enabled", False, type=bool)

    @smart_sudo_enabled.setter
    def smart_sudo_enabled(self, value: bool) -> None:
        self._store.setValue("smart_sudo_enabled", value)

    @property
    def memory_cache_option(self) -> bool:
        return self._store.value("memory_cache_option", False, type=bool)

    @memory_cache_option.setter
    def memory_cache_option(self, value: bool) -> None:
        self._store.setValue("memory_cache_option", value)

    @property
    def custom_qss(self) -> str:
        return self._store.value("custom_qss", "", type=str)

    @custom_qss.setter
    def custom_qss(self, value: str) -> None:
        self._store.setValue("custom_qss", value)

    @property
    def docker_meta(self) -> dict:
        """Per-container UI metadata (favorite / custom name / icon path), keyed by
        the container's docker name so it survives across restarts and refreshes."""
        raw = self._store.value("docker_meta", "{}", type=str)
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
        except (TypeError, ValueError):
            return {}

    def set_docker_meta(self, meta: dict) -> None:
        self._store.setValue("docker_meta", json.dumps(meta))

    def column_widths(self, table_key: str) -> list[int] | None:
        """Saved column widths for a table (e.g. "processes"), or None if never set."""
        raw = self._store.value(f"column_widths_{table_key}", "", type=str)
        if not raw:
            return None
        try:
            widths = json.loads(raw)
            return widths if isinstance(widths, list) else None
        except (TypeError, ValueError):
            return None

    def set_column_widths(self, table_key: str, widths: list[int]) -> None:
        self._store.setValue(f"column_widths_{table_key}", json.dumps(widths))

    def row_height(self, table_key: str, default: int) -> int:
        return self._store.value(f"row_height_{table_key}", default, type=int)

    def set_row_height(self, table_key: str, height: int) -> None:
        self._store.setValue(f"row_height_{table_key}", height)
