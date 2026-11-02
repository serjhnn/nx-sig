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
#   /api/ladders       the saved ladders with the
#                      price, ladders()
#   /api/alerts        the saved alerts with their
#                      level per stock and the
#                      process, alerts()
#   /api/basetrades    the basetrades with the price
#                      and their alert levels,
#                      basetrade_rows()
#   /api/chart/<s>?days=<n>
#                      the prices of stock s over n
#                      days (DEFAULT_DAYS without),
#                      its average buy price and
#                      trades, stock_chart(); 404 for
#                      a stock not in the config, 400
#                      for a bad n, 503 when the
#                      prices can't be fetched
# and the changes (POST, see below):
#   /api/trades/add    add a trade, add_trade()
#   /api/trades/delete delete a trade, delete_trade()
#   /api/ladders/add   save a ladder, maybe start it,
#                      add_ladder()
#   /api/ladders/run   start one, run_ladder()
#   /api/ladders/stop  stop one, stop_ladder()
#   /api/ladders/delete
#                      stop and delete one,
#                      delete_ladder()
#   /api/alerts/add    save an alert, start the
#                      process, add_alert()
#   /api/alerts/delete delete one, delete_alert()
#   /api/alerts/run    start the process, run_alerts()
#   /api/alerts/stop   stop it, stop_alerts()
#   /api/basetrades/add
#                      save a basetrade (or all from
#                      the trades), add_basetrade()
#   /api/basetrades/delete
#                      delete one, delete_basetrade()
# each answer also has the prices' time and error,
# the interval and demo (see prices()).
#
# who may ask: a server on 127.0.0.1 can still be
# reached by any website open in the same browser,
# so every /api request must name this server in its
# Host header (127.0.0.1, localhost or [::1] and the
# port; not a name that only points here). a change
# (a POST to a path of CHANGES) must also
#   - come from this server's own pages: its Origin
#     is http://<its Host>
#   - carry the token of the server in TOKEN_HEADER;
#     the server makes it when it starts and puts it
#     only into its pages (web/files.py)
#   - be a JSON object (Content-Type
#     application/json), at most MAX_BODY bytes
# and config "web" "read_only" must be off, else 403.
# a POST from another site with the token header is
# also stopped by the browser: the server answers no
# OPTIONS (CORS preflight).
#
# public functions:
#   find(path, address, headers, cache, query="")
#       (http status, data) of a GET of path with its
#       query (after the ?), None if it isn't an /api
#       path
#   change(path, address, headers, body, token)
#       (http status, data) of a POST of path
#   prices(cache)
#       the cached prices and what every answer has
#   status(cache)
#   trades(cache)
#   stock_trades(cache, name)
#   ladders(cache)
#   alerts(cache)
#   basetrade_rows(cache)
#   stock_chart(cache, name, query)
#       the data of the paths above
#   add_trade(data)
#   delete_trade(data)
#   add_ladder(data)
#   run_ladder(data)
#   stop_ladder(data)
#   delete_ladder(data)
#   add_alert(data)
#   delete_alert(data)
#   run_alerts(data)
#   stop_alerts(data)
#   add_basetrade(data)
#   delete_basetrade(data)
#       the changes above: (http status, data)

import hmac
import json
import logging
import math

from urllib.parse import parse_qs

import requests

import config
from engines import alerts as alerts_engine
from engines import chart
from engines import basetrades, ladder, overview, positions
from engines import trades as trades_engine
from notifiers import notifier
from storage import Stock, TradeType
from web.price_cache import BarsCache

# the addresses the api answers on
PRIVATE_HOSTS = ("127.0.0.1", "::1")
PRIVATE_ERROR = (
    "the positions are shown only when the web server "
    "listens on 127.0.0.1 (config web host)"
)
HOST_ERROR = (
    "open the page at 127.0.0.1 or localhost, not "
    "through another name"
)
ORIGIN_ERROR = "a change must come from this server's pages"
READ_ONLY_ERROR = (
    "the web pages only show the data: config web "
    "read_only is on"
)
TOKEN_ERROR = "the page is out of date, reload it"
# the header of a change with the server's token
TOKEN_HEADER = "X-NX-Token"
# the largest body of a change, in bytes
MAX_BODY = 10_000
# the levels of a ladder for the page's picture
LADDER_LEVELS = 3
# the most points of a chart
CHART_POINTS = 200
# the bars of the chart page, kept a minute
bars = BarsCache()
log = logging.getLogger("web")


