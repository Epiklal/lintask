import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QStandardItem, QStandardItemModel  # noqa: E402
from PySide6.QtWidgets import QApplication, QMenu, QPushButton, QTableView, QWidget  # noqa: E402

from app import system_info, ui_scale  # noqa: E402
from tests.test_gpu_multi import FakeMonitor  # noqa: E402
from widgets.table_menu import add_button_actions, rows_text  # noqa: E402


class TestFactorFor(unittest.TestCase):
    def test_common_resolutions(self):
        self.assertEqual(ui_scale.factor_for(1280, 720), 0.75)
        self.assertEqual(ui_scale.factor_for(1920, 1080), 1.0)
        self.assertEqual(ui_scale.factor_for(2560, 1440), 1.25)
        self.assertEqual(ui_scale.factor_for(3840, 2160), 2.0)
        self.assertEqual(ui_scale.factor_for(7680, 4320), 4.0)

    def test_short_side_counts_and_limits_hold(self):
        self.assertEqual(ui_scale.factor_for(1080, 1920), 1.0)  # portrait
        self.assertEqual(ui_scale.factor_for(3440, 1440), 1.25)  # ultrawide
        self.assertEqual(ui_scale.factor_for(800, 480), ui_scale.MIN_FACTOR)
        self.assertEqual(ui_scale.factor_for(15360, 8640), ui_scale.MAX_FACTOR)
        self.assertEqual(ui_scale.factor_for(0, 0), 1.0)

    def test_screen_factors_variable(self):
        value = ui_scale.screen_factors_variable(
            [("eDP-1", 1280, 720), ("DP-2", 3840, 2160), ("", 1920, 1080)]
        )
        self.assertEqual(value, "eDP-1=0.75;DP-2=2")


class TestApply(unittest.TestCase):
    def run_apply(self, percent, env):
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(ui_scale, "_probe_screens",
                                  return_value=[("HDMI-1", 3840, 2160)]):
            ui_scale.apply(percent)
            return dict(os.environ)

    def test_user_variables_win(self):
        env = self.run_apply(0, {"QT_SCALE_FACTOR": "1.5"})
        self.assertEqual(env["QT_SCALE_FACTOR"], "1.5")
        self.assertNotIn("QT_SCREEN_SCALE_FACTORS", env)

    def test_fixed_percent(self):
        self.assertEqual(self.run_apply(150, {})["QT_SCALE_FACTOR"], "1.5")
        self.assertNotIn("QT_SCALE_FACTOR", self.run_apply(100, {}))

    def test_automatic_sets_per_screen_factors(self):
        env = self.run_apply(0, {"QT_QPA_PLATFORM": "wayland"})
        self.assertEqual(env["QT_SCREEN_SCALE_FACTORS"], "HDMI-1=2")

    def test_automatic_skips_headless(self):
        self.assertNotIn("QT_SCREEN_SCALE_FACTORS", self.run_apply(0, {"QT_QPA_PLATFORM": "offscreen"}))


class TestTableMenu(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_view(self):
        model = QStandardItemModel(2, 3)
        model.setHorizontalHeaderLabels(["Name", "Hidden", "Status"])
        for row, (name, status) in enumerate((("sshd", "running"), ("cron", "dead"))):
            model.setItem(row, 0, QStandardItem(name))
            model.setItem(row, 1, QStandardItem("x"))
            model.setItem(row, 2, QStandardItem(status))
        view = QTableView()
        view.setModel(model)
        view.setColumnHidden(1, True)
        self.addCleanup(view.deleteLater)
        return view

    def test_rows_text_skips_hidden_columns(self):
        view = self.make_view()
        self.assertEqual(rows_text(view, [1]), "cron\tdead")
        self.assertEqual(rows_text(view, range(2), with_header=True),
                         "Name\tStatus\nsshd\trunning\ncron\tdead")

    def test_button_actions_mirror_buttons(self):
        parent = QWidget()
        self.addCleanup(parent.deleteLater)
        enabled, disabled, hidden = (QPushButton(text, parent) for text in ("Start", "Stop", "Gone"))
        disabled.setEnabled(False)
        hidden.hide()
        clicked = []
        enabled.clicked.connect(lambda: clicked.append(True))
        menu = QMenu()
        add_button_actions(menu, (enabled, None, disabled, hidden))
        actions = menu.actions()
        self.assertEqual([a.text() for a in actions], ["Start", "", "Stop"])
        self.assertFalse(actions[2].isEnabled())
        actions[0].trigger()
        self.assertEqual(clicked, [True])


class TestPerformanceTileText(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_tile_text_is_plain(self):
        from pages.performance_page import PerformancePage

        with mock.patch.object(system_info, "list_gpus", return_value=[]), \
                mock.patch.object(system_info, "GpuSystemMonitor", FakeMonitor):
            page = PerformancePage()
        page.shutdown()
        self.addCleanup(page.deleteLater)
        page._last_text["cpu"] = "<b>Some CPU</b><br>Speed: 1 GHz<br>A &amp; B"
        text = page.tile_text("cpu")
        self.assertTrue(text.startswith(page._labels["cpu"]))
        self.assertTrue(text.endswith("Some CPU\nSpeed: 1 GHz\nA & B"))
        self.assertNotIn("<", text)


if __name__ == "__main__":
    unittest.main()
