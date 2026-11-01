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
# logs: {storage_dir}/logs/web.log

import logging
import os
import sys
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
from engines import web

LOGO_PATH = os.path.join(
    config.ROOT_DIR, "assets", "logo.svg"
)
WEB_DIR = os.path.join(config.ROOT_DIR, "assets", "web")
STYLE_PATH = os.path.join(WEB_DIR, "style.css")
FONTS_DIR = os.path.join(WEB_DIR, "fonts")
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


def make_server(host, port):
    """a server on host:port (port 0: a free one),
    not serving yet; raises OSError if the port is
    taken"""
    return ThreadingHTTPServer((host, port), Handler)


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
        server.server_close()


if __name__ == "__main__" and sys.argv[1:] == ["run"]:
    run()
