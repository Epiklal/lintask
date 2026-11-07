import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import login_autostart
from app.system_info import _parse_desktop_entry


class LoginAutostartTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        patcher = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": self._tmp.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.path = Path(self._tmp.name) / "autostart" / login_autostart.FILENAME

    def test_entry_goes_to_the_xdg_config_home(self):
        self.assertEqual(login_autostart.entry_path(), self.path)

    def test_relative_or_empty_config_home_falls_back_to_dot_config(self):
        for value in ("", "relative/dir"):
            with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": value}):
                self.assertEqual(login_autostart.autostart_dir(),
                                 Path(os.path.expanduser("~/.config/autostart")))

    def test_enable_writes_an_entry_that_starts_in_the_tray(self):
        self.assertFalse(login_autostart.is_enabled())
        self.assertEqual(login_autostart.set_enabled(True), (True, ""))
        self.assertTrue(login_autostart.is_enabled())
        values = _parse_desktop_entry(str(self.path))
        self.assertEqual(values["Type"], "Application")
        self.assertTrue(values["Exec"].endswith(" --tray"))
        self.assertIn("Comment[de]", values)
        self.assertNotEqual(values["Comment[de]"], values["Comment"])
        self.assertFalse(self.path.with_name(self.path.name + ".tmp").exists())

    def test_disable_removes_the_entry_and_is_idempotent(self):
        login_autostart.set_enabled(True)
        self.assertEqual(login_autostart.set_enabled(False), (True, ""))
        self.assertFalse(self.path.exists())
        self.assertEqual(login_autostart.set_enabled(False), (True, ""))
        self.assertFalse(login_autostart.is_enabled())

    def test_entry_turned_off_elsewhere_counts_as_disabled(self):
        for line in ("X-GNOME-Autostart-enabled=false", "Hidden=true"):
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(f"[Desktop Entry]\nType=Application\nExec=lintask --tray\n{line}\n")
            self.assertFalse(login_autostart.is_enabled(), line)

    def test_write_failure_is_reported(self):
        Path(self._tmp.name, "autostart").write_text("not a directory")
        ok, error = login_autostart.set_enabled(True)
        self.assertFalse(ok)
        self.assertTrue(error)

    def test_exec_line_quotes_paths_per_desktop_spec(self):
        self.assertEqual(login_autostart.exec_line(["/usr/bin/lintask"]), "/usr/bin/lintask --tray")
        self.assertEqual(login_autostart.exec_line(["/home/a b/run.sh"]), '"/home/a b/run.sh" --tray')
        self.assertEqual(login_autostart.exec_line(["/x/$y"]), '"/x/\\\\$y" --tray')
        self.assertEqual(login_autostart.exec_line(["/x/100%"]), "/x/100%% --tray")

    def test_launch_command_prefers_the_appimage_file(self):
        with tempfile.NamedTemporaryFile() as image, \
                mock.patch.dict(os.environ, {"APPIMAGE": image.name}):
            self.assertEqual(login_autostart.launch_command(), [image.name])

    def test_launch_command_uses_run_sh_in_a_source_checkout(self):
        run_script = login_autostart._APP_DIR / "run.sh"
        if not os.access(run_script, os.X_OK):
            self.skipTest("run.sh is not executable here")
        with mock.patch.dict(os.environ, {"APPIMAGE": ""}):
            self.assertEqual(login_autostart.launch_command(), [str(run_script)])

    def test_launch_command_falls_back_to_this_python(self):
        with tempfile.TemporaryDirectory() as empty, \
                mock.patch.object(login_autostart, "_APP_DIR", Path(empty)), \
                mock.patch.object(login_autostart.shutil, "which", return_value=None), \
                mock.patch.dict(os.environ, {"APPIMAGE": ""}):
            self.assertEqual(login_autostart.launch_command(),
                             [login_autostart.sys.executable, str(Path(empty) / "main.py")])


if __name__ == "__main__":
    unittest.main()
