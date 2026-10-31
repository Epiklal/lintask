"""Persistent history of the system's totals, kept in a small SQLite file.

Free of Qt, because the headless server records with it as well. Each file describes only
the computer it lives on: the desktop records itself, and the history of a server comes
from the server's own file through its API. Only totals are stored, no process names.
"""
from __future__ import annotations

import math
import os
import re
import sqlite3
import sys
import threading
import time
from pathlib import Path

import psutil

SAMPLE_SECONDS = 10
# (seconds per bucket, seconds it is kept). Each tier is rolled up into the next one.
TIERS = ((SAMPLE_SECONDS, 24 * 3600), (300, 30 * 24 * 3600), (3600, 365 * 24 * 3600))
ROLLUP_SECONDS = TIERS[1][0]
MIN_RANGE_SECONDS = 60
MAX_RANGE_SECONDS = TIERS[-1][1]
# A chart is not wider than this in pixels, so more points would only cost time.
MAX_POINTS = 720
SCHEMA_VERSION = 1
DB_NAME = "history.sqlite3"

# Column names of the table: SQL is built from this tuple, never from outside input.
METRICS = (
    "cpu",         # percent
    "memory",      # percent
    "swap",        # percent
    "disk_used",   # percent of the root file system
    "disk_read",   # bytes per second
    "disk_write",  # bytes per second
    "net_recv",    # bytes per second
    "net_sent",    # bytes per second
    "cpu_temp",    # degrees Celsius
    "gpu",         # percent
    "gpu_temp",    # degrees Celsius
)
COLUMNS = ("time", *(f"{metric}_{kind}" for metric in METRICS for kind in ("avg", "max")))
_VALUE_COLUMNS = ", ".join(COLUMNS[1:])
_AGGREGATES = ", ".join(
    f"AVG({metric}_avg), MAX({metric}_max)" for metric in METRICS)

_QUERY_RE = re.compile(r"seconds=([0-9]{1,10})")
_MAX_MOMENT = 2 ** 37  # the year 6325
_MAX_VALUE = 1e18


class HistoryError(Exception):
    """The history file can't be used by this version of the program."""


def default_path() -> Path:
    """The service's own state directory, otherwise the user's."""
    service_directory = os.environ.get("STATE_DIRECTORY", "").split(":")[0]
    if service_directory:
        return Path(service_directory) / DB_NAME
    state_home = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(state_home) / "Lintask" / DB_NAME


