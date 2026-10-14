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

- **Background tasks**, each one its own process, so it
  keeps running when the shell is closed. The commands,
  their help and argument checks are in
  `scripts/commands.py`, they don't run anything yet:
  - `run ladder <stock> <down|up> <step> <price>`: save
    a new ladder to `data/ladders.csv` with an id and
    start its process, which polls the price and
    notifies each time it passes the next level, e.g.
    `down 10 100` at 90, 80, 70, ... The file keeps
    stock, direction, step, from price and the last
    level notified (so a level isn't notified twice).
  - `run ladder <id>`: start saved ladder <id> again,
    e.g. after a restart
  - ~~`run mail-broker`: start the mail watcher
    (`./mtsig start`)~~ (done)
  - `ps`: the running task processes with their ids
  - `ls ladder`: the saved ladders with their ids
  - `stop ladder <id>`, `stop mail-broker`: stop one
  - maybe start the ladders that were running before
    when the phone restarts
- `strategy` commands
- Notifications to a Garmin watch
  (see `scripts/watch_notify.py`)
- Send a notification when the watcher records an order