class NotFound(Exception):
    """a 404 of the api; the text says why"""


class BadRequest(Exception):
    """a 400 of the api; the text says why"""


class Unavailable(Exception):
    """a 503 of the api: the prices can't be fetched;
    the text says why"""


def find(path, address, headers, cache, query=""):
    """(http status, data) of a GET of path (without
    its ?query, which is query) with the request
    headers, for a server on address (host, port) with
    the price cache cache; None if it isn't an api
    path"""
    answer = PATHS.get(path)
    if answer is None:
        for prefix, one in PREFIXES.items():
            rest = path.removeprefix(prefix)
            if rest != path and rest and "/" not in rest:
                answer = _with(one, rest, query)
                break
        else:
            return None
    refused = _refused(address, headers)
    if refused:
        return refused
    try:
        return 200, answer(cache)
    except NotFound as e:
        return 404, {"error": str(e)}
    except BadRequest as e:
        return 400, {"error": str(e)}
    except Unavailable as e:
        return 503, {"error": str(e)}
    except Exception:
        log.exception("%s failed", path)
        return 500, {
            "error": "can't read the data, see "
            "the web log"
        }


def change(path, address, headers, body, token):
    """(http status, data) of a POST of path (without
    its ?query) with the request headers and body
    (bytes), for a server on address (host, port)
    whose token is token; the path's function of
    CHANGES gets the JSON object of the body and
    gives (http status, data)"""
    answer = CHANGES.get(path)
    if answer is None:
        return 404, {"error": f"no change at {path}"}
    refused = _refused(address, headers)
    if refused:
        return refused
    origin = "http://" + headers["Host"]
    if headers.get("Origin") != origin:
        return 403, {"error": ORIGIN_ERROR}
    if config.web_read_only():
        return 403, {"error": READ_ONLY_ERROR}
    given = headers.get(TOKEN_HEADER) or ""
    if not hmac.compare_digest(
        given.encode(), token.encode()
    ):
        return 403, {"error": TOKEN_ERROR}
    kind = headers.get("Content-Type") or ""
    if kind.split(";")[0].strip() != "application/json":
        return 415, {"error": "send the change as JSON"}
    try:
        data = json.loads(body)
    except ValueError:
        data = None
    if not isinstance(data, dict):
        return 400, {"error": "not a JSON object"}
    try:
        return answer(data)
    except Exception:
        log.exception("%s failed", path)
        return 500, {
            "error": "can't make the change, see "
            "the web log"
        }


