# Web plan

The plan for the web version of nX-sig (`run web`).
It starts with the main page, the web `status`: the
positions with their live gain/loss, the background
tasks and the last trades. The other pages (trades,
ladders, alerts, chart, ...) follow later and use the
same style. Each step is done, checked and confirmed
on its own (see `CLAUDE.md` "Plan first").

This replaces the xtop page plan: the main page is
the live view, there is no separate `/xtop`.

The main page is done (steps 1 to 8, the paths as
they were then: `assets/web/` is now `web/`, and
the price cache and `/api/status` moved from
`web_service.py` into `scripts/web/`). The trades
page, the ladders page and the alerts page are
done too (see their sections); what comes next is
under "Later".

## The style (style C)

`web/style.css`, served as `/style.css`, is shared
by every page:

- the teal accent of the module map, a dark and a
  light theme; the system's by default, a button in
  the top bar overrides it (kept in the browser)
- monospace (IBM Plex Mono) for anything that lines
  up: tickers, numbers, dates, tables; sans-serif
  (IBM Plex Sans) for labels, menus and sentences
- green gain/buy, red loss/sell, gold price, the
  same meaning as in the shell; a sign, a chip or a
  dot still tells the state without color
- phone first: bottom tabs on a narrow screen, a
  side menu from 720px wide
- nothing from the internet: the fonts are in
  `web/fonts/` (SIL Open Font License), no
  CDN, no build step; plain HTML, CSS and a little
  JS

## Where the code is

- `web/`: the browser files, `index.html` (one
  HTML file per page), `style.css`, `js/` (one
  script per page) and `fonts/`.
- `engines/web.py` starts and stops the server,
  `services/web_service.py` is its process: it
  answers on `127.0.0.1:8080` by default (config
  `web` `host`, `port`) with the parts in
  `scripts/web/`.
- `scripts/web/files.py` sends the files of `web/`
  and the logo, `api.py` the JSON (`/api/...`),
  `price_cache.py` keeps the prices. Like the shell
  they only call engines.
