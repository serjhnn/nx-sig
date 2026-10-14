# To do

## Split the shell from the background services

Keep the parts you interact with apart from the parts
that run in the background, and show it in the names:

- **`nx` prefix: the shell and user interaction**
  - `nxshell` (the shell, `scripts/commands.py`)
  - the notifiers (`ntfy.py`, `telegram_notify.py`,
    the planned Garmin watch notifications)
- **`mtsig`: mail transactions service**
  - ~~rename `watcher` to `mtsig`~~ (done)
  - the service code: `order_watcher.py`,
    `mail_reader.py`, `order_parser.py`

When doing it, also update the names that still point
to the watcher: the `mail watcher:` line of `status`
and the docs.

## Other

- `run tactics <stock> <down|up> <step> <price>`:
  a thread that polls the price and notifies each time
  it passes the next level, e.g. `down 10 100` at 90,
  80, 70, ... (the command and its arguments are there,
  the thread is not)
- `strategy` commands
- Notifications to a Garmin watch
  (see `scripts/watch_notify.py`)
- Send a notification when the watcher records an order
