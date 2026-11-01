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

import config
import tasks_owner
from engines import mail_broker
from shell.interface import Commands
from shell.ui import (
    print_error,
    print_log_tail,
    print_wrapped,
    short_time,
)

# the log lines 'ls mail-broker' shows
LOG_LINES = 5


def print_watcher_status():
    """print the line about the mail broker in
    'status', and its recent error and log"""
    info = mail_broker.summary()
    state, updated = info["state"], info["updated"]
    if state == "demo":
        print_wrapped("mail broker: not in the demo")
        return
    if state == "not started":
        print_wrapped("mail broker: not started")
        return
    if state == "unknown":
        print_wrapped("mail broker: unknown state")
        return
    if state == "stopped":
        line = f"mail broker: stopped {updated:%d.%m %H:%M}"
    elif state == "no reply":
        line = (
            "mail broker: not responding, last seen "
            f"{updated:%d.%m %H:%M}"
        )
    elif state == "running":
        line = (
            "mail broker: running, checked "
            f"{updated:%H:%M}"
        )
    else:
        line = f"mail broker: {state}, {updated:%H:%M}"
    if info["last_order"]:
        line += f", last order {info['last_order']}"
    print_wrapped(line)
    error = info["error"]
    if error:
        print_error(
            "mail broker error "
            f"{error['time']:%d.%m %H:%M}: "
            f"{error['text']}"
        )
    if info["log"]:
        print_wrapped(
            f"log: {os.path.relpath(info['log'])}"
        )


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
            updated = short_time(status.get("updated"))
            started = short_time(status.get("started"))
            print_wrapped(
                f"state: {status['state']}, {updated}"
            )
            print_wrapped(f"started: {started}")
        if status.get("last_order"):
            print_wrapped(
                f"last order: {status['last_order']}"
            )
        error = status.get("last_error") or {}
        if error.get("text"):
            when = short_time(error.get("time"))
            print_error(
                f"last error {when}: {error['text']}"
            )
        print_log_tail(
            mail_broker.log_path(),
            mail_broker.log_tail(LOG_LINES),
        )

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
        task = mail_broker.task()
        return [task] if task else []
