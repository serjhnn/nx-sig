# tests of the web server: config "web",
# scripts/engines/web.py,
# scripts/services/web_service.py and scripts/web/
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
from engines import ladder, overview, trades, web
from services import web_service
from web import api, files, price_cache
from storage import Stock, TradeType

# the script every page shares, the main page's
APP_PATH = os.path.join(files.JS_DIR, "app.js")
SCRIPT_PATH = os.path.join(files.JS_DIR, "main.js")


TRADES_SCRIPT = os.path.join(files.JS_DIR, "trades.js")


def scripts(page=SCRIPT_PATH):
    """the text of app.js and a page's script"""
    text = ""
    for path in (APP_PATH, page):
        with open(path) as f:
            text += f.read()
    return text


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

    def test_read_only(self):
        for value, expected in (
            (True, True),
            (False, False),
            (None, True),
            (0, True),
            ("false", True),
        ):
            self.patch({"web": {"read_only": value}})
            self.assertEqual(
                config.web_read_only(), expected, value
            )
        self.patch({})
        self.assertTrue(config.web_read_only())

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
        for module in (web_service, api):
            p = mock.patch.object(module, "log", self.log)
            p.start()
            self.addCleanup(p.stop)

    def request(
        self,
        path,
        method="GET",
        logged=True,
        body=None,
        headers=None,
    ):
        conn = http.client.HTTPConnection(
            "127.0.0.1", self.port, timeout=5
        )
        self.addCleanup(conn.close)
        self.log.reset_mock()
        conn.request(method, path, body, headers or {})
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
            self.assertEqual(
                body,
                files.page(
                    files.INDEX_PATH, self.server.token
                ),
            )
            self.assertIn(b'href="/style.css"', body)
            # the frame is in, app.js before main.js
            self.assertNotIn(files.FRAME_MARK, body)
            self.assertIn(b'<header class="top"', body)
            self.assertIn(b'<nav class="nav"', body)
            self.assertLess(
                body.index(b'src="/js/app.js"'),
                body.index(b'src="/js/main.js"'),
            )
            self.assertIn(b"width=device-width", body)

    def test_scripts(self):
        for path in (APP_PATH, SCRIPT_PATH):
            name = os.path.basename(path)
            response, body = self.request(f"/js/{name}")
            self.assertEqual(response.status, 200)
            self.assertEqual(
                response.getheader("Content-Type"),
                "text/javascript; charset=utf-8",
            )
            with open(path, "rb") as f:
                self.assertEqual(body, f.read())
        # what the main page asks for
        with open(SCRIPT_PATH) as f:
            self.assertIn('nx.poll("/api/status"', f.read())

    def test_page_ids(self):
        # every element the scripts look up is there
        ids = set(
            re.findall(r'\$\("([\w-]+)"\)', scripts())
        )
        page = files.page(
            files.INDEX_PATH, self.server.token
        ).decode()
        self.assertGreater(len(ids), 10)
        for name in ids:
            self.assertIn(f'id="{name}"', page)

    def test_trades_page(self):
        response, body = self.request("/trades")
        self.assertEqual(response.status, 200)
        self.assertEqual(
            response.getheader("Content-Type"),
            "text/html; charset=utf-8",
        )
        self.assertEqual(
            body,
            files.page(
                files.TRADES_PATH, self.server.token
            ),
        )
        self.assertIn(b'<nav class="nav"', body)
        self.assertLess(
            body.index(b'src="/js/app.js"'),
            body.index(b'src="/js/trades.js"'),
        )
        response, body = self.request("/js/trades.js")
        self.assertEqual(response.status, 200)
        with open(TRADES_SCRIPT, "rb") as f:
            script = f.read()
        self.assertEqual(body, script)
        self.assertIn(b'nx.poll("/api/trades"', script)
        self.assertIn(b'fetch("/api/trades/"', script)

    def test_trades_page_ids(self):
        ids = set(
            re.findall(
                r'\$\("([\w-]+)"\)', scripts(TRADES_SCRIPT)
            )
        )
        page = files.page(
            files.TRADES_PATH, self.server.token
        ).decode()
        self.assertGreater(len(ids), 10)
        for name in ids:
            self.assertIn(f'id="{name}"', page)

    def test_menu(self):
        # every page the menu links to is there, and
        # the frame isn't served by itself
        with open(files.FRAME_PATH) as f:
            links = re.findall(r'href="([^"]+)"', f.read())
        self.assertIn("/", links)
        self.assertIn("/trades", links)
        for path in links:
            response, _ = self.request(path)
            self.assertEqual(response.status, 200, path)
        response, _ = self.request("/frame.html")
        self.assertEqual(response.status, 404)

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
        with open(files.LOGO_PATH, "rb") as f:
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
        with open(files.STYLE_PATH, "rb") as f:
            self.assertEqual(body, f.read())

    def test_fonts(self):
        # every font the style uses is served
        with open(files.STYLE_PATH) as f:
            style = f.read()
        names = [
            n
            for n in os.listdir(files.FONTS_DIR)
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
            "/main.js",
            "/js/",
            "/js/x.js",
            "/js/../style.css",
            "/js/main.js/",
        ):
            response, _ = self.request(path)
            self.assertEqual(response.status, 404, path)

    def test_other_methods(self):
        for method in ("PUT", "DELETE", "OPTIONS"):
            response, _ = self.request("/", method)
            self.assertEqual(response.status, 501, method)

    def test_token(self):
        # in every page, new for every server
        token = self.server.token
        self.assertGreaterEqual(len(token), 40)
        for path in ("/", "/trades"):
            _, body = self.request(path)
            self.assertIn(
                f'data-token="{token}"'.encode(), body
            )
            self.assertNotIn(files.TOKEN_MARK, body)
        other = web_service.make_server("127.0.0.1", 0)
        self.addCleanup(other.server_close)
        self.assertNotEqual(other.token, token)
        # not in what /api gives
        self.server.prices = FakeCache()
        _, body = self.request("/api/status", logged=False)
        self.assertNotIn(token.encode(), body)


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


