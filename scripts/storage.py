# storage: reads and writes all nX-sig data in config
# "storage_dir" (csv files for trades, json files for
# rules and the watcher)
#
# public functions:
#   trade_add(stock, trade_type,
#                        count, price)
#       record a BUY/SELL trade in
#       {stock}_trades.csv
#   trades_get_all(stock)
#       return all recorded trades for a stock
#   trade_delete(stock, trade_id)
#       delete the trade with the given Id from
#       {stock}_trades.csv
#   trades_total_get(stock)
#       return (count held, average buy price) for a
#       stock, computed from its trades
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
#       the saved ladders of ladders.csv (see ladder.py)
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
#       the price alerts of alerts.csv (see alerts.py)
#   alerts_status_get(), alerts_status_set(status)
#       heartbeat of the alerts process (dict), with the
#       stocks past each alert, in alerts_status.json
#   tasks_owner_get(), tasks_owner_set(owner)
#       the device that runs the background tasks
#       (dict, None clears it), kept in
#       tasks_owner.json, see tasks_owner.py
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

try:
    import fcntl
except ImportError:  # Windows
    fcntl = None
    import msvcrt

# config.json, .env and data/ live in the repo root, one
# level above scripts/
ROOT_DIR = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)

with open(os.path.join(ROOT_DIR, "config.json")) as f:
    config = json.load(f)

