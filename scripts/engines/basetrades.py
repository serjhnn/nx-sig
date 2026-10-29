# basetrades: the basetrades engine, the last price you
# bought each stock at, one per stock
#
#   python tests/test_basetrades.py   the tests
#
# the shell's basetrade commands (shell/base_trade_cmd.py)
# and the alerts use it; storage.py only reads and writes
# base_trades.csv. a basetrade doesn't change the trades
# or their totals.
#
# public functions:
#   save(stock, price, count)
#       check and save the basetrade of a Stock, True if
#       it replaced an older one
#   delete(name)
#       the deleted basetrade of a stock name, or None
#   get(name)
#       the basetrade of a stock name, or None
#   get_all()
#       the basetrades in config order
#   from_trades(stock)
#       the lowest buy of a Stock since its last sell
#       (any sell, partial too), the later one of equal
#       prices; it isn't saved
#
# a basetrade is {"Stock" (name), "Price", "Count"}

import storage
from engines import trades
from storage import Stock, TradeType  # noqa: F401


class BaseTradeError(Exception):
    """a basetrade can't be saved; the text says why"""


def save(stock, price, count):
    if price <= 0 or count <= 0:
        raise BaseTradeError(
            "price and count must be positive"
        )
    return storage.basetrade_set(stock.name, price, count)


def delete(name):
    return storage.basetrade_delete(name)


def get(name):
    return next(
        (b for b in get_all() if b["Stock"] == name),
        None,
    )


def get_all():
    return storage.basetrades_get_all()


def from_trades(stock):
    lowest = None
    for t in trades.get_all(stock):
        if t["Type"] == TradeType.SELL:
            lowest = None
        elif (
            lowest is None or t["Price"] <= lowest["Price"]
        ):
            lowest = t
    if lowest is None:
        raise BaseTradeError(
            f"no buys of {stock.name} since the last "
            "sell, see 'ls trades'"
        )
    return lowest
