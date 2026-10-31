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
from engines import alerts, basetrades
from notifiers.notifier import notify
from engines.prices import get_latest_prices

log = logging.getLogger("alerts")


def run():
    """check the prices every INTERVAL seconds and
    notify each crossing, until SIGTERM or Ctrl+C"""
    process.service_setup(alerts.TASK)
    log.info("alerts starting, pid %s", os.getpid())

    def done():
        if not alerts.alerts_get_all():
            return "no alerts left, alerts end"
        return None

    process.run_loop(
        alerts.TASK,
        None,
        lambda: _check(alerts.alerts_get_all()),
        alerts.INTERVAL,
        done,
        log,
    )


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


if __name__ == "__main__" and sys.argv[1:] == ["run"]:
    run()
