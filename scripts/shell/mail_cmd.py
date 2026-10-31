# mail_cmd: the shell side of the mail broker
# (order_watcher.py, engines/mail_broker.py starts and
# stops it)
#
# MailBrokerCommands implements run [force], stop and
# ls (its state, last order and error, the last lines
# of its log); its tasks() are its row in 'ls tasks'.
# print_watcher_status() is its line in 'status'.
# not in the demo (./nxdemo)

import os
import re
from datetime import datetime

import config
import tasks_owner
from engines import mail_broker
from shell.interface import Commands
from shell.ui import (
    print_error,
    print_wrapped,
)

# order_watcher.py writes a heartbeat at least every 9
# minutes (IMAP IDLE renewal)
WATCHER_STALE_SECONDS = 15 * 60
# an order the mail broker could not record stays visible in
# 'status' this long
WATCHER_ERROR_DAYS = 7
# the log lines 'ls mail-broker' shows
LOG_LINES = 5
# '2026-10-31 14:29:40,612 INFO    name: text' of
# process.setup_logging, shown as '14:29:40 INFO
# name: text'
_LOG_LINE = re.compile(
    r"\d{4}-\d\d-\d\d (\d\d:\d\d:\d\d),\d+ +(\w+) +(.*)"
)


def print_watcher_status():
    """print one line about order_watcher.py from its
    heartbeat file"""
    if config.demo():
        print_wrapped("mail broker: not in the demo")
        return
    status = mail_broker.status()
    if not status or not status.get("updated"):
        print_wrapped("mail broker: not started")
        return
    try:
        updated = datetime.fromisoformat(status["updated"])
    except ValueError:
        print_wrapped("mail broker: unknown state")
        return

    state = status.get("state", "")
    age = (datetime.now() - updated).total_seconds()
    if state == "stopped":
        line = f"mail broker: stopped {updated:%d.%m %H:%M}"
    elif age > WATCHER_STALE_SECONDS:
        line = (
            "mail broker: not responding, last seen "
            f"{updated:%d.%m %H:%M}"
        )
    elif state in ("starting", "connected", "waiting"):
        line = (
            "mail broker: running, checked "
            f"{updated:%H:%M}"
        )
    else:
        line = f"mail broker: {state}, {updated:%H:%M}"
    if status.get("last_order"):
        line += f", last order {status['last_order']}"
    print_wrapped(line)

    error = status.get("last_error") or {}
    try:
        error_time = (
            datetime.fromisoformat(error["time"])
            if error.get("time")
            else None
        )
    except ValueError:
        error_time = None
    recent_error = (
        error_time
        and (datetime.now() - error_time).days
        < WATCHER_ERROR_DAYS
    )
    if recent_error:
        print_error(
            "mail broker error "
            f"{error_time:%d.%m %H:%M}: "
            f"{error.get('text', '')}"
        )
    if status.get("log") and (
        recent_error
        or state.startswith("crashed")
        or age > WATCHER_STALE_SECONDS
    ):
        print_wrapped(
            f"log: {os.path.relpath(status['log'])}"
        )


def _mail_broker_task():
    """the 'ls tasks' row of the mail broker, or None
    if it isn't running"""
    pid = mail_broker.running_pid()
    if pid is None:
        return None
    status = mail_broker.status() or {}
    started = updated = None
    try:
        started = datetime.fromisoformat(status["started"])
        updated = datetime.fromisoformat(status["updated"])
    except (KeyError, TypeError, ValueError):
        pass
    state = status.get("state", "") if updated else "-"
    healthy = state in ("starting", "connected", "waiting")
    if updated:
        age = (datetime.now() - updated).total_seconds()
        if age > WATCHER_STALE_SECONDS:
            state, healthy = "no reply", False
    return {
        "id": "-",
        "task": "mail-broker",
        "pid": pid,
        "started": started,
        "state": state,
        "healthy": healthy,
    }


def _when(text):
    """'31.10 14:29' of an ISO time, '-' if none"""
    try:
        return f"{datetime.fromisoformat(text):%d.%m %H:%M}"
    except (TypeError, ValueError):
        return "-"


def _log_line(line):
    """a log line without its date and milliseconds,
    so it fits the screen better"""
    match = _LOG_LINE.fullmatch(line)
    if not match:
        return line
    return " ".join(match.groups())


def _not_in_demo():
    """True, after saying so, in the demo: it would
    record real broker emails as trades"""
    if config.demo():
        print_error(
            "the mail broker is not in the demo, it "
            "records real broker emails"
        )
    return config.demo()


class MailBrokerCommands(Commands):
    name = "mail-broker"
    order = 60
    # one mail broker: 'ls mail-broker'
    plural_actions = ()

    def ls(self, arg):
        """
        ls mail-broker
            whether it runs, its state, the last
            order and error, and the last lines of
            its log
        """
        if arg.split():
            print_wrapped("usage: ls mail-broker")
            return
        if _not_in_demo():
            return
        pid = mail_broker.running_pid()
        print_wrapped(
            f"mail broker: running (pid {pid})"
            if pid
            else "mail broker: not running"
        )
        status = mail_broker.status() or {}
        if status.get("state"):
            print_wrapped(
                f"state: {status['state']}, "
                f"{_when(status.get('updated'))}"
            )
            print_wrapped(
                f"started: {_when(status.get('started'))}"
            )
        if status.get("last_order"):
            print_wrapped(
                f"last order: {status['last_order']}"
            )
        error = status.get("last_error") or {}
        if error.get("text"):
            print_error(
                f"last error {_when(error.get('time'))}: "
                f"{error['text']}"
            )
        lines = mail_broker.log_tail(LOG_LINES)
        if lines:
            log = os.path.relpath(mail_broker.log_path())
            print_wrapped(f"log ({log}):")
            for line in lines:
                print_wrapped(f"  {_log_line(line)}")

    def run(self, arg):
        """
        run mail-broker [force]
            start the mail broker that records
            broker order emails as trades; it keeps
            running when the shell is closed; force
            takes the background tasks over from the
            other device, see 'help run ladder'
        """
        args = [a.lower() for a in arg.split()]
        if args not in ([], ["force"]):
            print_wrapped("usage: run mail-broker [force]")
            return
        if _not_in_demo():
            return
        force = args == ["force"]
        if force and tasks_owner.lost():
            print_wrapped(
                "taking over the background tasks from "
                + tasks_owner.describe(tasks_owner.owner())
            )
        # it waits 3s to catch a crash at start
        print_wrapped("starting the mail broker...")
        try:
            pid = mail_broker.start(force)
        except mail_broker.MailBrokerError as e:
            print_error(f"error: {e}")
            if "right after starting" in str(e):
                log = os.path.relpath(
                    mail_broker.log_path()
                )
                print_wrapped(f"log: {log}")
            return
        print_wrapped(f"mail broker started (pid {pid})")

    def stop(self, arg):
        """
        stop mail-broker
            stop the mail broker, after a clean
            logout
        """
        if arg.split():
            print_wrapped("usage: stop mail-broker")
            return
        if _not_in_demo():
            return
        # it waits up to 20s for a clean logout
        print_wrapped("stopping the mail broker...")
        if mail_broker.stop():
            print_wrapped("mail broker stopped")
        else:
            print_wrapped("mail broker is not running")

    def complete(self, action, args):
        return [["force"]] if action == "run" else []

    def tasks(self):
        task = _mail_broker_task()
        return [task] if task else []
