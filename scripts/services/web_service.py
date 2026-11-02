# web service: the web server process (engines/web.py
# starts it)
#
#   python scripts/services/web_service.py run
#       ('run web' in the shell starts it)
#
# it answers GET, HEAD and POST, with the parts in
# scripts/web/:
#   web/api.py     /api/..., the JSON of the pages,
#                  and the changes (POST), with
#                  their checks
#   web/files.py   the pages, their style, scripts
#                  and fonts, the logo
# anything else is 404, another method 501
# (http.server). the server makes a token when it
# starts (server.token) for the changes; its pages
# get it.
#
# a successful GET of /api/... isn't logged: a page
# asks every few seconds. every change is logged.
#
# the server keeps the prices for the pages in a
# web/price_cache.py PriceCache (server.prices).
#
# logs: {storage_dir}/logs/web.log

import errno
import json
import logging
import os
import secrets
import sys
from datetime import datetime
from http.server import (
    BaseHTTPRequestHandler,
    ThreadingHTTPServer,
)

# engines/, web/, config.py and process.py are in
# scripts/, one level up
sys.path.insert(
    1,
    os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))
    ),
)

import config
import process
from engines import web
from web import api, files
from web.price_cache import PriceCache

log = logging.getLogger("web")


class Handler(BaseHTTPRequestHandler):
    server_version = "nx-sig"
    sys_version = ""

    def do_GET(self):
        self._send(True)

    def do_HEAD(self):
        self._send(False)

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        try:
            length = int(self.headers["Content-Length"])
        except (TypeError, ValueError):
            length = -1
        if not 0 <= length <= api.MAX_BODY:
            status, data = 413, {
                "error": "the change is too big or has "
                "no length"
            }
            # the body is left unread: close after
            self.close_connection = True
        else:
            status, data = api.change(
                path,
                self.server.server_address,
                self.headers,
                self.rfile.read(length),
                self.server.token,
            )
        body = json.dumps(data).encode()
        self._reply(status, body, "application/json", True)

    def _send(self, with_body):
        path = self.path.split("?", 1)[0]
        status = 200
        answer = api.find(
            path,
            self.server.server_address,
            self.headers,
            self.server.prices,
        )
        if answer:
            status, data = answer
            body = json.dumps(data).encode()
            kind = "application/json"
        else:
            found = files.find(path, self.server.token)
            if found is None:
                self.send_error(404)
                return
            body, kind = found
        self._reply(status, body, kind, with_body)

    def _reply(self, status, body, kind, with_body):
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", len(body))
        self.send_header(
            "Cache-Control",
            (
                "no-store"
                if kind == "application/json"
                else "no-cache"
            ),
        )
        self.end_headers()
        if with_body:
            self.wfile.write(body)

    def log_request(self, code="-", size="-"):
        # a page asks every few seconds: only the
        # failures go to the log
        path = self.path.split("?", 1)[0]
        if (
            self.command != "POST"
            and path.startswith("/api/")
            and code == 200
        ):
            return
        super().log_request(code, size)

    def log_message(self, format, *args):
        # to the log file, not stderr
        log.info(
            "%s %s", self.address_string(), format % args
        )


def make_server(host, port):
    """a server on host:port (port 0: a free one),
    not serving yet, with its PriceCache in .prices
    and its token for the changes in .token;
    raises OSError if the port is taken"""
    server = ThreadingHTTPServer((host, port), Handler)
    server.prices = PriceCache(config.web_interval())
    # for the changes, new at every start
    server.token = secrets.token_urlsafe(32)
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
        why = e.strerror or str(e)
        if e.errno == errno.EADDRINUSE:
            # the most likely one: the web server of the
            # other shell, which has its own data
            why = (
                "the port is in use, e.g. by the web "
                "server of the other shell (./nxshell or "
                "./nxdemo, see 'ls web' there); or set "
                "config web port"
            )
        print(f"can't listen on {host}:{port}: {why}")
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
