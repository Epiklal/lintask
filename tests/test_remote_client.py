"""The access token may reach only the server the user entered: not a proxy from the
environment and not the target of a redirect. Tested over real HTTP on loopback ports.
"""
import importlib.util
import json
import os
import threading
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

TOKEN = "correct-token"


class RecordingServer:
    """Answers every request through `answer(handler)` and records each one's headers."""

    def __init__(self, test, answer):
        self.requests = []
        recording = self.requests

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 (HTTP handler override)
                recording.append(self.headers)
                answer(self)

            def log_message(self, format, *args):
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        test.addCleanup(thread.join)
        test.addCleanup(self.server.server_close)
        test.addCleanup(self.server.shutdown)


def answer_json(payload):
    def answer(handler):
        body = json.dumps(payload).encode()
        handler.send_response(200)
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)
    return answer


@unittest.skipUnless(importlib.util.find_spec("PySide6"), "PySide6 fehlt")
class TestTokenStaysWithTheServer(unittest.TestCase):
    def poll_once(self, port):
        """One round of the real worker loop, in this thread: (snapshot, error)."""
        from app.remote_client import RemoteSnapshotWorker

        worker = RemoteSnapshotWorker("127.0.0.1", port, TOKEN, interval=0.05)
        snapshots, errors = [], []

        def finish(results, result):
            results.append(result)
            worker._running = False

        worker.snapshotReady.connect(lambda payload: finish(snapshots, payload))
        worker.connectionError.connect(lambda text: finish(errors, text))
        worker.run()
        return (snapshots or [None])[0], (errors or [None])[0]

    def test_token_reaches_the_server(self):
        server = RecordingServer(self, answer_json({"via": "direct"}))
        snapshot, error = self.poll_once(server.port)
        self.assertIsNone(error)
        self.assertEqual(snapshot, {"via": "direct"})
        self.assertEqual(server.requests[0]["Authorization"], f"Bearer {TOKEN}")

    def test_redirect_is_not_followed(self):
        target = RecordingServer(self, answer_json({"via": "target"}))

        def redirect(handler):
            handler.send_response(302)
            handler.send_header("Location", f"http://127.0.0.1:{target.port}/stolen")
            handler.send_header("Content-Length", "0")
            handler.end_headers()

        origin = RecordingServer(self, redirect)
        snapshot, error = self.poll_once(origin.port)
        self.assertIsNone(snapshot)
        self.assertTrue(error)
        self.assertEqual(target.requests, [])

    def test_proxy_from_the_environment_is_ignored(self):
        proxy = RecordingServer(self, answer_json({"via": "proxy"}))
        server = RecordingServer(self, answer_json({"via": "direct"}))
        environment = {name: value for name, value in os.environ.items()
                       if name.lower() != "no_proxy"}
        environment["http_proxy"] = f"http://127.0.0.1:{proxy.port}"
        # urlopen keeps the opener of its first call, which read the proxies of that moment.
        with mock.patch.dict(os.environ, environment, clear=True), \
                mock.patch.object(urllib.request, "_opener", None):
            snapshot, error = self.poll_once(server.port)
        self.assertIsNone(error)
        self.assertEqual(snapshot, {"via": "direct"})
        self.assertEqual(proxy.requests, [])


if __name__ == "__main__":
    unittest.main()
