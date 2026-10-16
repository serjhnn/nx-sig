<p align="center">
  <img src="assets/logo.svg" alt="nX-sig" width="520">
</p>

[![tests](https://github.com/serjhnn/nx-sig/actions/workflows/tests.yml/badge.svg)](https://github.com/serjhnn/nx-sig/actions/workflows/tests.yml)

**nX-sig** is a small terminal tool for tracking stock positions. It records
your buy and sell trades, keeps the count and average buy price of every
stock, shows live prices and your gain or loss, and can record broker orders
automatically from the confirmation emails. It is made to run on a phone in
[Termux](https://termux.dev), so all output fits a 48-character screen.

## Features

- **Interactive shell** (`./nxshell`) to add, list and delete trades,
  see positions with live prices and gain/loss, and keep personal trading rules
- **Live prices** from the [Alpaca](https://alpaca.markets) market data API
- **Mail trades service** (`./mtsig`) that waits for broker emails over IMAP and
  records FILLED orders as trades, running in the background
- **Plain files** for storage: CSV for trades, JSON for rules and state,
  written atomically and locked, so the shell and the watcher can run together
- **Ladders**: background price-step alerts on Telegram, e.g. at 90, 80, 70, ...
  when a stock falls from 100
- **Notifications** through [ntfy](https://ntfy.sh) and Telegram

## Requirements

- Python **3.12+** for the shell, **3.14+** for the order watcher
  (it uses IMAP IDLE, added to `imaplib` in 3.14)
- Python packages: `requests`, `python-dotenv` (and `rich` for `latest_trade.py`)
- An Alpaca account for prices, and an email account with IMAP access
  (e.g. Gmail with an app password) for the order watcher

## Setup

```bash
git clone https://github.com/serjhnn/nx-sig.git
cd nx-sig
pip install -r requirements.txt
```

In Termux, install Python and git first: `pkg install python git`.

Create a `.env` file in the repo folder with your keys (it is in `.gitignore`):

```ini
# prices (Alpaca market data)
APCA_API_KEY_ID=your-key-id
APCA_API_SECRET_KEY=your-secret-key

# order watcher (IMAP)
IMAP_HOST=imap.gmail.com
IMAP_USERNAME=you@gmail.com
IMAP_APP_PASSWORD=your-16-char-app-password
IMAP_SENDER=address-your-broker-sends-orders-from@example.com
# optional
IMAP_MAILBOX=INBOX
LOG_LEVEL=INFO

# notifications (optional)
NTFY_TOPIC=your-ntfy-topic
TOKEN=telegram-bot-token
CHAT_ID=telegram-chat-id
```

For Gmail, turn on 2-Step Verification and create an app password at
<https://myaccount.google.com/apppasswords>.

**About Telegram and privacy.** The alerts are encrypted on the way: nX-sig
sends them to Telegram's Bot API over HTTPS, and Telegram delivers them to
your app over its own encrypted connection. But they are not end-to-end
encrypted: a chat with a bot is a normal cloud chat, kept on Telegram's
servers, and Telegram holds the keys, so Telegram can read the alerts (stock,
prices, gain). Telegram's end-to-end "secret chats" are not available for
bots. Keep `TOKEN` private too: anyone with it can send and read messages as
your bot.

`config.json` holds the rest of the settings:

| Key | Meaning |
|---|---|
| `indices` | the stocks you track; only these can be used in commands and are recorded by the watcher |
| `storage_dir` | where data files are kept, relative to the repo folder (default `./data/`) |
| `gain_alert` | `xtop` sends a Telegram message when a stock's gain reaches this amount (default `100`) |
| `gain_alert_pct` | ... or when its gain reaches this % (default `10`) |
| `ladder_interval` | how often a ladder checks the price, in seconds (default `30`) |
| `url`, `feed` | the Alpaca latest-trades endpoint and data feed |

## Running

### The shell

```bash
./nxshell
```

It starts from the repo folder by itself, so `~/nx-sig/nxshell` works from
anywhere. Set `NXSHELL_PYTHON` to use a specific Python.

Commands are `<action> <object> [arguments]`. The actions are `ls` (list or
show), `add` (save), `rm` (delete, after confirmation), `run` and `stop`
(background tasks). The object is plural after `ls` and singular everywhere
else: `ls ladders`, but `rm ladder 1`.

| Object | Actions | e.g. |
|---|---|---|
| `stocks` | `ls` | `ls stocks`: held stocks with growth % |
| `trade` | `ls`, `add`, `rm` | `add trade SOXL buy count 10 price 20.5` |
| `ladder` | `ls`, `add`, `rm`, `run`, `stop` | `add ladder SOXL down 10 from 100 run` |
| `rule` | `ls`, `add`, `rm` | `add rule never buy on a gap up` |
| `basetrade` | `ls`, `add`, `rm` | `add basetrade MRVU price 100 count 10` |
| `mail-broker` | `run`, `stop` | `run mail-broker` |
| `tasks` | `ls` | `ls tasks`: running background tasks |

And the commands of their own: `status` (positions with gain/loss and the
mail watcher's state), `xtop [sec]` (live gain/loss with Telegram alerts at
`gain_alert` / `gain_alert_pct`), `help [<command>]` and `exit`.

Every command with its arguments is in **[COMMANDS.md](COMMANDS.md)**, the same
text as `help` in the shell (`help add trade`, `help rm`, `help ladder`).

An action alone lists its objects (`ls` prints `ls: stocks, trades, ...`).
Keywords with a value, like `count 10 price 20.5`, may come in either order.
Tab completes actions, objects, stock names, ids and keywords.

The average price is a weighted average of your buys:
`avg = (avg × count + price × bought) / (count + bought)`. Sells lower the count
and keep the average. Gain/loss in `status` is `count × price − count × avg`.

### The mail trades service (mtsig)

```bash
./mtsig start      # run it in the background
./mtsig status     # running or not, last order, last log lines
./mtsig stop       # stop it cleanly
./mtsig restart
```

It waits for new emails from `IMAP_SENDER`, reads the order with
`scripts/order_parser.py` and records it when its status is `FILLED` and the
symbol is in `indices`. Emails like this one are understood (a
translation in brackets after each label is allowed too):

```
Symbol TSMX
Quantity 10
Executed Price 87.54
Order Type Buy  LMT  DAY
Status *FILLED*
```

- It remembers the last email it handled, so after a restart it picks up the
  emails it missed and never records an order twice. On the very first start it
  begins after the newest email, so old emails are not imported.
- A dropped connection is reconnected automatically.
- `./mtsig` finds a Python 3.14+ by itself, or uses `WATCHER_PYTHON`.
  In Termux it takes a wake lock while it runs, so Android does not pause it.
- Logs are in `data/logs/mtsig.log` (rotated at 1 MB, 5 files kept).
  `LOG_LEVEL=DEBUG` in `.env` logs more detail.
- If an order is found but can't be saved, the log and `status` in the shell
  show `ORDER NOT RECORDED` with the `add trade` command to add it by hand.

### Ladders

```
nX-sig> add ladder SOXL down 10 from 100 run
ladder 1 saved: SOXL down every 10 from 100
starting ladder 1...
ladder 1 started (pid 366), next alert at 90
```

Each ladder is its own process (`scripts/ladder.py`), so it keeps running when
the shell is closed. It checks the price every `ladder_interval` seconds and
sends a Telegram message when the price passes the next level, like
`SOXL down to 89.50, passed 90 (ladder 1, next 80)`. When the price jumps over
several levels between two checks, one message names the farthest one.

- The last level sent is saved, so after `stop ladder` and `run ladder <id>`,
  or a phone restart, no level is sent twice.
- A down ladder ends when its next level would be 0 or less (`done` in
  `ls ladders`).
- If a message can't be sent, the level is not saved and is sent at the next
  check.
- Telegram (`TOKEN`, `CHAT_ID` in `.env`) must be set up to start a ladder.
- In Termux a wake lock is held while a ladder or the mail watcher runs.
- Logs are in `data/logs/ladder_<id>.log`.

### Syncing the phone and the PC

`./syncnx` keeps `data/` the same on the phone (Termux) and the PC
(Linux) with [Syncthing](https://syncthing.net). The two devices connect
directly over Wi-Fi, a phone hotspot or USB tethering. No internet is needed,
and no outside server is used (global discovery and relays are off).

```bash
./syncnx setup        # install, start, print this device's ID
./syncnx setup <ID>   # also share data/ with device <ID>
./syncnx status       # ID, peers, folder state, web page
./syncnx stop
```

You can also open the web UI at http://127.0.0.1:8384 to see and change the
sync configuration (`./syncnx status` prints the address in use).

To pair the devices, run `setup` on both of them, then run `setup <ID>` on each
one with the other's ID. Before the first sync, only one device should have
data in `data/`. Otherwise, the files that differ end up as
`*.sync-conflict-*` copies.

- Run the mail watcher and the ladders on one device only, or the alerts come
  twice.
- Don't record trades on both devices before they have synced.
- These stay on each device and are never synced: `.lock`, `logs/`,
  `mtsig.pid` and the `*_status.json` heartbeats (see `data/.stignore`).
- Replaced or deleted files are kept in `data/.stversions` (the last 10).
- Syncthing runs with its own config in `~/.config/nx-sig-sync`, so it doesn't
  touch another Syncthing on the same device. After a phone restart, run
  `setup` again to start it.

## Data

Everything is kept in `storage_dir` (`data/`, not in git):

| File | Contents |
|---|---|
| `<stock>_trades.csv` | the stock's trades: Id, Date, Time, Type, Count, Price |
| `trades_total.csv` | count and average price of every stock |
| `personal_rules.json` | your rules |
| `base_trades.csv` | the basetrades (last buying prices), one per stock: Stock, Price, Count |
| `mail_state.json` | the last email the watcher handled |
| `mtsig_status.json` | the watcher's heartbeat, shown by `status` |
| `mtsig.pid` | the process id of the running `./mtsig` |
| `ladders.csv` | the saved ladders: Id, Stock, Direction, Step, From, Last (the last level sent), Created |
| `ladders_status.json` | the ladder processes' heartbeats, shown by `ls tasks` |
| `logs/` | the watcher's and the ladders' logs (`mtsig.log`, `ladder_<id>.log`) |

Data from before the rename of transactions to trades (the files
`<stock>_transactions.csv`, `transactions_total.csv` and `base_buy.csv`) is
renamed once with `./migrate_data`; run it on every device before using the
shell. The script is temporary and will be removed later.

## Project layout

```
nx-sig/
├── nxshell               start the shell
├── mtsig                 start/stop/status of the order watcher
│                         (mail trades service)
├── syncnx                sync data/ between phone and PC
├── migrate_data          renames old data files once (temporary)
├── config.json           stocks, data folder, price API
├── requirements.txt      the Python packages
├── .github/workflows/tests.yml
│                         CI: the tests on every push
├── CODE_STYLE.md         code style rules
├── COMMANDS.md           every shell command (generated)
├── assets/logo.svg
└── scripts/
    ├── commands.py       the shell: actions, help, collects the modules
    ├── shell/            the shell's commands, one module per feature
    │   ├── interface.py      Commands: what every *_cmd.py implements
    │   ├── ui.py             colors, WIDTH, printing, parsers
    │   ├── trade_cmd.py      trades
    │   ├── stocks_cmd.py     ls stocks
    │   ├── rule_cmd.py       rules
    │   ├── base_trade_cmd.py basetrades
    │   ├── ladder_cmd.py     ladders (the shell side)
    │   ├── mail_cmd.py       mail broker (./mtsig)
    │   ├── tasks_cmd.py      ls tasks
    │   └── overview_cmd.py   status, xtop
    ├── shell_test.py     tests of the shell commands
    ├── storage.py        trades, totals, rules and watcher state on disk
    ├── trade_engine.py   latest prices from Alpaca (one-off and polling)
    ├── order_watcher.py  email -> parsed order -> trade
    ├── mail_reader.py    IMAP IDLE watcher with reconnects
    ├── order_parser.py   reads an order from a broker email
    ├── ladder.py         price-step alerts, one process each
    ├── sync.py           syncs data/ between phone and PC (Syncthing)
    ├── metrics.py        metrics engine: statistics of your actions (planned)
    ├── latest_trade.py   prints the latest prices once
    ├── ntfy.py           push notification through ntfy.sh
    ├── telegram_notify.py  message through a Telegram bot
    ├── watch_notify.py   notes for a planned Garmin watch app
    ├── gen_docs.py       writes COMMANDS.md from the help texts
    └── check_style.py    checks the code style rules and COMMANDS.md
```

## Tests

```bash
python scripts/storage.py        # trades, totals, rules, locking
python scripts/order_parser.py   # order email parsing
python scripts/ladder.py         # ladder levels
python scripts/shell_test.py     # every shell command, faked prices
python scripts/sync.py           # device IDs, .stignore
python scripts/check_style.py    # code style (line width), COMMANDS.md
```

GitHub Actions runs all of these on every push and pull request,
on Python 3.12 and 3.14 ([tests.yml](.github/workflows/tests.yml)),
and also checks that `order_watcher.py` and `mail_reader.py` compile
and that the shell scripts have no syntax errors. A red mark on the
commit (or the badge at the top) means something broke.

## Code style

The code is written to be read on a phone: lines are at most
60 characters and the shell's output at most 48. See
[CODE_STYLE.md](CODE_STYLE.md) for the rules and how to check them.

## Planned

See [TODO.md](TODO.md).

## Python virtual environment 

git clone <repo-url>

cd <repo>

python -m venv .venv

source .venv/bin/activate

pip install -r requirements.txt

