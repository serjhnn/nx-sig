# web_cmd: the shell side of the web server, the engine
# is engines/web.py
#
#   run web, stop web
#
# WebCommands implements them for the verb commands of
# commands.py. print_web_status() is the 'web:' line of
# 'status'

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


def print_web_status():
    """print one line: whether the web server runs and
    its address"""
    if web.running_pid():
        url = (web.status() or {}).get("url") or web.url()
        print_wrapped(f"web: running at {url}")
    else:
        print_wrapped("web: not running, see 'run web'")
