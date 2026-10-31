# web_cmd: the shell side of the web server, the engine
# is engines/web.py
#
#   run web, stop web
#
# WebCommands implements them for the verb commands of
# commands.py; its tasks() are the web server's row in
# 'ls tasks'. print_web_status() is the 'web:' line of
# 'status'

from datetime import datetime

from engines import web
from shell.interface import Commands
from shell.ui import print_error, print_wrapped


class WebCommands(Commands):
    name = "web"
    order = 65

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
        task = _web_task()
        return [task] if task else []


def _web_task():
    """the 'ls tasks' row of the web server, or None
    if it isn't running"""
    pid = web.running_pid()
    if not pid:
        return None
    status = web.status() or {}
    try:
        started = datetime.fromisoformat(status["started"])
    except (KeyError, TypeError, ValueError):
        started = None
    state = status.get("state") or "-"
    return {
        "id": "-",
        "task": "web",
        "pid": pid,
        "started": started,
        "state": state,
        "healthy": state in ("starting", "serving"),
    }


def print_web_status():
    """print one line: whether the web server runs and
    its address"""
    if web.running_pid():
        url = (web.status() or {}).get("url") or web.url()
        print_wrapped(f"web: running at {url}")
    else:
        print_wrapped("web: not running, see 'run web'")
