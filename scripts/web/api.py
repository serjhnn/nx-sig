# api: the JSON the web pages ask for
#
#   python tests/test_web.py   the tests
#
# the paths, only when the server listens on
# 127.0.0.1: the positions and trades are private,
# any other address gets 403:
#   /api/status        the main page's data, status()
#   /api/trades        the stocks that have trades,
#                      trades()
#   /api/trades/<s>    the trades of stock s,
#                      stock_trades(); 404 for a stock
#                      not in the config
# each answer also has the prices' time and error,
# the interval and demo (see prices()).
#
# public functions:
#   find(path, host, cache)
#       (http status, data) of path, None if it isn't
#       an /api path
#   prices(cache)
#       the cached prices and what every answer has
#   status(cache)
#   trades(cache)
#   stock_trades(cache, name)
#       the data of the paths above

import logging

import config
from engines import overview, positions
from engines import trades as trades_engine
from storage import Stock

# the addresses the api answers on
PRIVATE_HOSTS = ("127.0.0.1", "::1")
PRIVATE_ERROR = (
    "the positions are shown only when the web server "
    "listens on 127.0.0.1 (config web host)"
)
log = logging.getLogger("web")


class NotFound(Exception):
    """a 404 of the api; the text says why"""


def find(path, host, cache):
    """(http status, data) of path (without its
    ?query) for a server on host with the price cache
    cache; None if it isn't an api path"""
    answer = PATHS.get(path)
    if answer is None:
        for prefix, one in PREFIXES.items():
            rest = path.removeprefix(prefix)
            if rest != path and rest and "/" not in rest:
                answer = _with(one, rest)
                break
        else:
            return None
    if host not in PRIVATE_HOSTS:
        return 403, {"error": PRIVATE_ERROR}
    try:
        return 200, answer(cache)
    except NotFound as e:
        return 404, {"error": str(e)}
    except Exception:
        log.exception("%s failed", path)
        return 500, {
            "error": "can't read the data, see "
            "the web log"
        }


def status(cache):
    """the data of /api/status: overview.status() at
    the cached prices, ready for json; times are ISO
    strings, numbers as they are (the page rounds)

    what every answer has (see prices()) and
    {"positions": [{"stock", "count", "avg", "cost",
                    "price", "gain", "pct"}],
     "total": {"gain", "cost", "pct"},
     "tasks": [{"id", "task", "pid", "started",
                "state", "healthy"}],
     "mail_broker": {"state", "updated",
                     "last_order", "error"},
     "owner": {"name", "here"} or None,
     "last_trades": [{"stock", "id", "date", "time",
                      "type", "count", "price"}]}"""
    found_prices, data = prices(cache)
    found = overview.status(found_prices)
    gain, cost, pct = found["total"]
    mail = found["mail_broker"]
    error = mail["error"]
    owner = found["owner"]
    return {
        **data,
        "positions": [
            dict(row, stock=row["stock"].name)
            for row in found["positions"]
        ],
        "total": {"gain": gain, "cost": cost, "pct": pct},
        "tasks": [
            dict(task, started=_iso(task["started"]))
            for task in found["tasks"]
        ],
        "mail_broker": {
            "state": mail["state"],
            "updated": _iso(mail["updated"]),
            "last_order": mail["last_order"],
            "error": error
            and {
                "time": _iso(error["time"]),
                "text": error["text"],
            },
        },
        "owner": owner
        and {
            "name": owner.get("name") or owner["id"],
            "here": found["here"],
        },
        "last_trades": [
            {"stock": t["Stock"].name, **_trade(t)}
            for t in found["last_trades"]
        ],
    }


def prices(cache):
    """(prices, data): the cached {stock name: price}
    and what every answer has:

    {"updated", "error": the prices' time and error,
     "interval": seconds between two price requests,
     "demo": True in the demo,
     "read_only": True while config "web"
                  "read_only" is on}"""
    cached = cache.get()
    return cached["prices"], {
        "updated": _iso(cached["updated"]),
        "error": cached["error"],
        "interval": cache.interval,
        "demo": config.demo(),
        "read_only": config.web_read_only(),
    }


def trades(cache):
    """the data of /api/trades: what every answer has
    (see prices()) and

    {"stocks": [a stock (see _stock()) of each stock
                that has trades, in config order]}"""
    found_prices, data = prices(cache)
    data["stocks"] = [
        _stock(row, found_prices)
        for row in trades_engine.by_stock()
    ]
    return data


def stock_trades(cache, name):
    """the data of /api/trades/<name>: what every
    answer has (see prices()) and

    {"stock": the stock (see _stock()),
     "trades": [{"id", "date", "time", "type",
                 "count", "price"}], oldest first}

    raises NotFound if name (any case) isn't a stock
    of the config"""
    try:
        stock = Stock[name.upper()]
    except KeyError:
        raise NotFound(
            f"unknown stock '{name}', expected one "
            f"of: {', '.join(s.name for s in Stock)}"
        ) from None
    found_prices, data = prices(cache)
    found = trades_engine.get_all(stock)
    count, avg_price = trades_engine.total(stock)
    row = {
        "stock": stock,
        "trades": len(found),
        "last": found[-1] if found else None,
        "count": count,
        "avg": avg_price,
    }
    data["stock"] = _stock(row, found_prices)
    data["trades"] = [_trade(t) for t in found]
    return data


def _stock(row, found_prices):
    """a row of trades.by_stock() with its gain at
    found_prices, ready for json:

    {"stock", "trades", "last": a trade or None,
     "count", "avg", "cost", "price", "gain", "pct"
     (see positions.rows())}"""
    found = positions.row(
        row["stock"],
        row["count"],
        row["avg"],
        found_prices,
    )
    last = row["last"]
    return dict(
        found,
        stock=row["stock"].name,
        trades=row["trades"],
        last=last and _trade(last),
    )


def _trade(t):
    """a trade, ready for json"""
    return {
        "id": t["Id"],
        "date": t["Date"],
        "time": t["Time"],
        "type": t["Type"].name,
        "count": t["Count"],
        "price": t["Price"],
    }


def _with(answer, name):
    """answer(cache, name) as a function of cache"""
    return lambda cache: answer(cache, name)


# {path: function(cache) giving its data}
PATHS = {"/api/status": status, "/api/trades": trades}
# {path prefix: function(cache, the rest of the path)}
PREFIXES = {"/api/trades/": stock_trades}


def _iso(when):
    """a datetime as an ISO string, None as None"""
    if when is None:
        return None
    return when.isoformat(timespec="seconds")