- `engines/positions.py` works out the held stocks
  and their gain for `status`, `xtop` and `ls
  stocks`; the web uses it too (the web service
  doesn't import shell code).
- `prices.get_latest_prices()` loads the `.env`
  keys itself and gives the made-up prices in the
  demo.

## How the values update

- The web server fetches the prices itself, every
  `interval` seconds like `xtop`, and keeps the last
  result in memory.
- The page asks for it (`/api/status`, JSON) every
  few seconds and changes only the numbers: no page
  reload, no flicker.
- The server fetches only while a page asked in the
  last ~30 seconds: no API calls when no page is
  open, and one call per interval however many tabs
  are open.

Why polling and not Server-Sent Events (SSE): it
fits `http.server` (SSE keeps a thread and a
connection per open page), and it survives a phone
going to sleep, the next request just works again.

## Who may see it

The main page shows the positions and gains,
private data unlike the logo. Decided: localhost
only for now. `/api/status` is served only when the
server listens on `127.0.0.1`; with any other host
(e.g. `0.0.0.0`) it returns 403 and the page says
so.

A login (e.g. a `WEB_TOKEN` in `.env` the page asks
for once) comes later, when the page should be
opened from another device.

## Steps

1. ~~**The shared style**~~ (done):
   `assets/web/style.css` with the tokens, fonts,
   the app frame, panels, tables, chips, buttons and
   form fields; the IBM Plex fonts in
   `assets/web/fonts/`. Served as `/style.css` and
   `/fonts/<file>.woff2` (only the files in that
   folder); the logo page uses it.
2. ~~**The positions in an engine**~~ (done):
   `engines/positions.py` with `held()`,
   `rows(prices)` and `total(rows)`, moved from
   `shell/ui.py` and `shell/overview_cmd.py`.
   `xtop`, `status` and `ls stocks` use it, the
   shell tests pass as they were. `status` now
   works out the gain like `xtop` (count * (price
   - avg)), so the two can't differ by a cent.
3. ~~**The status in an engine**~~ (done):
   `engines/overview.py`, `status(prices)` with the
   positions and their total, the running tasks, the
   mail broker's state, the device that runs the
   background tasks and the last trades;
   `tasks()` and `last_trades()`. The task rows of
   'ls tasks' moved from the shell into their
   engines (`ladder.tasks()`, `alerts.task()`,
   `mail_broker.task()`, `web.task()`), and the mail
   broker's line in 'status' into
   `mail_broker.summary()`. The shell prints the
   same as before.
4. ~~**The price cache in the web service**~~
   (done): `PriceCache` in `web_service.py`
   (`server.prices`), a thread with
   `prices.get_latest_prices()` running only while
   a page asked in the last 30 seconds. A missing
   key or a network error is kept (with the last
   prices) for the page and logged once. New config
   `web` `interval` (`config.web_interval()`,
   default `5`, at least `1`).
5. ~~**`/api/status`**~~ (done): `api_status()` in
   `web_service.py`, JSON with each stock (count,
   average, cost, price, gain, gain %), the total,
   the tasks, the mail broker, the device that runs
   the tasks, the last trades, the prices' update
   time and error, the interval. Read on every
   request, so a trade the mail broker records shows
   up. 403 when the server doesn't listen on
   `127.0.0.1` (or `::1`), 500 with a short error
   (the details in the log) if the data can't be
   read. Only the failures are logged.
6. ~~**The main page `/`**~~ (done,
   `assets/web/index.html` and `main.js`): the top
   bar (the name in the logo colors, a demo chip,
   the live dot and update time, the theme button),
   the total gain/loss, the positions table, the
   background tasks and the last trades; the menu
   with Home, and Trades, Ladders, Alerts, Chart
   (on a wide screen also Basetrades, Rules) greyed
   out until they exist. It asks every `interval`
   seconds, flashes the numbers that changed,
   pauses while the tab is hidden, keeps the last
   values on an error and says what went wrong (no
   prices, a missing key, 403, the server stopped).
   Checked in a browser at 360px, 390px and 1200px,
   dark and light. The logo page moved to `/logo`.
7. ~~**Tests**~~ (done): the engines
   (`test_positions.py`, `test_overview.py`, the
   task rows in `test_ladder.py`, `test_alerts.py`,
   `test_mail_broker.py`, `test_web.py`), the JSON
   with faked prices (also in the demo), the price
   cache with a fake clock (no fetching while nobody
   watches), the 127.0.0.1 guard, the pages and
   files served, every element id `main.js` looks up
   is in `index.html`, every field it reads is in
   the JSON. The page itself was checked in a
   browser (not in CI).
8. ~~**Docs**~~ (done): README (the web server
   section, config `interval`, the layout, the
   tests), `TODO.md`, `COMMANDS.md` and the module
   map.

## The trades page

`/trades`: the stocks that have trades and the
trades of one, like `ls trades`, and adding and
deleting a trade, like `add trade` and `rm trade`.

Read-only option: a new config `web` `read_only`
(default `true`). While it is on the page only
shows the trades (no forms) and the server turns
every change away with 403; set it to `false` to
add and delete trades on the web.

Changes are protected: the server listens on
`127.0.0.1`, so another website open in the same
browser could send it a request. A change must be
a POST with a JSON body, its `Origin` must be the
server's own address, and it must carry a token
the server makes when it starts and gives only to
its own pages.

0. **The web folder** (done): `assets/web/` moved
   to `web/` (`main.js` to `web/js/`, served as
   `/js/main.js`), the price cache and
   `/api/status` from `web_service.py` into
   `scripts/web/` (`files.py`, `api.py`,
   `price_cache.py`). No visible change.
1. ~~**Shared page parts**~~ (done): the helpers
   every page needs (numbers, times, theme button,
   notice, the prices in the top bar, polling) moved
   from `main.js` into `web/js/app.js` (`nx.poll(url,
   draw)` and the rest in `window.nx`); the top bar
   and the menu into `web/frame.html`, which
   `files.py` puts into each page at its `<!-- frame
   -->` line, and `app.js` marks the open page in
   the menu. The main page looks the same (compared
   pixel by pixel). The Trades link goes live with
   its page in step 4.
2. ~~**Trades in an engine**~~ (done): the engine
   already had most of it (`summary()`, `get_all()`,
   `total()`); new is `trades.by_stock()`, each
   stock that has trades with how many, the last
   one, the count held and the average, each file
   read once. `ls trades` uses it and prints the
   same (compared with and without color).
3. ~~**`/api/trades`**~~ (done): `/api/trades`,
   the stocks of `trades.by_stock()` with their
   price, gain and gain % (`positions.row()`, the
   main page's math), and `/api/trades/<stock>`,
   one stock (any case) and its trades, oldest
   first; 404 for a stock not in the config. Every
   answer has the prices' time and error, the
   interval, demo and `read_only` (config `web`
   `read_only`, default `true`, already read here;
   it is enforced in step 5). Only on `127.0.0.1`,
   only failures logged.
4. ~~**The page `/trades`**~~ (done):
   `web/trades.html` and `web/js/trades.js`. The
   stocks as chips (held at average, gain %; the
   chosen one marked), the chosen stock's gain and
   its trades newest first (id, date and time,
   buy/sell, count, price; on a wide screen also
   the value). The chosen stock is in the address
   (`/trades#SOXL`), else the first one held. The
   chips update every interval (`/api/trades`); a
   stock's trades are asked again
   (`/api/trades/<stock>`) only when its number of
   trades or its last one changed. The Trades link
   in the menu works. Checked in a browser at 360,
   390 and 1200px, dark and light: nothing wider
   than the screen, no errors.
5. ~~**Config `read_only` and the protection**~~
   (done): `api.change()` for a POST to a path of
   `api.CHANGES` (none yet; step 6 adds them). It
   checks, in order: the server listens on
   `127.0.0.1`, the `Host` names it (also for every
   GET of `/api/`, against DNS rebinding), the
   `Origin` is the server's own, `read_only` is off,
   the token (`server.token`, new at each start, in
   the pages' top bar as `data-token`) matches,
   `Content-Type` is JSON, the body a JSON object of
   at most 10 KB; else 403, 415, 400 or 413. No
   OPTIONS answer, so the browser itself stops a
   cross-site request with the token header.
   `nx.send(url, data)` in `app.js` sends a change.
   Checked in a browser: the page's own change
   works, another site's is stopped.
6. ~~**Add and delete**~~ (done):
   `POST /api/trades/add` (stock, buy or sell,
   count, price, a date and time or none) calls
   `trades.add()`; `POST /api/trades/delete` (stock,
   id) `trades.delete()`; the shell's checks and
   texts, every change logged. On the page "Add
   trade" opens a form (the stocks of the config,
   a buy/sell switch, date and time inputs), the
   bin of a trade row deletes it after asking; the
   result shows for a few seconds, the page asks
   anew right away. Hidden while `read_only` is on,
   the header then says "read-only". The bank
   statement import stays in the shell. Checked in
   a browser: adding (also for a stock without
   trades, at a date), the server's errors in the
   form, deleting, the read-only view.
7. ~~**Tests**~~ (done, with each step):
   `trades.by_stock()` (`test_trades.py`), the
   config `read_only`, `/api/trades` and
   `/api/trades/<stock>`, every check of a change
   (other host names, origins, a missing or wrong
   token, a form post, bad JSON, too big, the
   read-only option), adding and deleting with the
   shell's errors, the pages served with their
   frame and token, every element id the scripts
   look up is in the page, every field they read
   in the JSON (`test_web.py`). The pages checked
   in a browser at 360, 390 and 1200px, dark and
   light, read-only and not: nothing wider than
   the screen, no errors (not in CI).
8. ~~**Docs**~~ (done, with each step): README
   (the layout with `web/` and `scripts/web/`, the
   config `read_only`, the trades page, the checks
   of a change, the tests), `CLAUDE.md` (where the
   web code is), `TODO.md` and the module map;
   `COMMANDS.md` didn't change (no new shell
   command).

## The ladders page

`/ladders`: the saved ladders like `ls ladders`,
with the price and how far it is from the next
level, and adding, running, stopping and deleting
them like `add`, `run`, `stop` and `rm ladder`.
The same `read_only` option and checks of a change
as the trades page.

Running a ladder from the page starts its process
from the web server (`ladder.start()`). When
another device runs the background tasks, the page
shows the engine's text; taking them over (`run
ladder <id> force`) stays in the shell.

1. ~~**Ladder rows in the engine**~~ (done):
   `ladder.rows()` and `ladder.row(saved)`, each
   saved ladder with its state (running, stopped,
   done, crashed), its pid and its next level
   (none when done), moved from `shell/
   ladder_cmd.py`. `ls ladders` and `rm ladder`
   print the same (compared in every state, with
   and without color).
2. ~~**`/api/ladders`**~~ (done): each saved
   ladder (id, stock, direction, step, from, last,
   created, state, next) with its stock's price,
   `away` (how far the price still has to move to
   the next level: price - next down, next - price
   up; 0 or less once passed while stopped) and
   `away_pct` (% of the price), and the next three
   levels (`ladder.levels()`, new: a down ladder's
   stop above 0, none when done); `names` for the
   add form. Only on `127.0.0.1`, with `read_only`.
3. ~~**The page `/ladders`, read-only**~~ (done):
   `web/ladders.html` and `web/js/ladders.js`, a
   card per ladder (stock, "down 1 from 35", the
   state as a chip, the next level and how far the
   price still has to move, "price past the level"
   for a stopped ladder that missed it, the last
   level sent, since when) and the rungs: the last
   level and the next three as ticks on a line,
   the price as a dot, at an end with an arrow when
   it is beyond them. A card is made once, only its
   texts change (they flash). One column on a
   phone, two from 720px. `put()` and
   `shortDate()` moved from `trades.js` into
   `app.js`. The Ladders link in the menu works.
   Checked in a browser at 360, 390 and 1200px,
   dark and light, with a ladder in every state: no
   label outside its card, no errors.
4. ~~**The changes**~~ (done): POST
   `/api/ladders/add` (stock, down or up, step,
   from, run; the notify channel must be set up,
   like the shell checks), `/run`, `/stop`,
   `/delete` (an id) behind the checks of a change,
   with `ladder.create()`, `start()` (never force),
   `stop()`, `remove()` and the shell's texts. A
   ladder saved but not started is still 200, with
   `start_error`; `run` gives 409 with the engine's
   text when it doesn't start (it runs already,
   another device runs the tasks), an unknown id
   404. Tested with faked processes, and once with
   a real ladder process started, stopped and
   deleted through the web.
5. ~~**The forms**~~ (done): "Add ladder" opens a
   form (stock, a down/up switch, step, from
   filled in with the stock's price until typed
   in, "run it now"; `/api/ladders` gives every
   stock's price for it); each card has Run (not
   when running or done), Stop (when running) and
   Delete (after asking, "stop and delete" for a
   running one). The buttons say "Starting…" while
   the server starts the process. Hidden while
   `read_only` is on, the header then says
   "read-only". The result of a change shows in its
   own box (`nx.tell()` in `app.js`, also used by
   the trades page now), so the next poll doesn't
   hide it. Checked in a browser with real ladder
   processes in the demo: add and run, stop, run,
   stop and delete, the server's errors in the
   form, the read-only view.
6. ~~**Tests**~~ (done, with each step):
   `ladder.rows()` and `ladder.levels()`
   (`test_ladder.py`); `/api/ladders` in every
   state (running, stopped, done, crashed, a level
   passed, no price, near 0); the four changes
   with faked processes (add, add and run, saved
   but not started, bad input, no notify channel,
   running twice, deleting a running one, unknown
   ids, read-only); the page's ids and the fields
   `ladders.js` reads (`test_web.py`); the demo's
   reset with five ladders (`test_demo.py`). Real
   ladder processes started, stopped and deleted
   through the page in the demo. The three pages
   checked in a browser at 360, 390 and 1200px,
   dark and light, read-only and not: nothing
   wider than the screen, no label or button
   outside its card, no errors (not in CI).
7. ~~**Docs**~~ (done, with each step): README (the
   ladders page and its changes, `/api/ladders`,
   the demo's web settings and sample data, the
   tests), `TODO.md` and the module map;
   `COMMANDS.md` didn't change.

## The alerts page

`/alerts`: the saved alerts like `ls alerts`, each
with its level per stock (`ls basetrades al`, `xtop
al`): the price, how far it is and whether it was
reached; adding and deleting alerts, running and
stopping their process, like `add alert`, `rm
alert`, `run alerts` and `stop alerts`. The same
`read_only` option and checks of a change as the
other pages; taking the background tasks over from
another device (`run alerts force`) stays in the
shell.

One process checks every alert: run and stop are
for the page, not for one alert. Adding an alert
starts it, deleting the last one stops it, as in
the shell.

1. ~~**The process state in the engine**~~ (done):
   `alerts.process_state()`, whether the process
   runs (with its last check), runs on another
   device (which one) or not, moved from
   `shell/alert_cmd.py`. `ls alerts` prints the
   same (compared in every state, with and without
   color).
2. ~~**`/api/alerts`**~~ (done): the process state
   (`process_state()`, its last check as ISO), each
   alert (id, kind, the shell's text, direction,
   percent or amount, the stock of a gain alert,
   created) with its levels per stock
   (`basetrade_levels()` per basetrade,
   `gain_levels()` per held stock; none for a gain
   alert of a stock not held): the level, the
   price, `away_pct` (how far the price still has
   to move, in % of it; 0 or less once reached)
   and `reached` (the engine's `past()`); the stock
   names for the form. Only on `127.0.0.1`, with
   `read_only`.
3. ~~**The page `/alerts`, read-only**~~ (done):
   `web/alerts.html` and `web/js/alerts.js`. A bar
   with the process (a dot and chip: running with
   its last check, elsewhere with the other device,
   stopped); a card per alert with its text ("down
   10%", "TSMX +100"), its kind and a table of its
   stocks (level, price, how far in %, or a
   "reached" chip, green for up, red for down);
   "no basetrades yet" or "TSMX isn't held" when it
   has no level. One column on a phone, two from
   720px; a short card keeps its rows at the top
   (the ladder cards too now). The Alerts link in
   the menu works. Checked in a browser at 360, 390
   and 1200px, dark and light, the process running
   and stopped: nothing wider than the screen, no
   errors.
4. ~~**The changes**~~ (done): POST
   `/api/alerts/add` (`{"kind": "basetrades",
   "direction", "percent"}` or `{"kind": "gain",
   "stock"` (a name or all), `"value"` (negative
   for a loss), `"in_percent"}`; the notify channel
   must be set up), `/delete` (an id), `/run`,
   `/stop` behind the checks of a change, with
   `alerts.create()`, `create_gain()`, `remove()`,
   `start()` (never force), `stop()` and the
   shell's texts. Adding starts the process if it
   doesn't run (still 200 with `start_error` when
   it doesn't start), deleting the last alert stops
   it; `run` gives 409 with the engine's text (no
   alerts, it runs already, another device). Tested
   with a faked process, and once with the real
   alerts process in the demo.
5. ~~**The forms**~~ (done): "Add alert" opens a
   form with a basetrades/gain switch: basetrades
   has down or up and a percent; gain has the stock
   (or all), gain or loss (sent as a negative
   value), an amount and whether it is money or %
   of the average buy price. The process bar has
   Run (not without an alert) or Stop; each card
   has Delete after asking ("it is the last one:
   the alerts process stops" when it is). The
   results show with `nx.tell()`. Hidden while
   `read_only` is on, the header then says
   "read-only". Checked in a browser with the real
   alerts process in the demo: run, add both kinds,
   the server's error in the form, delete, stop;
   and the read-only view.
6. ~~**Tests**~~ (done, with each step):
   `alerts.process_state()` (`test_alerts.py`);
   `/api/alerts` with both kinds, reached levels,
   a stock not held, no price, the process running;
   the four changes with a faked process (both
   kinds, adding while it runs, saved but not
   started, bad input, no notify channel, run and
   stop in every state, deleting the last one,
   read-only); the page's ids and the fields
   `alerts.js` reads (`test_web.py`). The real
   alerts process run, stopped and its alerts added
   and deleted through the page in the demo. The
   four pages checked in a browser at 360, 390 and
   1200px, dark and light, read-only and not:
   nothing wider than the screen, nothing outside
   its card, no errors (not in CI).
7. ~~**Docs**~~ (done, with each step): README (the
   alerts page and its changes, `/api/alerts`, the
   tests), `TODO.md` and the module map;
   `COMMANDS.md` didn't change.

## Later

- The other pages: chart, basetrades, rules; with
  `web/frame.html`, `app.js` (`nx.poll`,
  `nx.send`, `nx.tell`) and the forms and cards of
  the trades, ladders and alerts pages.
- On the trades page: the bank statement import
  (`add trade from <file>`, an upload).
- The gain alerts on the main page, like `xtop al`
  (`/api/alerts` has them now).
- A login, if the page should be opened from
  another device.
