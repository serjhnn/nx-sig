# positions: the stocks you hold and their gain/loss
# at given prices, for the shell ('status', 'xtop',
# 'ls stocks') and the web page
#
#   python tests/test_positions.py   the tests
#
# the counts and average buy prices come from the
# trades engine; the prices are passed in, this
# module requests none.
#
# public functions:
#   held()
#       [(stock, count, average buy price)] of every
#       stock whose count is not 0
#   rows(prices)
#       one dict per held stock with its gain at
#       prices ({stock name: price})
#   row(stock, count, avg_price, prices)
#       the dict of one stock (see rows())
#   total(rows)
#       (gain, cost, pct) of the rows that have a
#       price

from engines import trades
from storage import Stock


def held():
    """(stock, count, average buy price) of every stock
    whose count is not 0"""
    positions = [
        (stock, *trades.total(stock)) for stock in Stock
    ]
    return [p for p in positions if p[1] != 0]


def rows(prices):
    """one dict per held stock: stock, count, avg,
    cost (abs(count) * avg), price, gain (count *
    (price - avg)) and pct (gain % of cost); price,
    gain and pct are None without a price, pct also
    without a cost"""
    # read again each time: the mail broker may record
    # a trade between two calls
    return [
        row(stock, count, avg_price, prices)
        for stock, count, avg_price in held()
    ]


def row(stock, count, avg_price, prices):
    """the dict of one stock with count at avg_price,
    at prices (see rows())"""
    found = {
        "stock": stock,
        "count": count,
        "avg": avg_price,
        "price": None,
        "gain": None,
        "pct": None,
        "cost": abs(count) * avg_price,
    }
    if stock.name in prices:
        found["price"] = prices[stock.name]
        found["gain"] = count * (found["price"] - avg_price)
        if found["cost"]:
            found["pct"] = (
                found["gain"] / found["cost"] * 100
            )
    return found


def total(rows):
    """(gain, cost, pct) of the rows that have a price:
    the sum of their gains and costs, and the gain % of
    the cost (None without a cost)"""
    priced = [r for r in rows if r["gain"] is not None]
    gain = sum(r["gain"] for r in priced)
    cost = sum(r["cost"] for r in priced)
    pct = gain / cost * 100 if cost else None
    return gain, cost, pct
