# To do

## Split the shell from the background services

Keep the parts you interact with apart from the parts
that run in the background, and show it in the names:

- **`nx` prefix: the shell and user interaction**
  - `nxshell` (the shell, `scripts/commands.py`)
  - the notifiers (`ntfy.py`, `telegram_notify.py`,
    the planned Garmin watch notifications)
- **`mtsig`: mail transactions service**
  - rename `watcher` to `mtsig` (start / stop /
    status / restart)
  - the service code: `order_watcher.py`,
    `mail_reader.py`, `order_parser.py`

When doing it, also update the names that point to the
watcher: `data/order_watcher.pid`,
`data/logs/order_watcher.log`, `watcher_status.json`,
the `mail watcher:` line of `status`, `README.md` and
`CODE_STYLE.md`.

## Other

- Growth % in `ls` (currently always 0)
- `strategy` commands
- Notifications to a Garmin watch
  (see `scripts/watch_notify.py`)
- Send a notification when the watcher records an order
