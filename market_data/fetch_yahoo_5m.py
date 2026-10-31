# fetch_yahoo_5m: saves a month of 5-minute bars of a
# symbol, pre/post market included, from the yahoo
# chart api to a csv, each bar labeled pre, regular or
# post by its new york time
#
# usage: python fetch_yahoo_5m.py MRVU [out.csv]

import csv
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

ET = ZoneInfo("America/New_York")
URL = (
    "https://query1.finance.yahoo.com"
    "/v8/finance/chart/{}"
)
# regular session is 9:30-16:00 et, in minutes
OPEN, CLOSE = 9 * 60 + 30, 16 * 60
FIELDS = ("open", "high", "low", "close")


def session(dt):
    minute = dt.hour * 60 + dt.minute
    if minute < OPEN:
        return "pre"
    return "regular" if minute < CLOSE else "post"


def fetch(symbol):
    response = requests.get(
        URL.format(symbol),
        params={
            "interval": "5m",
            "range": "1mo",
            "includePrePost": "true",
        },
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["chart"]["result"][0]


def rows(result):
    quote = result["indicators"]["quote"][0]
    for i, ts in enumerate(result["timestamp"]):
        # yahoo leaves empty slots as nulls
        if quote["close"][i] is None:
            continue
        dt = datetime.fromtimestamp(ts, ET)
        prices = [
            round(quote[f][i], 4) for f in FIELDS
        ]
        volume = quote["volume"][i] or 0
        yield [dt.isoformat(), ts, session(dt)] + (
            prices + [volume]
        )


def main():
    symbol = sys.argv[1].upper()
    data = list(rows(fetch(symbol)))
    first, last = data[0][0][:10], data[-1][0][:10]
    name = f"{symbol}_5m_{first}_{last}.csv"
    out = sys.argv[2] if len(sys.argv) > 2 else name
    with open(out, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["datetime_et", "timestamp_utc", "session"]
            + list(FIELDS)
            + ["volume"]
        )
        writer.writerows(data)
    print(f"{len(data)} bars -> {out}")


if __name__ == "__main__":
    main()
