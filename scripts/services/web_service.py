# web service: the web server process, a page with the
# nX-sig logo (engines/web.py starts it)
#
#   python scripts/services/web_service.py run
#       ('run web' in the shell starts it)
#
# it serves only these paths, read-only, and touches
# no data:
#   /             a page with the logo, as wide as the
#                 screen
#   /logo.svg     assets/logo.svg
#   /style.css    assets/web/style.css, the style
#                 every page shares
#   /fonts/<f>    a .woff2 of assets/web/fonts/
# anything else is 404, a method other than GET or HEAD
# 501 (http.server).
#
# the server keeps the prices for the main page in a
# PriceCache (server.prices): a thread fetches them
# every config "web" "interval" seconds, but only
# while a page asked for them in the last
# WATCH_SECONDS, so no page open means no requests,
# and one request per interval however many pages are
# open.
#
# logs: {storage_dir}/logs/web.log

import logging
import os
import sys
import threading
import time
from datetime import datetime
from http.server import (
    BaseHTTPRequestHandler,
    ThreadingHTTPServer,
)

# engines/, config.py and process.py are in scripts/,
# one level up
sys.path.insert(
    1,
    os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))
    ),
)

import config
import process
from engines import prices, web

LOGO_PATH = os.path.join(
    config.ROOT_DIR, "assets", "logo.svg"
)
WEB_DIR = os.path.join(config.ROOT_DIR, "assets", "web")
STYLE_PATH = os.path.join(WEB_DIR, "style.css")
FONTS_DIR = os.path.join(WEB_DIR, "fonts")
# the prices are fetched while a page asked for them
# this recently
WATCH_SECONDS = 30
PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport"
 content="width=device-width, initial-scale=1">
<title>nX-sig</title>
<link rel="stylesheet" href="/style.css">
<style>
body {
  display: flex;
  align-items: center;
  justify-content: center;
}
img {
  width: min(520px, calc(100vw - 32px));
  height: auto;
}
</style>
</head>
<body>
<img src="/logo.svg" alt="nX-sig">
</body>
</html>
"""

log = logging.getLogger("web")


class Handler(BaseHTTPRequestHandler):
    server_version = "nx-sig"
    sys_version = ""

    def do_GET(self):
        self._send(True)

    def do_HEAD(self):
        self._send(False)

    def _send(self, with_body):
        path = self.path.split("?", 1)[0]
        if path == "/":
            body = PAGE.encode()
            kind = "text/html; charset=utf-8"
        elif path == "/logo.svg":
            body = _read(LOGO_PATH)
            kind = "image/svg+xml"
        elif path == "/style.css":
            body = _read(STYLE_PATH)
            kind = "text/css; charset=utf-8"
        elif _font(path):
            body = _read(_font(path))
            kind = "font/woff2"
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", len(body))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        if with_body:
            self.wfile.write(body)

    def log_message(self, format, *args):
        # to the log file, not stderr
        log.info(
            "%s %s", self.address_string(), format % args
        )


def _read(path):
    with open(path, "rb") as f:
        return f.read()


def _font(path):
    """the file of a /fonts/<name>.woff2 path, None
    if there is none; only the names in FONTS_DIR, so
    no other file can be asked for"""
    name = path.removeprefix("/fonts/")
    if name == path or not name.endswith(".woff2"):
        return None
    if name not in os.listdir(FONTS_DIR):
        return None
    return os.path.join(FONTS_DIR, name)


class PriceCache:
    """the last prices, fetched by a thread every
    interval seconds while get() was called in the last
    watch seconds; fetch() gives {stock name: price}"""

    def __init__(
        self,
        interval,
        fetch=prices.get_latest_prices,
        watch=WATCH_SECONDS,
        clock=time.monotonic,
    ):
        self.interval = interval
        self.watch = watch
        self._fetch = fetch
        self._clock = clock
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._asked = None
        self._prices = {}
        self._updated = None
        self._error = None

    def get(self):
        """{"prices", "updated", "error"}: the last
        prices and when they came (a datetime, None
        before the first), the error of the last fetch
        (the prices are then the ones before it);
        starts the fetching if it is idle"""
        with self._lock:
            self._asked = self._clock()
            if self._thread is None and (
                not self._stop.is_set()
            ):
                self._thread = threading.Thread(
                    target=self._run, daemon=True
                )
                self._thread.start()
            return {
                "prices": dict(self._prices),
                "updated": self._updated,
                "error": self._error,
            }

    def fetching(self):
        """True while its thread runs"""
        with self._lock:
            return self._thread is not None

    def stop(self):
        """end the thread, for good"""
        self._stop.set()

    def _run(self):
        while not self._stop.is_set():
            self._fetch_once()
            if self._stop.wait(self.interval):
                break
            with self._lock:
                idle = self._clock() - self._asked
                if idle >= self.watch:
                    # nobody watches: end here, the
                    # next get() starts a new thread
                    self._thread = None
                    return
        with self._lock:
            self._thread = None

    def _fetch_once(self):
        try:
            found = self._fetch()
        except KeyError as e:
            error = f"missing {e.args[0]} in .env"
        except Exception as e:  # network or API errors
            error = str(e) or type(e).__name__
        else:
            with self._lock:
                self._prices = dict(found)
                self._updated = datetime.now()
                self._error = None
            return
        with self._lock:
            new = error != self._error
            self._error = error
        if new:
            # once, not every interval
            log.warning("can't get the prices: %s", error)


def make_server(host, port):
    """a server on host:port (port 0: a free one),
    not serving yet, with its PriceCache in .prices;
    raises OSError if the port is taken"""
    server = ThreadingHTTPServer((host, port), Handler)
    server.prices = PriceCache(config.web_interval())
    return server


def run():
    """serve until SIGTERM or Ctrl+C"""
    process.service_setup(web.TASK)
    pid = os.getpid()
    started = datetime.now().isoformat(timespec="seconds")
    host, port = config.web_host(), config.web_port()
    log.info("web server starting, pid %s", pid)
    try:
        server = make_server(host, port)
    except OSError as e:
        # last_line() shows it to 'run web'
        log.error(
            "can't listen on %s:%s: %s", host, port, e
        )
        print(f"can't listen on {host}:{port}: {e}")
        web.save_status(pid, started, "crashed")
        sys.exit(1)
    web.save_status(pid, started, "serving")
    log.info("serving %s", web.url())
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        web.save_status(pid, started, "stopped")
        log.info("web server stopped")
    except Exception:
        log.critical("web server crashed", exc_info=True)
        web.save_status(pid, started, "crashed")
        sys.exit(1)
    finally:
        server.prices.stop()
        server.server_close()


if __name__ == "__main__" and sys.argv[1:] == ["run"]:
    run()
