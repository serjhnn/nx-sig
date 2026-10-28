# storage: reads and writes all nX-sig data in config
# "storage_dir" (csv files for trades, json files for
# rules and the watcher)
#
# public functions:
#   trade_add(stock, trade_type, count, price,
#             date=None, time=None)
#       record a BUY/SELL trade in
#       {stock}_trades.csv, at the date and time
#       ("dd.mm.yyyy", "hh:mm") or now; the file stays
#       in date order
#   trades_get_all(stock)
#       return all recorded trades for a stock
#   trade_delete(stock, trade_id)
#       delete the trade with the given Id from
#       {stock}_trades.csv
#   rules_get_all()
#       return all personal rules from personal_rules.json,
#       numbered from 1
#   rules_add(rule)
#       add a personal rule to personal_rules.json
#   rules_delete(rule_id)
#       delete a personal rule by its Id, the remaining
#       rules are renumbered
#   mail_position_get()
#   mail_position_set(uid_validity, last_uid)
#       the last email handled by order_watcher.py, kept in
#       mail_state.json
#   watcher_status_get(), watcher_status_set(status)
#       heartbeat of order_watcher.py (dict), kept in
#       mtsig_status.json
#   mtsig_pid_get()
#       the pid in mtsig.pid, written by ./mtsig start
#   ladders_get_all(), ladder_get(ladder_id)
#       the saved ladders of ladders.csv (see
#       engines/ladder.py)
#   ladder_add(stock_name, direction, step, from_price)
#       save a new ladder, return its Id
#   ladder_set_last(ladder_id, level)
#       save the last level a ladder notified
#   ladder_delete(ladder_id)
#       delete a saved ladder and its heartbeat
#   basetrades_get_all()
#   basetrade_set(stock_name, price, count)
#   basetrade_delete(stock_name)
#       basetrades (the last buying price you keep for a
#       stock, one per stock) in base_trades.csv
#   ladder_status_get(ladder_id),
#   ladder_status_set(ladder_id, status)
#       heartbeat of a ladder process (dict), kept in
#       ladders_status.json
#   alerts_get_all()
#   alert_add(target, direction, percent=None,
#             stock="", amount=None)
#   alert_delete(alert_id)
#       the price alerts of alerts.csv (see
#       engines/alerts.py)
#   alerts_status_get(), alerts_status_set(status)
#       heartbeat of the alerts process (dict), with the
#       stocks past each alert, in alerts_status.json
#   tasks_owner_get(), tasks_owner_set(owner)
#       the device that runs the background tasks
#       (dict, None clears it), kept in
#       tasks_owner.json, see tasks_owner.py
#   demo_fill(seed_dir, reset=False)
#       copy the demo's sample data into the data folder
#       (only in the demo)
#   demo_prices_get(), demo_prices_set(state)
#       the demo's prices now (dict), demo_prices.json
#   demo_prices_change(change)
#       save change(state) of the prices now, under the
#       lock, and return it
#   demo_bars_get(), demo_bars_set(bars)
#       the demo's price history (dict), demo_bars.json
#   demo_prices_status_get(), demo_prices_status_set(s)
#       heartbeat of the demo's prices process (dict),
#       demo_prices_status.json
#   demo_message_add(text, keep)
#       keep a message of the demo's notify channel, the
#       last keep, in demo_messages.json
#   demo_messages_take()
#       the messages not taken yet
#
# all writes take an exclusive lock on {storage_dir}/.lock,
# so the CLI and order_watcher.py running at the same time
# don't overwrite each other's changes

# usage example
# trade_add(Stock.SOXL, TradeType.BUY,
#                      1, 100)

import csv
import functools
import os
import tempfile
import threading
from contextlib import contextmanager
from datetime import datetime
from enum import Enum
import json

import config

try:
    import fcntl
except ImportError:  # Windows
    fcntl = None
    import msvcrt

