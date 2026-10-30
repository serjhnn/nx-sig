# web service: the web server process, a page with the
# nX-sig logo (engines/web.py starts it)
#
#   python scripts/services/web_service.py run
#       ('run web' in the shell starts it)
#
# it serves only two paths, read-only, and touches no
# data:
#   /          a page with the logo, as wide as the
#              screen
#   /logo.svg  assets/logo.svg
# anything else is 404, a method other than GET or HEAD
# 501 (http.server).
#
# logs: {storage_dir}/logs/web.log

import logging
import os
import signal
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
# the logo's own background, so it blends in
PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport"
 content="width=device-width, initial-scale=1">
<title>nX-sig</title>
<style>
html, body {
  margin: 0;
  height: 100%;
  background: #0d1117;
}
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
            with open(LOGO_PATH, "rb") as f:
                body = f.read()
            kind = "image/svg+xml"
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


def make_server(host, port):
    """a server on host:port (port 0: a free one),
    not serving yet; raises OSError if the port is
    taken"""
    return ThreadingHTTPServer((host, port), Handler)


def run():
    """serve until SIGTERM or Ctrl+C"""
    signal.signal(signal.SIGTERM, _stop_on_signal)
    signal.signal(signal.SIGINT, signal.default_int_handler)
    process.setup_logging(web.log_path())
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


def _stop_on_signal(signum, frame):
    # handled like Ctrl+C: the heartbeat says 'stopped'
    raise KeyboardInterrupt


if __name__ == "__main__" and sys.argv[1:] == ["run"]:
    run()
