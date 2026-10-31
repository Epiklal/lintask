"""Persistent history: the SQLite file, its roll-ups, the API over real loopback HTTP, and
the page with its charts on the offscreen Qt platform."""
import contextlib
import http.client
import importlib.util
import io
import json
import os
import sqlite3
import stat
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import history  # noqa: E402
from app.history import (  # noqa: E402
    COLUMNS,
    MAX_POINTS,
    MAX_RANGE_SECONDS,
    HistoryError,
    HistoryRecorder,
    HistoryService,
    HistoryStore,
    MetricSampler,
    check_range,
    default_path,
    parse_range_query,
    validate_payload,
)
from app.i18n import set_language  # noqa: E402
from app.remote_server import MonitoringHandler  # noqa: E402

HAS_QT = importlib.util.find_spec("PySide6") is not None
TOKEN = "correct-token"
# On a full hour, so that the buckets of every tier start with the test.
START = 1_700_000_000 // 3600 * 3600
DAY = 86400


def column(payload: dict, name: str) -> list:
    index = payload["columns"].index(name)
    return [row[index] for row in payload["rows"]]


class StoreTestCase(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "state" / "history.sqlite3"
        self.store = HistoryStore(self.path)
        self.addCleanup(self.store.close)

    def stored(self, tier: int) -> list:
        return self.store._db.execute(
            "SELECT bucket, cpu_avg, cpu_max FROM samples WHERE tier=? ORDER BY bucket",
            (tier,)).fetchall()


class TestStore(StoreTestCase):
    def test_a_sample_comes_back(self):
        self.store.record({"cpu": 12.5, "memory": 40}, now=START + 20)
        payload = self.store.query(3600, now=START + 30)
        self.assertEqual(payload["columns"], list(COLUMNS))
        self.assertEqual(column(payload, "cpu_avg"), [12.5])
        self.assertEqual(column(payload, "cpu_max"), [12.5])
        self.assertEqual(column(payload, "memory_avg"), [40.0])
        self.assertEqual(column(payload, "gpu_avg"), [None])
        validate_payload(json.loads(json.dumps(payload)))

    def test_the_history_survives_closing_the_file(self):
        self.store.record({"cpu": 1.0}, now=START)
        self.store.close()
        self.store = HistoryStore(self.path)
        self.addCleanup(self.store.close)
        self.assertEqual(column(self.store.query(60, now=START), "cpu_avg"), [1.0])

    def test_values_that_are_no_finite_numbers_stay_empty(self):
        for broken in (float("nan"), float("inf"), "12", True, None):
            with self.subTest(broken=broken):
                self.store.record({"cpu": broken, "memory": 5.0}, now=START)
                self.assertEqual(column(self.store.query(60, now=START), "cpu_avg"), [None])

    def test_a_sample_without_any_value_is_not_stored(self):
        self.store.record({"cpu": None, "unknown": 5.0}, now=START)
        self.assertEqual(self.store.query(60, now=START)["rows"], [])

    def test_a_range_shows_only_what_is_inside_it(self):
        self.store.record({"cpu": 1.0}, now=START)
        self.store.record({"cpu": 2.0}, now=START + 100)
        self.assertEqual(column(self.store.query(60, now=START + 100), "cpu_avg"), [2.0])

    def test_gaps_are_not_filled(self):
        self.store.record({"cpu": 1.0}, now=START)
        self.store.record({"cpu": 2.0}, now=START + 1000)
        self.assertEqual(len(self.store.query(3600, now=START + 1000)["rows"]), 2)

    def test_no_range_returns_more_points_than_a_chart_can_show(self):
        for seconds in (3600, 6 * 3600, DAY, 7 * DAY, 30 * DAY, 365 * DAY):
            with self.subTest(seconds=seconds):
                payload = self.store.query(seconds, now=START)
                self.assertLessEqual(seconds / payload["step"], MAX_POINTS + 1)

    def test_coarse_slots_keep_the_average_and_the_peak(self):
        for offset, cpu in ((0, 10.0), (10, 20.0), (20, 90.0)):
            self.store.record({"cpu": cpu}, now=START + offset)
        payload = self.store.query(DAY, now=START + 30)
        self.assertEqual(payload["step"], 120)
        self.assertEqual(column(payload, "cpu_avg"), [40.0])
        self.assertEqual(column(payload, "cpu_max"), [90.0])

    def test_a_range_outside_the_limits_is_refused(self):
        for seconds in (59, MAX_RANGE_SECONDS + 1):
            with self.subTest(seconds=seconds), self.assertRaises(ValueError):
                self.store.query(seconds)


class TestRollup(StoreTestCase):
    def fill(self, seconds: int, every: int, value=None, start: int = START) -> int:
        """Samples up to `seconds` later; `value` gives each one's CPU value."""
        for offset in range(0, seconds, every):
            cpu = value(offset) if value else 10.0
            self.store.record({"cpu": cpu}, now=start + offset)
        return start + seconds

    def test_finished_buckets_are_rolled_up_with_average_and_peak(self):
        # 10 and 30 within the first five minutes.
        end = self.fill(300, 10, lambda offset: 30.0 if offset >= 150 else 10.0)
        self.assertEqual(self.stored(300), [])
        self.store.record({"cpu": 50.0}, now=end)
        self.assertEqual(self.stored(300), [(START, 20.0, 30.0)])

    def test_the_unfinished_bucket_is_not_rolled_up_yet(self):
        self.store.record({"cpu": 10.0}, now=START)
        self.store.record({"cpu": 20.0}, now=START + 299)
        self.assertEqual(self.stored(300), [])

    def test_an_hour_is_rolled_up_from_its_five_minute_buckets(self):
        end = self.fill(3600, 60, lambda offset: 80.0 if offset >= 3300 else 20.0)
        self.store.record({"cpu": 50.0}, now=end)
        ((bucket, average, peak),) = self.stored(3600)
        self.assertEqual(bucket, START)
        self.assertEqual(peak, 80.0)
        self.assertEqual(average, 25.0)

    def test_nothing_is_rolled_up_twice(self):
        self.store.record({"cpu": 10.0}, now=START)
        self.store.record({"cpu": 20.0}, now=START + 300)
        self.store.record({"cpu": 30.0}, now=START + 600)
        self.assertEqual(self.stored(300), [(START, 10.0, 10.0), (START + 300, 20.0, 20.0)])

    def test_samples_from_before_a_restart_are_rolled_up_afterwards(self):
        self.store.record({"cpu": 10.0}, now=START)
        self.store.close()
        self.store = HistoryStore(self.path)
        self.addCleanup(self.store.close)
        self.store.record({"cpu": 20.0}, now=START + 10 * DAY)
        self.assertEqual(self.stored(300), [(START, 10.0, 10.0)])
        # The fine sample is gone by now: the coarse tiers are all that is left of it.
        self.assertEqual([row[0] for row in self.stored(10)], [START + 10 * DAY])

    def test_each_tier_is_pruned_after_its_time(self):
        self.store.record({"cpu": 10.0}, now=START)
        self.store.record({"cpu": 20.0}, now=START + DAY + 600)
        self.assertEqual([row[0] for row in self.stored(10)], [START + DAY + 600])
        self.assertEqual(self.stored(300)[0][0], START)
        self.store.record({"cpu": 30.0}, now=START + 31 * DAY)
        self.assertNotIn(START, [row[0] for row in self.stored(300)])
        self.assertEqual(self.stored(3600)[0][0], START)
        self.store.record({"cpu": 40.0}, now=START + 366 * DAY)
        self.assertNotIn(START, [row[0] for row in self.stored(3600)])

    def test_what_a_wrong_clock_left_in_the_future_goes_away(self):
        self.store.record({"cpu": 10.0}, now=START + 10 * DAY)
        self.store.close()
        self.store = HistoryStore(self.path)
        self.addCleanup(self.store.close)
        self.store.record({"cpu": 20.0}, now=START)
        self.assertEqual(self.stored(10), [(START, 20.0, 20.0)])

    def test_the_file_stays_small_when_the_clock_goes_back(self):
        self.store.record({"cpu": 10.0}, now=START + 10 * DAY)
        self.store.record({"cpu": 20.0}, now=START + 10 * DAY + 300)
        self.store.record({"cpu": 30.0}, now=START)
        self.store.record({"cpu": 40.0}, now=START + 300)
        self.assertEqual(self.stored(300)[-1], (START, 30.0, 30.0))


class TestFile(StoreTestCase):
    def test_the_file_and_its_directory_belong_to_the_owner_alone(self):
        self.store.record({"cpu": 1.0}, now=START)
        for path in self.path.parent.iterdir():
            with self.subTest(path=path.name):
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.path.parent.stat().st_mode), 0o700)

    def test_wider_rights_of_an_existing_file_are_narrowed(self):
        self.store.close()
        self.path.chmod(0o644)
        self.store = HistoryStore(self.path)
        self.addCleanup(self.store.close)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)

    def test_a_symlink_in_place_of_the_file_is_refused(self):
        target = self.path.parent / "target"
        target.write_text("precious")
        link = self.path.parent / "link.sqlite3"
        link.symlink_to(target)
        with self.assertRaises(OSError):
            HistoryStore(link)
        self.assertEqual(target.read_text(), "precious")

    def test_a_file_of_a_newer_version_is_left_alone(self):
        self.store.close()
        db = sqlite3.connect(self.path)
        db.execute(f"PRAGMA user_version={history.SCHEMA_VERSION + 1}")
        db.close()
        with self.assertRaises(HistoryError):
            HistoryStore(self.path)
        db = sqlite3.connect(self.path)
        self.addCleanup(db.close)
        self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0],
                         history.SCHEMA_VERSION + 1)
        self.store = HistoryStore(self.path.with_name("other.sqlite3"))
        self.addCleanup(self.store.close)

    def test_clear_removes_the_values_from_the_file_too(self):
        marker = 123456.789
        self.store.record({"cpu": marker}, now=START)
        self.store.clear()
        self.assertEqual(self.store.query(60, now=START)["rows"], [])
        raw = b"".join(path.read_bytes() for path in self.path.parent.iterdir())
        self.assertNotIn(__import__("struct").pack(">d", marker), raw)

    def test_recording_goes_on_after_clear(self):
        self.store.record({"cpu": 1.0}, now=START)
        self.store.clear()
        self.store.record({"cpu": 2.0}, now=START + 10)
        self.assertEqual(column(self.store.query(60, now=START + 10), "cpu_avg"), [2.0])

    def test_reading_and_recording_from_several_threads_works(self):
        errors = []

        def work(base):
            try:
                for offset in range(30):
                    self.store.record({"cpu": 1.0}, now=base + offset * 10)
                    self.store.query(3600, now=base + offset * 10)
            except Exception as error:  # noqa: BLE001 (reported by the assertion below)
                errors.append(error)

        threads = [threading.Thread(target=work, args=(START + i * 1000,)) for i in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])


