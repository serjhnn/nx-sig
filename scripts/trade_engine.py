# trade engine: polls the latest trades for
# config["indices"] in a background thread
#
# public functions:
#   start_polling(interval=5, on_update=print, on_error=...)
#       start a thread that every `interval` seconds
#       requests config["url"], collects {index: price} for
#       config["indices"] and passes it to on_update (prints
#       it by default). failed requests go to on_error.
#       returns a threading.Event, call .set() on it to stop
#       the thread
#   get_latest_prices()
#       request config["url"] once and return {index: price}
#       for config["indices"], raises
#       requests.RequestException if the request fails

import json
import os
import threading

import requests
from dotenv import load_dotenv

# config.json and .env live in the repo root, one level
# above scripts/
ROOT_DIR = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)

load_dotenv(os.path.join(ROOT_DIR, ".env"))
with open(os.path.join(ROOT_DIR, "config.json")) as f:
    config = json.load(f)


def _print_error(e):
    print(f"trade engine: request failed: {e}")


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


def get_latest_prices():
    return _latest_prices(_headers())


def _headers():
    return {
        "accept": "application/json",
        "APCA-API-KEY-ID": os.environ["APCA_API_KEY_ID"],
        "APCA-API-SECRET-KEY": os.environ[
            "APCA_API_SECRET_KEY"
        ],
    }


def _poll(interval, stop_event, on_update, on_error):
    headers = _headers()

    # wait() returns True once stop_event is set, otherwise
    # sleeps `interval` seconds
    while True:
        try:
            on_update(_latest_prices(headers))
        except requests.RequestException as e:
            on_error(e)

        if stop_event.wait(interval):
            break


def _latest_prices(headers):
    response = requests.get(
        config["url"],
        params={
            "symbols": ",".join(config["indices"]),
            "feed": config["feed"],
        },
        headers=headers,
        timeout=15,
    )
    response.raise_for_status()

    trades = response.json()["trades"]
    return {
        index: trades[index]["p"]
        for index in config["indices"]
        if index in trades
    }


if __name__ == "__main__":
    stop = start_polling()
    try:
        input("polling, press Enter to stop\n")
    finally:
        stop.set()
