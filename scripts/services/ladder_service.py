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
import signal
import sys
import time
from datetime import datetime

import requests

# engines/, process.py and tasks_owner.py are in
# scripts/, one level up
sys.path.insert(
    1,
    os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))
    ),
)

import process
import tasks_owner
from engines import ladder
from notifier import notify
from engines.prices import get_latest_prices

log = logging.getLogger("ladder")


def run(ladder_id):
    """check the price every INTERVAL seconds and notify
    each level passed, until SIGTERM or Ctrl+C"""
    signal.signal(signal.SIGTERM, _stop_on_signal)
    signal.signal(signal.SIGINT, signal.default_int_handler)
    process.setup_logging(ladder.log_path(ladder_id))
    saved = ladder.get(ladder_id)
    if saved is None:
        log.error("no ladder %s in ladders.csv", ladder_id)
        sys.exit(1)
    pid = os.getpid()
    started = datetime.now().isoformat(timespec="seconds")
    log.info(
        "ladder %s starting, pid %s: %s %s every %g "
        "from %g, next level %g",
        ladder_id,
        pid,
        saved["Stock"],
        saved["Direction"],
        saved["Step"],
        saved["From"],
        ladder.next_level(saved),
    )
    ladder.save_status(ladder_id, pid, started, "starting")
    try:
        while True:
            if tasks_owner.lost():
                log.warning(
                    "%s took over the background "
                    "tasks, ladder %s stops",
                    tasks_owner.describe(
                        tasks_owner.owner()
                    ),
                    ladder_id,
                )
                ladder.save_status(
                    ladder_id, pid, started, "taken over"
                )
                break
            if ladder.next_level(saved) <= 0:
                log.info("no levels left, ladder ends")
                ladder.save_status(
                    ladder_id, pid, started, "done"
                )
                break
            state, price = _check(saved)
            ladder.save_status(
                ladder_id, pid, started, state, price
            )
            time.sleep(ladder.INTERVAL)
    except KeyboardInterrupt:
        ladder.save_status(
            ladder_id, pid, started, "stopped"
        )
        log.info("ladder %s stopped", ladder_id)
    except Exception:
        log.critical(
            "ladder %s crashed", ladder_id, exc_info=True
        )
        ladder.save_status(
            ladder_id, pid, started, "crashed"
        )
        sys.exit(1)
    finally:
        process.release_if_idle(ending_id=ladder_id)


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


def _stop_on_signal(signum, frame):
    # handled like Ctrl+C: the heartbeat says 'stopped'
    raise KeyboardInterrupt


if __name__ == "__main__" and len(sys.argv) == 2:
    run(int(sys.argv[1]))
