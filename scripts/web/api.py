# api: the JSON the web pages ask for
#
#   python tests/test_web.py   the tests
#
# the paths:
#   /api/status   the main page's data (see status()),
#                 only when the server listens on
#                 127.0.0.1: the positions are
#                 private, any other address gets 403
#
# public functions:
#   find(path, host, cache)
#       (http status, data) of path, None if it isn't
#       an /api path
#   status(cache)
#       the data of /api/status

import logging

from engines import overview

# the addresses the api answers on
PRIVATE_HOSTS = ("127.0.0.1", "::1")
PRIVATE_ERROR = (
    "the positions are shown only when the web server "
    "listens on 127.0.0.1 (config web host)"
)
log = logging.getLogger("web")


def find(path, host, cache):
    """(http status, data) of path (without its
    ?query) for a server on host with the price cache
    cache; None if it isn't an api path"""
    answer = PATHS.get(path)
    if answer is None:
        return None
    if host not in PRIVATE_HOSTS:
        return 403, {"error": PRIVATE_ERROR}
    try:
        return 200, answer(cache)
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

    {"updated", "error": the prices' time and error,
     "interval": seconds between two price requests,
     "demo",
     "positions": [{"stock", "count", "avg", "cost",
                    "price", "gain", "pct"}],
     "total": {"gain", "cost", "pct"},
     "tasks": [{"id", "task", "pid", "started",
                "state", "healthy"}],
     "mail_broker": {"state", "updated",
                     "last_order", "error"},
     "owner": {"name", "here"} or None,
     "last_trades": [{"stock", "id", "date", "time",
                      "type", "count", "price"}]}"""
    cached = cache.get()
    found = overview.status(cached["prices"])
    gain, cost, pct = found["total"]
    mail = found["mail_broker"]
    error = mail["error"]
    owner = found["owner"]
    return {
        "updated": _iso(cached["updated"]),
        "error": cached["error"],
        "interval": cache.interval,
        "demo": found["demo"],
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
            {
                "stock": t["Stock"].name,
                "id": t["Id"],
                "date": t["Date"],
                "time": t["Time"],
                "type": t["Type"].name,
                "count": t["Count"],
                "price": t["Price"],
            }
            for t in found["last_trades"]
        ],
    }


# {path: function(cache) giving its data}
PATHS = {"/api/status": status}


def _iso(when):
    """a datetime as an ISO string, None as None"""
    if when is None:
        return None
    return when.isoformat(timespec="seconds")
