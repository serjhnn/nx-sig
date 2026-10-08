# trade engine: polls the latest trades for config["indices"] in a background thread
#
# public functions:
#   start_polling(interval=5)
#       start a thread that every `interval` seconds requests config["url"],
#       collects {index: price} for config["indices"] and prints it.
#       returns a threading.Event, call .set() on it to stop the thread

import json
import os
import threading

import requests
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

load_dotenv(os.path.join(BASE_DIR, ".env"))
with open(os.path.join(BASE_DIR, "config.json")) as f:
    config = json.load(f)


def start_polling(interval=5):
    stop_event = threading.Event()
    thread = threading.Thread(target=_poll, args=(interval, stop_event), daemon=True)
    thread.start()
    return stop_event


def _poll(interval, stop_event):
    headers = {
        "accept": "application/json",
        "APCA-API-KEY-ID": os.environ["APCA_API_KEY_ID"],
        "APCA-API-SECRET-KEY": os.environ["APCA_API_SECRET_KEY"]
    }

    # wait() returns True once stop_event is set, otherwise sleeps `interval` seconds
    while True:
        try:
            print(_latest_prices(headers))
        except requests.RequestException as e:
            print(f"trade engine: request failed: {e}")

        if stop_event.wait(interval):
            break


def _latest_prices(headers):
    response = requests.get(config["url"],
        params = {
            "symbols": ",".join(config["indices"]),
            "feed": config["feed"]
            },
        headers=headers,
        timeout=15)
    response.raise_for_status()

    trades = response.json()["trades"]
    return {index: trades[index]["p"] for index in config["indices"] if index in trades}


if __name__ == "__main__":
    stop = start_polling()
    try:
        input("polling, press Enter to stop\n")
    finally:
        stop.set()