class TestDefaultPath(unittest.TestCase):
    def test_the_service_uses_its_state_directory(self):
        with mock.patch.dict(os.environ, {"STATE_DIRECTORY": "/var/lib/lintask:/other"}):
            self.assertEqual(default_path(), Path("/var/lib/lintask/history.sqlite3"))

    def test_a_user_uses_the_state_home(self):
        with mock.patch.dict(os.environ, {"XDG_STATE_HOME": "/state"}):
            os.environ.pop("STATE_DIRECTORY", None)
            self.assertEqual(default_path(), Path("/state/Lintask/history.sqlite3"))


class TestChecks(unittest.TestCase):
    def payload(self, **changes) -> dict:
        payload = {"seconds": 3600, "step": 10, "now": START, "columns": ["time", "cpu_avg"],
                   "rows": [[START, 1.5], [START + 10, None]]}
        payload.update(changes)
        return payload

    def test_range_query(self):
        self.assertEqual(parse_range_query("seconds=3600"), 3600)
        for query in ("", "seconds=", "seconds=59", f"seconds={MAX_RANGE_SECONDS + 1}",
                      "seconds=-60", "seconds=1e3", "seconds=3600&x=1", "x=1&seconds=3600",
                      "seconds=٣٦٠٠", "seconds=99999999999999"):
            with self.subTest(query=query), self.assertRaises(ValueError):
                parse_range_query(query)

    def test_range_limits(self):
        self.assertEqual(check_range(MAX_RANGE_SECONDS), MAX_RANGE_SECONDS)
        with self.assertRaises(ValueError):
            check_range(0)

    def test_a_good_answer_passes(self):
        self.assertEqual(validate_payload(self.payload()), self.payload())

    def test_a_bad_answer_is_refused(self):
        huge = 10.0 ** 300
        cases = {
            "no object": [],
            "columns missing": self.payload(columns=None),
            "first column": self.payload(columns=["cpu_avg", "time"]),
            "column type": self.payload(columns=["time", 1]),
            "step zero": self.payload(step=0),
            "step text": self.payload(step="10"),
            "step boolean": self.payload(step=True),
            "now infinite": self.payload(now=float("inf")),
            "now far away": self.payload(now=huge),
            "now negative": self.payload(now=-1),
            "seconds zero": self.payload(seconds=0),
            "seconds too many": self.payload(seconds=MAX_RANGE_SECONDS + 1),
            "rows missing": self.payload(rows=None),
            "too many rows": self.payload(rows=[[START, 1.0]] * (2 * MAX_POINTS + 1)),
            "row type": self.payload(rows=[1]),
            "row length": self.payload(rows=[[START]]),
            "time empty": self.payload(rows=[[None, 1.0]]),
            "time far away": self.payload(rows=[[huge, 1.0]]),
            "value text": self.payload(rows=[[START, "1"]]),
            "value not finite": self.payload(rows=[[START, float("nan")]]),
            "value absurd": self.payload(rows=[[START, huge]]),
        }
        for name, payload in cases.items():
            with self.subTest(name), self.assertRaises(ValueError):
                validate_payload(payload)


