# To do

## Split the shell from the background services

Keep the parts you interact with apart from the parts
that run in the background, and show it in the names:

- **`nx` prefix: the shell and user interaction**
  - `nxshell` (the shell, `scripts/commands.py`)
  - the notifiers (`ntfy_notify.py`, `telegram_notify.py`,
    the planned Garmin watch notifications)
- **`mtsig`: mail trades service**
  - ~~rename `watcher` to `mtsig`~~ (done)
  - ~~the service code: `order_watcher.py`,
    `mail_reader.py`, `order_parser.py`~~ (done, in
    `scripts/mtsig/`)

~~When doing it, also update the names that still point
to the watcher: the `mail watcher:` line of `status`
and the docs.~~ (done, it is "mail broker" now)

## Next: protect what is built

In this order, before metrics and strategy add more:

1. ~~**CI**: a GitHub Actions workflow that runs every
   test (`storage.py`, `order_parser.py`, `ladder.py`,
   `shell_test.py`, `sync.py`) and `check_style.py` on
   each push, so a change from the phone that breaks
   something shows up right away.~~ (done,
   `.github/workflows/tests.yml`, Python 3.12 and 3.14)
2. ~~**Totals check**: `trades_total.csv` is a cache of
   the trade files. Add a check that rebuilds each
   stock's total from its trades and reports (or
   fixes) a difference.~~ (done differently: the
   cache is gone, `trades.total` computes the
   total from the trades)
3. **Tests for the mail watcher**: `order_watcher.py`
   and `mail_reader.py` need Python 3.14 and have no
   tests yet. Run them in CI with 3.14 and test
   `handle_email` with fake emails (recorded, skipped,
   not a FILLED order, unknown stock, failed write).
4. ~~**One device runs the background tasks**: the mail
   watcher or a ladder on both the phone and the PC
   records orders or sends alerts twice.~~ (done,
   `tasks_owner.py`: a synced owner file, `force` to
   take over)
5. **Start the ladders after a phone restart** that
   were running before (Termux:Boot), see Background
   tasks below.
6. Small cleanups:
   - ~~the shared helpers in `shell/ui.py` still have a
     leading `_` though several modules use them~~
     (done)
   - ~~`status` still says `order_watcher.py`, see the
     mtsig split above~~ (done: "mail broker" in
     everything the user sees)
7. **One engine per kind of data**: a `*_cmd.py` file
   only reads the command, calls one engine function
   and prints the result; only engines import
   `storage` (and only `engines/prices.py` requests
   the prices), and `storage.py` stays
   the only file that reads and writes the data files.
   So a bot, a web page or the setup wizard can use the
   same functions, and the shell tests fake one
   function per command. `chart` is done
   (`chart.stock_chart`); `test_cmd_files_use_engines`
   in `tests/test_shell.py` checks the files that are done,
   add each file to its list. One step per file, the
   shell tests proving the output stays the same:
   - ~~`trade_cmd.py`: a `trades.py` engine (add, delete,
     list, total); the totals math (`_total_apply`)
     moves there from `storage.py`~~ (done,
     `scripts/engines/trades.py`)
   - ~~`rule_cmd.py`: a `rules.py` engine (thin: list,
     add, delete)~~ (done, `scripts/engines/rules.py`)
   - ~~`base_trade_cmd.py`: a `basetrades.py` engine
     (thin)~~ (done, `scripts/engines/basetrades.py`)
   - ~~`ladder_cmd.py`: its reads (`ladder_get`,
     `ladders_get_all`, `ladder_status_get`) through
     `ladder.py`~~ (done, `scripts/engines/ladder.py`)
   - ~~`mail_cmd.py`: `mtsig_pid_get` and
     `watcher_status_get` through a small mail broker
     function~~ (done, `scripts/engines/mail_broker.py`)
   - `overview_cmd.py`: `config` through the engines
     (the gain alert settings); ~~`start_polling`~~
     (done, `scripts/engines/prices.py`)
   - ~~`ui.py`: `fetch_prices` calls a `trade_engine`
     function through an engine, not directly~~ (done,
     `scripts/engines/prices.py`; `held_positions`
     uses `trades.total`)
   - last: the test checks every `*_cmd.py` and
     `ui.py`

## Privacy

The data lives only on your devices; a few services
see some of it. Say so, and let alerts say less:

