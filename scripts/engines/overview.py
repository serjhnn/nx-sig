# overview: everything 'status' shows, in one place,
# for the shell and the web page
#
#   python tests/test_overview.py   the tests
#
# it only gathers what the other engines give; the
# prices are passed in, this module requests none.
#
# public functions:
#   tasks()
#       the task rows of every running background task
#       (ladders, alerts, mail broker, web server), in
#       the order of 'ls tasks'
#   last_trades(count=5)
#       the newest trades of all stocks
#   status(prices)
#       the positions and their total at prices, the
#       tasks, the mail broker, the device that runs
#       the background tasks, the last trades

from datetime import datetime

import config
import tasks_owner
from engines import (
    alerts,
    ladder,
    mail_broker,
    positions,
    trades,
    web,
)

LAST_TRADES = 5


def tasks():
    """the task rows (see engines/ladder.py) of the
    running background tasks"""
    rows = ladder.tasks()
    for one in (alerts.task, mail_broker.task, web.task):
        row = one()
        if row:
            rows.append(row)
    return rows


def last_trades(count=LAST_TRADES):
    """the newest count trades of all stocks, newest
    first: each trade with its "Stock" (a Stock)"""
    found = [
        dict(trade, Stock=stock)
        for stock, stock_trades in trades.summary()
        for trade in stock_trades
    ]
    found.sort(key=_when, reverse=True)
    return found[:count]


def _when(trade):
    """the sort key of a trade: its date and time,
    then its Id (two trades in one minute)"""
    try:
        when = datetime.strptime(
            f"{trade['Date']} {trade['Time']}",
            "%d.%m.%Y %H:%M",
        )
    except (KeyError, TypeError, ValueError):
        when = datetime.min
    return when, trade.get("Id") or 0


def status(prices):
    """what 'status' shows, at prices ({stock name:
    price}):

    {"positions": the rows of positions.rows(),
     "total": (gain, cost, pct) of positions.total(),
     "tasks": tasks(),
     "mail_broker": mail_broker.summary(),
     "owner": the device that runs the background
              tasks (tasks_owner.owner()) or None,
     "here": True if it is this device,
     "demo": True in the demo,
     "last_trades": last_trades()}"""
    rows = positions.rows(prices)
    owner = tasks_owner.owner()
    here = bool(
        owner
        and owner["id"] == tasks_owner.this_device()["id"]
    )
    return {
        "positions": rows,
        "total": positions.total(rows),
        "tasks": tasks(),
        "mail_broker": mail_broker.summary(),
        "owner": owner,
        "here": here,
        "demo": config.demo(),
        "last_trades": last_trades(),
    }
