# CLI blueprint

The plan for reorganising the `nxshell` commands by
feature. Nothing here is implemented yet.

## Why

The shell has grown to 1800+ lines in one file, and the
commands mix two styles:

- feature first: `tr add ...`, `rules add ...`
- action first: `run ladder ...`, `stop ladder ...`,
  `rm ladder ...`, `ls ladder`

The action words are mixed as well: `tr get` / `ls`,
`tr del-last` / `rules delete` / `rm`.

## Rules for every command

1. **`<feature> <action> [arguments]`**, e.g.
   `ladder run MRVL down 10 from 140`.
2. **The same action words in every feature:**
   - `ls`: list or show
   - `add`: save a new record
   - `rm`: delete, after confirmation
   - `run`, `stop`: start or stop a background task
3. **A feature alone shows its help**: `ladder` prints
   the same as `help ladder`, the list of its actions.
4. **Top-level commands only for what spans features**:
   `status`, `xtop`, `ps`, `help`, `exit`.
5. **No aliases for the old commands**: the data folder
   starts clean, there is nothing to stay compatible
   with.
6. **Readable keywords are required**, not optional, so
   there is one way to write a command: `from` in
   `ladder run`, `count` and `price` in `tr add`. Tab
   completion fills them in.
7. Output stays within 48 characters, code within 60
   (see CODE_STYLE.md).

## The command set

### Transactions (`tr`)

| Now | New |
|---|---|
| `tr add <stock> <buy\|sell> <count> <price>` | `tr add <stock> <buy\|sell> count <count> price <price>` |
| `ls` | `tr ls` (totals of held stocks, growth %) |
| `tr get <stock>`, `ls <stock>` | `tr ls <stock>` |
| `tr del-last <stock>` | `tr rm-last <stock>` |

e.g. `tr add SOXL buy count 10 price 20.5`. The
`count` and `price` keywords say which number is which,
so the two can't be swapped by mistake.

### Rules (`rules`)

| Now | New |
|---|---|
| `rules` | `rules ls` |
| `rules add <rule>` | `rules add <rule>` |
| `rules delete <id>` | `rules rm <id>` |

### Ladders (`ladder`)

| Now | New |
|---|---|
| `run ladder <stock> <down\|up> <step> <price>` | `ladder run <stock> <down\|up> <step> from <price>` |
| `run ladder <id>` | `ladder run <id>` |
| `stop ladder <id>` | `ladder stop <id>` |
| `rm ladder <id>` | `ladder rm <id>` |
| `ls ladder` | `ladder ls` |

### Mail broker (`mail-broker`)

| Now | New |
|---|---|
| `run mail-broker` | `mail-broker run` |
| `stop mail-broker` | `mail-broker stop` |

### Top-level

- `status`: positions with gain/loss and the state of
  the background tasks
- `xtop [sec]`: live gain/loss
- `ps`: running background tasks of all features
- `help`, `help <feature>`, `exit` / `quit` / `q`

### Left as it is

- `strategy`: stays unchanged for now, it is not part
  of this reorganisation.

### Later features

They follow the same rules when they are built:

- `metrics ...` (see `scripts/metrics.py`)

## Code structure

```
scripts/
  commands.py       the shell: NxSigShell, banner,
                    prompt, help, dispatch
  shell/
    __init__.py
    ui.py           colors, WIDTH, printing, tables,
                    completion and argument parsers
                    (_parse_stock, _parse_id, ...)
    tr_cmd.py       tr
    rules_cmd.py    rules
    ladder_cmd.py   ladder (the shell side;
                    the engine stays scripts/ladder.py)
    mail_cmd.py     mail-broker
    overview_cmd.py status, xtop, ps
```

The `_cmd` suffix keeps the shell files apart from the
engines with the same name (`ladder_cmd.py` vs
`ladder.py`).

`strategy` stays in `commands.py` as it is.

- **One class per feature**, mixed into `NxSigShell`
  (`class NxSigShell(TrCmd, RulesCmd, LadderCmd, ...,
  cmd.Cmd)`).
- **One method per action**, e.g. `ladder_run`,
  `ladder_ls`. Its docstring is its help text, at most
  48 characters wide.
- **A shared dispatcher** turns `do_ladder(arg)` into a
  call of the action method. It handles a missing action
  (shows the feature's help) and an unknown one
  (`unknown action 'x' for ladder, expected
  ls/run/stop/rm`).
- **Help is built from the docstrings**: `help ladder`
  joins the docstrings of its actions, and the overview
  of `help` joins all the features. The hand-written
  `HELP` text goes away.
- **Completion per action**: `complete_ladder` offers
  the actions, then calls the action's own completer if
  it has one (stocks, `down`/`up`, `from`, ids).
- **`ps` asks every feature** with background tasks for
  its rows, so a new feature adds itself to `ps` without
  changing it.

## Steps

Each step is its own commit, so a problem is easy to
place.

1. **Move the code, keep the commands.** Split
   `commands.py` into `scripts/shell/` as above, without
   changing any command. Check it by running every
   command before and after and comparing the output.
2. **Add the dispatcher and per-action methods,** still
   with the old command names.
3. **Rename the commands** to the new set. Update the
   help, README, TODO.md and the docstring rule in
   CODE_STYLE.md.
4. **Generate `COMMANDS.md`** from the docstrings with a
   small `scripts/gen_docs.py`. The README keeps a short
   overview and links to it. `check_style.py` warns
   when `COMMANDS.md` is out of date.

## Tests

Add `scripts/shell_test.py`: runs every command through
`NxSigShell.onecmd()` against a temporary data folder
and a fake price feed, and checks the output. It is
written in step 1, so steps 2-4 are checked by it.

## Open questions, for later

- A `mail-broker status` with the last log lines, like
  `./mtsig status`?
- `status`: keep the `mail watcher:` line, or show all
  background tasks there (see the nx/mtsig split in
  TODO.md)?
