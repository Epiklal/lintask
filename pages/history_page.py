"""History tab - how the system's totals developed over hours, days and months."""
from __future__ import annotations

import http.client
import sqlite3

from PySide6.QtCore import QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.history import SAMPLE_SECONDS
from app.i18n import N_, format_decimal, tr
from app.remote_client import fetch_history
from app.themes import WIN10_CHART_COLORS
from pages.performance_page import _format_bits
from widgets.history_chart import ChartSeries, HistoryChart

REFRESH_MS = SAMPLE_SECONDS * 1000
_HOUR = 3600
_DAY = 24 * _HOUR
RANGES = (
    (N_("1 hour"), _HOUR),
    (N_("6 hours"), 6 * _HOUR),
    (N_("24 hours"), _DAY),
    (N_("7 days"), 7 * _DAY),
    (N_("30 days"), 30 * _DAY),
    (N_("1 year"), 365 * _DAY),
)
DEFAULT_RANGE = _DAY


def _number(value: float) -> str:
    return f"{value:.0f}" if value == round(value) else format_decimal(value)


def _percent(value: float) -> str:
    return _number(value) + "%"


def _celsius(value: float) -> str:
    return _number(value) + " °C"


def _bits(bytes_per_second: float) -> str:
    return _format_bits(bytes_per_second * 8 / 1000)


def _bytes(bytes_per_second: float) -> str:
    if bytes_per_second >= 1e9:
        return format_decimal(bytes_per_second / 1e9) + " GB/s"
    if bytes_per_second >= 1e6:
        return format_decimal(bytes_per_second / 1e6) + " MB/s"
    return f"{bytes_per_second / 1e3:.0f} KB/s"


# (title, formatter, fixed y maximum, ((series name, chart colour, metric), ...))
CHARTS = (
    (N_("CPU"), _percent, 100.0, ((N_("Usage"), "cpu", "cpu"),)),
    (N_("Memory"), _percent, 100.0,
     ((N_("RAM"), "memory", "memory"), (N_("Swap"), "memory", "swap"))),
    (N_("GPU"), _percent, 100.0, ((N_("Usage"), "gpu", "gpu"),)),
    (N_("Network"), _bits, None,
     ((N_("Receive"), "network", "net_recv"), (N_("Send"), "network", "net_sent"))),
    (N_("Disk activity"), _bytes, None,
     ((N_("Read"), "disk", "disk_read"), (N_("Write"), "disk", "disk_write"))),
    (N_("Disk space"), _percent, 100.0, ((N_("Used"), "disk", "disk_used"),)),
    (N_("Temperatures"), _celsius, None,
     ((N_("CPU"), "cpu", "cpu_temp"), (N_("GPU"), "gpu", "gpu_temp"))),
)


class HistoryLoader(QThread):
    """Reads one range outside the GUI thread: a server may take seconds to answer."""

    loaded = Signal(int, object, str)  # request id, payload or None, error text

    def __init__(self, request_id: int, seconds: int, store, remote: tuple | None, parent=None):
        super().__init__(parent)
        self.request_id, self.seconds = request_id, seconds
        self.store, self.remote = store, remote

    def run(self) -> None:
        try:
            if self.remote:
                host, port, token = self.remote
                payload = fetch_history(host, port, token, self.seconds, timeout=5.0)
            else:
                payload = self.store.query(self.seconds)
        except (OSError, ValueError, http.client.HTTPException, sqlite3.Error) as error:
            self.loaded.emit(self.request_id, None, str(error))
            return
        self.loaded.emit(self.request_id, payload, "")


def series_from_payload(payload: dict, specs: tuple) -> tuple[list, list]:
    """Times and the series with any value at all. Looks columns up by name, so a server
    of another version may store more or fewer of them."""
    positions = {name: index for index, name in enumerate(payload["columns"])}
    rows = payload["rows"]
    times = [row[0] for row in rows]
    series = []
    for label, color_key, metric in specs:
        avg_at, peak_at = positions.get(f"{metric}_avg"), positions.get(f"{metric}_max")
        if avg_at is None or peak_at is None:
            continue
        average = [row[avg_at] for row in rows]
        if all(value is None for value in average):
            continue
        series.append(ChartSeries(tr(label), color_key, average,
                                  [row[peak_at] for row in rows]))
    return times, series