# storage_dir is relative to the repo root (or absolute)
DB_DIR = os.path.normpath(
    os.path.join(ROOT_DIR, config["storage_dir"])
)
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
Stock = Enum("Stock", config["indices"])


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
def trade_add(stock, trade_type, count, price):
    """
    Add trade to {stock_name}_trades.csv file

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

    rows.append(
        {
            "Id": next_id,
            "Date": now.strftime("%d.%m.%Y"),
            "Time": now.strftime("%H:%M"),
            "Type": trade_type.name,
            "Count": count,
            "Price": price,
        }
    )
    _write_csv_atomic(path, TRADE_FIELDNAMES, rows)


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


def _total_apply(
    total_count, avg_price, trade_type, count, price
):
    """
    return (total_count, avg_price) after applying one
    trade to them
    """
    if trade_type == TradeType.BUY:
        if total_count + count > 0:
            avg_price = (
                avg_price * total_count + price * count
            ) / (total_count + count)
        total_count += count
    else:  # sell
        total_count -= count
    return total_count, avg_price


def trades_total_get(stock):
    """
    return (total_count, avg_price) for a stock,
    computed from its trades in {stock_name}_trades.csv

    for every trade in order:
        if BUY :
            avg_price = (avg_price * total_count
                         + price * count)
                        / (total_count + count)
            total_count += count
        else : # sell
            total_count -= count
    """
    total_count, avg_price = 0, 0.0
    for t in trades_get_all(stock):
        total_count, avg_price = _total_apply(
            total_count,
            avg_price,
            t["Type"],
            t["Count"],
            t["Price"],
        )
    return total_count, avg_price


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
    order = config["indices"]
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


if __name__ == "__main__":
    import tempfile
    import unittest

    class TradesTest(unittest.TestCase):
        def setUp(self):
            # redirect csv files to a temp dir so real data
            # is not touched
            global DB_DIR
            self._tmp = tempfile.TemporaryDirectory()
            self._orig_db_dir = DB_DIR
            DB_DIR = self._tmp.name

        def tearDown(self):
            global DB_DIR
            DB_DIR = self._orig_db_dir
            self._tmp.cleanup()

        def test_get_without_file_returns_empty(self):
            self.assertEqual(trades_get_all(Stock.SOXL), [])

        def test_add_creates_file_with_header(self):
            trade_add(Stock.TSMX, TradeType.BUY, 10, 250)

            with open(
                _trades_path(Stock.TSMX), newline=""
            ) as f:
                rows = list(csv.reader(f))
            self.assertEqual(rows[0], TRADE_FIELDNAMES)
            self.assertEqual(rows[1][0], "1")
            self.assertEqual(
                rows[1][3:], ["BUY", "10", "250"]
            )
            self.assertEqual(len(rows), 2)

        def test_add_and_get_roundtrip(self):
            trade_add(Stock.TSMX, TradeType.BUY, 10, 250)
            trade_add(Stock.TSMX, TradeType.SELL, 5, 260.5)

            trades = trades_get_all(Stock.TSMX)
            self.assertEqual(len(trades), 2)
            self.assertEqual(
                [t["Id"] for t in trades], [1, 2]
            )
            self.assertEqual(
                trades[0]["Type"], TradeType.BUY
            )
            self.assertEqual(trades[0]["Count"], 10)
            self.assertEqual(trades[0]["Price"], 250.0)
            self.assertEqual(
                trades[1]["Type"],
                TradeType.SELL,
            )
            self.assertEqual(trades[1]["Count"], 5)
            self.assertEqual(trades[1]["Price"], 260.5)

        def test_date_and_time_format(self):
            trade_add(Stock.SOXL, TradeType.BUY, 1, 100)

            trade = trades_get_all(Stock.SOXL)[0]
            datetime.strptime(trade["Date"], "%d.%m.%Y")
            datetime.strptime(trade["Time"], "%H:%M")

        def test_stocks_are_stored_separately(self):
            trade_add(Stock.SOXL, TradeType.BUY, 1, 100)
            trade_add(Stock.TSMX, TradeType.BUY, 2, 200)

            self.assertEqual(
                len(trades_get_all(Stock.SOXL)), 1
            )
            self.assertEqual(
                len(trades_get_all(Stock.TSMX)), 1
            )
            self.assertEqual(
                trades_get_all(Stock.TSMX)[0]["Count"],
                2,
            )

        def test_total_buy_averages_price(self):
            trade_add(Stock.TSMX, TradeType.BUY, 10, 250)
            trade_add(Stock.TSMX, TradeType.BUY, 10, 270)

            self.assertEqual(
                trades_total_get(Stock.TSMX),
                (20, 260.0),
            )

        def test_total_sell_keeps_price(self):
            trade_add(Stock.TSMX, TradeType.BUY, 10, 250)
            trade_add(Stock.TSMX, TradeType.SELL, 4, 300)

            self.assertEqual(
                trades_total_get(Stock.TSMX),
                (6, 250.0),
            )

        def test_total_of_each_stock(self):
            trade_add(Stock.SOXL, TradeType.BUY, 1, 100)
            trade_add(Stock.TSMX, TradeType.BUY, 2, 200)

            self.assertEqual(
                trades_total_get(Stock.SOXL),
                (1, 100.0),
            )
            self.assertEqual(
                trades_total_get(Stock.TSMX),
                (2, 200.0),
            )
            self.assertEqual(
                trades_total_get(Stock.NVDL), (0, 0.0)
            )

        def test_total_follows_edited_trades_file(self):
            # e.g. a hand edit or a Syncthing conflict
            trade_add(Stock.TSMX, TradeType.BUY, 10, 250)
            path = _trades_path(Stock.TSMX)
            with open(path) as f:
                text = f.read()
            with open(path, "w") as f:
                f.write(text.replace(",10,250", ",4,300"))

            self.assertEqual(
                trades_total_get(Stock.TSMX),
                (4, 300.0),
            )

        def test_delete_removes_row_and_keeps_ids(self):
            trade_add(Stock.TSMX, TradeType.BUY, 10, 250)
            trade_add(Stock.TSMX, TradeType.BUY, 10, 270)
            trade_add(Stock.TSMX, TradeType.SELL, 5, 300)

            self.assertTrue(trade_delete(Stock.TSMX, 2))

            trades = trades_get_all(Stock.TSMX)
            self.assertEqual(
                [t["Id"] for t in trades], [1, 3]
            )
            self.assertEqual(
                trades[1]["Type"],
                TradeType.SELL,
            )

        def test_delete_recalculates_total(self):
            trade_add(Stock.TSMX, TradeType.BUY, 10, 250)
            trade_add(Stock.TSMX, TradeType.BUY, 10, 270)
            trade_add(Stock.TSMX, TradeType.SELL, 5, 300)
            trade_add(Stock.SOXL, TradeType.BUY, 1, 100)

            trade_delete(Stock.TSMX, 2)

            self.assertEqual(
                trades_total_get(Stock.TSMX),
                (5, 250.0),
            )
            self.assertEqual(
                trades_total_get(Stock.SOXL),
                (1, 100.0),
            )

        def test_delete_last_trade_resets_total(self):
            trade_add(Stock.TSMX, TradeType.BUY, 10, 250)

            self.assertTrue(trade_delete(Stock.TSMX, 1))

            self.assertEqual(trades_get_all(Stock.TSMX), [])
            self.assertEqual(
                trades_total_get(Stock.TSMX), (0, 0.0)
            )

        def test_delete_unknown_id_returns_false(self):
            self.assertFalse(trade_delete(Stock.TSMX, 1))
            trade_add(Stock.TSMX, TradeType.BUY, 10, 250)

            self.assertFalse(trade_delete(Stock.TSMX, 5))
            self.assertEqual(
                len(trades_get_all(Stock.TSMX)), 1
            )

        def test_add_after_delete_does_not_reuse_id(
            self,
        ):
            trade_add(Stock.TSMX, TradeType.BUY, 10, 250)
            trade_add(Stock.TSMX, TradeType.BUY, 10, 270)
            trade_delete(Stock.TSMX, 1)
            trade_add(Stock.TSMX, TradeType.BUY, 1, 100)

            self.assertEqual(
                [
                    t["Id"]
                    for t in trades_get_all(Stock.TSMX)
                ],
                [2, 3],
            )

        def test_failed_write_keeps_old_file(self):
            # and leaves no temp files
            trade_add(Stock.TSMX, TradeType.BUY, 10, 250)
            path = _trades_path(Stock.TSMX)
            with open(path, newline="") as f:
                before = f.read()

            class Boom(dict):
                def keys(self):
                    raise RuntimeError("boom")

            with self.assertRaises(Exception):
                _write_csv_atomic(
                    path,
                    TRADE_FIELDNAMES,
                    [{"Id": 1}, Boom()],
                )

            with open(path, newline="") as f:
                self.assertEqual(f.read(), before)
            self.assertEqual(
                sorted(
                    f
                    for f in os.listdir(DB_DIR)
                    if f != ".lock"
                ),
                ["tsmx_trades.csv"],
            )

        def test_rules_without_file_returns_empty(self):
            self.assertEqual(rules_get_all(), [])
            self.assertIsNone(rules_delete(1))

        def test_rules_add_and_get(self):
            self.assertEqual(
                rules_add("never buy on a gap up"), 1
            )
            self.assertEqual(
                rules_add("sell half at +20%"), 2
            )

            self.assertEqual(
                rules_get_all(),
                [
                    {
                        "Id": 1,
                        "Rule": "never buy on a gap up",
                    },
                    {"Id": 2, "Rule": "sell half at +20%"},
                ],
            )

        def test_rules_delete_renumbers(self):
            rules_add("first")
            rules_add("second")
            rules_add("third")

            self.assertEqual(rules_delete(2), "second")

            self.assertEqual(
                rules_get_all(),
                [
                    {"Id": 1, "Rule": "first"},
                    {"Id": 2, "Rule": "third"},
                ],
            )
            self.assertIsNone(rules_delete(5))
            self.assertEqual(len(rules_get_all()), 2)

        def test_mail_position(self):
            self.assertIsNone(mail_position_get())
            mail_position_set("777", 42)
            self.assertEqual(
                mail_position_get(), ("777", 42)
            )

        def test_watcher_status(self):
            self.assertIsNone(watcher_status_get())
            watcher_status_set(
                {
                    "state": "waiting",
                    "updated": "2026-10-10T12:00:00",
                }
            )
            self.assertEqual(
                watcher_status_get()["state"], "waiting"
            )

        def test_basetrades(self):
            self.assertEqual(basetrades_get_all(), [])
            self.assertFalse(basetrade_set("SOXL", 20.5, 3))
            self.assertFalse(
                basetrade_set("MRVU", 100.0, 10)
            )
            # config order (MRVU before SOXL), not the
            # order they were added in
            self.assertEqual(
                [b["Stock"] for b in basetrades_get_all()],
                ["MRVU", "SOXL"],
            )
            self.assertEqual(
                basetrades_get_all()[1],
                {
                    "Stock": "SOXL",
                    "Price": 20.5,
                    "Count": 3,
                },
            )

            # one per stock: a new one replaces the old
            self.assertTrue(basetrade_set("SOXL", 19.0, 5))
            self.assertEqual(len(basetrades_get_all()), 2)
            self.assertEqual(
                basetrades_get_all()[1]["Price"], 19.0
            )

            self.assertEqual(
                basetrade_delete("MRVU")["Count"], 10
            )
            self.assertIsNone(basetrade_delete("MRVU"))
            self.assertEqual(
                [b["Stock"] for b in basetrades_get_all()],
                ["SOXL"],
            )

        def test_alerts(self):
            self.assertEqual(alerts_get_all(), [])
            self.assertEqual(
                alert_add("basetrades", "down", 10.0), 1
            )
            self.assertEqual(
                alert_add("basetrades", "up", 2.5), 2
            )
            alert_add(
                "gain", "down", stock="TSMX", amount=50.0
            )
            gain = alerts_get_all()[2]
            self.assertEqual(
                (
                    gain["For"],
                    gain["Stock"],
                    gain["Amount"],
                    gain["Percent"],
                ),
                ("gain", "TSMX", 50.0, None),
            )
            self.assertEqual(
                alerts_get_all()[0]["Stock"], ""
            )
            first = alerts_get_all()[0]
            self.assertEqual(
                {k: first[k] for k in ALERT_FIELDNAMES[:4]},
                {
                    "Id": 1,
                    "For": "basetrades",
                    "Direction": "down",
                    "Percent": 10.0,
                },
            )
            alerts_status_set(
                {"state": "waiting", "past": {"1": {}}}
            )
            self.assertEqual(alert_delete(1)["Id"], 1)
            self.assertIsNone(alert_delete(1))
            self.assertEqual(
                alerts_status_get(),
                {"state": "waiting", "past": {}},
            )
            # the next Id follows the highest one
            self.assertEqual(
                alert_add("basetrades", "down", 5.0), 4
            )

        def test_ladders(self):
            self.assertEqual(ladders_get_all(), [])
            self.assertIsNone(ladder_get(1))
            self.assertEqual(
                ladder_add("SOXL", "down", 10, 100), 1
            )
            self.assertEqual(
                ladder_add("TSMX", "up", 2.5, 80.5), 2
            )

            ladder = ladder_get(2)
            self.assertEqual(ladder["Stock"], "TSMX")
            self.assertEqual(ladder["Direction"], "up")
            self.assertEqual(ladder["Step"], 2.5)
            self.assertEqual(ladder["Last"], 80.5)

            self.assertTrue(ladder_set_last(1, 90))
            self.assertFalse(ladder_set_last(5, 90))
            self.assertEqual(ladder_get(1)["Last"], 90.0)
            self.assertEqual(ladder_get(2)["Last"], 80.5)

        def test_ladder_delete(self):
            ladder_add("SOXL", "down", 10, 100)
            ladder_add("TSMX", "up", 1, 50)
            ladder_status_set(1, {"state": "stopped"})
            ladder_status_set(2, {"state": "waiting"})

            self.assertTrue(ladder_delete(1))
            self.assertFalse(ladder_delete(1))
            self.assertEqual(
                [l["Id"] for l in ladders_get_all()], [2]
            )
            self.assertIsNone(ladder_status_get(1))
            self.assertEqual(
                ladder_status_get(2)["state"], "waiting"
            )

        def test_ladder_status(self):
            self.assertIsNone(ladder_status_get(1))
            ladder_status_set(1, {"state": "waiting"})
            ladder_status_set(2, {"state": "starting"})
            self.assertEqual(
                ladder_status_get(1), {"state": "waiting"}
            )
            self.assertEqual(
                ladder_status_get(2)["state"], "starting"
            )

        def test_lock_is_reentrant(self):
            with _db_lock():
                with _db_lock():
                    trade_add(
                        Stock.TSMX,
                        TradeType.BUY,
                        1,
                        100,
                    )
            self.assertEqual(
                trades_total_get(Stock.TSMX),
                (1, 100.0),
            )

        @unittest.skipUnless(
            fcntl and hasattr(os, "fork"),
            "needs fork and fcntl",
        )
        def test_parallel_processes_lose_nothing(self):
            import multiprocessing

            def add_many():
                for _ in range(25):
                    trade_add(
                        Stock.TSMX,
                        TradeType.BUY,
                        1,
                        100,
                    )

            # the forked processes inherit the temp DB_DIR
            processes = [
                multiprocessing.get_context("fork").Process(
                    target=add_many
                )
                for _ in range(4)
            ]
            for p in processes:
                p.start()
            for p in processes:
                p.join()

            trades = trades_get_all(Stock.TSMX)
            self.assertEqual(len(trades), 100)
            self.assertEqual(
                sorted(t["Id"] for t in trades),
                list(range(1, 101)),
            )
            self.assertEqual(
                trades_total_get(Stock.TSMX),
                (100, 100.0),
            )

    unittest.main()

    # trade_add(Stock.SOXL, TradeType.BUY,
    # 1, 100) trade_add(Stock.TSMX,
    # TradeType.BUY, 2, 200)
