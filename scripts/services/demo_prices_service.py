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
import signal
import sys
import time
from datetime import datetime

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
    signal.signal(signal.SIGTERM, _stop_on_signal)
    signal.signal(signal.SIGINT, signal.default_int_handler)
    process.setup_logging(demo_prices.log_path())
    if not config.demo():
        # its prices would be taken for real ones
        log.error("not in the demo (NX_DEMO=1), ends")
        sys.exit(1)
    pid = os.getpid()
    started = datetime.now().isoformat(timespec="seconds")
    log.info("demo prices starting, pid %s", pid)
    demo_prices.save_status(pid, started, "starting")
    try:
        while True:
            if not demo_prices.needed():
                log.info(
                    "no demo shell or task left, "
                    "demo prices end"
                )
                demo_prices.save_status(
                    pid, started, "done"
                )
                break
            demo_prices.move()
            demo_prices.save_status(pid, started, "moving")
            time.sleep(config.demo_number("interval"))
    except KeyboardInterrupt:
        demo_prices.save_status(pid, started, "stopped")
        log.info("demo prices stopped")
    except Exception:
        log.critical("demo prices crashed", exc_info=True)
        demo_prices.save_status(pid, started, "crashed")
        sys.exit(1)
    finally:
        process.release_if_idle()


def _stop_on_signal(signum, frame):
    # handled like Ctrl+C: the heartbeat says 'stopped'
    raise KeyboardInterrupt


if __name__ == "__main__" and sys.argv[1:] == ["run"]:
    run()