class ApiMixin(ServerMixin):
    """the data in a temp dir, not the demo, no device
    that runs the tasks, no fee"""

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


class ApiStatusTest(ApiMixin, unittest.TestCase):
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
                "read_only": True,
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

    def test_fields_of_the_page(self):
        # every field main.js reads is in the JSON
        trades.add(
            Stock.SOXL,
            TradeType.BUY,
            20,
            25,
            "02.09.2026",
            "15:31",
        )
        now = datetime.now().replace(microsecond=0)
        storage.watcher_status_set(
            {
                "updated": now.isoformat(),
                "state": "waiting",
                "last_order": "BUY 20 SOXL",
                "last_error": {
                    "time": now.isoformat(),
                    "text": "x",
                },
            }
        )
        row = {
            "id": "-",
            "task": "web",
            "pid": 9,
            "started": now,
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
            _, data = self.api(FakeCache({"SOXL": 30.0}))
        task, trade = (
            data["tasks"][0],
            data["last_trades"][0],
        )
        fields = {
            "data": data,
            "lastData": data,
            "data.total": data["total"],
            "data.owner": data["owner"],
            "data.mail_broker": data["mail_broker"],
            "mail": data["mail_broker"],
            "mail.error": data["mail_broker"]["error"],
            "p": data["positions"][0],
            "best": data["positions"][0],
            # t is a task or a trade
            "t": dict(task, **trade),
        }
        script = scripts()
        # "name.field", not "name.fieldName" (the DOM)
        used = re.findall(
            r"\b((?:data|lastData|p|best|t|mail)"
            r"(?:\.(?:total|owner|mail_broker|error))?)"
            r"\.([a-z_]+)\b(?![A-Za-z(])",
            script,
        )
        self.assertGreater(len(used), 30)
        array = {"length", "some", "reduce", "for"}
        for name, field in set(used):
            if field in array or field in (
                "total",
                "owner",
                "mail_broker",
                "error",
            ):
                continue
            self.assertIn(field, fields[name], name)

    def test_demo(self):
        with mock.patch.object(config, "DEMO", True):
            _, data = self.api()
        self.assertTrue(data["demo"])
        self.assertEqual(
            data["mail_broker"]["state"], "demo"
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


class ApiTradesTest(ApiMixin, unittest.TestCase):
    """/api/trades and /api/trades/<stock>"""

    def get(
        self,
        path,
        cache=None,
        host="127.0.0.1",
        logged=False,
    ):
        """(response, data); only the failures are
        logged"""
        self.serve(host)
        self.server.prices = cache or FakeCache()
        response, body = self.request(path, logged=logged)
        return response, json.loads(body)

    def add(self):
        trades.add(
            Stock.SOXL,
            TradeType.BUY,
            20,
            25,
            "02.09.2026",
            "15:31",
        )
        trades.add(
            Stock.SOXL,
            TradeType.SELL,
            5,
            30,
            "03.09.2026",
            "16:00",
        )
        trades.add(
            Stock.TSMX,
            TradeType.BUY,
            10,
            40,
            "10.09.2026",
            "15:55",
        )
        trades.add(
            Stock.TSMX,
            TradeType.SELL,
            10,
            45,
            "11.09.2026",
            "15:55",
        )

    def test_empty(self):
        response, data = self.get("/api/trades")
        self.assertEqual(response.status, 200)
        self.assertEqual(
            data,
            {
                "updated": None,
                "error": None,
                "interval": 5,
                "demo": False,
                "read_only": True,
                "names": [s.name for s in Stock],
                "stocks": [],
            },
        )

    def test_stocks(self):
        self.add()
        updated = datetime(2026, 11, 2, 14, 30, 5)
        cache = FakeCache(
            {"SOXL": 30.0, "TSMX": 50.0}, updated
        )
        _, data = self.get("/api/trades", cache)
        self.assertEqual(
            data["updated"], "2026-11-02T14:30:05"
        )
        # config order
        self.assertEqual(
            [r["stock"] for r in data["stocks"]],
            [
                s.name
                for s in Stock
                if s.name in ("SOXL", "TSMX")
            ],
        )
        rows = {r["stock"]: r for r in data["stocks"]}
        soxl, tsmx = rows["SOXL"], rows["TSMX"]
        self.assertEqual(
            soxl,
            {
                "stock": "SOXL",
                "trades": 2,
                "last": {
                    "id": 2,
                    "date": "03.09.2026",
                    "time": "16:00",
                    "type": "SELL",
                    "count": 5,
                    "price": 30.0,
                },
                "count": 15,
                "avg": 25.0,
                "cost": 375.0,
                "price": 30.0,
                "gain": 75.0,
                "pct": 20.0,
            },
        )
        # all sold: listed, nothing held, no gain %
        self.assertEqual(tsmx["count"], 0)
        self.assertEqual(tsmx["gain"], 0)
        self.assertIsNone(tsmx["pct"])
        # the same gain as the main page
        _, status = self.api(cache)
        self.assertEqual(
            {k: soxl[k] for k in status["positions"][0]},
            dict(status["positions"][0]),
        )

    def test_no_price(self):
        self.add()
        _, data = self.get("/api/trades")
        for row in data["stocks"]:
            self.assertIsNone(row["price"])
            self.assertIsNone(row["gain"])
            self.assertIsNone(row["pct"])

    def test_one_stock(self):
        self.add()
        cache = FakeCache({"SOXL": 30.0})
        for name in ("SOXL", "soxl"):
            response, data = self.get(
                f"/api/trades/{name}", cache
            )
            self.assertEqual(response.status, 200)
            self.assertEqual(data["stock"]["stock"], "SOXL")
            self.assertEqual(data["stock"]["gain"], 75.0)
            # oldest first, the ids of 'rm trade'
            self.assertEqual(
                [t["id"] for t in data["trades"]], [1, 2]
            )
            self.assertEqual(
                data["trades"][0],
                {
                    "id": 1,
                    "date": "02.09.2026",
                    "time": "15:31",
                    "type": "BUY",
                    "count": 20,
                    "price": 25.0,
                },
            )
            self.assertTrue(data["read_only"])

    def test_stock_without_trades(self):
        _, data = self.get("/api/trades/NVDL")
        self.assertEqual(data["trades"], [])
        self.assertEqual(data["stock"]["trades"], 0)
        self.assertIsNone(data["stock"]["last"])
        self.assertEqual(data["stock"]["count"], 0)

    def test_unknown_stock(self):
        response, data = self.get(
            "/api/trades/XYZ", logged=True
        )
        self.assertEqual(response.status, 404)
        self.assertIn("unknown stock 'XYZ'", data["error"])
        self.assertIn("SOXL", data["error"])

    def test_not_api_paths(self):
        self.serve()
        for path in (
            "/api/trades/",
            "/api/trades/SOXL/1",
            "/api/tradesx",
            "/api/x",
        ):
            response, _ = self.request(path)
            self.assertEqual(response.status, 404, path)
            self.assertEqual(
                response.getheader("Content-Type"),
                "text/html;charset=utf-8",
                path,
            )

    def test_fields_of_the_page(self):
        # every field trades.js reads is in the JSON
        self.add()
        cache = FakeCache({"SOXL": 30.0})
        _, data = self.get("/api/trades", cache)
        _, detail = self.get("/api/trades/SOXL", cache)
        row = detail["stock"]
        trade = detail["trades"][0]
        fields = {
            "data": dict(data, **detail),
            "lastData": data,
            "detail": detail,
            "data.stock": row,
            "detail.stock": row,
            "s": row,
            "had": row,
            "s.last": trade,
            "had.last": trade,
            "t": trade,
            "result": {"text": "", "trade": trade},
        }
        used = re.findall(
            r"\b((?:data|lastData|detail|s|had|t|result)"
            r"(?:\.(?:stock|last))?)"
            r"\.([a-z_]+)\b(?![A-Za-z(])",
            scripts(TRADES_SCRIPT),
        )
        self.assertGreater(len(used), 20)
        array = {
            "length",
            "slice",
            "reduce",
            "filter",
            "forEach",
        }
        for name, field in set(used):
            if field in array:
                continue
            self.assertIn(field, fields[name], name)

    def test_read_only_off(self):
        config.DATA["web"] = {"read_only": False}
        _, data = self.get("/api/trades")
        self.assertFalse(data["read_only"])
        _, data = self.get("/api/trades/SOXL")
        self.assertFalse(data["read_only"])

    def test_only_on_localhost(self):
        self.add()
        for path in ("/api/trades", "/api/trades/SOXL"):
            response, data = self.get(
                path, host="0.0.0.0", logged=True
            )
            self.assertEqual(response.status, 403)
            self.assertIn("127.0.0.1", data["error"])
            self.assertEqual(list(data), ["error"])

    def test_failure(self):
        def broken():
            raise OSError("disk")

        with mock.patch.object(trades, "by_stock", broken):
            self.serve()
            self.server.prices = FakeCache()
            response, body = self.request("/api/trades")
        self.assertEqual(response.status, 500)
        self.assertIn("web log", json.loads(body)["error"])
        self.log.exception.assert_called()


class ApiLaddersTest(ApiMixin, unittest.TestCase):
    """/api/ladders"""

    def get(self, cache=None, host="127.0.0.1"):
        self.serve(host)
        self.server.prices = cache or FakeCache()
        response, body = self.request(
            "/api/ladders", logged=host != "127.0.0.1"
        )
        return response, json.loads(body)

    def setUp(self):
        super().setUp()
        self.running = {}
        p = mock.patch.object(
            ladder, "running_pid", self.running.get
        )
        p.start()
        self.addCleanup(p.stop)

    def test_empty(self):
        response, data = self.get()
        self.assertEqual(response.status, 200)
        self.assertEqual(
            data,
            {
                "updated": None,
                "error": None,
                "interval": 5,
                "demo": False,
                "read_only": True,
                "names": [s.name for s in Stock],
                "ladders": [],
            },
        )

    def test_ladders(self):
        down = ladder.create("SOXL", "down", 1, 35)
        ladder.create("TSMX", "up", 2.5, 40)
        self.running[down] = 4242
        _, data = self.get(
            FakeCache({"SOXL": 34.5, "TSMX": 41.0})
        )
        first, second = data["ladders"]
        self.assertEqual(
            first,
            {
                "id": down,
                "stock": "SOXL",
                "direction": "down",
                "step": 1.0,
                "from": 35.0,
                "last": 35.0,
                "created": first["created"],
                "state": "running",
                "next": 34.0,
                "levels": [34.0, 33.0, 32.0],
                "price": 34.5,
                "away": 0.5,
                "away_pct": 0.5 / 34.5 * 100,
            },
        )
        self.assertRegex(
            first["created"], r"^\d\d\.\d\d\.\d{4} "
        )
        self.assertEqual(second["state"], "stopped")
        self.assertEqual(second["next"], 42.5)
        self.assertEqual(
            second["levels"], [42.5, 45.0, 47.5]
        )
        # up: the next level is 1.5 above the price
        self.assertEqual(second["away"], 1.5)

    def test_passed_and_no_price(self):
        down = ladder.create("SOXL", "down", 1, 35)
        ladder.create("TSMX", "up", 2.5, 40)
        # passed while it doesn't run
        _, data = self.get(FakeCache({"SOXL": 33.0}))
        soxl, tsmx = data["ladders"]
        self.assertEqual(soxl["id"], down)
        self.assertEqual(soxl["away"], -1.0)
        for key in ("price", "away", "away_pct"):
            self.assertIsNone(tsmx[key], key)
        self.assertEqual(tsmx["next"], 42.5)

    def test_done_and_crashed(self):
        done = ladder.create("SOXL", "down", 10, 30)
        crashed = ladder.create("NVDL", "down", 1, 30)
        ladder.set_last(done, 10)
        ladder.save_status(done, 1, None, "done")
        ladder.save_status(crashed, 2, None, "crashed")
        _, data = self.get(
            FakeCache({"SOXL": 8.0, "NVDL": 29.5})
        )
        first, second = data["ladders"]
        self.assertEqual(first["state"], "done")
        self.assertIsNone(first["next"])
        self.assertEqual(first["levels"], [])
        self.assertIsNone(first["away"])
        self.assertEqual(first["price"], 8.0)
        self.assertEqual(second["state"], "crashed")
        self.assertEqual(second["away"], 0.5)

    def test_near_zero(self):
        ladder.create("SOXL", "down", 10, 25)
        _, data = self.get()
        self.assertEqual(
            data["ladders"][0]["levels"], [15.0, 5.0]
        )

    def test_only_on_localhost(self):
        ladder.create("SOXL", "down", 1, 35)
        response, data = self.get(host="0.0.0.0")
        self.assertEqual(response.status, 403)
        self.assertEqual(list(data), ["error"])

    def test_failure(self):
        def broken():
            raise OSError("disk")

        with mock.patch.object(ladder, "rows", broken):
            self.serve()
            self.server.prices = FakeCache()
            response, body = self.request("/api/ladders")
        self.assertEqual(response.status, 500)
        self.log.exception.assert_called()


class ChangeTest(ApiMixin, unittest.TestCase):
    """the checks of a change (a POST), with a fake
    change at /api/test"""

    def setUp(self):
        super().setUp()
        self.got = []

        def fake(data):
            self.got.append(data)
            return 200, {"done": data}

        p = mock.patch.dict(
            api.CHANGES, {"/api/test": fake}
        )
        p.start()
        self.addCleanup(p.stop)
        config.DATA["web"] = {"read_only": False}
        self.serve()

    def post(self, data=None, host=None, **headers):
        """(status, data) of a POST to /api/test; the
        headers of the server's own page unless given
        (None leaves one out)"""
        host = host or f"127.0.0.1:{self.port}"
        sent = {
            "Host": host,
            "Origin": f"http://{host}",
            "Content-Type": "application/json",
            api.TOKEN_HEADER: self.server.token,
        }
        for name, value in headers.items():
            name = name.replace("_", "-")
            if name == "token":
                name = api.TOKEN_HEADER
            sent[name] = value
        sent = {
            k: v for k, v in sent.items() if v is not None
        }
        body = (
            data
            if isinstance(data, bytes)
            else (
                json.dumps(
                    {"a": 1} if data is None else data
                )
            ).encode()
        )
        response, answer = self.request(
            headers.pop("path", "/api/test"),
            "POST",
            body=body,
            headers=sent,
        )
        return response.status, json.loads(answer or b"{}")

    def refused(self, status, error=None, **kwargs):
        got, data = self.post(**kwargs)
        self.assertEqual(got, status, kwargs)
        if error:
            self.assertEqual(data["error"], error)
        self.assertEqual(self.got, [])

    def test_from_its_page(self):
        status, data = self.post({"x": [1, 2]})
        self.assertEqual(status, 200)
        self.assertEqual(data, {"done": {"x": [1, 2]}})
        self.assertEqual(self.got, [{"x": [1, 2]}])
        # every change is logged
        self.log.info.assert_called()

    def test_at_localhost(self):
        status, _ = self.post(host=f"localhost:{self.port}")
        self.assertEqual(status, 200)

    def test_read_only(self):
        config.DATA["web"] = {}
        self.refused(403, api.READ_ONLY_ERROR)

    def test_other_origin(self):
        for origin in (
            None,
            "null",
            "http://evil.example",
            f"http://localhost:{self.port}",
            f"https://127.0.0.1:{self.port}",
        ):
            self.refused(
                403, api.ORIGIN_ERROR, Origin=origin
            )

    def test_other_host_name(self):
        # a name of another site that points here (DNS
        # rebinding): the browser thinks it is that site
        evil = f"evil.example:{self.port}"
        self.refused(403, api.HOST_ERROR, host=evil)
        self.refused(
            403, api.HOST_ERROR, host="127.0.0.1:1"
        )
        # reading isn't allowed either
        self.server.prices = FakeCache()
        response, body = self.request(
            "/api/status", headers={"Host": evil}
        )
        self.assertEqual(response.status, 403)
        self.assertNotIn(b"positions", body)

    def test_token(self):
        self.refused(403, api.TOKEN_ERROR, token=None)
        self.refused(403, api.TOKEN_ERROR, token="")
        self.refused(403, api.TOKEN_ERROR, token="x" * 43)
        self.refused(
            403,
            api.TOKEN_ERROR,
            token=self.server.token[:-1],
        )

    def test_not_json(self):
        # a form of another site can't send JSON
        for kind in (
            "text/plain",
            "application/x-www-form-urlencoded",
            "multipart/form-data",
            None,
        ):
            self.refused(415, Content_Type=kind)
        status, _ = self.post(
            Content_Type="application/json; charset=utf-8"
        )
        self.assertEqual(status, 200)
        self.got.clear()
        for body in (b"{", b"[1]", b"1", b"", "ä".encode()):
            self.refused(400, data=body)

    def test_too_big(self):
        big = {"a": "x" * api.MAX_BODY}
        self.refused(413, data=big)

    def test_unknown_change(self):
        self.refused(404, path="/api/status")
        self.refused(404, path="/api/x")
        self.refused(404, path="/")

    def test_only_on_localhost(self):
        self.serve("0.0.0.0")
        self.refused(403, api.PRIVATE_ERROR)

    def test_failure(self):
        def broken(data):
            raise OSError("disk")

        api.CHANGES["/api/test"] = broken
        status, data = self.post()
        self.assertEqual(status, 500)
        self.assertIn("web log", data["error"])
        self.log.exception.assert_called()


class TradeChangeTest(ApiMixin, unittest.TestCase):
    """POST /api/trades/add and /api/trades/delete"""

    def setUp(self):
        super().setUp()
        config.DATA["web"] = {"read_only": False}
        self.serve()

    def post(self, path, data):
        """(status, data) of a change from the
        server's own page"""
        host = f"127.0.0.1:{self.port}"
        body = (
            data
            if isinstance(data, bytes)
            else (json.dumps(data).encode())
        )
        response, answer = self.request(
            path,
            "POST",
            body=body,
            headers={
                "Host": host,
                "Origin": f"http://{host}",
                "Content-Type": "application/json",
                api.TOKEN_HEADER: self.server.token,
            },
        )
        return response.status, json.loads(answer)

    def add(self, **data):
        change = {
            "stock": "SOXL",
            "type": "buy",
            "count": 10,
            "price": 20.5,
        }
        change.update(data)
        return self.post("/api/trades/add", change)

    def test_add(self):
        status, data = self.add()
        self.assertEqual(status, 200)
        self.assertEqual(
            data["text"], "added BUY 10 SOXL @ 20.5"
        )
        found = trades.get_all(Stock.SOXL)
        self.assertEqual(len(found), 1)
        self.assertEqual(
            data["trade"]["id"], found[0]["Id"]
        )
        self.assertEqual(data["trade"]["type"], "BUY")
        self.assertEqual(found[0]["Count"], 10)
        self.assertEqual(found[0]["Price"], 20.5)
        # it is logged
        self.assertIn(
            "added BUY 10 SOXL @ 20.5",
            [
                c.args[0] % c.args[1:]
                for c in self.log.info.call_args_list
            ],
        )

    def test_add_any_case_at_a_time(self):
        status, data = self.add(
            stock="soxl",
            type="SeLl",
            count=3,
            price=7,
            date="01.10.2026",
            time="15:45",
        )
        self.assertEqual(status, 200)
        self.assertEqual(
            data["text"], "added SELL 3 SOXL @ 7"
        )
        self.assertEqual(
            data["trade"],
            {
                "id": 1,
                "date": "01.10.2026",
                "time": "15:45",
                "type": "SELL",
                "count": 3,
                "price": 7.0,
            },
        )
        # an older trade: the id of the trade added,
        # not of the last one in the file
        status, data = self.add(
            date="01.09.2026", time="10:00"
        )
        self.assertEqual(data["trade"]["id"], 2)
        self.assertEqual(
            data["trade"]["date"], "01.09.2026"
        )

    def test_add_refused(self):
        for change, error in (
            ({"stock": "XYZ"}, "unknown stock 'XYZ'"),
            ({"stock": None}, "unknown stock"),
            ({"type": "hold"}, "unknown trade type 'hold'"),
            ({"type": 1}, "unknown trade type"),
            (
                {"count": 1.5},
                "count must be a whole number",
            ),
            ({"count": "10"}, "count must be a whole"),
            ({"count": True}, "count must be a whole"),
            ({"count": None}, "count must be a whole"),
            ({"price": "20"}, "price a number"),
            ({"count": 0}, "must be positive"),
            ({"price": -1}, "must be positive"),
            (
                {"date": "01.10.2026"},
                "give both date and time",
            ),
            (
                {"date": "31.02.2026", "time": "10:00"},
                "bad date or time",
            ),
            (
                {"date": 1, "time": 2},
                "date and time are text",
            ),
        ):
            status, data = self.add(**change)
            self.assertEqual(status, 400, change)
            self.assertIn(error, data["error"], change)
        # what json.loads lets through
        for price in (b"NaN", b"Infinity", b"-Infinity"):
            body = (
                b'{"stock": "SOXL", "type": "buy", '
                b'"count": 1, "price": ' + price + b"}"
            )
            status, data = self.post(
                "/api/trades/add", body
            )
            self.assertEqual(status, 400, price)
        self.assertEqual(trades.get_all(Stock.SOXL), [])

    def test_delete(self):
        self.add()
        self.add(price=21)
        status, data = self.post(
            "/api/trades/delete", {"stock": "soxl", "id": 1}
        )
        self.assertEqual(status, 200)
        self.assertEqual(
            data["text"], "deleted SOXL trade 1"
        )
        self.assertEqual(
            [t["Id"] for t in trades.get_all(Stock.SOXL)],
            [2],
        )
        # again: gone
        status, data = self.post(
            "/api/trades/delete", {"stock": "SOXL", "id": 1}
        )
        self.assertEqual(status, 404)
        self.assertEqual(data["error"], "no SOXL trade 1")

    def test_delete_refused(self):
        self.add()
        for change in (
            {"stock": "XYZ", "id": 1},
            {"stock": "SOXL", "id": "1"},
            {"stock": "SOXL", "id": 1.0},
            {"stock": "SOXL"},
        ):
            status, _ = self.post(
                "/api/trades/delete", change
            )
            self.assertEqual(status, 400, change)
        self.assertEqual(len(trades.get_all(Stock.SOXL)), 1)

    def test_read_only(self):
        config.DATA["web"] = {}
        status, data = self.add()
        self.assertEqual(status, 403)
        self.assertEqual(data["error"], api.READ_ONLY_ERROR)
        trades.add(Stock.SOXL, TradeType.BUY, 1, 1)
        status, _ = self.post(
            "/api/trades/delete", {"stock": "SOXL", "id": 1}
        )
        self.assertEqual(status, 403)
        self.assertEqual(len(trades.get_all(Stock.SOXL)), 1)

    def test_names(self):
        self.server.prices = FakeCache()
        response, body = self.request(
            "/api/trades", logged=False
        )
        self.assertEqual(
            json.loads(body)["names"],
            [s.name for s in Stock],
        )


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
        self.cache = price_cache.PriceCache(
            0.01,
            fetch=self.fetch,
            watch=30,
            clock=self.clock,
        )
        self.addCleanup(self.cache.stop)
        self.log = mock.Mock()
        p = mock.patch.object(price_cache, "log", self.log)
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
            server.prices, price_cache.PriceCache
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

    def test_task(self):
        self.assertIsNone(web.task())
        web.save_status(
            31, "2026-11-02T09:00:00", "serving"
        )
        self.alive.add(31)
        row = web.task()
        self.assertEqual(
            row,
            {
                "id": "-",
                "task": "web",
                "pid": 31,
                "started": datetime(2026, 11, 2, 9, 0),
                "state": "serving",
                "healthy": True,
            },
        )
        web.save_status(31, None, "crashed")
        self.assertFalse(web.task()["healthy"])

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
