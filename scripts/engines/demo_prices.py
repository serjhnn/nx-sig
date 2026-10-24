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
#   start(shell_pid), stop(), running_pid()
#       the process that moves the prices,
#       services/demo_prices_service.py; it runs while
#       the demo shell shell_pid or a background task
#       (a ladder, the alerts) runs, so their prices
#       keep moving after the shell is closed
#   needed()
#       True while the process should run
#   status(), save_status(pid, started, state,
#                         shell=None)
#       its heartbeat
#   log_path()
#       the log file of the process

import logging
import math
import os
import random
import signal
import time
from datetime import datetime

import config
import process
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

SERVICE = "demo_prices_service.py"
SCRIPT = os.path.join(
    config.ROOT_DIR, "scripts", "services", SERVICE
)
# the script of the shell, to know if it still runs
SHELL = "commands.py"

_rng = random.Random(config.demo_seed())
log = logging.getLogger("demo_prices")


class DemoPricesError(Exception):
    pass


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


def status():
    return storage.demo_prices_status_get()


def running_pid():
    pid = (status() or {}).get("pid")
    if pid and process.process_runs(pid, SERVICE, "run"):
        return pid
    return None


def needed():
    shell = (status() or {}).get("shell")
    if shell and process.process_runs(shell, SHELL):
        return True
    return process.tasks_run()


def start(shell_pid):
    """
    start the process that moves the prices, for the
    demo shell shell_pid, and return its pid; when it
    runs already it moves them for this shell too.
    raise DemoPricesError outside the demo or when it
    stops right away
    """
    if not config.demo():
        raise DemoPricesError("only in the demo")
    pid = running_pid()
    if pid:
        save_status(pid, None, "moving", shell_pid)
        return pid
    out = _out_path()
    child = process.spawn([SCRIPT, "run"], out)
    # so running_pid() and needed() know it before the
    # process writes its first heartbeat
    save_status(child.pid, _now(), "starting", shell_pid)
    deadline = (
        time.monotonic() + process.START_CHECK_SECONDS
    )
    while time.monotonic() < deadline:
        if child.poll() is not None:
            raise DemoPricesError(
                "the demo prices stopped right after "
                "starting: "
                + process.last_line([out, log_path()])
            )
        time.sleep(0.2)
    return child.pid


def stop():
    """stop the process (SIGTERM, then SIGKILL), True
    if it was running"""
    pid = running_pid()
    if not pid or not process.kill(pid, signal.SIGTERM):
        return False
    deadline = time.monotonic() + process.STOP_WAIT_SECONDS
    while time.monotonic() < deadline:
        process.reap(pid)
        if not running_pid():
            return True
        time.sleep(0.2)
    process.kill(pid, signal.SIGKILL)
    save_status(pid, None, "stopped")
    return True


def save_status(pid, started, state, shell=None):
    """write the heartbeat; started and shell None
    keep the saved ones"""
    previous = status() or {}
    try:
        storage.demo_prices_status_set(
            {
                "pid": pid,
                "started": started
                or previous.get("started"),
                "updated": _now(),
                "state": state,
                "shell": shell or previous.get("shell"),
            }
        )
    except Exception:
        log.exception("could not write the status")


def _out_path():
    return os.path.join(
        storage.DB_DIR, "logs", "demo_prices.out"
    )


def log_path():
    return os.path.join(
        storage.DB_DIR, "logs", "demo_prices.log"
    )


def _now():
    return datetime.now().isoformat(timespec="seconds")
