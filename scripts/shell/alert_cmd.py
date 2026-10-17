# alert_cmd: the shell side of the price alerts, the
# engine is scripts/alerts.py
#
#   add alert basetrades <down|up> <n> percent
#   rm alert <id>
#   ls alerts
#   run alert [force], stop alert
#
# AlertCommands implements them for the verb commands
# of commands.py; its tasks() are the alerts process's
# row in 'ls tasks'. print_basetrade_alerts() is the
# part of 'ls basetrades' below its table

import textwrap
from datetime import datetime

import alerts
import tasks_owner
from telegram_notify import (
    is_configured as telegram_configured,
)
from shell.interface import Commands
from shell.ui import (
    BOLD,
    DIM,
    RESET,
    TOTAL_STOCK_COLOR,
    confirm,
    parse_direction,
    parse_id,
    print_dim,
    print_error,
    print_wrapped,
    space_separator,
    supports_color,
    width,
)

NO_BREAK = "\u00a0"
ADD_USAGE = (
    "usage: add alert basetrades <down|up> <n> percent"
)


class AlertCommands(Commands):
    # an alert is a change in percent from the buying
    # price of every basetrade, one process checks them
    # all
    name = "alert"
    plural = "alerts"
    order = 55

    def ls(self, arg):
        """
        ls alerts
            the saved alerts and whether the alerts
            process checks them; the levels per
            stock are in 'ls basetrades'
        """
        if arg.split():
            print_wrapped("usage: ls alerts")
            return
        saved = alerts.alerts_get_all()
        if not saved:
            print_wrapped(
                "no alerts yet, see 'help add alert'"
            )
            return
        _print_alerts(saved)
        print_wrapped(_task_line())

    def add(self, arg):
        """
        add alert basetrades <down|up> <n> percent
            a Telegram message each time the price
            of a basetrade's stock crosses <n>
            percent below (down) or above (up) its
            buying price, e.g. 'add alert basetrades
            down 10 percent'; sent again after the
            price went back past the level (by 1%
            of the buying price) and crosses it
            once more. starts the alerts process if
            it isn't running
        """
        args = arg.lower().split()
        if len(args) != 4 or args[3] not in (
            "percent",
            "%",
        ):
            print_wrapped(ADD_USAGE)
            return
        try:
            direction = parse_direction(args[1])
            percent = float(args[2].rstrip("%"))
        except ValueError as e:
            print_error(
                f"error: {e}"
                if "direction" in str(e)
                else "error: <n> must be a number"
            )
            return
        if not telegram_configured():
            print_error(
                "error: Telegram isn't set up, add TOKEN "
                "and CHAT_ID to .env"
            )
            return
        try:
            alert_id = alerts.create(
                args[0], direction, percent
            )
        except alerts.AlertError as e:
            print_error(f"error: {e}")
            return
        print_wrapped(
            f"alert {alert_id} saved: basetrades "
            f"{direction} {percent:g}%"
        )
        if not alerts.running_pid():
            self._start()

    def rm(self, arg):
        """
        rm alert <id>
            delete alert <id> after confirmation;
            the alerts process stops when no alert
            is left
        """
        args = arg.split()
        alert_id = (
            parse_id(args[0]) if len(args) == 1 else None
        )
        if alert_id is None:
            print_wrapped("usage: rm alert <id>")
            return
        found = next(
            (
                a
                for a in alerts.alerts_get_all()
                if a["Id"] == alert_id
            ),
            None,
        )
        if found is None:
            print_error(
                f"error: no alert {alert_id}, see "
                "'ls alerts'"
            )
            return
        if not confirm(
            f"delete alert {alert_id}: {found['For']} "
            f"{alerts.describe(found)}? [y/N] "
        ):
            print_wrapped("cancelled")
            return
        was_running = bool(alerts.running_pid())
        alerts.remove(alert_id)
        line = f"deleted alert {alert_id}"
        if was_running and not alerts.running_pid():
            line += ", no alerts left: alerts stopped"
        print_wrapped(line)

    def run(self, arg):
        """
        run alert [force]
            start the alerts process that checks
            every alert (add alert starts it too);
            it keeps running when the shell is
            closed; force takes the background
            tasks over from the other device, see
            'help run ladder'
        """
        args = [a.lower() for a in arg.split()]
        if args not in ([], ["force"]):
            print_wrapped("usage: run alert [force]")
            return
        self._start(force=bool(args))

    def stop(self, arg):
        """
        stop alert
            stop the alerts process, the alerts
            stay saved
        """
        if arg.split():
            print_wrapped("usage: stop alert")
            return
        if alerts.stop():
            print_wrapped("alerts stopped")
        else:
            print_wrapped("the alerts aren't running")

    def complete(self, action, args):
        if action == "add":
            return [
                ["basetrades"],
                ["down", "up"],
                [],
                ["percent"],
            ]
        if action == "rm":
            return [
                [
                    str(a["Id"])
                    for a in alerts.alerts_get_all()
                ]
            ]
        if action == "run":
            return [["force"]]
        return []

    def tasks(self):
        task = _alerts_task()
        return [task] if task else []

    def _start(self, force=False):
        if force and tasks_owner.lost():
            print_wrapped(
                "taking over the background tasks from "
                + tasks_owner.describe(tasks_owner.owner())
            )
        try:
            pid = alerts.start(force)
        except alerts.AlertError as e:
            print_error(f"error: {e}")
            return
        print_wrapped(f"alerts started (pid {pid})")


