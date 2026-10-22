# CLAUDE.md

What a new Claude Code session needs to work on
nX-sig. The style rules are in `CODE_STYLE.md`, the
folders, config and tests in `README.md`, the
command pattern in `CLI_BLUEPRINT.md` and the open
work in `TODO.md`: read them before changing code.

## The project

A Python terminal tool for stock positions: trades,
rules, basetrades, price ladders, alerts and a mail
broker that turns broker emails into trades. It runs
in Termux on a phone and on a Linux PC, so the code
and the output must fit a phone screen.

- `./nxshell` starts the shell (`scripts/commands.py`)
- `./mtsig` starts the mail broker (`scripts/mtsig/`)
- `./syncnx` syncs `data/` between phone and PC
- `config.json` holds the settings, `.env` the
  secrets (not in the repo), `data/` the data files

## How the code is split

- `scripts/shell/<feature>_cmd.py` parses a command,
  calls an engine and prints. It doesn't read or
  write data itself.
- `scripts/engines/` holds the logic. Only engines
  use `storage.py`. Import them as
  `from engines import trades`.
- `scripts/services/<engine>_service.py` is the
  background process an engine starts and stops.
- `scripts/notifiers/` holds the notify channels.
  `notifier.py` sends through the one config
  `"notify"` chooses (`telegram`, `termux`, `ntfy`,
  listed in `CHANNELS` and `config.NOTIFY_CHANNELS`).
  A channel module has `notify(text, key=None)` (the
  same key replaces the earlier message where the
  channel can), `is_configured()` and `SETUP_ERROR`.
- Running ladders and alerts keep the code they
  started with until they are restarted.

## Plan first

For any change that isn't small (more than a quick
fix in one place), don't start coding right away:

1. Describe what has to be done as a numbered list
   of steps, and wait for confirmation.
2. Do one step, report what changed, and wait for
   confirmation before the next step.

Small changes (a rename, a one-line fix, a doc
line) can be done directly.

## Rules

- Code lines at most 60 characters, shell output at
  most `width()` (see `CODE_STYLE.md`).
- Secrets only in `.env`, never in code or
  `config.json`.
- No migration code for old data in the scripts; old
  data is handled by `./migrate_data`, keep it.
- Keep `README.md` (layout, config table) and
  `TODO.md` up to date with each change.
- A new test file must also be added as a step to
  `.github/workflows/tests.yml`.
- Don't create pull requests unless asked.
- No model names or ids in commits or in the repo.

## Before each commit

```bash
# format only the files you changed
black -q -l 60 -S <changed .py files>
pyflakes scripts tests
python scripts/gen_docs.py   # help docstrings changed
python scripts/gen_deps.py   # imports/modules changed
python scripts/check_style.py
$V -m unittest discover tests
```

`black` and `pyflakes` are the system ones, not in
the venv. Never run black on all of `scripts/`.

These pyflakes warnings are expected, leave them:

- `'paths' imported but unused` in the tests
- `'chart' imported but unused` in `test_shell.py`
- `'storage.Stock' imported but unused` in
  `engines/ladder.py`

## Tests on Python 3.14

Test only on 3.14 (CI uses it, the mail broker needs
it). Make a venv in the session's scratchpad:

```bash
V=<scratchpad>/venv3.14/bin/python
uv venv -p 3.14 <scratchpad>/venv3.14
uv pip install -p $V -r requirements.txt
$V -m unittest discover tests
```

The tests fake prices, `.env` keys and background
processes, so nothing is sent anywhere.

## Git

- Work on the session's branch and push with
  `git push -q origin HEAD:<branch>`.
  Don't push to other feature branches.
- "push it to main" means:

  ```bash
  git status -s
  git fetch -q origin main <branch>
  # must print nothing:
  git log --oneline origin/<branch>..origin/main
  git push origin origin/<branch>:main
  ```

  Then wait about a minute and check the `tests.yml`
  run on main (GitHub MCP `actions_list`,
  `list_workflow_runs`, branch `main`, perPage 1).
  Report the run number and result.
