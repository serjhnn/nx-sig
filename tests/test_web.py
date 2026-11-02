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
import json
import os
import re
import socket
import tempfile
import threading
import unittest
from datetime import datetime
from unittest import mock

import paths  # noqa: F401, scripts/ on sys.path
import config
import process
import storage
import tasks_owner
from engines import overview, trades, web
from services import web_service
from storage import Stock, TradeType


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
        self.assertEqual(config.web_interval(), 5)
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
        self.assertEqual(config.web_interval(), 5)

    def test_interval(self):
        for value, expected in (
            (10, 10),
            (1, 1),
            (2.5, 2.5),
            (0.5, 5),
            (0, 5),
            (-3, 5),
            ("10", 5),
            (True, 5),
            (None, 5),
        ):
            self.patch({"web": {"interval": value}})
            self.assertEqual(
                config.web_interval(), expected, value
            )


class ServerMixin:
    """a server in a thread on a free port"""

    def serve(self, host="127.0.0.1"):
        self.server = web_service.make_server(host, 0)
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

    def request(self, path, method="GET", logged=True):
        conn = http.client.HTTPConnection(
            "127.0.0.1", self.port, timeout=5
        )
        self.addCleanup(conn.close)
        self.log.reset_mock()
        conn.request(method, path)
        response = conn.getresponse()
        body = response.read()
        # the request is logged, not printed
        self.assertEqual(self.log.info.called, logged)
        return response, body


class WebServerTest(ServerMixin, unittest.TestCase):
    def setUp(self):
        self.serve()

    def test_main_page(self):
        for path in ("/", "/?from=phone"):
            response, body = self.request(path)
            self.assertEqual(response.status, 200)
            self.assertEqual(
                response.getheader("Content-Type"),
                "text/html; charset=utf-8",
            )
            with open(web_service.INDEX_PATH, "rb") as f:
                self.assertEqual(body, f.read())
            self.assertIn(b'href="/style.css"', body)
            self.assertIn(b'src="/main.js"', body)
            self.assertIn(b"width=device-width", body)

    def test_script(self):
        response, body = self.request("/main.js")
        self.assertEqual(response.status, 200)
        self.assertEqual(
            response.getheader("Content-Type"),
            "text/javascript; charset=utf-8",
        )
        with open(web_service.SCRIPT_PATH, "rb") as f:
            self.assertEqual(body, f.read())
        # what it asks for
        self.assertIn(b'"/api/status"', body)

    def test_page_ids(self):
        # every element the script looks up is there
        with open(web_service.SCRIPT_PATH) as f:
            ids = set(
                re.findall(r'\$\("([\w-]+)"\)', f.read())
            )
        with open(web_service.INDEX_PATH) as f:
            page = f.read()
        self.assertGreater(len(ids), 10)
        for name in ids:
            self.assertIn(f'id="{name}"', page)

    def test_logo_page(self):
        response, body = self.request("/logo")
        self.assertEqual(response.status, 200)
        self.assertEqual(
            response.getheader("Content-Type"),
            "text/html; charset=utf-8",
        )
        self.assertIn(b'<img src="/logo.svg"', body)
        self.assertIn(b'href="/style.css"', body)
        self.assertIn(b'<a href="/">', body)

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

    def test_style(self):
        response, body = self.request("/style.css")
        self.assertEqual(response.status, 200)
        self.assertEqual(
            response.getheader("Content-Type"),
            "text/css; charset=utf-8",
        )
        with open(web_service.STYLE_PATH, "rb") as f:
            self.assertEqual(body, f.read())

    def test_fonts(self):
        # every font the style uses is served
        with open(web_service.STYLE_PATH) as f:
            style = f.read()
        names = [
            n
            for n in os.listdir(web_service.FONTS_DIR)
            if n.endswith(".woff2")
        ]
        self.assertEqual(len(names), 4)
        for name in names:
            self.assertIn(f'url("/fonts/{name}")', style)
            response, body = self.request(f"/fonts/{name}")
            self.assertEqual(response.status, 200)
            self.assertEqual(
                response.getheader("Content-Type"),
                "font/woff2",
            )
            self.assertEqual(body[:4], b"wOF2")

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
            "/fonts/",
            "/fonts/OFL.txt",
            "/fonts/x.woff2",
            "/fonts/../style.css",
            "/fonts/../../../config.json",
            "/web/style.css",
        ):
            response, _ = self.request(path)
            self.assertEqual(response.status, 404, path)

    def test_other_methods(self):
        for method in ("POST", "PUT", "DELETE"):
            response, _ = self.request("/", method)
            self.assertEqual(response.status, 501, method)