def print_basetrade_alerts(basetrades, prices):
    """the lines below the 'ls basetrades' table: each
    alert's level per stock, the stocks past one and
    whether the alerts are checked"""
    rows = alerts.basetrade_levels(basetrades, prices)
    if not rows:
        print_wrapped("no alerts, see 'help add alert'")
        return
    for alert, stocks in rows:
        _print_list(
            f"alert {alert['Id']} "
            f"{alerts.describe(alert)}: ",
            [
                f"{name} {at:.2f}"
                + ("!" if is_past else "")
                for name, at, is_past in stocks
            ],
        )
    past_now = [
        f"{name} #{alert['Id']}"
        for alert, stocks in rows
        for name, _, is_past in stocks
        if is_past
    ]
    if past_now:
        _print_list("! in alert: ", past_now)
    print_wrapped(_task_line())


def _print_list(head, items):
    """head and the items joined by ', ', wrapped to
    width() with the next lines starting under the
    first item; an item ('SOXL 18.00') is never split"""
    # a no-break space keeps an item on one line
    text = head + ", ".join(
        i.replace(" ", NO_BREAK) for i in items or ["-"]
    )
    indent = len(head) if len(head) <= width() // 2 else 2
    lines = textwrap.wrap(
        text,
        width(),
        subsequent_indent=" " * indent,
        break_on_hyphens=False,
        break_long_words=False,
    )
    for line in lines:
        print_dim(line.replace(NO_BREAK, " "))


def _task_line():
    """whether the alerts process runs"""
    if alerts.running_pid():
        updated = _time(alerts.status() or {}, "updated")
        if updated is None:
            return "alerts: running"
        return (
            f"alerts: running, last check {updated:%H:%M}"
        )
    current = tasks_owner.owner()
    if current and tasks_owner.lost():
        return (
            "alerts: not running here, the background "
            f"tasks run on {tasks_owner.describe(current)}"
        )
    return "alerts: not running, see 'run alert'"


def _time(status, key):
    """the time status[key] of a heartbeat, or None"""
    try:
        return datetime.fromisoformat(status[key])
    except (KeyError, TypeError, ValueError):
        return None


def _alerts_task():
    """the 'ls tasks' row of the alerts process, or
    None if it isn't running"""
    pid = alerts.running_pid()
    if not pid:
        return None
    status = alerts.status() or {}
    started, updated = (
        _time(status, "started"),
        _time(status, "updated"),
    )
    state = status.get("state") or "-"
    healthy = state in ("starting", "waiting")
    if updated:
        age = (datetime.now() - updated).total_seconds()
        if age > alerts.STALE_SECONDS:
            state, healthy = "no reply", False
    return {
        "id": "-",
        "task": "alerts",
        "pid": pid,
        "started": started,
        "state": state,
        "healthy": healthy,
    }


def _print_alerts(saved):
    """the ls alerts table: Id, For, Alert, Created"""
    color = supports_color()
    sep = space_separator(4, 2)
    header = sep.join(
        [
            f"{'Id':>2}",
            f"{'For':<10}",
            f"{'Alert':<10}",
            "Created",
        ]
    )
    separator = "-" * width()
    print()
    if color:
        print(f"{DIM}{header}{RESET}")
        print(f"{DIM}{separator}{RESET}")
    else:
        print(header)
        print(separator)
    for alert in saved:
        cols = [
            f"{alert['Id']:>2}",
            f"{alert['For']:<10.10}",
            f"{alerts.describe(alert):<10.10}",
            f"{alert['Created']:<16.16}",
        ]
        if color:
            cols = [
                f"{DIM}{cols[0]}{RESET}",
                f"{BOLD}{TOTAL_STOCK_COLOR}"
                f"{cols[1]}{RESET}",
                cols[2],
                f"{DIM}{cols[3]}{RESET}",
            ]
        print(sep.join(cols))
    print()
