# ladder service: the process of one ladder, checks the
# price every INTERVAL seconds and notifies each level
# passed (engines/ladder.py starts and stops it)
#
#   python scripts/services/ladder_service.py <id>
#       run saved ladder <id> ('run ladder' in the shell
#       starts it)
#
# logs: {storage_dir}/logs/ladder_<id>.log

import logging
import os
import sys

import requests

# engines/ and process.py are in
# scripts/, one level up
sys.path.insert(
    1,
    os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))
    ),
)

import process
from engines import ladder
from notifiers.notifier import notify
from engines.prices import get_latest_prices

log = logging.getLogger("ladder")


def run(ladder_id):
    """check the price every INTERVAL seconds and notify
    each level passed, until SIGTERM or Ctrl+C"""
    process.service_setup(ladder.TASK, ladder_id)
    saved = ladder.get(ladder_id)
    if saved is None:
        log.error("no ladder %s in ladders.csv", ladder_id)
        sys.exit(1)
    log.info(
        "ladder %s starting, pid %s: %s %s every %g "
        "from %g, next level %g",
        ladder_id,
        os.getpid(),
        saved["Stock"],
        saved["Direction"],
        saved["Step"],
        saved["From"],
        ladder.next_level(saved),
    )

    def done():
        if ladder.next_level(saved) <= 0:
            return "no levels left, ladder ends"
        return None

    process.run_loop(
        ladder.TASK,
        ladder_id,
        lambda: _check(saved),
        ladder.INTERVAL,
        done,
        log,
    )


def _check(saved):
    """one check of the price; return (state, price)"""
    try:
        prices = get_latest_prices()
    except (
        requests.RequestException,
        KeyError,
        ValueError,
    ) as e:
        log.warning("price request failed: %s", e)
        return "no price", None
    price = prices.get(saved["Stock"])
    if price is None:
        log.warning("no price for %s", saved["Stock"])
        return "no price", None
    log.debug("%s %s", saved["Stock"], price)

    level = ladder.passed_level(saved, price)
    if level is None:
        return "waiting", price
    following = ladder.next_level(dict(saved, Last=level))
    upcoming = (
        f"next {following:g}"
        if following > 0
        else "the last level"
    )
    text = (
        f"{saved['Stock']} {saved['Direction']} to "
        f"{price:.2f}, passed {level:g} "
        f"(ladder {saved['Id']}, {upcoming})"
    )
    try:
        notify(text)
    except Exception as e:
        # the level isn't saved, so it is sent again at
        # the next check
        log.warning("could not send %r: %s", text, e)
        return "no notify", price
    ladder.set_last(saved["Id"], level)
    saved["Last"] = level
    log.info("sent: %s", text)
    return "waiting", price


if __name__ == "__main__" and len(sys.argv) == 2:
    run(int(sys.argv[1]))
