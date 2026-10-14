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

- **Tactics** (the `run tactics` command and its
  arguments are there, the rest is not):
  - `run tactics <stock> <down|up> <step> <price>`
    starts a thread that polls the price and notifies
    each time it passes the next level, e.g.
    `down 10 100` at 90, 80, 70, ...
  - save each tactic to `data/tactics.csv` with a
    number, so it can be run again after a restart:
    stock, direction, step, from price, state
    (running / stopped) and the last level notified
    (so a level isn't notified twice)
  - `ls tactics`: list the saved and running tactics
    with their numbers and state
  - `run tactics <n>`: start saved tactic number n
  - `stop tactics <n>`: stop running tactic number n
  - maybe start the tactics that were running before
    when the shell starts again
- `strategy` commands
- Notifications to a Garmin watch
  (see `scripts/watch_notify.py`)
- Send a notification when the watcher records an order
