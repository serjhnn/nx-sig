# handle read and write requests to database
# use csv file as a first approach
#
# public functions:
#   transactions_add_one(stock, transaction_type, count, price)
#       record a BUY/SELL transaction in {stock}_transactions.csv
#       and update the stock's totals in transactions_total.csv
#   transactions_get_all(stock)
#       return all recorded transactions for a stock
#   transactions_delete(stock, index)
#       delete the transaction with the given Index from {stock}_transactions.csv
#       and recalculate the stock's totals in transactions_total.csv
#   transactions_total_get(stock)
#       return (count held, average buy price) for a stock
#   rules_get_all()
#       return all personal rules from personal_rules.json, numbered from 1
#   rules_add(rule)
#       add a personal rule to personal_rules.json
#   rules_delete(rule_id)
#       delete a personal rule by its Id, the remaining rules are renumbered

# usage example
# transactions_add_one(Stock.NVDA, TransactionType.BUY, 1, 100)

import csv
import os
import tempfile
from datetime import datetime
from enum import Enum
import json

with open("config.json") as f:
    config = json.load(f)

# DB_DIR = os.path.dirname(os.path.abspath(__file__))
DB_DIR = config["storage_dir"]
FIELDNAMES = ["Index", "Date", "Time", "Type", "Count", "Price"]
TOTAL_FIELDNAMES = ["Type", "Count", "Price"]

# stocks are the "indices" listed in config.json
Stock = Enum("Stock", config["indices"])

class TransactionType(Enum):
    BUY = 1
    SELL = 2

