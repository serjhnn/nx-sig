# demo_prices: the demo's prices, a random walk per
# stock, so ./nxdemo needs no keys and no network
#
#   python tests/test_demo_prices.py   the tests
#
# a move works on the log of the price: a random step
# of config "demo" "volatility" a day, scaled to the
# time passed, "speed" times faster than real time,
# and a pull of REVERT a day back to the starting
# price, so the prices wobble around it (about
# volatility / sqrt(2 * REVERT), 11% for 5%) instead
# of drifting off
#
# the prices now are kept in demo_prices.json,
# rewritten on every move, the history in
# demo_bars.json: a point a minute at most, thinned the
# older it gets (TIERS). a new demo gets a year of
# history, made backwards from the starting prices
#
# times are seconds since the epoch, as time.time()
#
# public functions:
#   create(now=None, rng=None)
#       the starting prices (config.demo_prices()) and
#       their history
#   ensure()
#       create() if there are no demo prices yet
#   move(now=None, rng=None)
#       move every price by the time since the last
#       move (at most MAX_GAP), return {symbol: price}
#   latest()
#       {symbol: price} now, {} before create()
#   bars(symbol, days, now=None)
#       [(local time, price)] of the last days, oldest
#       first, ending with the price now

import math
import random
import time
from datetime import datetime

import config
import storage

DAY = 24 * 3600
# how much of the way back to the starting price a
# day of demo time goes
REVERT = 0.1
# (age up to, seconds between two points) of the
# history, newest first
TIERS = [
    (6 * 3600, 60),
    (2 * DAY, 15 * 60),
    (30 * DAY, 3600),
    (365 * DAY, DAY),
]
HISTORY = TIERS[-1][0]
# after a longer pause (the demo was closed) the
# prices move as much as after MAX_GAP seconds
MAX_GAP = 60
# a point is kept when the one after it is at least
# its tier's gap less THIN_SLACK seconds later (the
# moves come a second or two late)
THIN_SLACK = 30

_rng = random.Random(config.demo_seed())


def create(now=None, rng=None):
    now = time.time() if now is None else now
    rng = rng or _rng
    start = config.demo_prices()
    times = _history_times(now)
    bars = {}
    for symbol, price in start.items():
        bars[symbol] = _history(price, times, rng)
    storage.demo_bars_set(bars)
    storage.demo_prices_set(
        {"time": now, "recorded": now, "prices": start}
    )


def ensure():
    if (
        storage.demo_prices_get() is None
        or storage.demo_bars_get() is None
    ):
        create()


def move(now=None, rng=None):
    now = time.time() if now is None else now
    rng = rng or _rng
    state = storage.demo_prices_get()
    if not state:
        create(now, rng)
        return latest()
    gap = min(max(now - state["time"], 0), MAX_GAP)
    days = gap * config.demo_number("speed") / DAY
    prices = {}
    for symbol, start in config.demo_prices().items():
        price = state["prices"].get(symbol, start)
        log = _step(
            math.log(price), math.log(start), days, rng
        )
        prices[symbol] = round(math.exp(log), 4)
    state = {
        "time": now,
        "recorded": state.get("recorded", 0),
        "prices": prices,
    }
    if now - state["recorded"] >= TIERS[0][1]:
        _record(prices, now)
        state["recorded"] = now
    storage.demo_prices_set(state)
    return prices


def latest():
    state = storage.demo_prices_get()
    return dict(state["prices"]) if state else {}


def bars(symbol, days, now=None):
    now = time.time() if now is None else now
    since = now - days * DAY
    points = (storage.demo_bars_get() or {}).get(symbol, [])
    found = [
        (datetime.fromtimestamp(t), price)
        for t, price in points
        if since <= t < now
    ]
    price = latest().get(symbol)
    if price is not None:
        found.append((datetime.fromtimestamp(now), price))
    return found


def _step(log, start, days, rng):
    """the log price log after days of demo time; the
    exact steps of a walk pulled back to start, so a
    long step (a high speed) doesn't overshoot"""
    volatility = config.demo_number("volatility")
    kept = math.exp(-REVERT * days)
    spread = volatility * math.sqrt(
        (1 - kept * kept) / (2 * REVERT)
    )
    mean = start + (log - start) * kept
    return mean + spread * rng.gauss(0, 1)


def _gap(age):
    """seconds between two history points of age"""
    for limit, gap in TIERS:
        if age < limit:
            return gap
    return TIERS[-1][1]


def _history_times(now):
    """the times of a new history, oldest first,
    ending with now"""
    times = [now]
    while now - times[-1] < HISTORY:
        times.append(times[-1] - _gap(now - times[-1]))
    return times[::-1]


def _history(price, times, rng):
    """[[time, price]] of times, made backwards from
    price at the last time (the walk looks the same
    either way)"""
    start = log = math.log(price)
    points = [[int(times[-1]), round(price, 2)]]
    for i in range(len(times) - 1, 0, -1):
        days = (times[i] - times[i - 1]) / DAY
        log = _step(log, start, days, rng)
        points.append(
            [int(times[i - 1]), round(math.exp(log), 2)]
        )
    return points[::-1]


def _record(prices, now):
    """add the prices now to the history"""
    history = storage.demo_bars_get() or {}
    for symbol, price in prices.items():
        points = history.get(symbol, [])
        points.append([int(now), round(price, 2)])
        history[symbol] = _thin(points, now)
    storage.demo_bars_set(history)


def _thin(points, now):
    """points, oldest first, without those older than
    HISTORY or closer to the next one than the gap of
    its tier (as _history_times() makes them)"""
    kept = [points[-1]]
    for point in reversed(points[:-1]):
        if now - point[0] > HISTORY:
            break
        newer = kept[-1][0]
        enough = _gap(now - newer) - THIN_SLACK
        if newer - point[0] >= enough:
            kept.append(point)
    return kept[::-1]
