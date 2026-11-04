"""A sudo call that can only fail is a line in the system log: the SMART worker runs the
helper only with a matching rule, and doesn't poll once it has a way to read the data."""
import json
import os
import subprocess
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import system_info
from app.system_info import DiskSmartWorker, _smartctl_disk_stats, read_dmi_memory


class TestSmartCommands(unittest.TestCase):
    def commands(self, helper, smartctl=None):
        calls = []

        def run(command, timeout):
            calls.append(command)
            return subprocess.CompletedProcess(command, 0, json.dumps({}))

        with mock.patch.object(system_info, "smart_helper", return_value=helper), \
                mock.patch.object(system_info.shutil, "which", return_value=smartctl):
            _smartctl_disk_stats("sda", run=run)
        return calls

    def test_helper_with_a_rule_is_run(self):
        self.assertEqual(self.commands("/helper"), [["sudo", "-n", "/helper", "sda"]])

    def test_without_a_rule_sudo_is_not_called(self):
        self.assertEqual(self.commands(None), [])

    def test_without_a_rule_smartctl_still_runs_directly(self):
        command = ["/usr/sbin/smartctl", "--all", "--json=o", "/dev/sda"]
        self.assertEqual(self.commands(None, "/usr/sbin/smartctl"), [command])


class TestDmiCommands(unittest.TestCase):
    def test_without_a_rule_sudo_is_not_called(self):
        with mock.patch.object(system_info, "sudo_helper", return_value=None), \
                mock.patch.object(system_info.shutil, "which", return_value=None), \
                mock.patch.object(system_info, "_run_capture") as run:
            self.assertIsNone(read_dmi_memory())
        run.assert_not_called()


class TestPollInterval(unittest.TestCase):
    def wait_seconds(self, helper, smartctl):
        worker = DiskSmartWorker([], interval=60.0)
        with mock.patch.object(system_info, "smart_helper", return_value=helper), \
                mock.patch.object(system_info.shutil, "which", return_value=smartctl), \
                mock.patch.object(worker._stop_event, "wait",
                                  side_effect=lambda _seconds: worker._stop_event.set()) as wait:
            worker.run()
        return wait.call_args.args[0]

    def test_helper_outside_the_path_uses_the_interval(self):
        self.assertEqual(self.wait_seconds("/helper", None), 60.0)

    def test_smartctl_uses_the_interval(self):
        self.assertEqual(self.wait_seconds(None, "/usr/sbin/smartctl"), 60.0)

    def test_nothing_to_read_yet_looks_again_soon(self):
        self.assertEqual(self.wait_seconds(None, None), 5.0)


if __name__ == "__main__":
    unittest.main()
