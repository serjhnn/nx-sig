# trades: the trades engine, your buys and sells and
# what they add up to
#
#   python tests/test_trades.py   the tests
#
# the shell's trade commands (shell/trade_cmd.py), the
# alerts, the chart and the mail broker use it;
# storage.py only reads and writes the trades files.
#
# public functions:
#   add(stock, trade_type, count, price, date=None,
#       time=None)
#       check and record a trade, at date and time
#       ("dd.mm.yyyy", "hh:mm") or now
#   import_statement(path)
#       record the trades of a bank statement csv (see
#       engines/statement.py), return (added, skipped)
#   delete(stock, trade_id)
#       True if the trade was deleted
#   get(stock, trade_id)
#       the trade, or None
#   get_all(stock)
#       the trades of a stock, oldest first
#   total(stock)
#       (count held, average buy price); each buy
#       adds config "fee" to its cost
#   summary()
#       [(stock, trades)] of the stocks that have trades
#
# a trade is {"Id", "Date", "Time", "Type", "Count",
# "Price"}, Type a TradeType

from datetime import datetime

import config
import storage
from engines import statement
from storage import Stock, TradeType  # noqa: F401


class TradeError(Exception):
    """a trade can't be recorded; the text says why"""


def add(
    stock, trade_type, count, price, date=None, time=None
):
    if count <= 0 or price <= 0:
        raise TradeError("count and price must be positive")
    if (date is None) != (time is None):
        raise TradeError("give both date and time")
    if date is not None:
        try:
            datetime.strptime(
                f"{date} {time}", "%d.%m.%Y %H:%M"
            )
        except ValueError:
            raise TradeError(
                f"bad date or time: {date} {time}"
            ) from None
    storage.trade_add(
        stock, trade_type, count, price, date, time
    )


def import_statement(path):
    """
    record the trades of the bank statement at path,
    oldest first. returns (added, skipped): added the
    statement trades recorded (see statement.py),
    skipped a text for each one left out:
        "row 4: count 1.50"
        "order 460827: no stock VOO"
        "order 699534: already recorded"
    a trade is already recorded if its stock has one
    with the same date, time, type, count and price;
    so a statement can be imported again
    OSError if the file can't be read
    """
    found, bad_rows = statement.parse_statement(path)
    skipped = [
        f"row {number}: {reason}"
        for number, reason in bad_rows
    ]
    added = []
    # the recorded trades of each stock, each one
    # matches one statement trade at most
    recorded = {}
    for t in found:
        label = f"order {t['Order']}"
        stock = Stock.__members__.get(t["Stock"])
        if stock is None:
            skipped.append(
                f"{label}: no stock {t['Stock']}"
            )
            continue
        if stock not in recorded:
            recorded[stock] = [
                _key(r) for r in get_all(stock)
            ]
        if _key(t) in recorded[stock]:
            recorded[stock].remove(_key(t))
            skipped.append(f"{label}: already recorded")
            continue
        add(
            stock,
            t["Type"],
            t["Count"],
            t["Price"],
            t["Date"],
            t["Time"],
        )
        added.append(t)
    return added, skipped


def _key(trade):
    return (
        trade["Date"],
        trade["Time"],
        trade["Type"],
        trade["Count"],
        round(trade["Price"], 4),
    )


def delete(stock, trade_id):
    return storage.trade_delete(stock, trade_id)


def get(stock, trade_id):
    return next(
        (t for t in get_all(stock) if t["Id"] == trade_id),
        None,
    )


def get_all(stock):
    return storage.trades_get_all(stock)


def total(stock):
    """
    computed from the trades in order:
        if BUY :
            avg_price = (avg_price * total_count
                         + price * count + fee)
                        / (total_count + count)
            total_count += count
        else : # sell
            total_count -= count
    fee is config "fee", the fee of one trade; a
    sell's fee doesn't change the average
    """
    fee = config.fee()
    total_count, avg_price = 0, 0.0
    for t in get_all(stock):
        total_count, avg_price = _apply(
            total_count,
            avg_price,
            t["Type"],
            t["Count"],
            t["Price"],
            fee,
        )
    return total_count, avg_price


def summary():
    found = []
    for stock in Stock:
        trades = get_all(stock)
        if trades:
            found.append((stock, trades))
    return found


def _apply(
    total_count,
    avg_price,
    trade_type,
    count,
    price,
    fee=0,
):
    """(total_count, avg_price) after one more trade;
    a buy's fee is added to its cost"""
    if trade_type == TradeType.BUY:
        if total_count + count > 0:
            avg_price = (
                avg_price * total_count
                + price * count
                + fee
            ) / (total_count + count)
        total_count += count
    else:  # sell
        total_count -= count
    return total_count, avg_price
