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

## The style (style C)

`assets/web/style.css`, served as `/style.css`, is
shared by every page:

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
  `assets/web/fonts/` (SIL Open Font License), no
  CDN, no build step; plain HTML, CSS and a little
  JS

## What is there

- The web server (`engines/web.py`,
  `services/web_service.py`) serves `/` (the logo
  page), `/logo.svg`, `/style.css` and `/fonts/`, on
  `127.0.0.1:8080` by default (config `web` `host`,
  `port`).
- `status` and `xtop` work out the positions in the
  shell: `held_positions()` in `shell/ui.py`,
  `_xtop_rows()` in `shell/overview_cmd.py`. The web
  service shouldn't import shell code, the logic
  belongs in `engines/`.
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
2. **The positions in an engine**:
   `engines/positions.py` with `held()` and
   `rows(prices)` plus the total, moved from
   `shell/ui.py` and `shell/overview_cmd.py`.
   `xtop`, `status` and `ls stocks` use it, their
   output doesn't change (the existing tests must
   pass as they are).
3. **The status in an engine**: one function with
   what `status` shows (the positions, the mail
   broker's and the web server's state, the running
   ladders and alerts) and the last trades, for the
   shell and the web.
4. **The price cache in the web service**: a thread
   with `prices.get_latest_prices()`, running only
   while a page is watched. A missing key or a
   network error is kept and shown on the page. New
   config `web` `interval` (default `5`, at least
   `1`).
5. **`/api/status`**: JSON with each stock
   (quantity, average, price, gain, gain %), the
   total, the tasks, the last trades, the update
   time and the error. Read on every request, so a
   trade the mail broker records shows up. 403 when
   not on `127.0.0.1`.
6. **The main page `/`**: the top bar (the name in
   the logo colors, the live dot and update time,
   the theme button), the total gain/loss, the
   positions table, the running tasks and the last
   trades; the menu with Home, and Trades, Ladders,
   Alerts, Chart greyed out until they exist. It
   updates every few seconds, pauses while the tab
   is hidden, keeps the last values on an error and
   shows it. The logo moves to `/logo`.
7. **Tests**: the engines, the JSON with faked
   prices, no polling while nobody watches, the
   127.0.0.1 guard, the page.
8. **Docs**: README (the web server section, config
   `interval`), `TODO.md`, the generated files.

## Later

- The other pages: trades, ladders, alerts, chart,
  basetrades, rules; with the forms of the style.
- The gain alerts on the main page, like `xtop al`.
- A login, if the page should be opened from
  another device.
