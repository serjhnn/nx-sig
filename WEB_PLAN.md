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
page is next, see "The trades page".

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
1. **Shared page parts**: the helpers every page
   needs (numbers, theme button, notice, polling)
   from `main.js` into `web/js/app.js`. The menu
   link to Trades works. The main page as it is.
2. **Trades in an engine**: what `ls trades` shows
   (the stocks that have trades with their count
   and average; one stock's trades with id, date,
   buy/sell, count, price) as a function the shell
   and the web use; `ls trades` prints the same.
3. **`/api/trades`**: the stocks, or one stock's
   trades and its total, with the price and gain
   from the price cache; only on `127.0.0.1`, and
   `read_only` in it so the page knows.
4. **The page `/trades`**: the stock chips (count,
   average, gain), the chosen stock's trades,
   newest first; on a phone the chips scroll
   sideways and the table fits 360px.
5. **Config `read_only` and the protection**:
   `config.web_read_only()`; POST only for
   changes, JSON body, `Origin` check, the token;
   403 while `read_only` is on.
6. **Add and delete**: the add form (stock, buy or
   sell, count, price, optional date and time)
   calls `trades.add()`, so the checks and error
   texts are the shell's; delete asks first, like
   `rm trade`. Hidden while `read_only` is on. The
   bank statement import stays in the shell.
7. **Tests**: the engine function, `/api/trades`,
   the read-only option, the protection (another
   origin, no token, a form post are turned away),
   the page's ids and fields; the page checked in
   a browser at 360, 390 and 1200px, dark and
   light.
8. **Docs**: README (config `read_only`, the page),
   `TODO.md`, `COMMANDS.md`, the module map.

## Later

- The other pages: ladders, alerts, chart,
  basetrades, rules; with the forms of the style.
- The gain alerts on the main page, like `xtop al`.
- A login, if the page should be opened from
  another device.
