"""Headless monitoring server for the desktop Task Manager client."""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
import secrets
import socket
import sqlite3
import subprocess
import threading
import time
import traceback
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from app.history import HistoryService, parse_range_query
from app.i18n import N_, language_override, tr

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8765
# Benchmark requests are tiny JSON objects; anything bigger is refused.
MAX_REQUEST_BYTES = 16 * 1024
MAX_BENCHMARK_SECONDS = 300
MAX_PRIME_LIMIT = 10_000_000
_BENCHMARK_LABELS = {"cpu": N_("CPU"), "memory": N_("Memory"), "gpu": N_("GPU"), "disk": N_("Disk")}
# Clients from before the language switch send no language and expect German.
_LEGACY_CLIENT_LANGUAGE = "de"
# Parallel clients share one collection instead of each starting their own.
SNAPSHOT_CACHE_SECONDS = 0.25
# Read instead of --token, because a command line is visible to every user in `ps`.
TOKEN_ENV = "LINTASK_SERVER_TOKEN"
MIN_TOKEN_LENGTH = 16


class BenchmarkBusyError(Exception):
    """Another benchmark is still running on this server."""


def make_benchmark_runner(list_disks, worker_class):
    """Returns the function that serves benchmark requests. One benchmark at a time;
    the disks and the worker are parameters so this works without Qt in the tests."""
    benchmark_lock = threading.Lock()

    def run_benchmark(request: dict) -> dict:
        with language_override(str(request.get("language", _LEGACY_CLIENT_LANGUAGE))):
            return _run_benchmark(request)

    def _run_benchmark(request: dict) -> dict:
        kind = request.get("kind")
        if kind not in _BENCHMARK_LABELS:
            raise ValueError(tr("Unknown benchmark"))
        # Clamp everything a client can send, so a request can't keep the server
        # busy for days or spawn thousands of threads.
        cpu_count = os.cpu_count() or 1
        cpu_threads = min(max(int(request.get("cpu_threads", 1)), 1), cpu_count)
        cpu_seconds = min(max(int(request.get("cpu_seconds", 30)), 1), MAX_BENCHMARK_SECONDS)
        cpu_max_prime = min(max(int(request.get("cpu_max_prime", 1_000_000)), 100),
                            MAX_PRIME_LIMIT)
        # The disk test writes a 256 MiB file: only into a mount point of a
        # physical disk, never into an arbitrary client-chosen directory.
        allowed_dirs = [mount for disk in list_disks()
                        for mount in disk.get("mountpoints") or []]
        disk_directory = request.get("disk_directory")
        if disk_directory not in allowed_dirs:
            if kind == "disk" and disk_directory:
                raise ValueError(tr("Target not allowed: {directory}", directory=disk_directory))
            disk_directory = allowed_dirs[0] if allowed_dirs else None
        if not benchmark_lock.acquire(blocking=False):
            raise BenchmarkBusyError(tr("A benchmark is already running on the server"))
        try:
            worker = worker_class(
                [kind], cpu_threads, cpu_seconds, cpu_max_prime, disk_directory)
            result, details = getattr(worker, f"_run_{kind}")()
        finally:
            benchmark_lock.release()
        return {"label": tr(_BENCHMARK_LABELS[kind]), "result": result, "details": details}

    return run_benchmark


def shared_snapshot(collect, max_age: float = SNAPSHOT_CACHE_SECONDS):
    """Returns `collect` behind one lock: the workers it uses keep state between calls and
    the server handles every request in its own thread. A failed collection is not kept."""
    lock = threading.Lock()
    cached = None
    collected_at = 0.0

    def snapshot() -> dict:
        nonlocal cached, collected_at
        with lock:
            if cached is None or time.monotonic() - collected_at >= max_age:
                cached = collect()
                collected_at = time.monotonic()
            return cached

    return snapshot


def startup_warnings(host: str, token: str | None) -> list[str]:
    warnings = []
    try:
        loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = host == "localhost"
    if not loopback:
        warnings.append(tr("WARNING: The connection is not encrypted. Anyone on the network path "
                           "can read the data and the access token. On untrusted networks start "
                           "with --host 127.0.0.1 and connect through an SSH tunnel."))
    if token and len(token) < MIN_TOKEN_LENGTH:
        warnings.append(tr("WARNING: The access token is shorter than {length} characters and "
                           "easy to guess.", length=MIN_TOKEN_LENGTH))
    return warnings