class TestSampler(unittest.TestCase):
    def test_the_first_call_only_sets_the_starting_point(self):
        sampler = MetricSampler()
        with mock.patch.object(MetricSampler, "_cpu_temperature", return_value=50.0), \
                mock.patch.object(MetricSampler, "_poll_gpu", return_value={"percent": 7}):
            self.assertIsNone(sampler.sample())
            values = sampler.sample()
        self.assertEqual(set(values), set(history.METRICS))
        self.assertEqual(values["cpu_temp"], 50.0)
        self.assertEqual(values["gpu"], 7)
        self.assertIsNone(values["gpu_temp"])
        self.assertGreater(values["memory"], 0)

    def test_rates(self):
        self.assertEqual(MetricSampler._rate(100, 300, 10.0), 20.0)
        # A counter that was reset must not show up as a huge or negative rate.
        self.assertIsNone(MetricSampler._rate(300, 100, 10.0))
        self.assertIsNone(MetricSampler._rate(None, 100, 10.0))
        self.assertIsNone(MetricSampler._rate(100, None, 10.0))
        self.assertIsNone(MetricSampler._rate(100, 300, 0.0))


class FakeSampler:
    def __init__(self, answers=None):
        self.answers = list(answers or [])
        self.done = threading.Event()

    def sample(self):
        if not self.answers:
            self.done.set()
            return None
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


