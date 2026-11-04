"""Memory view of the Performance tab - RAM and swap over time, the rating and everything known about the memory."""
from __future__ import annotations

from collections import deque

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QGridLayout,
    QGroupBox,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.i18n import tr
from app.memory_info import (
    DropCachesResult,
    DropCachesWorker,
    MemoryOverview,
    MemorySnapshot,
    MemoryWorker,
    format_bytes,
    is_tight,
    memory_data_sections,
    overview_from_remote,
    read_meminfo,
    read_overview,
    read_swaps,
)
from app.themes import WIN10_CHART_COLORS
from widgets.live_chart import LiveChart
from widgets.row_hover import enable_row_hover

_CHART_POINTS = 60
_CHART_MIN_HEIGHT = 160
_CHART_INTERVAL_MS = 1000


def _empty_history() -> deque:
    return deque([0.0] * _CHART_POINTS, maxlen=_CHART_POINTS)


class MemoryPage(QWidget):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings

        self._chart_colors = dict(WIN10_CHART_COLORS)
        self.memory_chart_label = QLabel(tr("RAM (solid line)"))
        self.swap_label = QLabel(tr("Swap (dashed line)"))
        self.memory_chart = LiveChart(max_points=_CHART_POINTS, max_value=100.0,
                                      line_color=self._chart_colors["memory"])
        self.memory_chart.setMinimumHeight(_CHART_MIN_HEIGHT)

        captions = QGridLayout()
        captions.addWidget(self.memory_chart_label, 0, 0)
        captions.addWidget(self.swap_label, 0, 1)
        captions.setColumnStretch(0, 1)
        captions.setColumnStretch(1, 1)

        self.rating_label = self._text_label()

        self.status_label = self._text_label()
        self.status_label.hide()

        self.cache_box = QGroupBox(tr("Emptying the cache"))
        self.cache_check = QCheckBox(tr("Offer to empty the cache"))
        self.cache_check.setChecked(settings.memory_cache_option)
        self.cache_check.toggled.connect(self._on_cache_option_toggled)
        self.cache_warning = self._text_label(tr(
            "This rarely helps. Linux gives the cache back on its own as soon as programs need "
            "the memory, and after emptying it programs and files load more slowly until it has "
            "filled up again. It needs the setup under Settings."
        ))
        self.drop_btn = QPushButton(tr("Empty cache now"))
        self.drop_btn.clicked.connect(self._on_drop_clicked)
        cache_layout = QVBoxLayout(self.cache_box)
        cache_layout.addWidget(self.cache_check)
        cache_layout.addWidget(self.cache_warning)
        cache_layout.addWidget(self.drop_btn, 0, Qt.AlignLeft)

        self.data_table = QTableWidget(0, 2)
        enable_row_hover(self.data_table)
        self.data_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.data_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.data_table.setFocusPolicy(Qt.NoFocus)
        self.data_table.horizontalHeader().setVisible(False)
        self.data_table.horizontalHeader().setStretchLastSection(True)
        self.data_table.verticalHeader().setVisible(False)
        self.data_table.setColumnWidth(0, 280)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(captions)
        layout.addWidget(self.memory_chart, 1)
        layout.addWidget(self.rating_label)
        layout.addWidget(self.status_label)
        layout.addWidget(self.cache_box)
        layout.addWidget(self.data_table, 1)

        self._overview: MemoryOverview = read_overview()
        self._remote = False
        self._remote_sensors: list[dict] | None = None
        self._hardware = None
        self._ram_sensors: list[dict] = []
        self._data_labels: list[tuple[str, str | None]] = []
        self._memory_history = _empty_history()
        self._swap_history = _empty_history()
        self.memory_chart.set_data(self._memory_history)
        self.memory_chart.set_secondary_data(self._swap_history)
        self._action_worker = None
        self._action_slot = None

        self._update_cache_option()
        self._update_actions()

        self.worker = MemoryWorker(parent=self)
        self.worker.snapshotReady.connect(self._on_snapshot)
        self.worker.hardwareReady.connect(self._on_hardware)
        self.worker.start()

        # Runs while the tab is hidden too, so the graph has a history when it is opened.
        self.chart_timer = QTimer(self)
        self.chart_timer.timeout.connect(self._on_chart_timer)
        self.chart_timer.start(_CHART_INTERVAL_MS)
        self._add_to_charts(self._overview)

    def set_theme(self, dark: bool, chart_background=None, chart_colors=None) -> None:
        self._chart_colors = dict(chart_colors or WIN10_CHART_COLORS)
        self.memory_chart.set_line_color(self._chart_colors["memory"])
        self.memory_chart.set_theme(dark, chart_background)

    @staticmethod
    def _text_label(text: str = "") -> QLabel:
        # Plain text: the texts carry values from outside that must not be read as markup.
        label = QLabel(text)
        label.setTextFormat(Qt.PlainText)
        label.setWordWrap(True)
        return label

    @property
    def overview(self) -> MemoryOverview:
        return self._overview

    def showEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().showEvent(event)
        self.worker.set_visible(True)

    def hideEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().hideEvent(event)
        self.worker.set_visible(False)

    def _on_snapshot(self, snapshot: MemorySnapshot) -> None:
        self.worker.mark_consumed()
        if not self._remote:
            self._ram_sensors = snapshot.ram_sensors
            self._overview = snapshot.overview
            self._show_overview(snapshot.overview)
            self._update_data_table()

    def _on_hardware(self, hardware) -> None:
        self._hardware = hardware
        self._update_data_table()

    def _on_chart_timer(self) -> None:
        if self._remote:
            return
        self._overview = read_overview()
        self._add_to_charts(self._overview)
        if self.isVisible():
            self._show_overview(self._overview)
            self._update_data_table()

    def _clear_charts(self) -> None:
        self._memory_history = _empty_history()
        self._swap_history = _empty_history()
        self.memory_chart.set_data(self._memory_history)
        self.memory_chart.set_secondary_data(self._swap_history)

    def _add_to_charts(self, overview: MemoryOverview) -> None:
        percent = overview.used * 100 / overview.total if overview.total else 0.0
        self._memory_history.append(percent)
        if overview.swap_total:
            self._swap_history.append((overview.swap_used or 0) * 100 / overview.swap_total)
        else:
            self._swap_history.append(0.0)
        self.memory_chart.set_data(self._memory_history)
        self.memory_chart.set_secondary_data(self._swap_history)

    def set_remote_data(self, payload: dict | None) -> None:
        was_remote = self._remote
        self._remote = payload is not None
        self.cache_box.setVisible(not self._remote)
        if self._remote != was_remote:
            self._clear_charts()
        if payload is None:
            if was_remote:
                self._remote_sensors = None
                self._ram_sensors = []
                self.worker.request_refresh()
            return
        system = payload.get("system")
        self._remote_sensors = payload.get("ram_sensors")
        if not system:
            return
        overview = overview_from_remote(system)
        self._add_to_charts(overview)
        self._overview = overview
        self._show_overview(overview)
        self._update_data_table()

    def _update_data_table(self) -> None:
        if self._remote:
            # An older server does not send this field, which says nothing about its sensors.
            sections = memory_data_sections(self._overview, {}, [], None, self._remote_sensors,
                                            remote=True)
        else:
            sections = memory_data_sections(self._overview, read_meminfo(), read_swaps(),
                                            self._hardware, self._ram_sensors)
        self._show_data(sections)

    def _show_data(self, sections: list[tuple[str, list[tuple[str, str]]]]) -> None:
        rows: list[tuple[str, str | None]] = []
        for title, entries in sections:
            rows.append((title, None))
            rows.extend(entries)
        labels = [(label, None if value is None else "") for label, value in rows]
        # With the same rows only the values change, so the scroll position stays.
        rebuild = labels != self._data_labels
        table = self.data_table
        table.setUpdatesEnabled(False)
        if rebuild:
            self._data_labels = labels
            table.clearSpans()
            table.setRowCount(len(rows))
            bold = QFont(table.font())
            bold.setBold(True)
        for index, (label, value) in enumerate(rows):
            if value is None:
                if rebuild:
                    item = QTableWidgetItem(label)
                    item.setFont(bold)
                    table.setItem(index, 0, item)
                    table.setItem(index, 1, None)
                    table.setSpan(index, 0, 1, 2)
                continue
            if rebuild:
                table.setItem(index, 0, QTableWidgetItem(label))
            item = table.item(index, 1)
            if item is None:
                table.setItem(index, 1, QTableWidgetItem(value))
            elif item.text() != value:
                item.setText(value)
        table.setUpdatesEnabled(True)

    def _show_overview(self, overview: MemoryOverview) -> None:
        if is_tight(overview):
            self.rating_label.setText(tr(
                "Memory is tight. Closing a program you do not need helps most."))
        else:
            self.rating_label.setText(tr(
                "Everything is fine. The cache is released automatically as soon as "
                "programs need the memory."))

    def _update_actions(self) -> None:
        self.drop_btn.setEnabled(self._action_worker is None)

    def _show_status(self, text: str) -> None:
        self.status_label.setText(text)
        self.status_label.setVisible(bool(text))

    def _start_action(self, worker, slot) -> None:
        self._stop_action_worker()
        self._show_status("")
        self._action_worker = worker
        self._action_slot = slot
        worker.resultReady.connect(slot)
        worker.start()
        self._update_actions()

    def _stop_action_worker(self) -> None:
        if self._action_worker is None:
            return
        self._action_worker.resultReady.disconnect(self._action_slot)
        self._action_worker.stop()
        self._action_worker.deleteLater()
        self._action_worker = None
        self._action_slot = None

    def _finish_action(self) -> None:
        self._stop_action_worker()
        self._update_actions()
        self.worker.request_refresh()

    def _on_cache_option_toggled(self, checked: bool) -> None:
        self.settings.memory_cache_option = checked
        self._update_cache_option()

    def _update_cache_option(self) -> None:
        checked = self.cache_check.isChecked()
        self.cache_warning.setVisible(checked)
        self.drop_btn.setVisible(checked)

    def _on_drop_clicked(self) -> None:
        answer = QMessageBox.warning(
            self, tr("Empty cache now"),
            tr("Really empty the cache?\n\nThis does not make the PC faster. Programs and files "
               "load more slowly until the cache has filled up again."),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer == QMessageBox.Yes:
            self._start_action(DropCachesWorker(parent=self), self._on_drop_result)

    def _on_drop_result(self, result: DropCachesResult) -> None:
        self._finish_action()
        if result.error:
            self._show_status(tr(result.error))
        else:
            self._show_status(tr("Cache emptied: {before} before, {after} now.",
                                 before=format_bytes(result.before_bytes),
                                 after=format_bytes(result.after_bytes)))

    def shutdown(self) -> None:
        self.chart_timer.stop()
        self._stop_action_worker()
        self.worker.snapshotReady.disconnect(self._on_snapshot)
        self.worker.hardwareReady.disconnect(self._on_hardware)
        self.worker.stop()
        self.worker.deleteLater()