class MonitoringHandler(BaseHTTPRequestHandler):
    monitor: object
    snapshot: object
    token: str | None
    benchmark: object
    history: object = None
    # Slow or idle clients can't hold a server thread forever.
    timeout = 30

    def _authorized(self) -> bool:
        token = type(self).token
        if not token:
            return True  # only when started with --no-auth
        supplied = self.headers.get("Authorization", "")
        # Constant-time comparison, so the token can't be guessed byte by byte.
        return secrets.compare_digest(supplied.encode("utf-8", "replace"),
                                      f"Bearer {token}".encode("utf-8"))

    def _send_history(self, query: str) -> None:
        if not self._authorized():
            self._send_json({"error": "unauthorized"}, 401)
            return
        store = type(self).history
        if store is None:
            self._send_json({"error": N_("This server does not record a history")}, 503)
            return
        try:
            seconds = parse_range_query(query)
        except ValueError:
            self._send_json({"error": N_("Invalid history range")}, 400)
            return
        try:
            self._send_json(store.query(seconds))
        except sqlite3.Error:
            traceback.print_exc()
            self._send_json({"error": N_("Could not read the history")}, 500)

    def do_GET(self) -> None:  # noqa: N802 (HTTP handler override)
        path, _, query = self.path.partition("?")
        if path == "/api/v1/history":
            self._send_history(query)
            return
        if self.path != "/api/v1/snapshot":
            self._send_json({"error": "not found"}, 404)
            return
        if not self._authorized():
            self._send_json({"error": "unauthorized"}, 401)
            return
        try:
            snapshot = type(self).snapshot()
        except Exception:
            # The cause goes to the server's log, not to the client.
            traceback.print_exc()
            self._send_json({"error": N_("Could not read the system data")}, 500)
            return
        payload = {
            "version": 1,
            "timestamp": time.time(),
            "hostname": socket.gethostname(),
        }
        payload.update(snapshot)
        self._send_json(payload)

    def do_POST(self) -> None:  # noqa: N802 (HTTP handler override)
        if self.path != "/api/v1/benchmark":
            self._send_json({"error": "not found"}, 404)
            return
        if not self._authorized():
            self._send_json({"error": "unauthorized"}, 401)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        if not 0 < length <= MAX_REQUEST_BYTES:
            self._send_json({"error": "invalid request size"}, 413)
            return
        try:
            request = json.loads(self.rfile.read(length))
            if not isinstance(request, dict):
                raise ValueError("request must be a JSON object")
            result = type(self).benchmark(request)
            self._send_json(result)
        except BenchmarkBusyError as error:
            self._send_json({"error": str(error)}, 409)
        except (ValueError, KeyError, TypeError, OverflowError, RecursionError, OSError,
                subprocess.SubprocessError) as error:
            self._send_json({"error": str(error)}, 400)

    def log_message(self, format: str, *args) -> None:
        return

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, separators=(",", ":"), default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def run_server(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
               token: str | None = None, show_token: bool = True,
               record_history: bool = True) -> None:
    from app.system_info import (
        AutostartEntry,
        CpuPowerMonitor,
        DockerWorker,
        GpuSystemMonitor,
        ProcessWorker,
        get_cpu_model_name,
        get_cpu_temperatures,
        list_physical_disks,
        list_autostart_entries,
        list_gpus,
        list_hardware_sensors,
        list_ram_sensors,
        poll_gpus,
        system_snapshot,
    )
    from pages.services_page import ServiceListWorker
    from pages.benchmarks_page import BenchmarkWorker

    # One monitor per GPU; the first one also serves older clients as "gpu".
    gpu_monitors = [GpuSystemMonitor(gpu) for gpu in list_gpus()] or [GpuSystemMonitor({})]
    MonitoringHandler.monitor = gpu_monitors[0]
    MonitoringHandler.snapshot = system_snapshot
    process_worker = ProcessWorker()
    docker_worker = DockerWorker()
    service_worker = ServiceListWorker()
    cpu_power_monitor = CpuPowerMonitor()

    def full_snapshot() -> dict:
        process_worker._sync_process_table()
        processes = [asdict(row) for row in process_worker._collect_rows()]
        # Older clients refuse a row with a field they don't know.
        for row in processes:
            del row["swap_mb"]
        docker_rows, docker_error = docker_worker._collect_rows()
        gpus = poll_gpus(gpu_monitors)
        cpu_power = cpu_power_monitor.poll_watts()
        cpu_power_reason = cpu_power_monitor.unavailable_reason()
        cpu_temps = get_cpu_temperatures()
        return {
            "system": system_snapshot(),
            "cpu_model": get_cpu_model_name(),
            "cpu_temp_c": max(cpu_temps, default=None),
            "cpu_temps_c": cpu_temps,
            "cpu_power_w": cpu_power,
            "cpu_powers_w": cpu_power_monitor.cpu_watts,
            "cpu_power_reason": cpu_power_reason,
            "gpu": gpus[0],
            "gpus": gpus,
            "processes": processes,
            "sensors": list_hardware_sensors(),
            "ram_sensors": list_ram_sensors(),
            "services": service_worker._fetch(),
            "docker": [asdict(row) for row in docker_rows],
            "docker_error": docker_error,
            "autostart": [asdict(entry) for entry in list_autostart_entries()],
            "disks": list_physical_disks(),
        }

    MonitoringHandler.snapshot = shared_snapshot(full_snapshot)
    MonitoringHandler.benchmark = make_benchmark_runner(list_physical_disks, BenchmarkWorker)
    MonitoringHandler.token = token
    server = ThreadingHTTPServer((host, port), MonitoringHandler)
    # After the port is ours: a server that can't start must not leave a recorder behind.
    history = HistoryService() if record_history else None
    MonitoringHandler.history = history.store if history else None
    display_host = host if host not in ("0.0.0.0", "::") else _local_ip()
    print(tr("Lintask server running on http://{host}:{port}", host=display_host, port=port), flush=True)
    if token and show_token:
        print(tr("Access token: {token}", token=token), flush=True)
    elif token:
        # The output usually ends up in the journal, a token you chose stays out of it.
        print(tr("Access token: your own (not shown)"), flush=True)
    else:
        print(tr("WARNING: Server is running WITHOUT an access token (--no-auth). Anyone "
                 "who can reach this port can read all data and start benchmarks."),
              flush=True)
    for warning in startup_warnings(host, token):
        print(warning, flush=True)
    print(tr("Press Ctrl+C to quit"), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print(tr("\nServer is shutting down."), flush=True)
    finally:
        server.server_close()
        if history:
            MonitoringHandler.history = None
            history.shutdown()


def _local_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("192.0.2.1", 80))
            return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def server_from_args(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=tr("Lintask monitoring server"))
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--token", help=tr("Your own bearer token, visible to all users in the process list; "
                                "better set {variable} (otherwise one is generated)",
                                variable=TOKEN_ENV))
    parser.add_argument("--generate-token", action="store_true",
                        help=tr("Generate a random access token (default)"))
    parser.add_argument("--no-auth", action="store_true",
                        help=tr("Start without an access token (only on trusted networks!)"))
    parser.add_argument("--no-history", action="store_true",
                        help=tr("Do not record a history of the system values"))
    args = parser.parse_args(argv)
    # Removed in any case, so the programs the server starts don't inherit it.
    env_token = os.environ.pop(TOKEN_ENV, "")
    if args.no_auth and args.token:
        parser.error(tr("--no-auth and --token are mutually exclusive"))
    if args.no_auth and env_token:
        parser.error(tr("--no-auth and {variable} are mutually exclusive", variable=TOKEN_ENV))
    own_token = args.token or env_token
    # A token is always required unless explicitly disabled.
    token = None if args.no_auth else (own_token or secrets.token_urlsafe(24))
    run_server(args.host, args.port, token, show_token=not own_token,
               record_history=not args.no_history)
