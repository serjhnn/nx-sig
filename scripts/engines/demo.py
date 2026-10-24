# demo: the demo engine, the sample data of ./nxdemo,
# which runs nX-sig without keys or accounts
#
#   python tests/test_demo.py   the tests
#
# the demo reads demo/config.json and keeps its data in
# its own folder (demo_data/), see config.py; the sample
# data (trades, basetrades, rules, a ladder, an alert)
# is in demo/seed/
#
# public functions:
#   prepare()   at the demo's first start, fill its data
#               folder with the sample data; True if it
#               did
#   reset()     replace the demo data with the sample
#               data again

import config
import storage


def prepare():
    return storage.demo_fill(config.DEMO_SEED_DIR)


def reset():
    storage.demo_fill(config.DEMO_SEED_DIR, reset=True)
