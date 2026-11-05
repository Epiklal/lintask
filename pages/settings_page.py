"""Settings tab - theme and refresh-rate controls, applied live and persisted."""
from __future__ import annotations

import getpass
import grp
import os
import shutil
from pathlib import Path

from PySide6.QtCore import QProcess, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QCheckBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.hardware_setup import setup_script, terminal_command
from app.i18n import N_, tr
from app import ui_scale
from app.settings import Settings
from app.themes import SCHEMES

QSS_TEMPLATES = {
    N_("Whole app"): """QWidget {
    background-color: #191919;
    color: #f1f1f1;
    font-size: 13px;
}""",
    N_("Tab bar"): """QTabBar::tab {
    background-color: #191919;
    color: #c9c9c9;
    padding: 9px 16px;
}
QTabBar::tab:selected {
    color: #ffffff;
    border-bottom: 2px solid #00b7c3;
}""",
    N_("Buttons"): """QPushButton {
    background-color: #242424;
    color: #f1f1f1;
    border: 1px solid #393939;
    border-radius: 2px;
    padding: 6px 16px;
}
QPushButton:hover {
    background-color: #313131;
    border-color: #00b7c3;
}""",
    N_("Tables"): """QTableView, QTableWidget {
    background-color: #1e1e1e;
    color: #f1f1f1;
    gridline-color: #303030;
    selection-background-color: #333333;
}
QHeaderView::section {
    background-color: #242424;
    color: #e6e6e6;
}""",
    N_("Performance tiles"): """QWidget#resourceTile {
    background-color: #191919;
    border-left: 3px solid transparent;
}
QWidget#resourceTile[selected=\"true\"] {
    background-color: #292929;
    border-left-color: #00b7c3;
}""",
    N_("Performance charts"): """LiveChart {
    qproperty-lineColor: #00b7c3;
    qproperty-backgroundColor: #191919;
    qproperty-gridColor: #303030;
}""",
}