# config.json, .env and data/ live in the repo root
ROOT_DIR = config.ROOT_DIR
DB_DIR = config.storage_dir()
TRADE_FIELDNAMES = [
    "Id",
    "Date",
    "Time",
    "Type",
    "Count",
    "Price",
]
BASETRADE_FIELDNAMES = ["Stock", "Price", "Count"]
LADDER_FIELDNAMES = [
    "Id",
    "Stock",
    "Direction",
    "Step",
    "From",
    "Last",
    "Created",
]
ALERT_FIELDNAMES = [
    "Id",
    "For",
    "Direction",
    "Percent",
    "Created",
    "Stock",
    "Amount",
]

# stocks are the "indices" listed in config.json
Stock = Enum("Stock", config.indices())


class TradeType(Enum):
    BUY = 1
    SELL = 2


_lock_state = threading.local()


@contextmanager
def _db_lock():
    """
    exclusive lock on {DB_DIR}/.lock shared by all processes
    using the database, so a read-modify-write (e.g. of
    a trades file) is not interleaved with another
    process doing the same; re-entrant within one thread
    """
    if getattr(_lock_state, "depth", 0):
        _lock_state.depth += 1
        try:
            yield
        finally:
            _lock_state.depth -= 1
        return

    os.makedirs(DB_DIR, exist_ok=True)
    with open(os.path.join(DB_DIR, ".lock"), "a+") as f:
        if fcntl:
            fcntl.flock(f, fcntl.LOCK_EX)
        else:
            f.seek(0)
            while True:
                try:
                    msvcrt.locking(
                        f.fileno(), msvcrt.LK_LOCK, 1
                    )
                    break
                except OSError:
                    # LK_LOCK gives up after ~10s, keep
                    # waiting
                    pass
        _lock_state.depth = 1
        try:
            yield
        finally:
            _lock_state.depth = 0
            if fcntl:
                fcntl.flock(f, fcntl.LOCK_UN)
            else:
                f.seek(0)
                msvcrt.locking(
                    f.fileno(), msvcrt.LK_UNLCK, 1
                )


def _locked(function):
    @functools.wraps(function)
    def wrapper(*args, **kwargs):
        with _db_lock():
            return function(*args, **kwargs)

    return wrapper


@_locked
def trade_add(
    stock, trade_type, count, price, date=None, time=None
):
    """
    Add trade to {stock_name}_trades.csv file, at date
    and time or now. A trade older than the last one is
    put before the newer ones, so the totals add up in
    date order.

        tsmx_trades.csv
    ______________________________________________
    |    Id |       Date |  Time | Type | Count |...
    |     1 | 05.10.2026 | 14:30 |  BUY |    10 |...

    """
    os.makedirs(DB_DIR, exist_ok=True)
    path = _trades_path(stock)
    rows = []
    if os.path.exists(path) and os.path.getsize(path) > 0:
        with open(path, newline="") as f:
            rows = list(csv.DictReader(f))
    # Ids stay stable after deletions, so continue from
    # the highest one.
    next_id = (
        max((int(row["Id"]) for row in rows), default=0) + 1
    )
    now = datetime.now()
    row = {
        "Id": next_id,
        "Date": date or now.strftime("%d.%m.%Y"),
        "Time": time or now.strftime("%H:%M"),
        "Type": trade_type.name,
        "Count": count,
        "Price": price,
    }
    # after every trade of the same time or older
    when = _trade_time(row)
    at = len(rows)
    while at > 0 and _trade_time(rows[at - 1]) > when:
        at -= 1
    rows.insert(at, row)
    _write_csv_atomic(path, TRADE_FIELDNAMES, rows)


def _trade_time(row):
    return datetime.strptime(
        f"{row['Date']} {row['Time']}", "%d.%m.%Y %H:%M"
    )


def trades_get_all(stock):
    """
    return all trades stored in file
    {stock_name}_trades.csv in a dictionary
    """
    path = _trades_path(stock)
    if not os.path.exists(path):
        return []

    with open(path, newline="") as f:
        return [
            {
                "Id": int(row["Id"]),
                "Date": row["Date"],
                "Time": row["Time"],
                "Type": TradeType[row["Type"]],
                "Count": int(row["Count"]),
                "Price": float(row["Price"]),
            }
            for row in csv.DictReader(f)
        ]


