# To do

## Split the shell from the background services

Keep the parts you interact with apart from the parts
that run in the background, and show it in the names:

- **`nx` prefix: the shell and user interaction**
  - `nxshell` (the shell, `scripts/commands.py`)
  - the notifiers (`ntfy.py`, `telegram_notify.py`,
    the planned Garmin watch notifications)
- **`mtsig`: mail trades service**
  - ~~rename `watcher` to `mtsig`~~ (done)
  - the service code: `order_watcher.py`,
    `mail_reader.py`, `order_parser.py`

When doing it, also update the names that still point
to the watcher: the `mail watcher:` line of `status`
and the docs.

## Other

- **Reorganise the shell commands by feature**
  (`ladder run ...`, `tr ls`, ...), see
  [CLI_BLUEPRINT.md](CLI_BLUEPRINT.md)
- **Background tasks**: ~~`run`, `stop`, `ps`,
  `ls ladder` for ladders and the mail broker~~ (done,
  `scripts/ladder.py`). Still open:
  - maybe start the ladders that were running before
    when the phone restarts
- Metrics (`scripts/metrics.py`): statistics of your
  actions, once enough data is collected
- `strategy` commands
- Notifications to a Garmin watch
  (see `scripts/watch_notify.py`)
- Send a notification when the watcher records an order
