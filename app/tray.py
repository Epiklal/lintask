"""Panel (system tray) icon: Lintask keeps recording the history while the window and
all pages are gone. The icon only reads the recorder's last sample, so the panel costs
one small redraw every SAMPLE_SECONDS and no measuring of its own."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from app.history import SAMPLE_SECONDS, HistoryService
from app.i18n import format_decimal, tr

_ICON_FILE = Path(__file__).resolve().parents[1] / "packaging" / "icons" / "lintask.svg"
_SIZE = 32


def tray_available() -> bool:
    return QSystemTrayIcon.isSystemTrayAvailable()


def app_icon() -> QIcon:
    fallback = QIcon(str(_ICON_FILE)) if _ICON_FILE.exists() else QIcon()
    return QIcon.fromTheme("utilities-system-monitor", fallback)


def _meter_icon(cpu: float) -> QIcon:
    """A dark square that fills from the bottom with the CPU load."""
    pixmap = QPixmap(_SIZE, _SIZE)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor("#202020"))
    painter.drawRoundedRect(QRectF(1, 1, _SIZE - 2, _SIZE - 2), 5, 5)
    fraction = max(0.0, min(cpu, 100.0)) / 100
    inner = _SIZE - 8
    height = max(1.0, inner * fraction)
    color = "#4caf50" if cpu < 60 else "#ffb300" if cpu < 85 else "#e53935"
    painter.setBrush(QColor(color))
    painter.drawRect(QRectF(4, 4 + inner - height, inner, height))
    painter.end()
    return QIcon(pixmap)


class TrayIcon(QSystemTrayIcon):
    openRequested = Signal()
    quitRequested = Signal()

    def __init__(self, history: HistoryService, parent=None):
        super().__init__(app_icon(), parent)
        self._history = history
        self._menu = QMenu()
        self._open_action = self._menu.addAction(tr("Open Lintask"), self.openRequested.emit)
        self._menu.addSeparator()
        self._quit_action = self._menu.addAction(tr("Exit"), self.quitRequested.emit)
        self.setContextMenu(self._menu)
        self.activated.connect(self._on_activated)
        self._timer = QTimer(self)
        self._timer.setInterval(SAMPLE_SECONDS * 1000)
        self._timer.timeout.connect(self._refresh)
        self._last_level: int | None = None
        self.setToolTip("Lintask")

    def retranslate(self) -> None:
        self._open_action.setText(tr("Open Lintask"))
        self._quit_action.setText(tr("Exit"))

    def start(self) -> None:
        self._refresh()
        self._timer.start()
        self.show()

    def stop(self) -> None:
        self._timer.stop()
        self.hide()

    def _on_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.Trigger:
            self.openRequested.emit()

    def _refresh(self) -> None:
        values = self._history.latest
        cpu = values.get("cpu") if values else None
        if cpu is None:
            if self._last_level is not None:
                self.setIcon(app_icon())
                self._last_level = None
            self.setToolTip("Lintask")
            return
        # Redraw only when the bar moves by a pixel or the color changes.
        level = round(cpu / 100 * (_SIZE - 8)) * 1000 + (0 if cpu < 60 else 1 if cpu < 85 else 2)
        if level != self._last_level:
            self.setIcon(_meter_icon(cpu))
            self._last_level = level
        lines = ["Lintask", tr("CPU: {value} %", value=format_decimal(cpu))]
        memory = values.get("memory")
        if memory is not None:
            lines.append(tr("Memory: {value} %", value=format_decimal(memory)))
        self.setToolTip("\n".join(lines))
