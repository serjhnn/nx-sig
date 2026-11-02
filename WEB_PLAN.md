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
page is done too (steps 0 to 8 of "The trades
page"). The ladders page is next, see "The ladders
page".

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
3. **The page `/ladders`, read-only**: a card per
   ladder (stock, "down 1 from 35", the last level
   sent, the next one, the price and its distance,
   the state as a chip) with a small picture of the
   rungs and the price between them; phone first,
   the Ladders link in the menu works.
4. **The changes**: POST `/api/ladders/add`,
   `/run`, `/stop`, `/delete` behind the checks of
   a change, with `ladder.create()`, `start()`,
   `stop()`, `remove()` and the shell's texts.
5. **The forms**: add (stock, down or up, step,
   from with the price filled in, run now); on
   each card run or stop, and delete after asking.
   Hidden while `read_only` is on.
6. **Tests**: the rows, the api, the changes
   (also another device running the tasks), the
   page's ids and fields; the processes faked as
   in `test_ladder.py`. The page checked in a
   browser at 360, 390 and 1200px, dark and light,
   read-only and not.
7. **Docs**: README, `TODO.md`, the module map.

## Later

- The other pages: ladders, alerts, chart,
  basetrades, rules; with `web/frame.html`,
  `app.js` (`nx.poll`, `nx.send`) and the forms of
  the trades page.
- On the trades page: the bank statement import
  (`add trade from <file>`, an upload).
- The gain alerts on the main page, like `xtop al`.
- A login, if the page should be opened from
  another device.