class TestRecorder(StoreTestCase):
    def run_recorder(self, sampler) -> str:
        output = io.StringIO()
        with contextlib.redirect_stderr(output):
            recorder = HistoryRecorder(self.store, sampler, interval=0.01)
            recorder.start()
            self.assertTrue(sampler.done.wait(10))
            recorder.stop()
        self.assertFalse(recorder.is_alive())
        return output.getvalue()

    def test_it_records_what_the_sampler_reads(self):
        self.run_recorder(FakeSampler([None, {"cpu": 5.0}]))
        self.assertEqual(column(self.store.query(60), "cpu_avg"), [5.0])

    def test_failures_are_reported_once_and_do_not_end_it(self):
        error = OSError("sensor gone")
        errors = self.run_recorder(FakeSampler([error, error, error, {"cpu": 5.0}]))
        self.assertEqual(errors.count("sensor gone"), 1)
        self.assertEqual(column(self.store.query(60), "cpu_avg"), [5.0])

    def test_a_failure_after_a_recovery_is_reported_again(self):
        error = OSError("sensor gone")
        errors = self.run_recorder(FakeSampler([error, {"cpu": 5.0}, error]))
        self.assertEqual(errors.count("sensor gone"), 2)


class TestService(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)

    def service(self, recording, path=None) -> HistoryService:
        service = HistoryService(recording, path or self.directory / "history.sqlite3",
                                 sampler_factory=FakeSampler)
        self.addCleanup(service.shutdown)
        return service

    def test_recording_can_be_switched(self):
        service = self.service(False)
        self.assertFalse(service.recording)
        service.set_recording(True)
        self.assertTrue(service.recording)
        service.set_recording(True)
        service.set_recording(False)
        self.assertFalse(service.recording)

    def test_an_unusable_path_does_not_stop_anything(self):
        blocker = self.directory / "file"
        blocker.write_text("")
        output = io.StringIO()
        with contextlib.redirect_stderr(output):
            service = self.service(True, blocker / "history.sqlite3")
        self.assertIsNone(service.store)
        self.assertFalse(service.recording)
        self.assertIn("Lintask history", output.getvalue())

    def test_a_file_that_is_no_database_does_not_stop_anything(self):
        path = self.directory / "history.sqlite3"
        path.write_bytes(b"no database" * 1000)
        with contextlib.redirect_stderr(io.StringIO()):
            service = self.service(True, path)
        self.assertIsNone(service.store)
        self.assertEqual(path.read_bytes(), b"no database" * 1000)

    def test_shutdown_stops_recording_and_can_be_repeated(self):
        service = self.service(True)
        service.shutdown()
        self.assertFalse(service.recording)
        self.assertIsNone(service.store)
        service.shutdown()
        service.set_recording(True)
        self.assertFalse(service.recording)