def transactions_add_one(stock, transaction_type, count, price):
    """ 
    Add transaction to {stock_name}_transactions.csv file 
    
        mrvl_transactions.csv
    _____________________________________________
    |       Date |  Time | Type | Count | Price |
    | 05.10.2026 | 14:30 | MRVL |    10 |   250 |

    """
    os.makedirs(DB_DIR, exist_ok=True)
    path = _transactions_path(stock)
    rows = []
    if os.path.exists(path) and os.path.getsize(path) > 0:
        with open(path, newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        # Upgrade existing files that predate the Index column, preserving row order.
        if "Index" not in (reader.fieldnames or []):
            for index, row in enumerate(rows, 1):
                row["Index"] = index
    # Indexes stay stable after deletions, so continue from the highest one.
    next_index = max((int(row["Index"]) for row in rows), default=0) + 1
    now = datetime.now()

    rows.append({
        "Index": next_index,
        "Date": now.strftime("%d.%m.%Y"),
        "Time": now.strftime("%H:%M"),
        "Type": transaction_type.name,
        "Count": count,
        "Price": price,
    })
    _write_csv_atomic(path, FIELDNAMES, rows)

    _transactions_total_save(stock, transaction_type, count, price)

def transactions_get_all(stock):
    """
        return all transactions stored in file {stock_name}_transactions.csv
        in a dictionary
    """
    path = _transactions_path(stock)
    if not os.path.exists(path):
        return []

    with open(path, newline="") as f:
        return [
            {
                "Index": int(row.get("Index") or index),
                "Date": row["Date"],
                "Time": row["Time"],
                "Type": TransactionType[row["Type"]],
                "Count": int(row["Count"]),
                "Price": float(row["Price"]),
            }
            for index, row in enumerate(csv.DictReader(f), 1)
        ]

def transactions_delete(stock, index):
    """
        delete the transaction with the given Index from {stock_name}_transactions.csv
        and recalculate the stock's totals in transactions_total.csv

        remaining transactions keep their Index
        return True if a transaction was deleted, False if the index was not found
    """
    transactions = transactions_get_all(stock)
    remaining = [t for t in transactions if t["Index"] != index]
    if len(remaining) == len(transactions):
        return False

    _write_csv_atomic(_transactions_path(stock), FIELDNAMES,
                      [{**t, "Type": t["Type"].name} for t in remaining])

    # replay the remaining transactions to rebuild the totals from scratch
    total_count, avg_price = 0, 0.0
    for t in remaining:
        total_count, avg_price = _total_apply(total_count, avg_price, t["Type"], t["Count"], t["Price"])
    _transactions_total_set(stock, total_count, avg_price)
    return True

def _transactions_path(stock):
    return os.path.join(DB_DIR, f"{stock.name.lower()}_transactions.csv")

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
        call write(f) on a temporary file in the same directory, then replace path with it,
        so a crash or error mid-write never leaves a truncated or half-written file
    """
    directory = os.path.dirname(path) or "."
    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".tmp_", suffix=os.path.splitext(path)[1])
    try:
        with os.fdopen(fd, "w", newline="") as f:
            write(f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)  # atomic on both POSIX and Windows
    except BaseException:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def _transactions_total_save(stock, transaction_type, count, price):
    """
        save transactions total in transactions_total.csv file

            transactions_total.csv
     ______________________
    | Type | Count | Price |
    | MRVL |    10 |   250 |

    where
        Count and price are repeatedly updated after every transaction 
        Count - total sum of all stocks buyed and still not sold
        Price - average price for a stock for multiple buy transaction  

        if BUY :
            avg_price = (avg_price * total_count + price * count) / (total_count + count) 
            total_count += count
        else : # sell
            total_count -= count

        place total_count in "Count" row
        place avg_price in "Price" row 

        for a specified stock


    """
    total_count, avg_price = transactions_total_get(stock)
    total_count, avg_price = _total_apply(total_count, avg_price, transaction_type, count, price)
    _transactions_total_set(stock, total_count, avg_price)

def _total_apply(total_count, avg_price, transaction_type, count, price):
    """
        return (total_count, avg_price) after applying one transaction to them
    """
    if transaction_type == TransactionType.BUY:
        if total_count + count > 0:
            avg_price = (avg_price * total_count + price * count) / (total_count + count)
        total_count += count
    else:  # sell
        total_count -= count
    return total_count, avg_price

def _transactions_total_set(stock, total_count, avg_price):
    """
        store total_count and avg_price of a stock in transactions_total.csv
    """
    os.makedirs(DB_DIR, exist_ok=True)
    path = _transactions_total_path()
    rows = []
    if os.path.exists(path):
        with open(path, newline="") as f:
            rows = list(csv.DictReader(f))

    row = next((r for r in rows if r["Type"] == stock.name), None)
    if row is None:
        row = {"Type": stock.name}
        rows.append(row)
    row["Count"] = total_count
    row["Price"] = avg_price

    _write_csv_atomic(path, TOTAL_FIELDNAMES, rows)

def transactions_total_get(stock):
    """
        return (total_count, avg_price) for a stock from transactions_total.csv
    """
    path = _transactions_total_path()
    if os.path.exists(path):
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                if row["Type"] == stock.name:
                    return int(row["Count"]), float(row["Price"])
    return 0, 0.0

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
    return [{"Id": i, "Rule": rule["Rule"]} for i, rule in enumerate(rules, 1)]

def rules_add(rule):
    """
        add a personal rule to the end of personal_rules.json, return its Id
    """
    rules = rules_get_all()
    rules.append({"Id": len(rules) + 1, "Rule": rule})
    _rules_save(rules)
    return len(rules)

def rules_delete(rule_id):
    """
        delete the personal rule with the given Id from personal_rules.json,
        the remaining rules are renumbered from 1
        return the deleted rule text, or None if the Id was not found
    """
    rules = rules_get_all()
    deleted = next((r["Rule"] for r in rules if r["Id"] == rule_id), None)
    if deleted is None:
        return None
    _rules_save([r for r in rules if r["Id"] != rule_id])
    return deleted

def _rules_save(rules):
    os.makedirs(DB_DIR, exist_ok=True)
    rules = [{"Id": i, "Rule": r["Rule"]} for i, r in enumerate(rules, 1)]
    _write_atomic(_rules_path(), lambda f: json.dump(rules, f, indent=4, ensure_ascii=False))

def _rules_path():
    return os.path.join(DB_DIR, "personal_rules.json")

def _transactions_total_path():
    return os.path.join(DB_DIR, "transactions_total.csv")


if __name__ == "__main__":
    import tempfile
    import unittest

    class TransactionsTest(unittest.TestCase):
        def setUp(self):
            # redirect csv files to a temp dir so real data is not touched
            global DB_DIR
            self._tmp = tempfile.TemporaryDirectory()
            self._orig_db_dir = DB_DIR
            DB_DIR = self._tmp.name

        def tearDown(self):
            global DB_DIR
            DB_DIR = self._orig_db_dir
            self._tmp.cleanup()

        def test_get_without_file_returns_empty(self):
            self.assertEqual(transactions_get_all(Stock.NVDA), [])

        def test_add_creates_file_with_header(self):
            transactions_add_one(Stock.MRVL, TransactionType.BUY, 10, 250)

            with open(_transactions_path(Stock.MRVL), newline="") as f:
                rows = list(csv.reader(f))
            self.assertEqual(rows[0], FIELDNAMES)
            self.assertEqual(rows[1][0], "1")
            self.assertEqual(rows[1][3:], ["BUY", "10", "250"])
            self.assertEqual(len(rows), 2)

        def test_add_and_get_roundtrip(self):
            transactions_add_one(Stock.MRVL, TransactionType.BUY, 10, 250)
            transactions_add_one(Stock.MRVL, TransactionType.SELL, 5, 260.5)

            transactions = transactions_get_all(Stock.MRVL)
            self.assertEqual(len(transactions), 2)
            self.assertEqual([t["Index"] for t in transactions], [1, 2])
            self.assertEqual(transactions[0]["Type"], TransactionType.BUY)
            self.assertEqual(transactions[0]["Count"], 10)
            self.assertEqual(transactions[0]["Price"], 250.0)
            self.assertEqual(transactions[1]["Type"], TransactionType.SELL)
            self.assertEqual(transactions[1]["Count"], 5)
            self.assertEqual(transactions[1]["Price"], 260.5)

        def test_date_and_time_format(self):
            transactions_add_one(Stock.NVDA, TransactionType.BUY, 1, 100)

            transaction = transactions_get_all(Stock.NVDA)[0]
            datetime.strptime(transaction["Date"], "%d.%m.%Y")
            datetime.strptime(transaction["Time"], "%H:%M")

        def test_stocks_are_stored_separately(self):
            transactions_add_one(Stock.NVDA, TransactionType.BUY, 1, 100)
            transactions_add_one(Stock.MRVL, TransactionType.BUY, 2, 200)

            self.assertEqual(len(transactions_get_all(Stock.NVDA)), 1)
            self.assertEqual(len(transactions_get_all(Stock.MRVL)), 1)
            self.assertEqual(transactions_get_all(Stock.MRVL)[0]["Count"], 2)

        def test_total_buy_averages_price(self):
            transactions_add_one(Stock.MRVL, TransactionType.BUY, 10, 250)
            transactions_add_one(Stock.MRVL, TransactionType.BUY, 10, 270)

            self.assertEqual(transactions_total_get(Stock.MRVL), (20, 260.0))

        def test_total_sell_keeps_price(self):
            transactions_add_one(Stock.MRVL, TransactionType.BUY, 10, 250)
            transactions_add_one(Stock.MRVL, TransactionType.SELL, 4, 300)

            self.assertEqual(transactions_total_get(Stock.MRVL), (6, 250.0))

        def test_total_stocks_in_one_file(self):
            transactions_add_one(Stock.NVDA, TransactionType.BUY, 1, 100)
            transactions_add_one(Stock.MRVL, TransactionType.BUY, 2, 200)

            with open(_transactions_total_path(), newline="") as f:
                rows = list(csv.reader(f))
            self.assertEqual(rows[0], TOTAL_FIELDNAMES)
            self.assertEqual(len(rows), 3)
            self.assertEqual(transactions_total_get(Stock.NVDA), (1, 100.0))
            self.assertEqual(transactions_total_get(Stock.MRVL), (2, 200.0))

        def test_delete_removes_row_and_keeps_indexes(self):
            transactions_add_one(Stock.MRVL, TransactionType.BUY, 10, 250)
            transactions_add_one(Stock.MRVL, TransactionType.BUY, 10, 270)
            transactions_add_one(Stock.MRVL, TransactionType.SELL, 5, 300)

            self.assertTrue(transactions_delete(Stock.MRVL, 2))

            transactions = transactions_get_all(Stock.MRVL)
            self.assertEqual([t["Index"] for t in transactions], [1, 3])
            self.assertEqual(transactions[1]["Type"], TransactionType.SELL)

        def test_delete_recalculates_total(self):
            transactions_add_one(Stock.MRVL, TransactionType.BUY, 10, 250)
            transactions_add_one(Stock.MRVL, TransactionType.BUY, 10, 270)
            transactions_add_one(Stock.MRVL, TransactionType.SELL, 5, 300)
            transactions_add_one(Stock.NVDA, TransactionType.BUY, 1, 100)

            transactions_delete(Stock.MRVL, 2)

            self.assertEqual(transactions_total_get(Stock.MRVL), (5, 250.0))
            self.assertEqual(transactions_total_get(Stock.NVDA), (1, 100.0))

        def test_delete_last_transaction_resets_total(self):
            transactions_add_one(Stock.MRVL, TransactionType.BUY, 10, 250)

            self.assertTrue(transactions_delete(Stock.MRVL, 1))

            self.assertEqual(transactions_get_all(Stock.MRVL), [])
            self.assertEqual(transactions_total_get(Stock.MRVL), (0, 0.0))

        def test_delete_unknown_index_returns_false(self):
            self.assertFalse(transactions_delete(Stock.MRVL, 1))
            transactions_add_one(Stock.MRVL, TransactionType.BUY, 10, 250)

            self.assertFalse(transactions_delete(Stock.MRVL, 5))
            self.assertEqual(len(transactions_get_all(Stock.MRVL)), 1)

        def test_add_after_delete_does_not_reuse_index(self):
            transactions_add_one(Stock.MRVL, TransactionType.BUY, 10, 250)
            transactions_add_one(Stock.MRVL, TransactionType.BUY, 10, 270)
            transactions_delete(Stock.MRVL, 1)
            transactions_add_one(Stock.MRVL, TransactionType.BUY, 1, 100)

            self.assertEqual([t["Index"] for t in transactions_get_all(Stock.MRVL)], [2, 3])

        def test_failed_write_keeps_old_file_and_no_temp_files(self):
            transactions_add_one(Stock.MRVL, TransactionType.BUY, 10, 250)
            path = _transactions_path(Stock.MRVL)
            with open(path, newline="") as f:
                before = f.read()

            class Boom(dict):
                def keys(self):
                    raise RuntimeError("boom")
            with self.assertRaises(Exception):
                _write_csv_atomic(path, FIELDNAMES, [{"Index": 1}, Boom()])

            with open(path, newline="") as f:
                self.assertEqual(f.read(), before)
            self.assertEqual(sorted(os.listdir(DB_DIR)),
                             ["mrvl_transactions.csv", "transactions_total.csv"])

        def test_rules_without_file_returns_empty(self):
            self.assertEqual(rules_get_all(), [])
            self.assertIsNone(rules_delete(1))

        def test_rules_add_and_get(self):
            self.assertEqual(rules_add("never buy on a gap up"), 1)
            self.assertEqual(rules_add("sell half at +20%"), 2)

            self.assertEqual(rules_get_all(), [
                {"Id": 1, "Rule": "never buy on a gap up"},
                {"Id": 2, "Rule": "sell half at +20%"},
            ])

        def test_rules_delete_renumbers(self):
            rules_add("first")
            rules_add("second")
            rules_add("third")

            self.assertEqual(rules_delete(2), "second")

            self.assertEqual(rules_get_all(), [
                {"Id": 1, "Rule": "first"},
                {"Id": 2, "Rule": "third"},
            ])
            self.assertIsNone(rules_delete(5))
            self.assertEqual(len(rules_get_all()), 2)

        def test_add_upgrades_file_without_index_column(self):
            os.makedirs(DB_DIR, exist_ok=True)
            with open(_transactions_path(Stock.MRVL), "w", newline="") as f:
                f.write("Date,Time,Type,Count,Price\r\n05.10.2026,14:30,BUY,10,250\r\n")

            transactions_add_one(Stock.MRVL, TransactionType.BUY, 1, 100)

            self.assertEqual([t["Index"] for t in transactions_get_all(Stock.MRVL)], [1, 2])

    unittest.main()

    #transactions_add_one(Stock.NVDA, TransactionType.BUY, 1, 100)
    #transactions_add_one(Stock.MRVL, TransactionType.BUY, 2, 200)
