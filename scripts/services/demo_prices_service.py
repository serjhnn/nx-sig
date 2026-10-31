# demo prices service: the demo's prices process, moves
# the prices every "interval" seconds (demo/config.json
# "demo") while the demo shell or a background task of
# the demo runs (engines/demo_prices.py starts it)
#
#   python scripts/services/demo_prices_service.py run
#       (./nxdemo starts it)
#
# logs: {storage_dir}/logs/demo_prices.log

import logging
import os
import sys

# engines/, config.py and process.py are in scripts/,
# one level up
sys.path.insert(
    1,
    os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))
    ),
)

import config
import process
from engines import demo_prices

log = logging.getLogger("demo_prices")


def run():
    """move the prices every "interval" seconds until
    nothing needs them, SIGTERM or Ctrl+C"""
    process.service_setup(demo_prices.TASK)
    if not config.demo():
        # its prices would be taken for real ones
        log.error("not in the demo (NX_DEMO=1), ends")
        sys.exit(1)
    log.info("demo prices starting, pid %s", os.getpid())

    def done():
        if not demo_prices.needed():
            return (
                "no demo shell or task left, "
                "demo prices end"
            )
        return None

    def move():
        demo_prices.move()
        return ("moving",)

    process.run_loop(
        demo_prices.TASK,
        None,
        move,
        lambda: config.demo_number("interval"),
        done,
        log,
    )


if __name__ == "__main__" and sys.argv[1:] == ["run"]:
    run()