class SettingsPage(QWidget):
    themeChanged = Signal(str)
    styleChanged = Signal(str)
    languageChanged = Signal(str)
    processIntervalChanged = Signal(int)  # milliseconds
    performanceIntervalChanged = Signal(int)  # milliseconds
    smartSudoEnabled = Signal(bool)
    customQssChanged = Signal(str)
    remoteConnectionChanged = Signal(bool, str, int, str)
    alwaysOnTopChanged = Signal(bool)
    defaultPageChanged = Signal(str)

    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.settings = settings

        appearance_box = QGroupBox(tr("Appearance"))
        self.theme_combo = QComboBox()
        for key, scheme in SCHEMES.items():
            self.theme_combo.addItem(tr(scheme.name), key)
        self.theme_combo.setCurrentIndex(self.theme_combo.findData(settings.theme))
        self.theme_combo.currentIndexChanged.connect(self._on_theme_changed)

        self.style_combo = QComboBox()
        self.style_combo.addItem("Windows 10", "win10")
        self.style_combo.addItem("Windows 11", "win11")
        self.style_combo.setCurrentIndex(self.style_combo.findData(settings.style))
        self.style_combo.currentIndexChanged.connect(self._on_style_changed)

        self.language_combo = QComboBox()
        self.language_combo.addItem(tr("System default"), "system")
        # Each language keeps its own name, so it can be found from the other one.
        self.language_combo.addItem("Deutsch", "de")
        self.language_combo.addItem("English", "en")
        self.language_combo.setCurrentIndex(self.language_combo.findData(settings.language))
        self.language_combo.currentIndexChanged.connect(self._on_language_changed)

        self.ui_scale_combo = QComboBox()
        for percent in ui_scale.CHOICES:
            label = tr("Automatic (screen resolution)") if percent == 0 else f"{percent} %"
            self.ui_scale_combo.addItem(label, percent)
        self.ui_scale_combo.setCurrentIndex(max(0, self.ui_scale_combo.findData(settings.ui_scale)))
        self.ui_scale_combo.currentIndexChanged.connect(self._on_ui_scale_changed)
        self.ui_scale_hint = QLabel(tr("Takes effect after Lintask is restarted."))
        self.ui_scale_hint.setObjectName("detailInfo")
        self.ui_scale_hint.setVisible(False)

        appearance_form = QFormLayout(appearance_box)
        appearance_form.addRow(tr("Language:"), self.language_combo)
        appearance_form.addRow(tr("Style:"), self.style_combo)
        appearance_form.addRow(tr("Color scheme:"), self.theme_combo)
        appearance_form.addRow(tr("UI size:"), self.ui_scale_combo)
        appearance_form.addRow("", self.ui_scale_hint)

        # Windows 11 Task Manager: "Default start page" and "Window management".
        window_box = QGroupBox(tr("Window management"))
        self.default_page_combo = QComboBox()
        self.default_page_combo.currentIndexChanged.connect(self._on_default_page_changed)
        self.always_on_top_check = QCheckBox(tr("Always on top"))
        self.always_on_top_check.setChecked(settings.always_on_top)
        self.always_on_top_check.toggled.connect(self._on_always_on_top_toggled)
        window_form = QFormLayout(window_box)
        window_form.addRow(tr("Default start page:"), self.default_page_combo)
        window_form.addRow(self.always_on_top_check)

        speed_box = QGroupBox(tr("Refresh rate"))
        self.process_spin = QSpinBox()
        self.process_spin.setRange(200, 5000)
        self.process_spin.setSingleStep(100)
        self.process_spin.setSuffix(" ms")
        self.process_spin.setValue(settings.process_interval_ms)
        self.process_spin.valueChanged.connect(self._on_process_interval_changed)

        self.performance_spin = QSpinBox()
        self.performance_spin.setRange(100, 5000)
        self.performance_spin.setSingleStep(100)
        self.performance_spin.setSuffix(" ms")
        self.performance_spin.setValue(settings.performance_interval_ms)
        self.performance_spin.valueChanged.connect(self._on_performance_interval_changed)

        speed_form = QFormLayout(speed_box)
        speed_form.addRow(tr("Process list:"), self.process_spin)
        speed_form.addRow(tr("Performance charts:"), self.performance_spin)

        remote_box = QGroupBox(tr("Remote server"))
        self.remote_enabled_check = QCheckBox(tr("Use data from the server"))
        self.remote_enabled_check.setChecked(settings.remote_enabled)
        self.remote_host_edit = QLineEdit(settings.remote_host)
        self.remote_host_edit.setPlaceholderText(tr("127.0.0.1 or server IP"))
        self.remote_port_spin = QSpinBox()
        self.remote_port_spin.setRange(1, 65535)
        self.remote_port_spin.setValue(settings.remote_port)
        self.remote_token_edit = QLineEdit(settings.remote_token)
        self.remote_token_edit.setPlaceholderText(tr("Optional access token"))
        self.remote_token_edit.setEchoMode(QLineEdit.Password)
        self.remote_connect_button = QPushButton(tr("Apply server connection"))
        self.remote_connect_button.clicked.connect(self._apply_remote_connection)
        remote_form = QFormLayout(remote_box)
        remote_form.addRow(self.remote_enabled_check)
        remote_form.addRow(tr("Server IP:"), self.remote_host_edit)
        remote_form.addRow("Port:", self.remote_port_spin)
        remote_form.addRow(tr("Access token:"), self.remote_token_edit)
        remote_form.addRow(self.remote_connect_button)

        smart_box = QGroupBox(tr("Hardware data (SMART, memory, CPU and CCD power)"))
        self.smart_setup_button = QPushButton(tr("Set up hardware data with sudo"))
        self.smart_setup_button.clicked.connect(self._setup_smart_access)
        self.smart_status = QLabel(self._smart_status_text())
        self.smart_status.setWordWrap(True)
        smart_form = QFormLayout(smart_box)
        smart_form.addRow(self.smart_setup_button)
        smart_form.addRow(self.smart_status)

        custom_qss_box = QGroupBox(tr("Custom style (QSS)"))
        self.custom_qss_edit = QPlainTextEdit(settings.custom_qss)
        self.custom_qss_edit.setPlaceholderText(
            "QWidget { background-color: #191919; }\n"
            "QPushButton { border-radius: 0px; }"
        )
        self.custom_qss_edit.setMinimumHeight(190)
        self.qss_template_combo = QComboBox()
        self.qss_template_combo.addItem(tr("Choose template"))
        for name in QSS_TEMPLATES:
            self.qss_template_combo.addItem(tr(name), name)
        self.insert_qss_template_button = QPushButton(tr("Insert template"))
        self.insert_qss_template_button.clicked.connect(self._insert_qss_template)
        custom_qss_template_row = QHBoxLayout()
        custom_qss_template_row.addWidget(self.qss_template_combo, stretch=1)
        custom_qss_template_row.addWidget(self.insert_qss_template_button)
        self.apply_custom_qss_button = QPushButton(tr("Apply style"))
        self.apply_custom_qss_button.clicked.connect(self._apply_custom_qss)
        self.reset_custom_qss_button = QPushButton(tr("Reset style"))
        self.reset_custom_qss_button.clicked.connect(self._reset_custom_qss)
        custom_qss_actions = QHBoxLayout()
        custom_qss_actions.addWidget(self.apply_custom_qss_button)
        custom_qss_actions.addWidget(self.reset_custom_qss_button)
        custom_qss_layout = QVBoxLayout(custom_qss_box)
        custom_qss_layout.addLayout(custom_qss_template_row)
        custom_qss_layout.addWidget(self.custom_qss_edit)
        custom_qss_layout.addLayout(custom_qss_actions)

        hint = QLabel(tr("Smaller values refresh faster but use a little more CPU."))
        hint.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.addWidget(appearance_box)
        layout.addWidget(window_box)
        layout.addWidget(speed_box)
        layout.addWidget(remote_box)
        layout.addWidget(smart_box)
        layout.addWidget(custom_qss_box)
        layout.addWidget(hint)
        layout.addStretch(1)

    def _on_theme_changed(self, index: int) -> None:
        theme = self.theme_combo.itemData(index)
        self.settings.theme = theme
        self.themeChanged.emit(theme)

    def _on_style_changed(self, index: int) -> None:
        style = self.style_combo.itemData(index)
        self.settings.style = style
        self.styleChanged.emit(style)

    def _on_language_changed(self, index: int) -> None:
        language = self.language_combo.itemData(index)
        self.settings.language = language
        self.languageChanged.emit(language)

    def _on_ui_scale_changed(self, index: int) -> None:
        self.settings.ui_scale = self.ui_scale_combo.itemData(index)
        self.ui_scale_hint.setVisible(True)

    def set_start_pages(self, pages: list[tuple[str, str]]) -> None:
        """Fills the start page choice with (key, title) pairs, in tab order."""
        combo = self.default_page_combo
        combo.blockSignals(True)
        combo.clear()
        for key, title in pages:
            combo.addItem(title, key)
        combo.setCurrentIndex(max(0, combo.findData(self.settings.default_page)))
        combo.blockSignals(False)

    def _on_default_page_changed(self, index: int) -> None:
        key = self.default_page_combo.itemData(index)
        if key:
            self.settings.default_page = key
            self.defaultPageChanged.emit(key)

    def _on_always_on_top_toggled(self, enabled: bool) -> None:
        self.settings.always_on_top = enabled
        self.alwaysOnTopChanged.emit(enabled)

    def _on_process_interval_changed(self, value: int) -> None:
        self.settings.process_interval_ms = value
        self.processIntervalChanged.emit(value)

    def _on_performance_interval_changed(self, value: int) -> None:
        self.settings.performance_interval_ms = value
        self.performanceIntervalChanged.emit(value)

    def _apply_remote_connection(self) -> None:
        host = self.remote_host_edit.text().strip() or "127.0.0.1"
        port = self.remote_port_spin.value()
        token = self.remote_token_edit.text().strip()
        self.settings.remote_host = host
        self.settings.remote_port = port
        self.settings.remote_token = token
        self.settings.remote_enabled = self.remote_enabled_check.isChecked()
        self.remoteConnectionChanged.emit(
            self.remote_enabled_check.isChecked(), host, port, token
        )

    def _apply_custom_qss(self) -> None:
        qss = self.custom_qss_edit.toPlainText()
        self.settings.custom_qss = qss
        self.customQssChanged.emit(qss)

    def _insert_qss_template(self) -> None:
        template = QSS_TEMPLATES.get(self.qss_template_combo.currentData())
        if not template:
            return
        editor = self.custom_qss_edit
        if editor.toPlainText().strip():
            editor.appendPlainText("")
        editor.appendPlainText(template)

    def _reset_custom_qss(self) -> None:
        self.custom_qss_edit.clear()
        self._apply_custom_qss()

    def _smart_status_text(self) -> str:
        if self.settings.smart_sudo_enabled:
            return tr("SMART is queried with sudo. The authorization expires after a few minutes.")
        return tr("SMART usually needs sudo for temperature, start counts and totals.")

    def _setup_smart_access(self) -> None:
        if not shutil.which("sudo"):
            self.smart_status.setText(tr("sudo is not installed - the setup needs sudo."))
            return
        helper_source = Path(__file__).resolve().parents[1] / "scripts" / "lintask-smartctl"
        group = grp.getgrgid(os.getgid()).gr_name
        script = setup_script(str(helper_source), getpass.getuser(), group)
        command = terminal_command(script)
        if command is None or not QProcess.startDetached(command[0], command[1:]):
            # No known terminal emulator: show the commands so they can be run by hand.
            box = QMessageBox(self)
            box.setWindowTitle(tr("Set up hardware data"))
            box.setText(tr("No terminal found. Please run these commands in a terminal:"))
            box.setDetailedText(script)
            box.exec()
            self.smart_status.setText(tr("The terminal could not be started."))
            return
        self.smart_status.setText(tr(
            "Enter your password in the terminal and wait for it to finish. "
            "Press the button again later if sudo needs renewing."
        ))
        self.smartSudoEnabled.emit(True)
