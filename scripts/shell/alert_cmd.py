# alert_cmd: the shell side of the price alerts, the
# engine is engines/alerts.py
#
#   add alert basetrades <down|up> <n> percent
#   add alert gain <stock|all> <n> [percent]
#   rm alert <id>
#   ls alerts
#   run alerts [force], stop alerts
#
# AlertCommands implements them for the verb commands
# of commands.py; its tasks() are the alerts process's
# row in 'ls tasks'. print_basetrade_alerts() is the
# part of 'ls basetrades al' below its table

import textwrap
from datetime import datetime

from notifiers import notifier
import tasks_owner
from engines import alerts
from shell.interface import Commands
from shell.ui import (
    print_table,
    rule,
    BOLD,
    DIM,
    RESET,
    SELL_COLOR,
    TOTAL_STOCK_COLOR,
    confirm,
    parse_direction,
    parse_id,
    print_error,
    print_wrapped,
    space_separator,
    stock_names,
    supports_color,
    width,
)

NO_BREAK = "\u00a0"
# the terminal's default text color, keeps DIM on
DEFAULT_COLOR = "\033[39m"
ADD_USAGE = (
    "usage: add alert basetrades <down|up> <n> percent, "
    "or add alert gain <stock|all> <n> [percent]"
)


class AlertCommands(Commands):
    # an alert is a change in percent from the buying
    # price of every basetrade, or a gain of the held
    # stocks; one process checks them all
    name = "alert"
    plural = "alerts"
    order = 55
    # one process runs every alert: 'run alerts'
    plural_actions = ("ls", "run", "stop")

    def ls(self, arg):
        """
        ls alerts
            the saved alerts and whether the alerts
            process checks them; the levels per
            stock are in 'ls basetrades al'
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
            a notification each time the price
            of a basetrade's stock crosses <n>
            percent below (down) or above (up) its
            buying price, e.g. 'add alert basetrades
            down 10 percent'; sent again after the
            price went back past the level (by 1%
            of the buying price) and crosses it
            once more. starts the alerts process if
            it isn't running
        add alert gain <stock|all> <n> [percent]
            the same for the gain of a held stock
            (or of every one with all), from your
            trades as in xtop: an amount, or a % of
            the average buy price with percent; a
            negative <n> for a loss, e.g. 'add alert
            gain TSMX 100', 'add alert gain all 10
            percent'
        """
        args = arg.lower().split()
        if args and args[0] == "gain":
            self._add_gain(args[1:])
            return
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
        if not _notify_ready():
            return
        try:
            alert_id = alerts.create(
                args[0], direction, percent
            )
        except alerts.AlertError as e:
            print_error(f"error: {e}")
            return
        self._saved(alert_id)

    def _add_gain(self, args):
        """add alert gain <stock|all> <n> [percent]"""
        percent = len(args) == 3 and args[2] in (
            "percent",
            "%",
        )
        if len(args) != 2 and not percent:
            print_wrapped(ADD_USAGE)
            return
        percent = percent or args[1].endswith("%")
        try:
            value = float(args[1].rstrip("%"))
        except ValueError:
            print_error("error: <n> must be a number")
            return
        if not _notify_ready():
            return
        stock = (
            args[0] if args[0] == "all" else args[0].upper()
        )
        try:
            alert_id = alerts.create_gain(
                stock, value, percent
            )
        except alerts.AlertError as e:
            print_error(f"error: {e}")
            return
        self._saved(alert_id)

    def _saved(self, alert_id):
        """after an alert was saved: say so and start the
        alerts process if it isn't running"""
        saved = next(
            a
            for a in alerts.alerts_get_all()
            if a["Id"] == alert_id
        )
        print_wrapped(
            f"alert {alert_id} saved: {saved['For']} "
            f"{alerts.describe(saved)}"
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
        run alerts [force]
            start the alerts process that checks
            every alert (add alert starts it too);
            it keeps running when the shell is
            closed; force takes the background
            tasks over from the other device, see
            'help run ladder'
        """
        args = [a.lower() for a in arg.split()]
        if args not in ([], ["force"]):
            print_wrapped("usage: run alerts [force]")
            return
        self._start(force=bool(args))

    def stop(self, arg):
        """
        stop alerts
            stop the alerts process, the alerts
            stay saved
        """
        if arg.split():
            print_wrapped("usage: stop alerts")
            return
        if alerts.stop():
            print_wrapped("alerts stopped")
        else:
            print_wrapped("the alerts aren't running")

    def complete(self, action, args):
        if action == "add":
            if args and args[0].lower() == "gain":
                return [
                    list(alerts.TARGETS),
                    [*stock_names(), "all"],
                    [],
                    ["percent"],
                ]
            return [
                list(alerts.TARGETS),
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
    """the lines below the 'ls basetrades al' table: each
    alert's level per stock, the stocks past one and
    whether the alerts are checked"""
    for line in _level_lines(
        alerts.basetrade_levels(basetrades, prices),
        "basetrade",
    ):
        print(line)


def gain_alert_lines(prices):
    """the lines below the xtop table, like
    print_basetrade_alerts for the gain alerts but
    without the prices per stock; colored and fitted to
    width() already"""
    return _level_lines(
        alerts.gain_levels(prices), "gain", levels=False
    )


def _level_lines(rows, kind, levels=True):
    """the lines of rows, [(alert, [(stock, level,
    past)])]: each alert (with its level per stock, or
    without when not levels), the stocks past one and
    whether the alerts process runs"""
    if not rows:
        return _list_lines(
            f"no {kind} alerts, see 'help add alert'", []
        )
    lines = []
    for alert, stocks in rows:
        name = alerts.describe(alert)
        if alert["For"] == "gain":
            name = f"gain {name}"
        if not levels:
            lines += _list_lines(
                f"alert {alert['Id']} {name}", []
            )
            continue
        lines += _list_lines(
            f"alert {alert['Id']} {name}: ",
            [
                f"{stock} {at:.2f}"
                + ("!" if is_past else "")
                for stock, at, is_past in stocks
            ]
            or ["-"],
        )
    past_now = [
        f"{stock} #{alert['Id']}"
        for alert, stocks in rows
        for stock, _, is_past in stocks
        if is_past
    ]
    if past_now:
        lines += _list_lines("! in alert: ", past_now)
    return lines + _list_lines(_task_line(), [])


def _notify_ready():
    """True if the notify channel is set up, else
    print why"""
    if notifier.is_configured():
        return True
    print_error(notifier.setup_error())
    return False


def _list_lines(head, items):
    """head and the items joined by ', ', wrapped to
    width() with the next lines starting under the
    first item (2 spaces when head is long or there are
    no items); an item ('SOXL 18.00') is never split.
    dimmed, with a red !"""
    # a no-break space keeps an item on one line
    text = head + ", ".join(
        i.replace(" ", NO_BREAK) for i in items
    )
    indent = (
        len(head)
        if items and len(head) <= width() // 2
        else 2
    )
    lines = textwrap.wrap(
        text,
        width(),
        subsequent_indent=" " * indent,
        break_on_hyphens=False,
        break_long_words=False,
    )
    if not supports_color():
        return [l.replace(NO_BREAK, " ") for l in lines]
    return [
        # the line is dimmed: a red !, then the default
        # color, still dimmed
        DIM
        + l.replace(NO_BREAK, " ").replace(
            "!", f"{SELL_COLOR}!{DEFAULT_COLOR}"
        )
        + RESET
        for l in lines
    ]


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
    return "alerts: not running, see 'run alerts'"


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
            f"{'Alert':<12}",
            f"{'Created':<16}",
        ]
    )
    separator = rule(header)
    if color:
        lines = [
            f"{DIM}{header}{RESET}",
            f"{DIM}{separator}{RESET}",
        ]
    else:
        lines = [header, separator]
    for alert in saved:
        cols = [
            f"{alert['Id']:>2}",
            f"{alert['For']:<10.10}",
            f"{alerts.describe(alert):<12.12}",
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
        lines.append(sep.join(cols))
    print()
    print_table(lines)
    print()
