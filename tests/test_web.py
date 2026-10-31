# tests of the web server: config "web",
# scripts/engines/web.py and
# scripts/services/web_service.py
#
#   python tests/test_web.py
#
# the server runs in a thread on a free port; the
# engine's process is faked. the service's log is a
# mock: test_alerts.py turns logging off for the run

import http.client
import socket
import tempfile
import threading
import unittest
from unittest import mock

import paths  # noqa: F401, scripts/ on sys.path
import config
import process
import storage
from engines import web
from services import web_service


class FakeChild:
    def __init__(self, pid, code=None):
        self.pid = pid
        self.code = code

    def poll(self):
        return self.code


class WebConfigTest(unittest.TestCase):
    def patch(self, values):
        p = mock.patch.dict(config.DATA, values, clear=True)
        p.start()
        self.addCleanup(p.stop)

    def test_defaults(self):
        self.patch({})
        self.assertEqual(config.web_host(), "127.0.0.1")
        self.assertEqual(config.web_port(), 8080)
        self.assertEqual(
            web.url(), "http://127.0.0.1:8080/"
        )

    def test_set(self):
        self.patch({"web": {"host": "0.0.0.0", "port": 81}})
        self.assertEqual(config.web_host(), "0.0.0.0")
        self.assertEqual(config.web_port(), 81)
        # every address: open it on this device
        self.assertEqual(web.url(), "http://127.0.0.1:81/")

    def test_bad_values(self):
        for port in (0, 65536, "80", True, 80.5):
            self.patch({"web": {"host": "", "port": port}})
            self.assertEqual(config.web_host(), "127.0.0.1")
            self.assertEqual(config.web_port(), 8080)
        self.patch({"web": "on"})
        self.assertEqual(config.web_port(), 8080)


class WebServerTest(unittest.TestCase):
    def setUp(self):
        self.server = web_service.make_server(
            "127.0.0.1", 0
        )
        self.port = self.server.server_address[1]
        thread = threading.Thread(
            target=self.server.serve_forever, daemon=True
        )
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.log = mock.Mock()
        p = mock.patch.object(web_service, "log", self.log)
        p.start()
        self.addCleanup(p.stop)

    def request(self, path, method="GET"):
        conn = http.client.HTTPConnection(
            "127.0.0.1", self.port, timeout=5
        )
        self.addCleanup(conn.close)
        self.log.reset_mock()
        conn.request(method, path)
        response = conn.getresponse()
        body = response.read()
        # the request is logged, not printed
        self.log.info.assert_called()
        return response, body

    def test_page(self):
        for path in ("/", "/?from=phone"):
            response, body = self.request(path)
            self.assertEqual(response.status, 200)
            self.assertEqual(
                response.getheader("Content-Type"),
                "text/html; charset=utf-8",
            )
            self.assertIn(b'<img src="/logo.svg"', body)
            self.assertIn(b"width=device-width", body)

    def test_logo(self):
        response, body = self.request("/logo.svg")
        self.assertEqual(response.status, 200)
        self.assertEqual(
            response.getheader("Content-Type"),
            "image/svg+xml",
        )
        with open(web_service.LOGO_PATH, "rb") as f:
            self.assertEqual(body, f.read())
        self.assertEqual(
            int(response.getheader("Content-Length")),
            len(body),
        )

    def test_head(self):
        response, body = self.request("/", "HEAD")
        self.assertEqual(response.status, 200)
        self.assertEqual(body, b"")
        self.assertGreater(
            int(response.getheader("Content-Length")), 0
        )

    def test_not_found(self):
        for path in (
            "/x",
            "/assets/logo.svg",
            "/../config.json",
            "/logo.svg/",
        ):
            response, _ = self.request(path)
            self.assertEqual(response.status, 404, path)

    def test_other_methods(self):
        for method in ("POST", "PUT", "DELETE"):
            response, _ = self.request("/", method)
            self.assertEqual(response.status, 501, method)


class WebProcessTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_db_dir = storage.DB_DIR
        storage.DB_DIR = self._tmp.name
        self.patch(process, "START_CHECK_SECONDS", 0)
        self.alive = set()
        self.log = mock.Mock()
        self.patch(web_service, "log", self.log)
        self.patch(
            process,
            "process_runs",
            lambda pid, *a: pid in self.alive,
        )

    def tearDown(self):
        storage.DB_DIR = self._orig_db_dir
        self._tmp.cleanup()

    def patch(self, target, name, value):
        p = mock.patch.object(target, name, value)
        p.start()
        self.addCleanup(p.stop)

    def test_start(self):
        spawned = []

        def spawn(args, out, wake=True, python=None):
            spawned.append((args, wake))
            return FakeChild(500)

        self.patch(process, "spawn", spawn)
        self.assertEqual(web.start(), 500)
        # no wake lock, it sends nothing
        self.assertEqual(
            spawned, [([web.SCRIPT, "run"], False)]
        )
        status = web.status()
        self.assertEqual(status["pid"], 500)
        self.assertEqual(status["state"], "starting")
        self.assertEqual(status["url"], web.url())
        self.alive.add(500)
        self.assertEqual(web.running_pid(), 500)
        with self.assertRaisesRegex(
            web.WebError, "already runs"
        ):
            web.start()
        self.assertEqual(len(spawned), 1)

    def test_start_fails(self):
        self.patch(
            process,
            "spawn",
            lambda *a, **k: FakeChild(5, 1),
        )
        self.patch(process, "START_CHECK_SECONDS", 1)
        self.patch(
            process,
            "last_line",
            lambda files: "can't listen on 127.0.0.1",
        )
        with self.assertRaisesRegex(
            web.WebError,
            "stopped right after starting: " "can't listen",
        ):
            web.start()

    def test_stop(self):
        self.assertFalse(web.stop())
        web.save_status(500, None, "serving")
        self.alive.add(500)
        sent = []

        def kill(pid, sig):
            sent.append(pid)
            self.alive.discard(pid)
            return True

        self.patch(process, "kill", kill)
        self.patch(process, "reap", lambda pid: None)
        self.assertTrue(web.stop())
        self.assertEqual(sent, [500])
        self.assertIsNone(web.running_pid())

    def test_service(self):
        # serves until SIGTERM (KeyboardInterrupt)
        self.patch(process, "setup_logging", lambda p: None)
        self.patch(
            process.signal, "signal", lambda *a: None
        )
        server = mock.Mock()
        server.serve_forever.side_effect = KeyboardInterrupt
        self.patch(
            web_service, "make_server", lambda h, p: server
        )
        web_service.run()
        self.assertEqual(web.status()["state"], "stopped")
        self.log.info.assert_called_with(
            "web server stopped"
        )
        server.server_close.assert_called_once()

    def test_service_port_taken(self):
        self.patch(process, "setup_logging", lambda p: None)
        self.patch(
            process.signal, "signal", lambda *a: None
        )
        taken = socket.socket()
        self.addCleanup(taken.close)
        taken.bind(("127.0.0.1", 0))
        taken.listen()
        port = taken.getsockname()[1]
        self.patch(config, "web_port", lambda: port)
        with mock.patch("builtins.print") as printed:
            with self.assertRaises(SystemExit):
                web_service.run()
        self.log.error.assert_called_once()
        self.assertIn(
            "can't listen", printed.call_args.args[0]
        )
        self.assertEqual(web.status()["state"], "crashed")


if __name__ == "__main__":
    unittest.main()