@_locked
def trade_delete(stock, trade_id):
    """
    delete the trade with the given Id from
    {stock_name}_trades.csv

    remaining trades keep their Id
    return True if a trade was deleted, False if
    the Id was not found
    """
    trades = trades_get_all(stock)
    remaining = [t for t in trades if t["Id"] != trade_id]
    if len(remaining) == len(trades):
        return False

    _write_csv_atomic(
        _trades_path(stock),
        TRADE_FIELDNAMES,
        [{**t, "Type": t["Type"].name} for t in remaining],
    )
    return True


def _trades_path(stock):
    return os.path.join(
        DB_DIR, f"{stock.name.lower()}_trades.csv"
    )


def _write_csv_atomic(path, fieldnames, rows):
    """
    write rows to a csv file atomically, see _write_atomic
    """

    def write(f):
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    _write_atomic(path, write)


def _write_atomic(path, write):
    """
    call write(f) on a temporary file in the same directory,
    then replace path with it, so a crash or error mid-write
    never leaves a truncated or half-written file
    """
    directory = os.path.dirname(path) or "."
    fd, tmp_path = tempfile.mkstemp(
        dir=directory,
        prefix=".tmp_",
        suffix=os.path.splitext(path)[1],
    )
    try:
        with os.fdopen(fd, "w", newline="") as f:
            write(f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(
            tmp_path, path
        )  # atomic on both POSIX and Windows
    except BaseException:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def rules_get_all():
    """
    return all personal rules stored in personal_rules.json
    as a list of {"Id": n, "Rule": text}, numbered from 1
    """
    path = _rules_path()
    if not os.path.exists(path):
        return []
    with open(path) as f:
        rules = json.load(f)
    return [
        {"Id": i, "Rule": rule["Rule"]}
        for i, rule in enumerate(rules, 1)
    ]


@_locked
def rules_add(rule):
    """
    add a personal rule to the end of personal_rules.json,
    return its Id
    """
    rules = rules_get_all()
    rules.append({"Id": len(rules) + 1, "Rule": rule})
    _rules_save(rules)
    return len(rules)


@_locked
def rules_delete(rule_id):
    """
    delete the personal rule with the given Id from
    personal_rules.json, the remaining rules are renumbered
    from 1 return the deleted rule text, or None if the Id
    was not found
    """
    rules = rules_get_all()
    deleted = next(
        (r["Rule"] for r in rules if r["Id"] == rule_id),
        None,
    )
    if deleted is None:
        return None
    _rules_save([r for r in rules if r["Id"] != rule_id])
    return deleted


def _rules_save(rules):
    os.makedirs(DB_DIR, exist_ok=True)
    rules = [
        {"Id": i, "Rule": r["Rule"]}
        for i, r in enumerate(rules, 1)
    ]
    _write_atomic(
        _rules_path(),
        lambda f: json.dump(
            rules, f, indent=4, ensure_ascii=False
        ),
    )


def _rules_path():
    return os.path.join(DB_DIR, "personal_rules.json")


def mail_position_get():
    """
    return (uid_validity, last_uid) of the last email
    handled by order_watcher.py, or None if there is none
    yet
    """
    state = _json_get(_mail_state_path())
    if not state or state.get("last_uid") is None:
        return None
    return state.get("uid_validity"), int(state["last_uid"])


@_locked
def mail_position_set(uid_validity, last_uid):
    _json_set(
        _mail_state_path(),
        {
            "uid_validity": uid_validity,
            "last_uid": last_uid,
        },
    )


def watcher_status_get():
    """
    return the last heartbeat dict written by
    order_watcher.py, or None
    """
    return _json_get(_watcher_status_path())


@_locked
def watcher_status_set(status):
    _json_set(_watcher_status_path(), status)


def mtsig_pid_get():
    """
    return the pid that ./mtsig start wrote to
    mtsig.pid, or None; the process may have ended
    since
    """
    try:
        with open(os.path.join(DB_DIR, "mtsig.pid")) as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None


def basetrades_get_all():
    """
    return the basetrades of base_trades.csv as dicts: Stock
    (name), Price (float), Count (int), in the order of
    config "indices" (stocks no longer there come last)
    """
    path = _basetrades_path()
    if not os.path.exists(path):
        return []
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        row["Price"] = float(row["Price"])
        row["Count"] = int(row["Count"])
    order = config.indices()
    return sorted(
        rows,
        key=lambda r: (
            order.index(r["Stock"])
            if r["Stock"] in order
            else len(order)
        ),
    )


@_locked
def basetrade_set(stock_name, price, count):
    """
    save the basetrade of a stock to base_trades.csv, one
    per stock; return True if it replaced an older one
    """
    rows = [
        r
        for r in basetrades_get_all()
        if r["Stock"] != stock_name
    ]
    replaced = len(rows) < len(basetrades_get_all())
    rows.append(
        {
            "Stock": stock_name,
            "Price": price,
            "Count": count,
        }
    )
    _basetrades_save(rows)
    return replaced


@_locked
def basetrade_delete(stock_name):
    """
    delete the basetrade of a stock, return the deleted
    row or None if the stock has none
    """
    rows = basetrades_get_all()
    deleted = next(
        (r for r in rows if r["Stock"] == stock_name), None
    )
    if deleted is None:
        return None
    _basetrades_save(
        [r for r in rows if r["Stock"] != stock_name]
    )
    return deleted


def _basetrades_save(rows):
    os.makedirs(DB_DIR, exist_ok=True)
    _write_csv_atomic(
        _basetrades_path(), BASETRADE_FIELDNAMES, rows
    )


def _basetrades_path():
    return os.path.join(DB_DIR, "base_trades.csv")


def ladders_get_all():
    """
    return the saved ladders of ladders.csv as dicts:
    Id (int), Stock (name), Direction ("down"/"up"),
    Step, From, Last (floats: the last level notified,
    From until the first one), Created (text)
    """
    path = _ladders_path()
    if not os.path.exists(path):
        return []
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        row["Id"] = int(row["Id"])
        for key in ("Step", "From", "Last"):
            row[key] = float(row[key])
    return rows


def ladder_get(ladder_id):
    """return the saved ladder with this Id, or None"""
    return next(
        (
            l
            for l in ladders_get_all()
            if l["Id"] == ladder_id
        ),
        None,
    )


@_locked
def ladder_add(stock_name, direction, step, from_price):
    """
    save a new ladder to ladders.csv and return its Id,
    the one after the highest saved Id
    """
    rows = ladders_get_all()
    ladder_id = max((r["Id"] for r in rows), default=0) + 1
    rows.append(
        {
            "Id": ladder_id,
            "Stock": stock_name,
            "Direction": direction,
            "Step": step,
            "From": from_price,
            "Last": from_price,
            "Created": datetime.now().strftime(
                "%d.%m.%Y %H:%M"
            ),
        }
    )
    _ladders_save(rows)
    return ladder_id


@_locked
def ladder_set_last(ladder_id, level):
    """
    save the last level ladder <ladder_id> notified,
    return False if there is no such ladder
    """
    rows = ladders_get_all()
    row = next(
        (r for r in rows if r["Id"] == ladder_id), None
    )
    if row is None:
        return False
    row["Last"] = level
    _ladders_save(rows)
    return True


@_locked
def ladder_delete(ladder_id):
    """
    delete ladder <ladder_id> from ladders.csv and its
    heartbeat from ladders_status.json, return False if
    there is no such ladder
    """
    rows = ladders_get_all()
    kept = [r for r in rows if r["Id"] != ladder_id]
    if len(kept) == len(rows):
        return False
    _ladders_save(kept)
    statuses = _json_get(_ladders_status_path()) or {}
    if statuses.pop(str(ladder_id), None) is not None:
        _json_set(_ladders_status_path(), statuses)
    return True


def ladder_status_get(ladder_id):
    """
    return the last heartbeat dict of ladder
    <ladder_id>'s process, or None
    """
    statuses = _json_get(_ladders_status_path()) or {}
    return statuses.get(str(ladder_id))


@_locked
def ladder_status_set(ladder_id, status):
    statuses = _json_get(_ladders_status_path()) or {}
    statuses[str(ladder_id)] = status
    _json_set(_ladders_status_path(), statuses)


def alerts_get_all():
    """
    return the alerts of alerts.csv as dicts: Id (int),
    For ("basetrades"/"gain"), Direction ("down"/"up"),
    Percent and Amount (float, or None when not set),
    Stock (a stock name or "all", "" for basetrades),
    Created (text)
    """
    path = _alerts_path()
    if not os.path.exists(path):
        return []
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        row["Id"] = int(row["Id"])
        for key in ("Percent", "Amount"):
            row[key] = (
                float(row[key]) if row.get(key) else None
            )
        row["Stock"] = row.get("Stock") or ""
    return rows


@_locked
def alert_add(
    target, direction, percent=None, stock="", amount=None
):
    """
    save a new alert to alerts.csv and return its Id,
    the one after the highest saved Id
    """
    rows = alerts_get_all()
    alert_id = max((r["Id"] for r in rows), default=0) + 1
    rows.append(
        {
            "Id": alert_id,
            "For": target,
            "Direction": direction,
            "Percent": percent,
            "Created": datetime.now().strftime(
                "%d.%m.%Y %H:%M"
            ),
            "Stock": stock,
            "Amount": amount,
        }
    )
    _alerts_save(rows)
    return alert_id


@_locked
def alert_delete(alert_id):
    """
    delete alert <alert_id> from alerts.csv and its
    stocks from alerts_status.json, return the deleted
    alert or None if there is no such alert
    """
    rows = alerts_get_all()
    deleted = next(
        (r for r in rows if r["Id"] == alert_id), None
    )
    if deleted is None:
        return None
    _alerts_save([r for r in rows if r["Id"] != alert_id])
    status = _json_get(_alerts_status_path()) or {}
    past = status.get("past") or {}
    if past.pop(str(alert_id), None) is not None:
        _json_set(_alerts_status_path(), status)
    return deleted


def alerts_status_get():
    """
    return the last heartbeat dict of the alerts
    process, or None
    """
    return _json_get(_alerts_status_path())


@_locked
def alerts_status_set(status):
    _json_set(_alerts_status_path(), status)


def _alerts_save(rows):
    os.makedirs(DB_DIR, exist_ok=True)
    _write_csv_atomic(
        _alerts_path(), ALERT_FIELDNAMES, rows
    )


def _alerts_path():
    return os.path.join(DB_DIR, "alerts.csv")


def _alerts_status_path():
    return os.path.join(DB_DIR, "alerts_status.json")


def tasks_owner_get():
    return _json_get(_tasks_owner_path())


@_locked
def tasks_owner_set(owner):
    if owner is None:
        try:
            os.remove(_tasks_owner_path())
        except FileNotFoundError:
            pass
        return
    _json_set(_tasks_owner_path(), owner)


def _tasks_owner_path():
    return os.path.join(DB_DIR, "tasks_owner.json")


def demo_prices_get():
    return _json_get(_demo_prices_path())


@_locked
def demo_prices_set(state):
    _json_set(_demo_prices_path(), state)


@_locked
def demo_prices_change(change):
    """
    replace the demo's prices state with change(state),
    the read and the write under one lock, so the
    prices process and the shell don't undo each
    other's change; return the new state
    """
    state = change(demo_prices_get())
    demo_prices_set(state)
    return state


def _demo_prices_path():
    return os.path.join(DB_DIR, "demo_prices.json")


def demo_bars_get():
    return _json_get(_demo_bars_path())


@_locked
def demo_bars_set(bars):
    # thousands of points: without indent, so it stays
    # small
    os.makedirs(DB_DIR, exist_ok=True)
    _write_atomic(
        _demo_bars_path(),
        lambda f: json.dump(bars, f, separators=(",", ":")),
    )


def _demo_bars_path():
    return os.path.join(DB_DIR, "demo_bars.json")


def demo_prices_status_get():
    return _json_get(_demo_prices_status_path())


@_locked
def demo_prices_status_set(status):
    _json_set(_demo_prices_status_path(), status)


def _demo_prices_status_path():
    return os.path.join(DB_DIR, "demo_prices_status.json")


@_locked
def demo_message_add(text, keep):
    """
    add {"Id", "Time", "Text"} to demo_messages.json,
    keep only the last keep messages
    """
    data = _demo_messages()
    messages = data["messages"]
    last = messages[-1]["Id"] if messages else data["taken"]
    messages.append(
        {
            "Id": last + 1,
            "Time": datetime.now().strftime("%H:%M:%S"),
            "Text": text,
        }
    )
    data["messages"] = messages[-keep:]
    _json_set(_demo_messages_path(), data)


@_locked
def demo_messages_take():
    """
    the messages added since the last call, oldest
    first
    """
    data = _demo_messages()
    new = [
        m
        for m in data["messages"]
        if m["Id"] > data["taken"]
    ]
    if new:
        data["taken"] = new[-1]["Id"]
        _json_set(_demo_messages_path(), data)
    return new


def _demo_messages():
    data = _json_get(_demo_messages_path()) or {}
    return {
        "taken": data.get("taken", 0),
        "messages": data.get("messages", []),
    }


def _demo_messages_path():
    return os.path.join(DB_DIR, "demo_messages.json")


def _ladders_save(rows):
    os.makedirs(DB_DIR, exist_ok=True)
    _write_csv_atomic(
        _ladders_path(), LADDER_FIELDNAMES, rows
    )


def _ladders_path():
    return os.path.join(DB_DIR, "ladders.csv")


def _ladders_status_path():
    return os.path.join(DB_DIR, "ladders_status.json")


def _json_get(path):
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _json_set(path, data):
    os.makedirs(DB_DIR, exist_ok=True)
    _write_atomic(
        path,
        lambda f: json.dump(
            data, f, indent=4, ensure_ascii=False
        ),
    )


def _mail_state_path():
    return os.path.join(DB_DIR, "mail_state.json")


def _watcher_status_path():
    return os.path.join(DB_DIR, "mtsig_status.json")


def demo_fill(seed_dir, reset=False):
    """
    copy the files of seed_dir into the data folder at
    the demo's first start (a .demo file marks it done),
    or with reset again, after removing the files there;
    return True if it copied. only in the demo, so the
    real data is never touched
    """
    if not config.demo():
        raise RuntimeError("demo_fill outside the demo")
    return _demo_fill(seed_dir, reset)


# kept by a reset: the lock, and the heartbeat of the
# prices process, which goes on running
DEMO_KEEP = (".lock", "demo_prices_status.json")


@_locked
def _demo_fill(seed_dir, reset):
    marker = os.path.join(DB_DIR, ".demo")
    if os.path.exists(marker) and not reset:
        return False
    os.makedirs(DB_DIR, exist_ok=True)
    if reset:
        for name in os.listdir(DB_DIR):
            path = os.path.join(DB_DIR, name)
            if name not in DEMO_KEEP and os.path.isfile(
                path
            ):
                os.remove(path)
    for name in sorted(os.listdir(seed_dir)):
        source = os.path.join(seed_dir, name)
        if os.path.isfile(source):
            _copy_atomic(source, os.path.join(DB_DIR, name))
    open(marker, "w").close()
    return True


def _copy_atomic(source, path):
    with open(source, newline="") as f:
        text = f.read()
    _write_atomic(path, lambda f: f.write(text))
