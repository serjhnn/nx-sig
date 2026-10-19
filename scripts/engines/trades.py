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
#   add(stock, trade_type, count, price)
#       check and record a trade
#   delete(stock, trade_id)
#       True if the trade was deleted
#   get(stock, trade_id)
#       the trade, or None
#   get_all(stock)
#       the trades of a stock, oldest first
#   total(stock)
#       (count held, average buy price)
#   summary()
#       [(stock, trades)] of the stocks that have trades
#
# a trade is {"Id", "Date", "Time", "Type", "Count",
# "Price"}, Type a TradeType

import storage
from storage import Stock, TradeType  # noqa: F401


class TradeError(Exception):
    """a trade can't be recorded; the text says why"""


def add(stock, trade_type, count, price):
    if count <= 0 or price <= 0:
        raise TradeError("count and price must be positive")
    storage.trade_add(stock, trade_type, count, price)


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
                         + price * count)
                        / (total_count + count)
            total_count += count
        else : # sell
            total_count -= count
    """
    total_count, avg_price = 0, 0.0
    for t in get_all(stock):
        total_count, avg_price = _apply(
            total_count,
            avg_price,
            t["Type"],
            t["Count"],
            t["Price"],
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
    total_count, avg_price, trade_type, count, price
):
    """(total_count, avg_price) after one more trade"""
    if trade_type == TradeType.BUY:
        if total_count + count > 0:
            avg_price = (
                avg_price * total_count + price * count
            ) / (total_count + count)
        total_count += count
    else:  # sell
        total_count -= count
    return total_count, avg_price