class FakeCache:
    interval = 5

    def __init__(
        self, prices=None, updated=None, error=None
    ):
        self.result = {
            "prices": prices or {},
            "updated": updated,
            "error": error,
        }

    def get(self):
        return self.result


class ApiStatusTest(ServerMixin, unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for target, name, value in (
            (storage, "DB_DIR", tmp.name),
            (config, "DEMO", False),
            (tasks_owner, "owner", lambda: None),
        ):
            p = mock.patch.object(target, name, value)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.dict(config.DATA)
        p.start()
        self.addCleanup(p.stop)
        config.DATA.pop("fee", None)

    def api(self, cache=None, host="127.0.0.1"):
        self.serve(host)
        self.server.prices = cache or FakeCache()
        # only the failures are logged
        response, body = self.request(
            "/api/status",
            logged=host != "127.0.0.1",
        )
        return response, json.loads(body)

    def test_empty(self):
        response, data = self.api()
        self.assertEqual(response.status, 200)
        self.assertEqual(
            response.getheader("Content-Type"),
            "application/json",
        )
        self.assertEqual(
            response.getheader("Cache-Control"), "no-store"
        )
        self.assertEqual(
            data,
            {
                "updated": None,
                "error": None,
                "interval": 5,
                "demo": False,
                "positions": [],
                "total": {
                    "gain": 0,
                    "cost": 0,
                    "pct": None,
                },
                "tasks": [],
                "mail_broker": {
                    "state": "not started",
                    "updated": None,
                    "last_order": None,
                    "error": None,
                },
                "owner": None,
                "last_trades": [],
            },
        )

    def test_positions(self):
        trades.add(
            Stock.SOXL,
            TradeType.BUY,
            20,
            25,
            "02.09.2026",
            "15:31",
        )
        trades.add(
            Stock.TSMX,
            TradeType.BUY,
            10,
            40,
            "10.09.2026",
            "15:55",
        )
        cache = FakeCache(
            {"SOXL": 30.0},
            datetime(2026, 11, 2, 14, 30, 5),
            "network is down",
        )
        _, data = self.api(cache)
        self.assertEqual(
            data["updated"], "2026-11-02T14:30:05"
        )
        self.assertEqual(data["error"], "network is down")
        found = {p["stock"]: p for p in data["positions"]}
        self.assertEqual(sorted(found), ["SOXL", "TSMX"])
        soxl, tsmx = found["SOXL"], found["TSMX"]
        self.assertEqual(
            soxl,
            {
                "stock": "SOXL",
                "count": 20,
                "avg": 25.0,
                "cost": 500.0,
                "price": 30.0,
                "gain": 100.0,
                "pct": 20.0,
            },
        )
        # no price yet
        self.assertEqual(tsmx["stock"], "TSMX")
        self.assertIsNone(tsmx["price"])
        self.assertIsNone(tsmx["gain"])
        self.assertEqual(
            data["total"],
            {"gain": 100.0, "cost": 500.0, "pct": 20.0},
        )
        self.assertEqual(
            data["last_trades"][0],
            {
                "stock": "TSMX",
                "id": 1,
                "date": "10.09.2026",
                "time": "15:55",
                "type": "BUY",
                "count": 10,
                "price": 40.0,
            },
        )

    def test_tasks_and_owner(self):
        started = datetime(2026, 11, 2, 9, 0, 0)
        row = {
            "id": "-",
            "task": "web",
            "pid": 9,
            "started": started,
            "state": "serving",
            "healthy": True,
        }
        phone = {"id": "a1", "name": "phone"}
        with (
            mock.patch.object(
                overview, "tasks", lambda: [row]
            ),
            mock.patch.object(
                tasks_owner, "owner", lambda: phone
            ),
            mock.patch.object(
                tasks_owner, "this_device", lambda: phone
            ),
        ):
            _, data = self.api()
        self.assertEqual(
            data["tasks"],
            [dict(row, started="2026-11-02T09:00:00")],
        )
        self.assertEqual(
            data["owner"], {"name": "phone", "here": True}
        )

    def test_only_on_localhost(self):
        response, data = self.api(host="0.0.0.0")
        self.assertEqual(response.status, 403)
        self.assertIn("127.0.0.1", data["error"])
        self.assertNotIn("positions", data)

    def test_failure(self):
        def broken(prices):
            raise OSError("disk")

        with mock.patch.object(overview, "status", broken):
            self.serve()
            self.server.prices = FakeCache()
            response, body = self.request("/api/status")
        self.assertEqual(response.status, 500)
        self.assertIn("web log", json.loads(body)["error"])
        self.log.exception.assert_called()

    def test_head(self):
        self.serve()
        self.server.prices = FakeCache()
        response, body = self.request(
            "/api/status", "HEAD", logged=False
        )
        self.assertEqual(response.status, 200)
        self.assertEqual(body, b"")


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class PriceCacheTest(unittest.TestCase):
    def setUp(self):
        self.calls = 0
        self.result = {"SOXL": 30.0}
        self.clock = FakeClock()
        self.cache = web_service.PriceCache(
            0.01,
            fetch=self.fetch,
            watch=30,
            clock=self.clock,
        )
        self.addCleanup(self.cache.stop)
        self.log = mock.Mock()
        p = mock.patch.object(web_service, "log", self.log)
        p.start()
        self.addCleanup(p.stop)

    def fetch(self):
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result

    def wait_for(self, check):
        # the thread runs every 0.01s
        for _ in range(500):
            if check():
                return
            threading.Event().wait(0.01)
        self.fail("timed out")

    def test_nothing_without_a_page(self):
        threading.Event().wait(0.05)
        self.assertEqual(self.calls, 0)
        self.assertFalse(self.cache.fetching())

    def test_first_get(self):
        first = self.cache.get()
        self.assertEqual(
            first,
            {"prices": {}, "updated": None, "error": None},
        )
        self.assertTrue(self.cache.fetching())
        self.wait_for(lambda: self.cache.get()["updated"])
        got = self.cache.get()
        self.assertEqual(got["prices"], {"SOXL": 30.0})
        self.assertIsNone(got["error"])

    def test_one_thread(self):
        before = threading.active_count()
        for _ in range(20):
            self.cache.get()
        self.assertEqual(
            threading.active_count(), before + 1
        )

    def test_error_keeps_the_prices(self):
        self.cache.get()
        self.wait_for(lambda: self.cache.get()["updated"])
        updated = self.cache.get()["updated"]
        self.result = OSError("network is down")
        self.wait_for(lambda: self.cache.get()["error"])
        got = self.cache.get()
        self.assertEqual(got["error"], "network is down")
        self.assertEqual(got["prices"], {"SOXL": 30.0})
        self.assertEqual(got["updated"], updated)
        # logged once, not every interval
        calls = self.calls
        self.wait_for(lambda: self.calls > calls + 3)
        self.assertEqual(self.log.warning.call_count, 1)
        # back: the error is gone
        self.result = {"SOXL": 31.0}
        self.wait_for(
            lambda: self.cache.get()["error"] is None
        )
        self.assertEqual(
            self.cache.get()["prices"], {"SOXL": 31.0}
        )

    def test_missing_key(self):
        self.result = KeyError("APCA_API_KEY_ID")
        self.cache.get()
        self.wait_for(lambda: self.cache.get()["error"])
        self.assertEqual(
            self.cache.get()["error"],
            "missing APCA_API_KEY_ID in .env",
        )

    def test_stops_when_nobody_watches(self):
        self.cache.get()
        self.wait_for(lambda: self.calls >= 2)
        # 30s without a get(): the thread ends
        self.clock.now += 30
        self.wait_for(lambda: not self.cache.fetching())
        calls = self.calls
        threading.Event().wait(0.05)
        self.assertEqual(self.calls, calls)
        # a page again: fetching again
        self.cache.get()
        self.assertTrue(self.cache.fetching())
        self.wait_for(lambda: self.calls > calls)

    def test_stop(self):
        self.cache.get()
        self.cache.stop()
        self.wait_for(lambda: not self.cache.fetching())
        self.cache.get()
        self.assertFalse(self.cache.fetching())

    def test_server_has_one(self):
        server = web_service.make_server("127.0.0.1", 0)
        self.addCleanup(server.server_close)
        self.assertIsInstance(
            server.prices, web_service.PriceCache
        )
        self.assertEqual(
            server.prices.interval, config.web_interval()
        )
        self.assertFalse(server.prices.fetching())


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

    def test_log_tail(self):
        self.assertEqual(web.log_tail(), [])
        path = web.log_path()
        os.makedirs(os.path.dirname(path))
        with open(path, "w") as f:
            f.write("one\ntwo\nthree\n")
        self.assertEqual(web.log_tail(2), ["two", "three"])

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
