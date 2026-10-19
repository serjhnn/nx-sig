# alert service: the alerts process, checks the prices
# every INTERVAL seconds and notifies each crossing of
# the alerts (engines/alerts.py starts and stops it)
#
#   python scripts/services/alert_service.py run
#       ('run alerts' in the shell starts it)
#
# logs: {storage_dir}/logs/alerts.log

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
from engines import alerts, basetrades
from notifier import notify
from trade_engine import get_latest_prices

log = logging.getLogger("alerts")


def run():
    """check the prices every INTERVAL seconds and
    notify each crossing, until SIGTERM or Ctrl+C"""
    signal.signal(signal.SIGTERM, _stop_on_signal)
    signal.signal(signal.SIGINT, signal.default_int_handler)
    process.setup_logging(alerts.log_path())
    pid = os.getpid()
    started = datetime.now().isoformat(timespec="seconds")
    log.info("alerts starting, pid %s", pid)
    alerts.save_status(pid, started, "starting")
    try:
        while True:
            if tasks_owner.lost():
                log.warning(
                    "%s took over the background "
                    "tasks, alerts stop",
                    tasks_owner.describe(
                        tasks_owner.owner()
                    ),
                )
                alerts.save_status(
                    pid, started, "taken over"
                )
                break
            saved = alerts.alerts_get_all()
            if not saved:
                log.info("no alerts left, alerts end")
                alerts.save_status(pid, started, "done")
                break
            state, past_now = _check(saved)
            alerts.save_status(
                pid, started, state, past_now
            )
            time.sleep(alerts.INTERVAL)
    except KeyboardInterrupt:
        alerts.save_status(pid, started, "stopped")
        log.info("alerts stopped")
    except Exception:
        log.critical("alerts crashed", exc_info=True)
        alerts.save_status(pid, started, "crashed")
        sys.exit(1)
    finally:
        process.release_if_idle(alerts_ending=True)


def _check(saved):
    """one check of the prices; return (state, the
    stocks past each alert)"""
    past_now = (alerts.status() or {}).get("past") or {}
    try:
        prices = get_latest_prices()
    except (
        requests.RequestException,
        KeyError,
        ValueError,
    ) as e:
        log.warning("price request failed: %s", e)
        return "no price", past_now
    past_now, messages = alerts.check(
        saved,
        basetrades.get_all(),
        alerts.positions_get(),
        prices,
        past_now,
    )
    state = "waiting"
    for alert_id, name, key, text in messages:
        try:
            notify(text)
        except Exception as e:
            # not saved as past, so it is sent again at
            # the next check
            log.warning("could not send %r: %s", text, e)
            state = "no notify"
            continue
        past_now[str(alert_id)][name] = key
        log.info("sent: %s", text)
    return state, past_now


def _stop_on_signal(signum, frame):
    # handled like Ctrl+C: the heartbeat says 'stopped'
    raise KeyboardInterrupt


if __name__ == "__main__" and sys.argv[1:] == ["run"]:
    run()
