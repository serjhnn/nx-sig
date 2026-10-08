# handle read and write requests to database
# use csv file as a first approach
#
# public functions:
#   transactions_add_one(stock, transaction_type, count, price)
#       record a BUY/SELL transaction in {stock}_transactions.csv
#       and update the stock's totals in transactions_total.csv
#   transactions_get_all(stock)
#       return all recorded transactions for a stock
#   transactions_total_get(stock)
#       return (count held, average buy price) for a stock

# usage example
# transactions_add_one(Stock.NVDA, TransactionType.BUY, 1, 100)

import csv
import os
from datetime import datetime
from enum import Enum
import json

with open("config.json") as f:
    config = json.load(f)

# DB_DIR = os.path.dirname(os.path.abspath(__file__))
DB_DIR = config["storage_dir"]
FIELDNAMES = ["Date", "Time", "Type", "Count", "Price"]
TOTAL_FIELDNAMES = ["Type", "Count", "Price"]

class Stock(Enum):
    NVDA = 1
    MRVL = 2

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
    path = _transactions_path(stock)
    write_header = not os.path.exists(path) or os.path.getsize(path) == 0
    now = datetime.now()

    with open(path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        if write_header:
            writer.writeheader()
        writer.writerow({
            "Date": now.strftime("%d.%m.%Y"),
            "Time": now.strftime("%H:%M"),
            "Type": transaction_type.name,
            "Count": count,
            "Price": price,
        })

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
                "Date": row["Date"],
                "Time": row["Time"],
                "Type": TransactionType[row["Type"]],
                "Count": int(row["Count"]),
                "Price": float(row["Price"]),
            }
            for row in csv.DictReader(f)
        ]

def _transactions_path(stock):
    return os.path.join(DB_DIR, f"{stock.name.lower()}_transactions.csv")


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
    path = _transactions_total_path()
    rows = []
    if os.path.exists(path):
        with open(path, newline="") as f:
            rows = list(csv.DictReader(f))

    row = next((r for r in rows if r["Type"] == stock.name), None)
    if row is None:
        row = {"Type": stock.name, "Count": 0, "Price": 0}
        rows.append(row)

    total_count = int(row["Count"])
    avg_price = float(row["Price"])

    if transaction_type == TransactionType.BUY:
        if total_count + count > 0:
            avg_price = (avg_price * total_count + price * count) / (total_count + count)
        total_count += count
    else:  # sell
        total_count -= count

    row["Count"] = total_count
    row["Price"] = avg_price

    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=TOTAL_FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

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
            self.assertEqual(rows[1][2:], ["BUY", "10", "250"])
            self.assertEqual(len(rows), 2)

        def test_add_and_get_roundtrip(self):
            transactions_add_one(Stock.MRVL, TransactionType.BUY, 10, 250)
            transactions_add_one(Stock.MRVL, TransactionType.SELL, 5, 260.5)

            transactions = transactions_get_all(Stock.MRVL)
            self.assertEqual(len(transactions), 2)
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

    unittest.main()

    #transactions_add_one(Stock.NVDA, TransactionType.BUY, 1, 100)
    #transactions_add_one(Stock.MRVL, TransactionType.BUY, 2, 200)
