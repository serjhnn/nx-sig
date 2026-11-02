# price_cache: the prices of the web pages, fetched
# by a thread while a page watches
#
#   python tests/test_web.py   the tests
#
# the thread fetches them every config "web"
# "interval" seconds, but only while a page asked for
# them in the last WATCH_SECONDS, so no page open
# means no requests, and one request per interval
# however many pages are open.
#
# public classes:
#   PriceCache(interval)
#       get() the last prices, fetching() and stop()

import logging
import threading
import time
from datetime import datetime

from engines import prices

# the prices are fetched while a page asked for them
# this recently
WATCH_SECONDS = 30

log = logging.getLogger("web")


class PriceCache:
    """the last prices, fetched by a thread every
    interval seconds while get() was called in the last
    watch seconds; fetch() gives {stock name: price}"""

    def __init__(
        self,
        interval,
        fetch=prices.get_latest_prices,
        watch=WATCH_SECONDS,
        clock=time.monotonic,
    ):
        self.interval = interval
        self.watch = watch
        self._fetch = fetch
        self._clock = clock
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._asked = None
        self._prices = {}
        self._updated = None
        self._error = None

    def get(self):
        """{"prices", "updated", "error"}: the last
        prices and when they came (a datetime, None
        before the first), the error of the last fetch
        (the prices are then the ones before it);
        starts the fetching if it is idle"""
        with self._lock:
            self._asked = self._clock()
            if self._thread is None and (
                not self._stop.is_set()
            ):
                self._thread = threading.Thread(
                    target=self._run, daemon=True
                )
                self._thread.start()
            return {
                "prices": dict(self._prices),
                "updated": self._updated,
                "error": self._error,
            }

    def fetching(self):
        """True while its thread runs"""
        with self._lock:
            return self._thread is not None

    def stop(self):
        """end the thread, for good"""
        self._stop.set()

    def _run(self):
        while not self._stop.is_set():
            self._fetch_once()
            if self._stop.wait(self.interval):
                break
            with self._lock:
                idle = self._clock() - self._asked
                if idle >= self.watch:
                    # nobody watches: end here, the
                    # next get() starts a new thread
                    self._thread = None
                    return
        with self._lock:
            self._thread = None

    def _fetch_once(self):
        try:
            found = self._fetch()
        except KeyError as e:
            error = f"missing {e.args[0]} in .env"
        except Exception as e:  # network or API errors
            error = str(e) or type(e).__name__
        else:
            with self._lock:
                self._prices = dict(found)
                self._updated = datetime.now()
                self._error = None
            return
        with self._lock:
            new = error != self._error
            self._error = error
        if new:
            # once, not every interval
            log.warning("can't get the prices: %s", error)
