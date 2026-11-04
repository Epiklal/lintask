"""Docker's output is not ours: a line that can't be parsed must not end the worker, and on
the server it must not end the whole snapshot."""
import json
import os
import subprocess
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt

from app.system_info import DockerWorker

CONTAINER = {"ID": "abc", "Names": "web", "Image": "nginx", "Status": "Up 2 minutes"}


class TestMalformedDockerOutput(unittest.TestCase):
    def collect(self, ps_out, stats_out=""):
        worker = DockerWorker()
        worker._docker = "docker"

        def run_command(args, **_kwargs):
            return subprocess.CompletedProcess(args, 0, ps_out if "ps" in args else stats_out)

        with mock.patch.object(worker, "_run_command", side_effect=run_command), \
                mock.patch.object(worker._gpu_monitor, "available", return_value=False):
            return worker._collect_rows()

    def test_valid_output_is_read(self):
        stats = {"ID": "abc", "CPUPerc": "12.5%", "MemPerc": "1.5%", "MemUsage": "10MiB / 1GiB"}
        rows, error = self.collect(json.dumps(CONTAINER), json.dumps(stats))
        self.assertEqual(error, "")
        self.assertEqual(rows[0].name, "web")
        self.assertEqual(rows[0].cpu_percent, 12.5)
        self.assertEqual(rows[0].memory_percent, 1.5)

    def test_broken_container_list_is_reported(self):
        rows, error = self.collect("WARNING: this is not JSON")
        self.assertEqual(rows, [])
        self.assertTrue(error)

    def test_broken_stats_keep_the_containers(self):
        for stats in ("not JSON", json.dumps({"Name": "no id"}), json.dumps(["no", "object"])):
            with self.subTest(stats=stats):
                rows, error = self.collect(json.dumps(CONTAINER), stats)
                self.assertEqual(error, "")
                self.assertEqual(rows[0].name, "web")
                self.assertEqual(rows[0].cpu_percent, 0.0)

    def test_container_that_is_starting_has_no_numbers_yet(self):
        stats = {"ID": "abc", "CPUPerc": "--", "MemPerc": "--", "MemUsage": "-- / --"}
        rows, error = self.collect(json.dumps(CONTAINER), json.dumps(stats))
        self.assertEqual(error, "")
        self.assertEqual(rows[0].cpu_percent, 0.0)
        self.assertEqual(rows[0].memory_percent, 0.0)
        self.assertEqual(rows[0].memory_mb, 0.0)


class TestContainerList(unittest.TestCase):
    def test_list_does_not_ask_for_container_sizes(self):
        """`{{json .}}` or `.Size` makes the daemon measure every container, which can take
        longer than the timeout, and then no container is shown at all."""
        worker = DockerWorker()
        worker._docker = "docker"
        calls = []

        def run_command(args, **_kwargs):
            calls.append(args)
            return subprocess.CompletedProcess(args, 0, "")

        with mock.patch.object(worker, "_run_command", side_effect=run_command), \
                mock.patch.object(worker._gpu_monitor, "available", return_value=False):
            worker._collect_rows()
        ps_format = next(args for args in calls if "ps" in args)[-1]
        self.assertNotIn("{{json .}}", ps_format)
        self.assertNotIn(".Size", ps_format)


class TestRecovery(unittest.TestCase):
    def test_worker_keeps_trying_after_an_error(self):
        worker = DockerWorker()
        worker._docker = "docker"
        worker._interval = 0
        errors, batches = [], []

        def on_rows(rows):
            batches.append(rows)
            worker._stop_event.set()

        worker.unavailable.connect(errors.append, Qt.DirectConnection)
        worker.rowsReady.connect(on_rows, Qt.DirectConnection)
        results = [([], "daemon is down"), (["row"], "")]

        with mock.patch.object(worker, "_collect_rows", side_effect=results), \
                mock.patch("app.system_info._DOCKER_RETRY_SECONDS", 0):
            worker.run()
        self.assertEqual(errors, ["daemon is down"])
        self.assertEqual(batches, [["row"]])

    def test_missing_cli_is_final(self):
        worker = DockerWorker()
        worker._docker = None
        errors = []
        worker.unavailable.connect(errors.append, Qt.DirectConnection)
        worker.run()
        self.assertEqual(len(errors), 1)


if __name__ == "__main__":
    unittest.main()
