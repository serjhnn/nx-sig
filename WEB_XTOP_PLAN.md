# Web xtop plan

The plan for an xtop page in the web server (`run
web`): the live gain/loss of the held stocks in the
browser, updated by itself. Not started yet; each
step is done, checked and confirmed on its own (see
`CLAUDE.md` "Plan first").

## What is there now

- The web server (`engines/web.py`,
  `services/web_service.py`) serves only `/` (the
  logo page) and `/logo.svg`, on `127.0.0.1:8080`
  by default (config `web` `host`, `port`).
- `xtop` in the shell polls the prices every 5
  seconds (`prices.start_polling`) and redraws its
  table.
- The xtop math is in the shell: `_xtop_rows()` in
  `shell/overview_cmd.py` and `held_positions()` in
  `shell/ui.py`. The web service shouldn't import
  shell code, the logic belongs in `engines/`.
- `prices.get_latest_prices()` loads the `.env`
  keys itself and gives the made-up prices in the
  demo.

## How the values update

- The web server fetches the prices itself, every
  `interval` seconds like `xtop`, and keeps the last
  result in memory.
- The page asks for it (`/api/xtop`, JSON) every
  few seconds and changes only the numbers: no
  page reload, no flicker.
- The server fetches only while a page asked in the
  last ~30 seconds: no API calls when no xtop page
  is open, and one call per interval however many
  tabs are open.

Why polling and not Server-Sent Events (SSE): it
fits `http.server` (SSE keeps a thread and a
connection per open page), and it survives a phone
going to sleep, the next request just works again.

## Who may see it

The page shows the positions and gains, private data
unlike the logo. Proposed: `/xtop` and `/api/xtop`
only when the server listens on `127.0.0.1`; with
any other host (e.g. `0.0.0.0`) they return 403
until a login exists, the logo page still works.

The other way: a login now, e.g. a `WEB_TOKEN` in
`.env` the page asks for once (one more step).

To decide before step 1.

## Steps

1. **The position math in an engine**:
   `engines/positions.py` with `held()` and
   `rows(prices)` plus the total, moved from
   `shell/overview_cmd.py` and `shell/ui.py`.
   `xtop`, `status` and `ls stocks` use it, their
   output doesn't change (the existing tests must
   pass as they are).
2. **The price cache in the web service**: a thread
   with `prices.get_latest_prices()`, running only
   while the page is watched. A missing key or a
   network error is kept and shown on the page. New
   config `web` `interval` (default `5`, at least
   `1`).
3. **`/api/xtop`**: JSON with each stock (quantity,
   average, price, gain, gain %), the total, the
   update time and the error. The positions are
   read on every request, like `xtop`, so a trade
   the mail broker records shows up.
4. **The `/xtop` page**: a dark table like `xtop`,
   green and red for gain and loss, monospace, fits
   a phone, "updated 14:30:05" below it. On an
   error it keeps the last values and shows the
   error. It pauses while the tab is hidden, to
   save battery. The logo page links to it.
5. **Tests**: the engine rows, the JSON with faked
   prices, no polling while nobody watches, the
   127.0.0.1 guard (or the login).
6. **Docs**: README (the web server section, config
   `interval`), `TODO.md`, the generated files.

## Later

- The gain alerts below the table, like `xtop al`.
- A login, if the page should be opened from
  another device.