1. **A Privacy section in the README** that lists
   what leaves the device and to whom:
   - Alpaca: the symbols you ask prices for, with your
     API key (not your positions)
   - Gmail: the broker emails, read over IMAP
   - Telegram: the alerts, with stock, gain and
     amounts. They are encrypted on the way (HTTPS to
     the Bot API, Telegram's encryption to the app),
     but not end-to-end: a bot chat is a cloud chat on
     Telegram's servers, Telegram holds the keys and
     can read it, and secret chats don't work with
     bots (already in the README, under .env)
   - ntfy.sh, if used: the same as Telegram
   - Syncthing: nothing, it syncs directly between
     your devices (discovery and relays are off)
2. **Alerts that say less**, as an option: e.g. a
   config switch for 'SOXL alert, see nX-sig' without
   the amounts, and a self-hosted ntfy as an
   alternative to Telegram.
3. **Local notifications, one notifier per device**:
   the ladders, xtop and the mail watcher send every
   alert through one small notifier that picks what
   the device has, so alerts need no network by
   default:
   - phone: `termux-notification` of the Termux:API
     app (title, text, `--id` per ladder so a new alert
     replaces the old one, sound, vibration, maybe a
     'stop' button); as options `termux-vibrate`
     (a pattern), `termux-tts-speak` (read aloud) or
     `termux-media-player` (a sound). Needs the
     Termux:API app from the same source as Termux and
     `pkg install termux-api`.
   - PC: `notify-send` (desktop notification), as
     options `spd-say` / `espeak` or `paplay`.
   - without any of them: the terminal bell.
   - Telegram (or ntfy) only as an extra, for alerts
     that must reach you away from the device that
     runs the task.

   A config setting chooses the channels, e.g.
   `"notify": ["local", "telegram"]`.
4. **An alert log in the shell**: every alert is also
   written to a local file (e.g. `alerts.json`), the
   shell shows 'N new alerts' before the prompt, and
   `ls alerts` lists them. It works the same on the
   phone and the PC and keeps alerts that were missed
   or swiped away.

## ~~Demo: try nX-sig without keys~~ (done)

`./nxdemo` runs the shell with sample data and random
walk prices, so a new user can learn the features
without Alpaca keys, a mail account or a notify
channel. In this order:

1. ~~**Switch and data**: `./nxdemo` sets `NX_DEMO=1`,
   `config.py` then reads `demo/config.json` (data in
   `demo_data/`), the first start copies the sample
   data of `demo/seed/` (`engines/demo.py`)~~ (done)
2. ~~**Price generator** `engines/demo_prices.py`: a
   random walk per stock from the starting prices in
   `demo/config.json`, saved in `demo_data/`, with a
   generated history for `chart`~~ (done)
3. ~~**Price service** `services/demo_prices_service.py`:
   moves the prices every few seconds, started and
   stopped by the demo shell~~ (done, it also runs on
   while a ladder or the alerts of the demo run)
4. ~~**`prices.py` in the demo** reads the generated
   prices, no keys, no network~~ (done)
5. ~~**Notify and blocked parts**: messages printed in
   the shell with `[DEMO]`; `mtsig`, `syncnx` and the
   mail commands refused; `DEMO` in the prompt and
   `status`~~ (done)
6. ~~**`demo` command**: `demo reset`, `demo set`,
   `demo move`, `demo speed`, `demo tour`~~ (done)
7. ~~**Tests and docs**: `tests/test_demo.py` without
   `.env`, a "Try the demo" README section~~ (done,
   with pictures; `test_demo.py` runs `./nxdemo` from
   a copy of the repo)

## Later: open it up for other people

Only if it should be useful to others too; build it
for your own use first. In this order:

1. **A license** (e.g. MIT or GPL, one LICENSE file):
   without one nobody else may legally use or change
   the code, even in a public repo.
2. **A note in the README** that nX-sig tracks and
   journals trades and is not financial advice, the
   more so once strategy signals exist.
3. **A setup wizard** (`./nxshell setup` or similar)
   that asks for the Alpaca keys, the mail account and
   app password, the Telegram bot and the stocks, and
   writes `.env` and `config.json`. Today the setup is
   the biggest hurdle for a new user.
4. **Broker parsers as plugins**: `order_parser.py`
   reads one broker's email format. A `parsers/` folder
   with one file per broker, found at start like the
   `*_cmd.py` modules of the shell, so others can add
   their broker.
5. **Metrics as the main feature**: statistics of how
   you trade (trades against your rules, how long you
   hold losing positions, sells against basetrades), a
   private, local trading journal, see Metrics below.

## Other

- ~~**Reorganise the shell commands** as
  `<action> <object>` (`ls ladders`, `add trade ...`)~~
  (done, all commands in [COMMANDS.md](COMMANDS.md)),
  see [CLI_BLUEPRINT.md](CLI_BLUEPRINT.md)
- Delete `./migrate_data` once every device has run
  it
- **Background tasks**: ~~`run`, `stop`, `ls tasks`,
  `ls ladders` for ladders and the mail broker~~ (done,
  `scripts/engines/ladder.py`). Still open:
  - maybe start the ladders that were running before
    when the phone restarts
  - **One `BackgroundTask` class** for every task
    (`process.py`), in steps:
    1. ~~the class, with tests~~ (done)
    2. ~~web and demo prices use it~~ (done)
    3. ~~alerts and ladders use it~~ (done)
    4. ~~a mail broker engine (`engines/`) that the
       shell uses instead of `./mtsig`~~ (done)
    5. ~~a registry, so `tasks_run()` doesn't name
       every task~~ (done, `process.tasks()`)
    6. ~~one shared loop for the polling services
       (`process.run_loop`)~~ (done)
    7. ~~remove `./mtsig`; add a one-shot mode
       (`./nxshell run mail-broker`) and
       `ls mail-broker` (state, last order, last
       error, last log lines)~~ (done; run
       `./migrate_data` once on each device to
       delete the old `mtsig.pid`)
- Metrics (`scripts/metrics.py`): statistics of your
  actions, once enough data is collected
- `strategy` commands
- Notifications to a Garmin watch: Garmin Connect
  mirrors Android notifications to the watch, so the
  local notifications (Privacy, item 3) may already be
  enough, without a watch app
  (see `scripts/notifiers/watch_notify.py`)
- **Status on a smart watch as 7 colored cubes**: one
  cube per stock (7 in all) that lights up in a color
  for its state: green for a gain, red for a loss, and
  more colors for in-between levels (e.g. strong or
  small gain or loss, flat), so the state of all
  positions can be read at a glance without opening a
  message. Idea: the watch side updates the status by
  requests to localhost, answered by a small Termux
  service (colors as JSON), if Android can redirect
  those requests to it. Open: the color scale, which
  watch, whether that redirect works (plain
  notifications can't show colors), and how the 7
  stocks are picked.
- Send a notification when the watcher records an order
- ~~**Import a bank statement**~~ (done: `add trade
  from <file>`, `scripts/engines/statement.py`).
  Still open:
  - maybe one "N already recorded" line instead of
    one line per trade when a statement is imported
    again
  - maybe complete file names after `from`
- ~~**Trade fee**~~ (done: config `fee`, 5 USD, is
  added to the cost of each buy in `trades.total`, so
  the average buy price includes it). Still open:
  - maybe the fees paid, with the sells' fees, if a
    realized profit is shown one day
  - maybe the fee of a statement's own fee rows
    instead of the fixed one
- ~~**Basetrade from the trades**~~ (done: `add
  basetrade <stock>|all` takes the lowest buy since
  the last sell, a partial sell too;
  `basetrades.from_trades`). The mail broker doesn't
  update basetrades.
- ~~**Table padding**~~ (done: `terminal padding
  <spaces>`, per device in `.terminal.json`; every
  table starts after it, less where it wouldn't
  fit). Still open: maybe pad the text below a
  table too (the `al` lines), wrapped to the
  narrower width
- ~~**Price chart in the terminal**~~ (done: `chart
  <stock> [period <n> <unit>]`, one `*` per price, the
  avg buy line and B / S trades). Still open: maybe a
  one-line sparkline (`▁▂▃▄▅▆▇█`) per stock in
  `ls stocks` or `status`
- ~~**Feed choice in xtop**~~ (done: `xtop [sec]
  [sip|iex] [al]` takes the prices from the
  `delayed_sip` or `iex` feed, as `ls basetrades`
  does)
- ~~**Web server with the logo**~~ (done: `run web`,
  `stop web`, a page with `assets/logo.svg` at
  config `web`, 127.0.0.1:8080 by default;
  `engines/web.py`, `services/web_service.py`).
  Still open:
  - **xtop page**: the live gain/loss in the
    browser, updated by itself; planned in
    [WEB_XTOP_PLAN.md](WEB_XTOP_PLAN.md), not
    started
  - maybe start it after a phone restart, with the
    ladders (Termux:Boot)
