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
#   lowest_buys()
#       [(stock, from_trades(stock) or None)] of each
#       stock that has trades
#   all_from_trades(found=None)
#       save the lowest buy of each stock of found
#       (lowest_buys() by default) as its basetrade:
#       [(stock, buy, replaced)], buy and replaced
#       None for a stock without one (skipped); a
#       BaseTradeError when no stock has one
#
# a basetrade is {"Stock" (name), "Price", "Count"}

import storage
from engines import trades
from storage import TradeType

# for the shell, which doesn't import storage
Stock = storage.Stock


# what a basetrade from the trades is
LOWEST = "lowest buy since the last sell"
# when no stock has one
NO_LOWEST = f"no stock has a {LOWEST}, see 'ls trades'"


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
    lowest, sold = None, False
    for t in trades.get_all(stock):
        if t["Type"] == TradeType.SELL:
            lowest, sold = None, True
        elif (
            lowest is None or t["Price"] <= lowest["Price"]
        ):
            lowest = t
    if lowest is None:
        since = " since the last sell" if sold else ""
        raise BaseTradeError(
            f"no buys of {stock.name}{since}, see "
            "'ls trades'"
        )
    return lowest


def lowest_buys():
    found = []
    for stock, _ in trades.summary():
        try:
            buy = from_trades(stock)
        except BaseTradeError:
            buy = None
        found.append((stock, buy))
    return found


def all_from_trades(found=None):
    if found is None:
        found = lowest_buys()
    if not any(buy for _, buy in found):
        raise BaseTradeError(NO_LOWEST)
    saved = []
    for stock, buy in found:
        replaced = None
        if buy is not None:
            replaced = save(
                stock, buy["Price"], buy["Count"]
            )
        saved.append((stock, buy, replaced))
    return saved