def _refused(address, headers):
    """(403, data) if the api doesn't answer a request
    with headers on a server on address, else None:
    the server must listen on 127.0.0.1 (or ::1) and
    the request name it in its Host"""
    host, port = address[:2]
    if host not in PRIVATE_HOSTS:
        return 403, {"error": PRIVATE_ERROR}
    names = ("127.0.0.1", "localhost", "[::1]")
    if headers.get("Host") not in [
        f"{name}:{port}" for name in names
    ]:
        return 403, {"error": HOST_ERROR}
    return None


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
                that has trades, in config order],
     "names": the names of every stock of the config,
              for the add form}"""
    found_prices, data = prices(cache)
    data["names"] = [stock.name for stock in Stock]
    data["stocks"] = [
        _stock(row, found_prices)
        for row in trades_engine.by_stock()
    ]
    return data


def stock_trades(cache, name, query=""):
    """the data of /api/trades/<name> (query isn't
    used): what every answer has (see prices()) and

    {"stock": the stock (see _stock()),
     "trades": [{"id", "date", "time", "type",
                 "count", "price"}], oldest first}

    raises NotFound if name (any case) isn't a stock
    of the config"""
    stock = _stock_named(name)
    if stock is None:
        raise NotFound(_unknown_stock(name))
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


def ladders(cache):
    """the data of /api/ladders: what every answer has
    (see prices()) and

    {"ladders": [one dict per saved ladder, in id
                 order: "id", "stock", "direction",
                 "step", "from", "last" (the last
                 level sent, from at first), "created",
                 "state", "next" (see ladder.row()),
                 "levels": the next LADDER_LEVELS
                           levels (fewer for a down
                           ladder near 0, none when
                           done),
                 "price": its stock's, None without,
                 "away": how far the price still has
                         to move to the next level
                         (down: price - next, up: next
                         - price; 0 or less once
                         passed), None without a price
                         or a next level,
                 "away_pct": away in % of the price],
     "names": the names of every stock of the config,
     "prices": {name: price} of the ones that have
               one, for the add form}"""
    found_prices, data = prices(cache)
    data["names"] = [stock.name for stock in Stock]
    data["prices"] = {
        name: found_prices[name]
        for name in data["names"]
        if name in found_prices
    }
    data["ladders"] = [
        _ladder(row, found_prices.get(row["Stock"]))
        for row in ladder.rows()
    ]
    return data


def alerts(cache):
    """the data of /api/alerts: what every answer has
    (see prices()) and

    {"process": {"state": "running", "elsewhere" or
                 "stopped", "pid", "updated": its last
                 check, "owner": the other device}
                (alerts.process_state()),
     "alerts": [one dict per saved alert, in id order:
                "id", "kind": "basetrades" or "gain",
                "text": as 'ls alerts' ("down 10%",
                        "TSMX +100", "all +10%"),
                "direction", "percent", "amount"
                (one of the two for a gain alert),
                "stock": a name or "all" for a gain
                         alert, else None,
                "created",
                "levels": [{"stock", "level", "price",
                            "away_pct": how far the
                            price still has to move to
                            the level, in % of the
                            price (0 or less once
                            reached), "reached"}]: a
                          basetrades alert's per
                          basetrade, a gain alert's
                          per held stock],
     "names": the names of every stock of the config,
              for the add form}"""
    found_prices, data = prices(cache)
    levels = {}
    for alert, stocks in alerts_engine.basetrade_levels(
        basetrades.get_all(), found_prices
    ) + alerts_engine.gain_levels(found_prices):
        levels[alert["Id"]] = stocks
    state = alerts_engine.process_state()
    data["process"] = dict(
        state, updated=_iso(state["updated"])
    )
    data["alerts"] = [
        _alert(
            alert, levels.get(alert["Id"], []), found_prices
        )
        for alert in alerts_engine.alerts_get_all()
    ]
    data["names"] = [stock.name for stock in Stock]
    return data


def basetrade_rows(cache):
    """the data of /api/basetrades: what every answer
    has (see prices()) and

    {"basetrades": [one dict per basetrade, in config
                    order: "stock", "buy" (its
                    price), "count",
                    "price": its stock's, None
                             without,
                    "change_pct": price's change from
                                  buy in %, None
                                  without a price,
                    "alerts": [{"id", "text" ("down
                                10%"), "level",
                                "reached"}] of each
                              basetrades alert],
     "from_trades": {name: the lowest buy since the
                     last sell (a trade, see
                     _trade()), of each stock of the
                     config that has one, for the
                     add form},
     "names": the names of every stock of the
              config}"""
    found_prices, data = prices(cache)
    found = basetrades.get_all()
    levels = {b["Stock"]: [] for b in found}
    for alert, stocks in alerts_engine.basetrade_levels(
        found, found_prices
    ):
        for name, at, reached in stocks:
            levels[name].append(
                {
                    "id": alert["Id"],
                    "text": alerts_engine.describe(alert),
                    "level": at,
                    "reached": bool(reached),
                }
            )
    rows = []
    for b in found:
        price = found_prices.get(b["Stock"])
        change_pct = None
        if price is not None:
            change_pct = (
                (price - b["Price"]) / b["Price"] * 100
            )
        rows.append(
            {
                "stock": b["Stock"],
                "buy": b["Price"],
                "count": b["Count"],
                "price": price,
                "change_pct": change_pct,
                "alerts": levels[b["Stock"]],
            }
        )
    data["basetrades"] = rows
    data["from_trades"] = {}
    for stock in Stock:
        try:
            lowest = basetrades.from_trades(stock)
        except basetrades.BaseTradeError:
            continue
        data["from_trades"][stock.name] = _trade(lowest)
    data["names"] = [stock.name for stock in Stock]
    return data


def stock_chart(cache, name, query):
    """the data of /api/chart/<name>?days=<n>: what
    every answer has (see prices()) and

    {"stock", "days",
     "timeframe", "label": the bars' ("1Hour", "1h"),
     "points": [[time, price]], oldest first, at most
               CHART_POINTS (more bars are averaged),
     "avg": the average buy price, None when none are
            held,
     "trades": [{"time", "side": "B" or "S",
                 "price"}] since the first point,
     "price": the stock's cached price, None without,
     "names": the names of every stock of the config,
              for the picker}

    raises NotFound if name (any case) isn't a stock
    of the config, BadRequest for days not a whole
    number from 1 to chart.MAX_DAYS, Unavailable when
    the bars can't be fetched"""
    stock = _stock_named(name)
    if stock is None:
        raise NotFound(_unknown_stock(name))
    days = _days(query)
    found_prices, data = prices(cache)
    try:
        found = chart.data(
            stock, days, CHART_POINTS, bars.get_bars
        )
    except KeyError as e:
        raise Unavailable(
            f"missing {e.args[0]} in .env, can't get "
            "the prices"
        )
    except (requests.RequestException, ValueError) as e:
        raise Unavailable(f"can't get the prices: {e}")
    points = chart.thin(found["bars"], CHART_POINTS)
    first = points[0][0] if points else None
    data.update(
        stock=stock.name,
        days=days,
        timeframe=found["timeframe"],
        label=found["label"],
        points=[[_iso(t), p] for t, p in points],
        avg=found["avg"],
        trades=[
            {"time": _iso(t), "side": side, "price": p}
            for t, side, p in found["trades"]
            if first is not None and t >= first
        ],
        price=found_prices.get(stock.name),
        names=[s.name for s in Stock],
    )
    return data


def _days(query):
    """the days of a chart's query, DEFAULT_DAYS
    without; BadRequest if they aren't 1 to
    MAX_DAYS"""
    given = parse_qs(query).get("days")
    if not given:
        return chart.DEFAULT_DAYS
    text = given[-1]
    if not (text.isascii() and text.isdigit()) or not (
        1 <= int(text) <= chart.MAX_DAYS
    ):
        raise BadRequest(
            "days must be a whole number from 1 to "
            f"{chart.MAX_DAYS}"
        )
    return int(text)


def _alert(alert, stocks, found_prices):
    """a saved alert with its levels, stocks [(stock,
    level, reached)], ready for json (see alerts())"""
    down = alert["Direction"] == "down"
    rows = []
    for name, at, reached in stocks:
        price = found_prices.get(name)
        away_pct = None
        if price:
            away = price - at if down else at - price
            away_pct = away / price * 100
        rows.append(
            {
                "stock": name,
                "level": at,
                "price": price,
                "away_pct": away_pct,
                "reached": bool(reached),
            }
        )
    gain = alert["For"] == "gain"
    return {
        "id": alert["Id"],
        "kind": alert["For"],
        "text": alerts_engine.describe(alert),
        "direction": alert["Direction"],
        "percent": alert["Percent"],
        "amount": alert.get("Amount"),
        "stock": alert.get("Stock") if gain else None,
        "created": alert["Created"],
        "levels": rows,
    }


def _ladder(row, price):
    """a row of ladder.rows() at price, ready for
    json (see ladders())"""
    away = away_pct = None
    if price is not None and row["next"] is not None:
        if row["Direction"] == "down":
            away = price - row["next"]
        else:
            away = row["next"] - price
        if price:
            away_pct = away / price * 100
    return {
        "id": row["Id"],
        "stock": row["Stock"],
        "direction": row["Direction"],
        "step": row["Step"],
        "from": row["From"],
        "last": row["Last"],
        "created": row["Created"],
        "state": row["state"],
        "next": row["next"],
        "levels": (
            []
            if row["state"] == "done"
            else ladder.levels(row, LADDER_LEVELS)
        ),
        "price": price,
        "away": away,
        "away_pct": away_pct,
    }


def add_ladder(data):
    """POST /api/ladders/add: save a ladder like 'add
    ladder', with the engine's checks, and start it
    with "run" (like 'add ladder ... run').

    data: {"stock": a name (any case), "direction":
    "down" or "up" (any case), "step": a number,
    "from": a number, "run": true or false (none:
    false)}

    (200, {"id", "text": what the shell says,
    "start_error": why it didn't start, None}), or
    (400, {"error"}) with the shell's text; a ladder
    that is saved but doesn't start is still 200"""
    stock = _stock_named(data.get("stock"))
    if stock is None:
        return 400, {
            "error": _unknown_stock(data.get("stock"))
        }
    direction = data.get("direction")
    if not isinstance(direction, str) or (
        direction.lower() not in ladder.DIRECTIONS
    ):
        return 400, {
            "error": f"unknown direction '{direction}', "
            "expected down/up"
        }
    direction = direction.lower()
    step, price = data.get("step"), data.get("from")
    if not _is_number(step) or not _is_number(price):
        return 400, {
            "error": "step and price must be numbers"
        }
    run = data.get("run", False)
    if not isinstance(run, bool):
        return 400, {"error": "run is true or false"}
    if not notifier.is_configured():
        return 400, {"error": notifier.setup_error()}
    try:
        ladder_id = ladder.create(
            stock.name, direction, step, price
        )
    except ladder.LadderError as e:
        return 400, {"error": str(e)}
    log.info(
        "saved ladder %s: %s %s %s from %s",
        ladder_id,
        stock.name,
        direction,
        step,
        price,
    )
    text = (
        f"ladder {ladder_id} saved: {stock.name} "
        f"{direction} every {step:g} from {price:g}"
    )
    start_error = None
    if run:
        status, started = run_ladder({"id": ladder_id})
        if status == 200:
            text += "; " + started["text"]
        else:
            start_error = started["error"]
    return 200, {
        "id": ladder_id,
        "text": text,
        "start_error": start_error,
    }


def run_ladder(data):
    """POST /api/ladders/run: start ladder data["id"]
    like 'run ladder <id>' (taking the background
    tasks over from another device, force, stays in
    the shell).

    (200, {"text"}), (404, {"error"}) if there is no
    such ladder, (409, {"error"}) if it doesn't start
    (it runs already, another device runs the
    background tasks, it stops right away), with the
    engine's text"""
    found = _saved_ladder(data)
    if isinstance(found, tuple):
        return found
    try:
        pid = ladder.start(found["Id"])
    except ladder.LadderError as e:
        return 409, {"error": str(e)}
    log.info("started ladder %s, pid %s", found["Id"], pid)
    return 200, {
        "text": f"ladder {found['Id']} started (pid "
        f"{pid}), next alert at "
        f"{ladder.next_level(found):g}"
    }


def stop_ladder(data):
    """POST /api/ladders/stop: stop ladder data["id"]
    like 'stop ladder <id>'; it stays saved.

    (200, {"text"}), (404, {"error"}) if there is no
    such ladder"""
    found = _saved_ladder(data)
    if isinstance(found, tuple):
        return found
    ladder_id = found["Id"]
    if ladder.stop(ladder_id):
        log.info("stopped ladder %s", ladder_id)
        return 200, {"text": f"ladder {ladder_id} stopped"}
    return 200, {
        "text": f"ladder {ladder_id} is not running"
    }


def delete_ladder(data):
    """POST /api/ladders/delete: stop ladder
    data["id"] if it runs and delete it, like 'rm
    ladder <id>' (the page asks first).

    (200, {"text"}), (404, {"error"}) if there is no
    such ladder, (409, {"error"}) if its files can't
    be deleted"""
    found = _saved_ladder(data)
    if isinstance(found, tuple):
        return found
    ladder_id = found["Id"]
    try:
        was_running = ladder.remove(ladder_id)
    except (ladder.LadderError, OSError) as e:
        return 409, {"error": str(e)}
    log.info("deleted ladder %s", ladder_id)
    return 200, {
        "text": f"ladder {ladder_id} "
        + ("stopped and " if was_running else "")
        + "deleted"
    }


def add_alert(data):
    """POST /api/alerts/add: save an alert like 'add
    alert', with the engine's checks, and start the
    alerts process if it isn't running.

    data: {"kind": "basetrades", "direction": "down"
    or "up", "percent": a number} or {"kind": "gain",
    "stock": a name or "all" (any case), "value": a
    number, negative for a loss, "in_percent": true
    for a % of the average buy price (none: false)}

    (200, {"id", "text": what the shell says,
    "start_error": why the process didn't start,
    None}), or (400, {"error"}) with the shell's text;
    an alert that is saved when the process doesn't
    start is still 200"""
    kind = data.get("kind")
    if kind == "basetrades":
        direction = data.get("direction")
        if not isinstance(direction, str) or (
            direction.lower() not in ladder.DIRECTIONS
        ):
            return 400, {
                "error": f"unknown direction "
                f"'{direction}', expected down/up"
            }
        percent = data.get("percent")
        if not _is_number(percent):
            return 400, {"error": "<n> must be a number"}
        if not notifier.is_configured():
            return 400, {"error": notifier.setup_error()}
        try:
            alert_id = alerts_engine.create(
                kind, direction.lower(), percent
            )
        except alerts_engine.AlertError as e:
            return 400, {"error": str(e)}
    elif kind == "gain":
        stock = data.get("stock")
        if (
            isinstance(stock, str)
            and stock.lower() == "all"
        ):
            stock = "all"
        else:
            found = _stock_named(stock)
            if found is None:
                return 400, {"error": _unknown_stock(stock)}
            stock = found.name
        value = data.get("value")
        if not _is_number(value):
            return 400, {"error": "<n> must be a number"}
        in_percent = data.get("in_percent", False)
        if not isinstance(in_percent, bool):
            return 400, {
                "error": "in_percent is true or false"
            }
        if not notifier.is_configured():
            return 400, {"error": notifier.setup_error()}
        try:
            alert_id = alerts_engine.create_gain(
                stock, value, in_percent
            )
        except alerts_engine.AlertError as e:
            return 400, {"error": str(e)}
    else:
        return 400, {
            "error": "alerts are for basetrades/gain"
        }
    saved = _saved_alert(alert_id)
    text = (
        f"alert {alert_id} saved: {saved['For']} "
        f"{alerts_engine.describe(saved)}"
    )
    log.info("%s", text)
    start_error = None
    if not alerts_engine.running_pid():
        status, started = run_alerts({})
        if status == 200:
            text += "; " + started["text"]
        else:
            start_error = started["error"]
    return 200, {
        "id": alert_id,
        "text": text,
        "start_error": start_error,
    }


def delete_alert(data):
    """POST /api/alerts/delete: delete alert
    data["id"] like 'rm alert <id>' (the page asks
    first); the process stops when no alert is left.

    (200, {"text"}), (404, {"error"}) if there is no
    such alert, (400, {"error"}) for a bad id"""
    alert_id = data.get("id")
    if not _is_int(alert_id):
        return 400, {"error": "the id is a whole number"}
    if _saved_alert(alert_id) is None:
        return 404, {
            "error": f"no alert {alert_id}, see "
            "'ls alerts'"
        }
    was_running = bool(alerts_engine.running_pid())
    alerts_engine.remove(alert_id)
    log.info("deleted alert %s", alert_id)
    text = f"deleted alert {alert_id}"
    if was_running and not alerts_engine.running_pid():
        text += ", no alerts left: alerts stopped"
    return 200, {"text": text}


def run_alerts(data):
    """POST /api/alerts/run: start the alerts process
    like 'run alerts' (taking the background tasks
    over from another device, force, stays in the
    shell).

    (200, {"text"}), or (409, {"error"}) with the
    engine's text if it doesn't start (it runs
    already, another device runs the background
    tasks, no alert, it stops right away)"""
    try:
        pid = alerts_engine.start()
    except alerts_engine.AlertError as e:
        return 409, {"error": str(e)}
    log.info("started the alerts, pid %s", pid)
    return 200, {"text": f"alerts started (pid {pid})"}


def stop_alerts(data):
    """POST /api/alerts/stop: stop the alerts process
    like 'stop alerts'; the alerts stay saved.

    (200, {"text"})"""
    if alerts_engine.stop():
        log.info("stopped the alerts")
        return 200, {"text": "alerts stopped"}
    return 200, {"text": "the alerts aren't running"}


def add_basetrade(data):
    """POST /api/basetrades/add: save a basetrade like
    'add basetrade', with the engine's checks; it
    replaces the stock's older one.

    data: {"stock": a name (any case), "price": a
    number, "count": a whole number}, or {"stock",
    "from_trades": true} for the lowest buy since the
    last sell, or {"stock": "all"} for that of each
    stock that has trades (the page asks first)

    (200, {"text": what the shell says}), or (400,
    {"error"}) with the shell's text"""
    name = data.get("stock")
    if isinstance(name, str) and name.lower() == "all":
        return _add_all_basetrades()
    stock = _stock_named(name)
    if stock is None:
        return 400, {"error": _unknown_stock(name)}
    from_trades = data.get("from_trades", False)
    if not isinstance(from_trades, bool):
        return 400, {
            "error": "from_trades is true or false"
        }
    lowest = ""
    if from_trades:
        try:
            buy = basetrades.from_trades(stock)
        except basetrades.BaseTradeError as e:
            return 400, {"error": str(e)}
        price, count = buy["Price"], buy["Count"]
        lowest = (
            f" ({basetrades.LOWEST}, "
            f"{_short_date(buy['Date'])})"
        )
    else:
        price, count = data.get("price"), data.get("count")
        if not _is_number(price) or not _is_int(count):
            return 400, {
                "error": "price must be a number and "
                "count a whole number"
            }
    try:
        replaced = basetrades.save(stock, price, count)
    except basetrades.BaseTradeError as e:
        return 400, {"error": str(e)}
    text = (
        f"{'replaced' if replaced else 'added'} "
        f"basetrade of {stock.name}: {count} at "
        f"{price:g}{lowest}"
    )
    log.info("%s", text)
    return 200, {"text": text}


def _add_all_basetrades():
    """add_basetrade() of "all": (200, {"text": the
    shell's lines joined by "; "}), or (400,
    {"error"}) when no stock has a lowest buy"""
    try:
        saved = basetrades.all_from_trades()
    except basetrades.BaseTradeError as e:
        return 400, {"error": str(e)}
    lines = []
    for stock, buy, replaced in saved:
        if buy is None:
            lines.append(
                f"skipped {stock.name}: no buys since "
                "the last sell"
            )
            continue
        lines.append(
            f"{'replaced' if replaced else 'added'} "
            f"{stock.name}: {buy['Count']} at "
            f"{buy['Price']:g} "
            f"({_short_date(buy['Date'])})"
        )
    text = f"from the {basetrades.LOWEST}: " + "; ".join(
        lines
    )
    log.info("%s", text)
    return 200, {"text": text}


def delete_basetrade(data):
    """POST /api/basetrades/delete: delete the
    basetrade of data["stock"] like 'rm basetrade'
    (the page asks first).

    (200, {"text"}), (404, {"error"}) if the stock has
    no basetrade, (400, {"error"}) for an unknown
    stock"""
    stock = _stock_named(data.get("stock"))
    if stock is None:
        return 400, {
            "error": _unknown_stock(data.get("stock"))
        }
    if basetrades.delete(stock.name) is None:
        return 404, {
            "error": f"no basetrade of {stock.name}, "
            "see 'ls basetrades'"
        }
    log.info("deleted basetrade of %s", stock.name)
    return 200, {
        "text": f"deleted basetrade of {stock.name}"
    }


def _short_date(date):
    """ "02.09.2026" -> "02.09.26", as the shell"""
    return date[:6] + date[-2:] if len(date) == 10 else date


def _saved_alert(alert_id):
    """the saved alert alert_id, or None"""
    return next(
        (
            a
            for a in alerts_engine.alerts_get_all()
            if a["Id"] == alert_id
        ),
        None,
    )


def _saved_ladder(data):
    """the saved ladder of data["id"], or the (http
    status, data) of a bad or unknown id"""
    ladder_id = data.get("id")
    if not _is_int(ladder_id):
        return 400, {"error": "the id is a whole number"}
    found = ladder.get(ladder_id)
    if found is None:
        return 404, {
            "error": f"no ladder {ladder_id}, see "
            "'ls ladders'"
        }
    return found


def add_trade(data):
    """POST /api/trades/add: record a trade like 'add
    trade', with the engine's checks.

    data: {"stock": a name (any case), "type": "buy"
    or "sell" (any case), "count": a whole number,
    "price": a number, "date": "dd.mm.yyyy" and
    "time": "hh:mm" (both or neither, else now)}

    (200, {"text": what the shell says, "trade": the
    trade}), or (400, {"error"}) with the shell's
    text"""
    stock = _stock_named(data.get("stock"))
    if stock is None:
        return 400, {
            "error": _unknown_stock(data.get("stock"))
        }
    trade_type = data.get("type")
    try:
        trade_type = TradeType[trade_type.upper()]
    except (AttributeError, KeyError):
        return 400, {
            "error": f"unknown trade type '{trade_type}'"
            ", expected buy/sell"
        }
    count, price = data.get("count"), data.get("price")
    if not _is_int(count) or not _is_number(price):
        return 400, {
            "error": "count must be a whole number and "
            "price a number"
        }
    date, time = data.get("date"), data.get("time")
    if not all(
        isinstance(v, (str, type(None)))
        for v in (date, time)
    ):
        return 400, {"error": "date and time are text"}
    before = {t["Id"] for t in trades_engine.get_all(stock)}
    try:
        trades_engine.add(
            stock,
            trade_type,
            count,
            price,
            date or None,
            time or None,
        )
    except trades_engine.TradeError as e:
        return 400, {"error": str(e)}
    added = [
        t
        for t in trades_engine.get_all(stock)
        if t["Id"] not in before
    ]
    log.info(
        "added %s %s %s @ %s",
        trade_type.name,
        count,
        stock.name,
        price,
    )
    return 200, {
        "text": f"added {trade_type.name} {count} "
        f"{stock.name} @ {price:g}",
        "trade": _trade(added[0]) if added else None,
    }


def delete_trade(data):
    """POST /api/trades/delete: delete a trade like 'rm
    trade' (the page asks first).

    data: {"stock": a name (any case), "id": the
    trade's id}

    (200, {"text": what the shell says}), (404,
    {"error"}) if there is no such trade, (400,
    {"error"}) for a bad stock or id"""
    stock = _stock_named(data.get("stock"))
    if stock is None:
        return 400, {
            "error": _unknown_stock(data.get("stock"))
        }
    trade_id = data.get("id")
    if not _is_int(trade_id):
        return 400, {"error": "the id is a whole number"}
    if not trades_engine.delete(stock, trade_id):
        return 404, {
            "error": f"no {stock.name} trade {trade_id}"
        }
    log.info("deleted %s trade %s", stock.name, trade_id)
    return 200, {
        "text": f"deleted {stock.name} trade {trade_id}"
    }


def _stock_named(name):
    """the Stock of name (any case), None if there is
    none"""
    try:
        return Stock[name.upper()]
    except (AttributeError, KeyError):
        return None


def _unknown_stock(name):
    return (
        f"unknown stock '{name}', expected one of: "
        f"{', '.join(s.name for s in Stock)}"
    )


def _is_int(value):
    """a whole number of json, not true or false"""
    return isinstance(value, int) and not isinstance(
        value, bool
    )


def _is_number(value):
    """a finite number of json (not NaN or Infinity,
    which json.loads lets through)"""
    return _is_int(value) or (
        isinstance(value, float) and math.isfinite(value)
    )


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


def _with(answer, name, query):
    """answer(cache, name, query) as a function of
    cache"""
    return lambda cache: answer(cache, name, query)


# {path: function(cache) giving its data}
PATHS = {
    "/api/status": status,
    "/api/trades": trades,
    "/api/ladders": ladders,
    "/api/alerts": alerts,
    "/api/basetrades": basetrade_rows,
}
# {path prefix: function(cache, the rest of the
# path, the query)}
PREFIXES = {
    "/api/trades/": stock_trades,
    "/api/chart/": stock_chart,
}
# {path: function(data) of a change, see change()}
CHANGES = {
    "/api/trades/add": add_trade,
    "/api/trades/delete": delete_trade,
    "/api/ladders/add": add_ladder,
    "/api/ladders/run": run_ladder,
    "/api/ladders/stop": stop_ladder,
    "/api/ladders/delete": delete_ladder,
    "/api/alerts/add": add_alert,
    "/api/alerts/delete": delete_alert,
    "/api/alerts/run": run_alerts,
    "/api/alerts/stop": stop_alerts,
    "/api/basetrades/add": add_basetrade,
    "/api/basetrades/delete": delete_basetrade,
}


def _iso(when):
    """a datetime as an ISO string, None as None"""
    if when is None:
        return None
    return when.isoformat(timespec="seconds")
