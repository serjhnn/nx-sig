# demo: the demo engine, the sample data of ./nxdemo,
# which runs nX-sig without keys or accounts
#
#   python tests/test_demo.py   the tests
#
# the demo reads demo/config.json and keeps its data in
# its own folder (demo_data/), see config.py; the sample
# data (trades, basetrades, rules, a ladder, an alert)
# is in demo/seed/, the prices are made by
# engines/demo_prices.py
#
# public functions:
#   prepare()   at the demo's first start, fill its data
#               folder with the sample data and make
#               the prices; True if it did
#   reset()     stop the demo's ladders and alerts,
#               then the sample data and new prices
#               again; return how many tasks stopped
#   message_add(text)
#               keep a message of a ladder or an alert
#               (notifiers/demo_notify.py), the last
#               KEEP_MESSAGES
#   messages_new()
#               the messages the shell hasn't shown yet

import config
import storage
from engines import alerts, demo_prices, ladder

KEEP_MESSAGES = 100


def prepare():
    filled = storage.demo_fill(config.DEMO_SEED_DIR)
    demo_prices.ensure()
    return filled


def reset():
    if not config.demo():
        raise RuntimeError("reset outside the demo")
    stopped = sum(
        ladder.stop(saved["Id"])
        for saved in ladder.get_all()
    )
    stopped += alerts.stop()
    storage.demo_fill(config.DEMO_SEED_DIR, reset=True)
    demo_prices.create()
    return stopped


def message_add(text):
    storage.demo_message_add(text, KEEP_MESSAGES)


def messages_new():
    return storage.demo_messages_take()