class ServerTestCase(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store = HistoryStore(Path(directory.name) / "history.sqlite3")
        self.addCleanup(self.store.close)
        self.port = self.start_server(self.store)

    def start_server(self, store) -> int:
        handler = type("TestHandler", (MonitoringHandler,), {"token": TOKEN, "history": store})
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server.server_address[1]

    def get(self, path, token=TOKEN, port=None):
        connection = http.client.HTTPConnection("127.0.0.1", port or self.port, timeout=10)
        self.addCleanup(connection.close)
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        connection.request("GET", path, headers=headers)
        response = connection.getresponse()
        return response.status, json.loads(response.read())


class TestEndpoint(ServerTestCase):
    def test_the_answer_is_what_the_client_expects(self):
        self.store.record({"cpu": 7.0})
        status, payload = self.get("/api/v1/history?seconds=3600")
        self.assertEqual(status, 200)
        validate_payload(payload)
        self.assertEqual(column(payload, "cpu_avg"), [7.0])

    def test_nothing_comes_without_the_token(self):
        self.store.record({"cpu": 7.0})
        for token in (None, "wrong"):
            with self.subTest(token=token):
                status, payload = self.get("/api/v1/history?seconds=3600", token=token)
                self.assertEqual(status, 401)
                self.assertEqual(payload, {"error": "unauthorized"})

    def test_the_token_is_checked_before_everything_else(self):
        # Otherwise a stranger could find out whether the server records at all.
        port = self.start_server(None)
        self.assertEqual(self.get("/api/v1/history?seconds=3600", None, port)[0], 401)
        self.assertEqual(self.get("/api/v1/history?seconds=1", None)[0], 401)

    def test_a_server_without_history_says_so(self):
        port = self.start_server(None)
        status, payload = self.get("/api/v1/history?seconds=3600", port=port)
        self.assertEqual(status, 503)
        self.assertIn("error", payload)

    def test_invalid_ranges_are_refused(self):
        for query in ("", "?", "?seconds=", "?seconds=59", "?seconds=abc",
                      "?seconds=3600&seconds=60", f"?seconds={MAX_RANGE_SECONDS + 1}"):
            with self.subTest(query=query):
                self.assertEqual(self.get("/api/v1/history" + query)[0], 400)

    def test_a_query_does_not_open_other_paths(self):
        self.assertEqual(self.get("/api/v1/historyx?seconds=3600")[0], 404)
        self.assertEqual(self.get("/api/v1/snapshot?seconds=3600")[0], 404)

    def test_a_broken_database_does_not_reach_the_client(self):
        self.store.close()
        with contextlib.redirect_stderr(io.StringIO()) as errors:
            status, payload = self.get("/api/v1/history?seconds=3600")
        self.assertEqual(status, 500)
        self.assertNotIn(str(self.store.path), json.dumps(payload))
        self.assertIn("Error", errors.getvalue())

    def test_answers_are_small_enough_for_the_client(self):
        from app.remote_client import MAX_HISTORY_BYTES
        row = {metric: 123456789012.25 for metric in history.METRICS}
        for offset in range(MAX_POINTS):
            self.store._db.execute(
                f"INSERT INTO samples (tier, bucket, {history._VALUE_COLUMNS}) "
                f"VALUES (?, ?, {', '.join('?' * (len(COLUMNS) - 1))})",
                (10, int(time.time()) // 10 * 10 - offset * 10,
                 *[row[metric] for metric in history.METRICS for _ in range(2)]))
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        self.addCleanup(connection.close)
        connection.request("GET", "/api/v1/history?seconds=7200",
                           headers={"Authorization": f"Bearer {TOKEN}"})
        body = connection.getresponse().read()
        self.assertEqual(len(json.loads(body)["rows"]), 720)
        self.assertLess(len(body), MAX_HISTORY_BYTES)


class TestServerArguments(unittest.TestCase):
    def test_no_history_is_passed_on(self):
        from app import remote_server
        with mock.patch.object(remote_server, "run_server", return_value=0) as run:
            remote_server.server_from_args(["--token", "x" * 32, "--no-history"])
            self.assertFalse(run.call_args.kwargs["record_history"])
            remote_server.server_from_args(["--token", "x" * 32])
            self.assertTrue(run.call_args.kwargs["record_history"])


@unittest.skipUnless(HAS_QT, "PySide6 fehlt")
class TestFetchHistory(ServerTestCase):
    def setUp(self):
        super().setUp()
        set_language("en")
        self.addCleanup(set_language, "system")

    def fetch(self, port=None, token=TOKEN):
        from app.remote_client import fetch_history
        return fetch_history("127.0.0.1", port or self.port, token, 3600)

    def test_it_reads_a_real_server(self):
        self.store.record({"cpu": 7.0})
        self.assertEqual(column(self.fetch(), "cpu_avg"), [7.0])

    def test_a_wrong_token_is_explained(self):
        with self.assertRaisesRegex(ValueError, "token"):
            self.fetch(token="wrong")

    def test_a_server_that_does_not_record_is_explained(self):
        with self.assertRaisesRegex(ValueError, "does not record"):
            self.fetch(port=self.start_server(None))

    def answering(self, answer):
        from tests.test_remote_client import RecordingServer
        return RecordingServer(self, answer).port

    def test_an_old_server_is_explained(self):
        def answer(handler):
            handler.send_response(404)
            handler.send_header("Content-Length", "0")
            handler.end_headers()
        with self.assertRaisesRegex(ValueError, "too old"):
            self.fetch(port=self.answering(answer))

    def test_a_bad_answer_is_refused(self):
        from tests.test_remote_client import answer_json
        for payload in ({"columns": ["time"]}, [], "x"):
            with self.subTest(payload=payload), \
                    self.assertRaisesRegex(ValueError, "invalid history"):
                self.fetch(port=self.answering(answer_json(payload)))

    def test_an_answer_that_is_no_json_is_refused(self):
        def answer(handler):
            body = b"\xff not json"
            handler.send_response(200)
            handler.send_header("Content-Length", str(len(body)))
            handler.end_headers()
            handler.wfile.write(body)
        with self.assertRaisesRegex(ValueError, "invalid history"):
            self.fetch(port=self.answering(answer))

    def test_a_giant_answer_is_not_read_to_its_end(self):
        from app.remote_client import MAX_HISTORY_BYTES

        def answer(handler):
            handler.send_response(200)
            handler.send_header("Content-Length", str(MAX_HISTORY_BYTES + 2))
            handler.end_headers()
            with contextlib.suppress(OSError):
                handler.wfile.write(b" " * (MAX_HISTORY_BYTES + 2))
        with self.assertRaisesRegex(ValueError, "invalid history"):
            self.fetch(port=self.answering(answer))


class TestChartHelpers(unittest.TestCase):
    @unittest.skipUnless(HAS_QT, "PySide6 fehlt")
    def test_nice_maximum(self):
        from widgets.history_chart import nice_maximum
        self.assertEqual(nice_maximum(0), 1.0)
        self.assertEqual(nice_maximum(-5), 1.0)
        self.assertEqual(nice_maximum(1), 1)
        self.assertEqual(nice_maximum(1.5), 2)
        self.assertEqual(nice_maximum(45), 60)
        self.assertEqual(nice_maximum(900), 1000)
        self.assertEqual(nice_maximum(1e18), 1e18)
        self.assertGreaterEqual(nice_maximum(0.03), 0.03)

    @unittest.skipUnless(HAS_QT, "PySide6 fehlt")
    def test_segments_split_at_gaps_and_missing_values(self):
        from widgets.history_chart import segments
        times = [0, 10, 20, 100, 110, 120, 130]
        values = [1, 2, 3, 4, None, 6, 7]
        self.assertEqual(segments(times, values, 10), [[0, 1, 2], [3], [5, 6]])
        self.assertEqual(segments([], [], 10), [])
        self.assertEqual(segments([0, 10], [None, None], 10), [])

    @unittest.skipUnless(HAS_QT, "PySide6 fehlt")
    def test_time_ticks_are_round_and_not_too_many(self):
        from widgets.history_chart import time_ticks
        for span in (60, 3600, DAY, 7 * DAY, 30 * DAY, 365 * DAY):
            for max_ticks in (0, 1, 8, 40):
                with self.subTest(span=span, max_ticks=max_ticks):
                    ticks = time_ticks(START, START + span, max_ticks)
                    self.assertLessEqual(len(ticks), max(max_ticks, 1) + 5)
                    self.assertTrue(all(START <= tick <= START + span for tick in ticks))
                    self.assertEqual(ticks, sorted(ticks))


@unittest.skipUnless(HAS_QT, "PySide6 fehlt")
class TestTimeTicksAcrossClockChanges(unittest.TestCase):
    def setUp(self):
        previous = os.environ.get("TZ")

        def restore():
            if previous is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = previous
            time.tzset()

        self.addCleanup(restore)
        os.environ["TZ"] = "Europe/Berlin"
        time.tzset()

    def local_midnights(self, first_day, last_day, month):
        from widgets.history_chart import time_ticks
        start = time.mktime((2026, month, first_day, 12, 0, 0, 0, 0, -1))
        end = time.mktime((2026, month, last_day, 12, 0, 0, 0, 0, -1))
        return [time.localtime(tick) for tick in time_ticks(start, end, 10)]

    def test_daily_ticks_stay_on_midnight_when_the_clock_goes_back(self):
        ticks = self.local_midnights(23, 29, 10)  # 25 October 2026 has 25 hours
        self.assertEqual([tick.tm_mday for tick in ticks], [24, 25, 26, 27, 28, 29])
        self.assertEqual({tick.tm_hour for tick in ticks}, {0})

    def test_daily_ticks_stay_on_midnight_when_the_clock_goes_forward(self):
        ticks = self.local_midnights(26, 31, 3)  # 29 March 2026 has 23 hours
        self.assertEqual([tick.tm_mday for tick in ticks], [27, 28, 29, 30, 31])
        self.assertEqual({tick.tm_hour for tick in ticks}, {0})


class TestChart(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def chart(self):
        from widgets.history_chart import ChartSeries, HistoryChart
        chart = HistoryChart("CPU", lambda value: f"{value:.0f}%", 100.0)
        chart.set_theme(False, "#ffffff", {"cpu": "#ff0000", "memory": "#0000ff"})
        chart.resize(800, 200)
        # Two runs with nothing in between.
        times = [START + offset for offset in (0, 10, 20, 900, 910, 920)]
        chart.set_data(START, START + 1000, 10, times,
                       [ChartSeries("Usage", "cpu", [50.0] * 6, [60.0] * 6)])
        return chart

    @staticmethod
    def red_in_column(chart, moment) -> bool:
        plot = chart._plot_rect()
        image = chart.grab().toImage()
        x = round(chart._x(plot, moment))
        y = round(chart._y(plot, 50.0))
        colors = [image.pixelColor(x, y + offset) for offset in (-1, 0, 1)]
        return any(color.red() > 200 and color.green() < 120 for color in colors)

    def test_a_line_runs_where_values_are_and_not_across_a_gap(self):
        chart = self.chart()
        self.assertTrue(self.red_in_column(chart, START + 15))
        self.assertFalse(self.red_in_column(chart, START + 450))

    def test_the_mouse_finds_values_only_where_something_was_recorded(self):
        chart = self.chart()
        plot = chart._plot_rect()
        self.assertEqual(chart._index_at(chart._x(plot, START + 11)), 1)
        self.assertIsNone(chart._index_at(chart._x(plot, START + 450)))
        self.assertIsNone(chart._index_at(0))

    def test_every_shape_of_data_can_be_drawn(self):
        from widgets.history_chart import ChartSeries
        chart = self.chart()
        cases = {
            "empty": ([], []),
            "one point": ([START], [ChartSeries("A", "cpu", [5.0], [5.0])]),
            "peak missing": ([START, START + 10],
                             [ChartSeries("A", "cpu", [5.0, 6.0], [None, None])]),
            "above the top": ([START, START + 10],
                              [ChartSeries("A", "cpu", [500.0, 1e18], [500.0, 1e18])]),
            "two series": ([START, START + 10],
                           [ChartSeries("A", "cpu", [1.0, 2.0], [1.0, 2.0]),
                            ChartSeries("B", "unknown", [None, 2.0], [None, 2.0])]),
        }
        for name, (times, series) in cases.items():
            with self.subTest(name):
                chart.set_data(START, START + 100, 10, times, series)
                chart._hover = len(times) - 1 if times else None
                self.assertFalse(chart.grab().isNull())

    def test_a_chart_without_room_can_still_be_drawn(self):
        chart = self.chart()
        chart.setMinimumSize(1, 1)
        chart.resize(1, 1)
        self.assertFalse(chart.grab().isNull())


@unittest.skipUnless(HAS_QT, "PySide6 fehlt")
class TestPage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        set_language("en")
        self.addCleanup(set_language, "system")
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "history.sqlite3"
        self.service = HistoryService(False, self.path, sampler_factory=FakeSampler)
        self.addCleanup(self.service.shutdown)
        self.settings = SimpleNamespace(history_enabled=False)

    def page(self):
        from pages.history_page import HistoryPage
        page = HistoryPage(self.settings, self.service)
        page.resize(1000, 700)
        self.addCleanup(page.shutdown)
        return page

    def wait_for(self, condition) -> None:
        deadline = time.monotonic() + 10
        while not condition():
            self.assertLess(time.monotonic(), deadline, "timed out")
            self.app.processEvents()
            time.sleep(0.005)

    def visible_titles(self, page) -> list:
        return [chart.title for chart, _specs in page.charts if not chart.isHidden()]

    def test_it_shows_what_was_recorded(self):
        self.service.store.record({"cpu": 7.0, "memory": 30.0})
        page = self.page()
        page.show()
        self.wait_for(lambda: self.visible_titles(page))
        self.assertEqual(self.visible_titles(page), ["CPU", "Memory"])
        self.assertIn("switched off", page.status_label.text())
        page.close()

    def test_an_empty_history_is_explained(self):
        page = self.page()
        page.show()
        self.wait_for(lambda: page.status_label.text())
        self.assertIn("Nothing recorded", page.status_label.text())
        self.assertEqual(self.visible_titles(page), [])
        page.close()

    def test_it_only_loads_while_it_is_visible(self):
        page = self.page()
        with mock.patch("pages.history_page.HistoryLoader") as loader:
            page.reload()
        loader.assert_not_called()

    def test_an_unusable_file_is_explained(self):
        self.service.shutdown()
        page = self.page()
        page.show()
        self.assertIn("can't be used", page.status_label.text())
        self.assertFalse(page.record_check.isEnabled())
        self.assertFalse(page.clear_btn.isEnabled())
        page.close()

    def test_a_server_that_cannot_be_reached_is_explained(self):
        page = self.page()
        page.show()
        self.wait_for(lambda: page._loader is None)
        with mock.patch("pages.history_page.fetch_history", side_effect=OSError("refused")):
            page.set_remote_connection(True, "192.0.2.1", 8765, "token")
            self.wait_for(lambda: "refused" in page.status_label.text())
        self.assertIn("192.0.2.1", page.source_label.text())
        # The switch still belongs to this computer, deleting would not reach the server.
        self.assertTrue(page.record_check.isEnabled())
        self.assertFalse(page.clear_btn.isEnabled())
        page.close()

    def test_a_late_answer_of_an_old_request_is_ignored(self):
        page = self.page()
        page._request_id = 5
        page._on_loaded(4, None, "old error")
        self.assertEqual(page.status_label.text(), "")

    def test_the_series_are_looked_up_by_name(self):
        from pages.history_page import CHARTS, series_from_payload
        specs = next(specs for title, _f, _m, specs in CHARTS if title == "Memory")
        # Swap is missing, and a column this version does not know is ignored.
        payload = {"columns": ["time", "future_avg", "memory_max", "memory_avg"],
                   "rows": [[START, 9.0, 80.0, 70.0]]}
        times, series = series_from_payload(payload, specs)
        self.assertEqual(times, [START])
        self.assertEqual([(entry.avg, entry.peak) for entry in series], [([70.0], [80.0])])

    def test_recording_is_switched_from_the_page(self):
        page = self.page()
        page.record_check.setChecked(True)
        self.assertTrue(self.service.recording)
        self.assertTrue(self.settings.history_enabled)
        page.record_check.setChecked(False)
        self.assertFalse(self.service.recording)
        self.assertFalse(self.settings.history_enabled)

    def test_deleting_asks_first(self):
        from PySide6.QtWidgets import QMessageBox
        self.service.store.record({"cpu": 7.0})
        page = self.page()
        with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.No):
            page.clear_btn.click()
        self.assertEqual(len(self.service.store.query(60)["rows"]), 1)
        with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
            page.clear_btn.click()
        self.assertEqual(self.service.store.query(60)["rows"], [])


if __name__ == "__main__":
    unittest.main()
