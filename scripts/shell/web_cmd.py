# web_cmd: the shell side of the web server, the engine
# is engines/web.py
#
#   run web, stop web, ls web
#
# WebCommands implements them for the verb commands of
# commands.py; its tasks() are the web server's row in
# 'ls tasks'. print_web_status() is the 'web:' line of
# 'status'


import config
from engines import web
from shell.interface import Commands
from shell.ui import (
    print_error,
    print_log_tail,
    print_wrapped,
    short_time,
)

# the log lines 'ls web' shows
LOG_LINES = 5
# hosts only this device can open
LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")


class WebCommands(Commands):
    name = "web"
    order = 65
    # one web server: 'ls web'
    plural_actions = ()

    def ls(self, arg):
        """
        ls web
            whether the web server runs, its address
            and who can open it, its state and the
            last lines of its log
        """
        if arg.split():
            print_wrapped("usage: ls web")
            return
        pid = web.running_pid()
        print_wrapped(
            f"web server: running (pid {pid})"
            if pid
            else "web server: not running, see 'run web'"
        )
        default = (
            config.web_host() == config.DEFAULT_WEB_HOST
            and config.web_port() == config.DEFAULT_WEB_PORT
        )
        where = "default" if default else 'config "web"'
        print_wrapped(f"address: {web.url()} ({where})")
        print_wrapped(f"open from: {_reach()}")
        status = web.status() or {}
        if pid and status.get("state"):
            print_wrapped(
                f"state: {status['state']}, "
                f"{short_time(status.get('updated'))}"
            )
            print_wrapped(
                "started: "
                + short_time(status.get("started"))
            )
        print_log_tail(
            web.log_path(), web.log_tail(LOG_LINES)
        )

    def run(self, arg):
        """
        run web
            start the web server that shows the
            nX-sig logo, at config "web" "host" and
            "port" (http://127.0.0.1:8080/ by
            default, only this device); it keeps
            running when the shell is closed
        """
        if arg.split():
            print_wrapped("usage: run web")
            return
        try:
            pid = web.start()
        except web.WebError as e:
            print_error(f"error: {e}")
            return
        print_wrapped(
            f"web server started (pid {pid}), open "
            + web.url()
        )

    def stop(self, arg):
        """
        stop web
            stop the web server
        """
        if arg.split():
            print_wrapped("usage: stop web")
            return
        if web.stop():
            print_wrapped("web server stopped")
        else:
            print_wrapped("the web server isn't running")

    def tasks(self):
        task = web.task()
        return [task] if task else []


def _reach():
    """who can open the page, by config "web" "host" """
    host = config.web_host()
    if host in LOCAL_HOSTS:
        return "only this device"
    if host in ("0.0.0.0", "::"):
        return "this device and the network"
    return f"devices that reach {host}"


def print_web_status():
    """print one line: whether the web server runs and
    its address"""
    if web.running_pid():
        url = (web.status() or {}).get("url") or web.url()
        print_wrapped(f"web: running at {url}")
    else:
        print_wrapped("web: not running, see 'run web'")
