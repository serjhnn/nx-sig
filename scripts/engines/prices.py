# prices: the prices engine, the market prices of
# config["indices"] from Alpaca (the latest trade of
# each, and their bars), once or polled in a background
# thread; the only module that requests prices
#
# in the demo (config.demo()) the prices are the made
# up ones of engines/demo_prices.py instead: no keys,
# no network, the feed and timeframe are not used
#
# public functions:
#   start_polling(interval=5, on_update=print, on_error=...)
#       start a thread that every `interval` seconds
#       requests config["url"], collects {index: price} for
#       config["indices"] and passes it to on_update (prints
#       it by default). failed requests go to on_error.
#       returns a threading.Event, call .set() on it to stop
#       the thread
#   get_latest_prices(feed=None)
#       request config["url"] once and return {index: price}
#       for config["indices"], raises
#       requests.RequestException if the request fails;
#       feed (e.g. iex or delayed_sip) replaces config
#       "feed" for this request
#   get_bars(symbol, days, timeframe)
#       [(local time, close price)] of symbol's bars of
#       the last days, oldest first, from Alpaca's bars
#       endpoint (config "bars_url"); timeframe is e.g.
#       1Hour or 1Day

import os
import threading
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv

import config
from engines import demo_prices

load_dotenv(os.path.join(config.ROOT_DIR, ".env"))

# the free plan's historical bars: the sip feed without
# its newest 15 minutes (there is no delayed_sip feed for
# bars); config "bars_feed" (e.g. iex) chooses another
BARS_DELAY = timedelta(minutes=16)


def _print_error(e):
    print(f"prices: request failed: {e}")


def start_polling(
    interval=5, on_update=print, on_error=_print_error
):
    stop_event = threading.Event()
    thread = threading.Thread(
        target=_poll,
        args=(interval, stop_event, on_update, on_error),
        daemon=True,
    )
    thread.start()
    return stop_event


def get_latest_prices(feed=None):
    if config.demo():
        return _demo_latest()
    return _latest_prices(_headers(), feed)


def _headers():
    return {
        "accept": "application/json",
        "APCA-API-KEY-ID": os.environ["APCA_API_KEY_ID"],
        "APCA-API-SECRET-KEY": os.environ[
            "APCA_API_SECRET_KEY"
        ],
    }


def _poll(interval, stop_event, on_update, on_error):
    if config.demo():
        latest = _demo_latest
    else:
        headers = _headers()

        def latest():
            return _latest_prices(headers)

    # wait() returns True once stop_event is set, otherwise
    # sleeps `interval` seconds
    while True:
        try:
            on_update(latest())
        except requests.RequestException as e:
            on_error(e)

        if stop_event.wait(interval):
            break


def _latest_prices(headers, feed=None):
    response = requests.get(
        config.url(),
        params={
            "symbols": ",".join(config.indices()),
            "feed": feed or config.feed(),
        },
        headers=headers,
        timeout=15,
    )
    response.raise_for_status()

    trades = response.json()["trades"]
    return {
        index: trades[index]["p"]
        for index in config.indices()
        if index in trades
    }


def _demo_latest():
    found = demo_prices.latest()
    return {
        index: found[index]
        for index in config.indices()
        if index in found
    }


def get_bars(symbol, days, timeframe):
    if config.demo():
        return demo_prices.bars(symbol, days)
    return _bars(_headers(), symbol, days, timeframe)


def _bars(headers, symbol, days, timeframe):
    end = datetime.now(timezone.utc) - BARS_DELAY
    params = {
        "symbols": symbol,
        "timeframe": timeframe,
        "start": _iso(end - timedelta(days=days)),
        "end": _iso(end),
        "feed": config.bars_feed(),
        "adjustment": "split",
        "limit": 10000,
    }
    bars = []
    while True:
        response = requests.get(
            config.bars_url(),
            params=params,
            headers=headers,
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
        for bar in (data.get("bars") or {}).get(symbol, []):
            when = datetime.fromisoformat(bar["t"])
            # local time without a zone, like the trades
            local = when.astimezone().replace(tzinfo=None)
            bars.append((local, float(bar["c"])))
        token = data.get("next_page_token")
        if not token:
            return bars
        params["page_token"] = token


def _iso(when):
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


if __name__ == "__main__":
    stop = start_polling()
    try:
        input("polling, press Enter to stop\n")
    finally:
        stop.set()
