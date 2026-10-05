# handle read and write requests to database
# use csv file as a first approach

# usage example
# transaction_add(Stock.NVDA, TransactionType.BUY, 1, 100)

import csv
import os
from datetime import datetime
from enum import Enum

DB_DIR = os.path.dirname(os.path.abspath(__file__))
FIELDNAMES = ["Date", "Time", "Type", "Count", "Price"]

class Stock(Enum):
    NVDA = 1
    MRVL = 2

class TransactionType(Enum):
    BUY = 1
    SELL = 2

def transaction_add(stock, transaction_type, count, price):
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

def transactions_get(stock):
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
            self.assertEqual(transactions_get(Stock.NVDA), [])

        def test_add_creates_file_with_header(self):
            transaction_add(Stock.MRVL, TransactionType.BUY, 10, 250)

            with open(_transactions_path(Stock.MRVL), newline="") as f:
                rows = list(csv.reader(f))
            self.assertEqual(rows[0], FIELDNAMES)
            self.assertEqual(rows[1][2:], ["BUY", "10", "250"])
            self.assertEqual(len(rows), 2)

        def test_add_and_get_roundtrip(self):
            transaction_add(Stock.MRVL, TransactionType.BUY, 10, 250)
            transaction_add(Stock.MRVL, TransactionType.SELL, 5, 260.5)

            transactions = transactions_get(Stock.MRVL)
            self.assertEqual(len(transactions), 2)
            self.assertEqual(transactions[0]["Type"], TransactionType.BUY)
            self.assertEqual(transactions[0]["Count"], 10)
            self.assertEqual(transactions[0]["Price"], 250.0)
            self.assertEqual(transactions[1]["Type"], TransactionType.SELL)
            self.assertEqual(transactions[1]["Count"], 5)
            self.assertEqual(transactions[1]["Price"], 260.5)

        def test_date_and_time_format(self):
            transaction_add(Stock.NVDA, TransactionType.BUY, 1, 100)

            transaction = transactions_get(Stock.NVDA)[0]
            datetime.strptime(transaction["Date"], "%d.%m.%Y")
            datetime.strptime(transaction["Time"], "%H:%M")

        def test_stocks_are_stored_separately(self):
            transaction_add(Stock.NVDA, TransactionType.BUY, 1, 100)
            transaction_add(Stock.MRVL, TransactionType.BUY, 2, 200)

            self.assertEqual(len(transactions_get(Stock.NVDA)), 1)
            self.assertEqual(len(transactions_get(Stock.MRVL)), 1)
            self.assertEqual(transactions_get(Stock.MRVL)[0]["Count"], 2)

    unittest.main()

    #transaction_add(Stock.NVDA, TransactionType.BUY, 1, 100)
    #transaction_add(Stock.MRVL, TransactionType.BUY, 2, 200)