def _finite(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _is_moment(value) -> bool:
    return _finite(value) is not None and 0 <= value <= _MAX_MOMENT


def check_range(seconds: int) -> int:
    if not MIN_RANGE_SECONDS <= seconds <= MAX_RANGE_SECONDS:
        raise ValueError(f"range must be {MIN_RANGE_SECONDS} to {MAX_RANGE_SECONDS} seconds")
    return seconds


def parse_range_query(query: str) -> int:
    """The query string of a history request, strict because it comes from the network."""
    match = _QUERY_RE.fullmatch(query)
    if not match:
        raise ValueError("expected seconds=<number>")
    return check_range(int(match.group(1)))


def validate_payload(payload) -> dict:
    """Checks an answer of a server before anything draws it; raises ValueError."""
    if not isinstance(payload, dict):
        raise ValueError("history must be a JSON object")
    columns, rows = payload.get("columns"), payload.get("rows")
    step, now, seconds = payload.get("step"), payload.get("now"), payload.get("seconds")
    if not isinstance(columns, list) or not columns or columns[0] != "time" \
            or not all(isinstance(column, str) for column in columns):
        raise ValueError("invalid history columns")
    # The bounds keep the drawing safe: the axis steps through the range, and localtime()
    # and the number formats raise on absurd values.
    if _finite(step) is None or step <= 0 or not _is_moment(now) \
            or _finite(seconds) is None or not 0 < seconds <= MAX_RANGE_SECONDS:
        raise ValueError("invalid history range")
    if not isinstance(rows, list) or len(rows) > 2 * MAX_POINTS:
        raise ValueError("invalid history rows")
    for row in rows:
        if not isinstance(row, list) or len(row) != len(columns) or not _is_moment(row[0]):
            raise ValueError("invalid history row")
        for value in row[1:]:
            if value is not None and (_finite(value) is None or abs(value) > _MAX_VALUE):
                raise ValueError("invalid history value")
    return payload


class HistoryStore:
    """The SQLite file. One connection behind a lock: the recorder writes from its own
    thread while the page or the server's request threads read."""

    def __init__(self, path: str | os.PathLike | None = None):
        self.path = Path(path) if path else default_path()
        self._lock = threading.Lock()
        self._last_rollup: int | None = None
        self._db = self._open()

    def _open(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        # Created here, so that it never exists with wider rights than the owner's. SQLite
        # gives its -wal and -shm files the rights of this file.
        descriptor = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC,
                             0o600)
        try:
            os.fchmod(descriptor, 0o600)
        finally:
            os.close(descriptor)
        db = sqlite3.connect(self.path, timeout=5, check_same_thread=False)
        try:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                # Written by a newer Lintask: leave it alone instead of breaking it.
                raise HistoryError(f"{self.path} has the newer format {version}")
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=NORMAL")
            columns = ", ".join(f"{name} REAL" for name in COLUMNS[1:])
            with db:
                db.execute(f"CREATE TABLE IF NOT EXISTS samples (tier INTEGER NOT NULL, "
                           f"bucket INTEGER NOT NULL, {columns}, PRIMARY KEY (tier, bucket)) "
                           f"WITHOUT ROWID")
                db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        except BaseException:
            db.close()
            raise
        return db

    def record(self, values: dict, now: float | None = None) -> None:
        """Stores one sample; a metric that is missing or not a finite number stays empty."""
        now = int(time.time() if now is None else now)
        row = [_finite(values.get(metric)) for metric in METRICS]
        if all(value is None for value in row):
            return
        cells = [value for value in row for _ in ("avg", "max")]
        tier = TIERS[0][0]
        marks = ", ".join("?" * (len(cells) + 2))
        rollup = now // ROLLUP_SECONDS
        with self._lock, self._db:
            self._db.execute(
                f"INSERT OR REPLACE INTO samples (tier, bucket, {_VALUE_COLUMNS}) "
                f"VALUES ({marks})", (tier, now // tier * tier, *cells))
            if rollup != self._last_rollup:
                self._roll_up(now)
                self._prune(now)
        self._last_rollup = rollup

    def _roll_up(self, now: int) -> None:
        for (fine, _), (coarse, _) in zip(TIERS, TIERS[1:]):
            newest = self._db.execute("SELECT MAX(bucket) FROM samples WHERE tier=?",
                                      (coarse,)).fetchone()[0]
            until = now // coarse * coarse
            # Only finished buckets are rolled up, so the newest one needs no second look.
            since = 0 if newest is None else newest + coarse
            if since > until:  # the clock was set back
                since = until - coarse
            self._db.execute(
                f"INSERT OR REPLACE INTO samples (tier, bucket, {_VALUE_COLUMNS}) "
                f"SELECT ?, (bucket / ?) * ?, {_AGGREGATES} FROM samples "
                f"WHERE tier=? AND bucket>=? AND bucket<? GROUP BY 2",
                (coarse, coarse, coarse, fine, since, until))

    def _prune(self, now: int) -> None:
        for tier, keep in TIERS:
            # Buckets from the future are what a wrong clock left behind.
            self._db.execute("DELETE FROM samples WHERE tier=? AND (bucket<? OR bucket>?)",
                             (tier, now - keep, now + tier))

    def query(self, seconds: int, now: float | None = None) -> dict:
        """The last `seconds`, at most MAX_POINTS rows, oldest first. Empty buckets are
        left out: the gap in the times is what shows that nothing was recorded."""
        check_range(seconds)
        now = int(time.time() if now is None else now)
        tier = next(size for size, keep in TIERS if keep >= seconds)
        step = math.ceil(seconds / MAX_POINTS / tier) * tier
        with self._lock:
            rows = self._db.execute(
                f"SELECT (bucket / ?) * ? AS slot, {_AGGREGATES} FROM samples "
                f"WHERE tier=? AND bucket>=? AND bucket<=? GROUP BY slot ORDER BY slot",
                (step, step, tier, now - seconds, now)).fetchall()
        return {
            "seconds": seconds, "step": step, "now": now, "columns": list(COLUMNS),
            "rows": [[row[0], *(None if value is None else round(value, 2)
                                for value in row[1:])] for row in rows],
        }

    def clear(self) -> None:
        """Removes everything, including what deleting leaves behind in the file."""
        with self._lock:
            with self._db:
                self._db.execute("DELETE FROM samples")
            self._db.execute("VACUUM")
            self._db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self._last_rollup = None

    def close(self) -> None:
        with self._lock:
            self._db.close()


class MetricSampler:
    """Reads one sample. Keeps its own counters, so that it does not disturb the rates the
    pages calculate, and has to run on one thread: psutil's cpu_percent measures since the
    previous call of the same thread."""

    def __init__(self):
        self._gpu = None
        self._previous: tuple[float, tuple] | None = None

    def sample(self) -> dict | None:
        """The current values; None on the first call, which only sets the starting point."""
        cpu = psutil.cpu_percent(interval=None)
        moment = time.monotonic()
        disk_io = psutil.disk_io_counters()
        net = psutil.net_io_counters()
        counters = (disk_io.read_bytes if disk_io else None,
                    disk_io.write_bytes if disk_io else None,
                    net.bytes_recv if net else None,
                    net.bytes_sent if net else None)
        previous, self._previous = self._previous, (moment, counters)
        if previous is None:
            return None
        elapsed = moment - previous[0]
        read, write, recv, sent = (
            self._rate(old, new, elapsed) for old, new in zip(previous[1], counters))
        swap = psutil.swap_memory()
        gpu = self._poll_gpu()
        return {
            "cpu": cpu,
            "memory": psutil.virtual_memory().percent,
            "swap": swap.percent if swap.total else None,
            "disk_used": psutil.disk_usage("/").percent,
            "disk_read": read, "disk_write": write,
            "net_recv": recv, "net_sent": sent,
            "cpu_temp": self._cpu_temperature(),
            "gpu": gpu.get("percent"), "gpu_temp": gpu.get("temp_c"),
        }

    @staticmethod
    def _rate(old: int | None, new: int | None, elapsed: float) -> float | None:
        # A counter that went down was reset, for example with a network device.
        if old is None or new is None or new < old or elapsed <= 0:
            return None
        return (new - old) / elapsed

    @staticmethod
    def _cpu_temperature() -> float | None:
        from app.system_info import get_cpu_temperature
        return get_cpu_temperature()

    def _poll_gpu(self) -> dict:
        from app.system_info import GpuSystemMonitor
        if self._gpu is None:
            self._gpu = GpuSystemMonitor()
        return self._gpu.poll() or {}


class HistoryRecorder(threading.Thread):
    """Records until stop(). Failures are reported once and never end the monitoring."""

    def __init__(self, store: HistoryStore, sampler=None, interval: float = SAMPLE_SECONDS):
        super().__init__(name="lintask-history", daemon=True)
        self._store = store
        self._sampler = sampler or MetricSampler()
        self._interval = interval
        self._stop_event = threading.Event()

    def run(self) -> None:
        reported = False
        while True:
            try:
                values = self._sampler.sample()
                if values is not None:
                    self._store.record(values)
                reported = False
            except Exception as error:  # a sensor or the disk: the next sample may work
                if not reported:
                    print(f"Lintask history: {error}", file=sys.stderr, flush=True)
                    reported = True
            if self._stop_event.wait(self._delay()):
                return

    def _delay(self) -> float:
        # On the clock's full intervals, so that two buckets don't get the same sample
        # and the first rates don't come from a fraction of a second.
        delay = self._interval - time.time() % self._interval
        return delay + self._interval if delay < self._interval / 10 else delay

    def stop(self) -> None:
        self._stop_event.set()
        if self.is_alive():
            self.join(2)


class HistoryService:
    """The store and its recorder. Without a usable file everything else keeps working:
    `store` stays None and there is simply no history."""

    def __init__(self, recording: bool = True, path: str | os.PathLike | None = None,
                 sampler_factory=MetricSampler):
        self._sampler_factory = sampler_factory
        self._recorder: HistoryRecorder | None = None
        self.store: HistoryStore | None = None
        try:
            self.store = HistoryStore(path)
        except (OSError, sqlite3.Error, HistoryError) as error:
            print(f"Lintask history: {error}", file=sys.stderr, flush=True)
        self.set_recording(recording)

    @property
    def recording(self) -> bool:
        return self._recorder is not None

    def set_recording(self, enabled: bool) -> None:
        if enabled and self._recorder is None and self.store is not None:
            self._recorder = HistoryRecorder(self.store, self._sampler_factory())
            self._recorder.start()
        elif not enabled and self._recorder is not None:
            self._recorder.stop()
            self._recorder = None

    def shutdown(self) -> None:
        self.set_recording(False)
        if self.store is not None:
            self.store.close()
            self.store = None