class HistoryPage(QWidget):
    def __init__(self, settings, service, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.service = service
        self._remote: tuple | None = None
        self._loader: HistoryLoader | None = None
        self._request_id = 0
        self._reload_pending = False
        self._closing = False
        self._build_ui()
        self.set_theme(False, None, WIN10_CHART_COLORS)
        self._timer = QTimer(self)
        self._timer.setInterval(REFRESH_MS)
        self._timer.timeout.connect(self.reload)
        self._update_controls()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        controls = QHBoxLayout()
        controls.addWidget(QLabel(tr("Period:")))
        self.range_combo = QComboBox()
        for label, seconds in RANGES:
            self.range_combo.addItem(tr(label), seconds)
        self.range_combo.setCurrentIndex(self.range_combo.findData(DEFAULT_RANGE))
        # A bound method, not a lambda: a lambda that holds self keeps the page alive in a
        # reference cycle, and PySide aborts at exit when the collector reaches it.
        self.range_combo.currentIndexChanged.connect(self._on_range_changed)
        controls.addWidget(self.range_combo)
        self.source_label = QLabel()
        controls.addWidget(self.source_label)
        controls.addStretch(1)
        self.record_check = QCheckBox(tr("Record this computer's history"))
        self.record_check.setChecked(self.service.recording)
        self.record_check.toggled.connect(self._set_recording)
        controls.addWidget(self.record_check)
        self.clear_btn = QPushButton(tr("Delete history"))
        self.clear_btn.clicked.connect(self._clear)
        controls.addWidget(self.clear_btn)
        layout.addLayout(controls)

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        content = QWidget()
        charts_layout = QVBoxLayout(content)
        charts_layout.setContentsMargins(0, 0, 0, 0)
        self.charts: list[tuple[HistoryChart, tuple]] = []
        for title, formatter, fixed_max, specs in CHARTS:
            chart = HistoryChart(tr(title), formatter, fixed_max)
            chart.hide()
            charts_layout.addWidget(chart)
            self.charts.append((chart, specs))
        charts_layout.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)

    def set_theme(self, dark: bool, chart_background=None, chart_colors=None) -> None:
        for chart, _specs in self.charts:
            chart.set_theme(dark, chart_background, chart_colors or WIN10_CHART_COLORS)

    def set_remote_connection(self, enabled: bool, host: str, port: int, token: str) -> None:
        self._remote = (host, port, token) if enabled else None
        self._update_controls()
        self.reload()

    def _update_controls(self) -> None:
        usable = self.service.store is not None
        self.source_label.setText(
            tr("Server: {host}", host=self._remote[0]) if self._remote else tr("This computer"))
        self.record_check.setEnabled(usable)
        self.clear_btn.setEnabled(usable and self._remote is None)

    def showEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().showEvent(event)
        self._timer.start()
        self.reload()

    def hideEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().hideEvent(event)
        self._timer.stop()

    def _on_range_changed(self, _index: int) -> None:
        self.reload()

    def reload(self) -> None:
        if self._closing or not self.isVisible():
            return
        if self._loader is not None:
            self._reload_pending = True
            return
        if self._remote is None and self.service.store is None:
            self._show_message(tr("The history file can't be used, so nothing is recorded."))
            return
        self._request_id += 1
        self._loader = HistoryLoader(self._request_id, self.range_combo.currentData(),
                                     self.service.store, self._remote, self)
        self._loader.loaded.connect(self._on_loaded)
        self._loader.finished.connect(self._on_loader_finished)
        self._loader.start()

    def _on_loader_finished(self) -> None:
        loader, self._loader = self._loader, None
        if loader is not None:
            loader.deleteLater()
        if self._reload_pending:
            self._reload_pending = False
            self.reload()

    def _on_loaded(self, request_id: int, payload, error: str) -> None:
        if self._closing or request_id != self._request_id or self._reload_pending:
            return
        if payload is None:
            self._show_message(tr("Could not load the history: {error}", error=error))
        else:
            self.show_payload(payload)

    def _show_message(self, text: str) -> None:
        self.status_label.setText(text)
        self.status_label.setVisible(bool(text))
        for chart, _specs in self.charts:
            chart.hide()

    def show_payload(self, payload: dict) -> None:
        start, end, step = payload["now"] - payload["seconds"], payload["now"], payload["step"]
        shown = False
        for chart, specs in self.charts:
            times, series = series_from_payload(payload, specs)
            chart.set_data(start, end, step, times, series)
            chart.setVisible(bool(series))
            shown = shown or bool(series)
        # One time axis for all: the same moment sits at the same x in every chart.
        width = max(chart.axis_label_width() for chart, _specs in self.charts)
        for chart, _specs in self.charts:
            chart.set_label_width(width)
        if not shown:
            self._show_message(tr("Nothing recorded for this period yet. Lintask records every "
                                  "{seconds} seconds while it is running.",
                                  seconds=SAMPLE_SECONDS))
        elif self._remote is None and not self.service.recording:
            self.status_label.setText(tr("Recording is switched off: no new values are added."))
            self.status_label.show()
        else:
            self.status_label.hide()

    def _set_recording(self, enabled: bool) -> None:
        self.settings.history_enabled = enabled
        self.service.set_recording(enabled)
        self.reload()

    def _clear(self) -> None:
        if self.service.store is None or self._remote is not None:
            return
        confirm = QMessageBox.question(
            self, tr("Delete history"),
            tr("Do you really want to delete the whole history of this computer?"),
        )
        if confirm != QMessageBox.Yes:
            return
        try:
            self.service.store.clear()
        except sqlite3.Error as error:
            QMessageBox.warning(self, tr("Error"), tr("Action failed:\n{error}", error=str(error)))
        self.reload()

    def shutdown(self) -> None:
        """Waits for the loader: it reads from a store that gets closed after this."""
        self._closing = True
        self._timer.stop()
        if self._loader is not None:
            self._loader.wait()
