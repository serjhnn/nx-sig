# CLI blueprint

The plan for reorganising the `nxshell` commands.
All five steps are done; the open questions at the
end are for later.

## Why

The shell has grown to 1800+ lines in one file, and the
commands mix two styles:

- feature first: `tr add ...`, `rules add ...`,
  `bb add ...`
- action first: `run ladder ...`, `stop ladder ...`,
  `rm ladder ...`, `ls ladder`

The action words are mixed as well: `tr get` / `ls`,
`tr del-last` / `rules delete` / `rm`.

## The pattern: action first

Every command starts with what it does, then names the
kind of data it works on:

```
<action> <object> [arguments]
```

e.g. `ls ladders`, `add ladder MRVL down 10 from 140`,
`rm trade SOXL 12`.

Why action first:

- **A few verbs cover everything.** Learn `ls`, `add`,
  `rm`, `run`, `stop` once and they work on every kind
  of data.
- **The first word says what will happen.** `rm ...`
  always deletes, `ls ...` only reads.
- **A short top level.** Tab on an empty line offers
  the verbs plus `status`, `xtop`, `help`, `exit`, not
  every feature.

## Rules for every command

1. **`<action> <object> [arguments]`.**
2. **The same action words for every object:**
   - `ls`: list or show
   - `add`: save a new record
   - `rm`: delete, after confirmation
   - `run`, `stop`: start or stop a background task
3. **Plural after `ls`, singular everywhere else:**
   `ls ladders`, but `add ladder`, `rm ladder 1`,
   `run ladder 1`. There is exactly one spelling for
   each: `ls ladder` and `rm ladders` are errors that
   name the right form.
4. **An action alone lists its objects:** a bare `ls`
   prints `ls: stocks, trades, ladders, rules,
   basetrades, tasks`, and the same for `add`, `rm`, `run`, `stop`.
5. **Top-level commands only for what spans features**:
   `status`, `xtop`, `help`, `exit`.
6. **No aliases for the old commands**: the data folder
   starts clean, there is nothing to stay compatible
   with.
7. **Readable keywords are required**, not optional, so
   there is one way to write a command: `from` in
   `add ladder`, `count` and `price` in `add trade` and
   `add basetrade`. Tab completion fills them in.
   Keywords with a value (`count 10`, `price 20.5`) may
   come in either order, as `bb add` takes them now.
8. Output stays within 48 characters, code within 60
   (see CODE_STYLE.md).

## Words

- **trade**, not transaction: the word "transaction"
  and the `tr` shortcut go away everywhere (commands,
  help, code, data files, README).
- **basetrade** replaces `bb` (base buy): the last
  buying price of a stock. Its plural is
  **basetrades**. The data file becomes
  `base_trades.csv`.
- **task** is a background process: a ladder, the
  alerts or the mail broker.

## The command set

### Objects and their actions

| Object | ls | add | rm | run | stop |
|---|---|---|---|---|---|
| stocks | yes | | | | |
| trade | yes | yes | yes | | |
| rule | yes | yes | yes | | |
| basetrade | yes | yes | yes | | |
| ladder | yes | yes | yes | yes | yes |
| alert | yes | yes | yes | yes | yes |
| mail-broker | | | | yes | yes |
| tasks | yes | | | | yes |

### Stocks and trades

| Now | New |
|---|---|
| `ls` | `ls stocks` (totals of held stocks, growth %) |
| `tr get <stock>`, `ls <stock>` | `ls trades <stock>` |
| `tr add <stock> <buy\|sell> <count> <price>` | `add trade <stock> <buy\|sell> count <count> price <price>` |
| `tr del-last <stock>` | `rm trade <stock> <id>` |

- e.g. `add trade SOXL buy count 10 price 20.5`. The
  `count` and `price` keywords say which number is
  which, so the two can't be swapped by mistake.
- `ls trades <stock>` shows an Id column (the stock's
  trade number), so any trade can be deleted, not only
  the last one: `ls trades SOXL`, then
  `rm trade SOXL 12`.
- Deleting a trade from the middle recalculates the
  stock's total (count and average price) from its
  remaining trades.
- `ls trades` without a stock lists the stocks that
  have trades.
- `ls stocks` takes no arguments: `ls stocks SOXL` is
  an error that names the right form,
  `use 'ls trades SOXL'`, so each thing has one way to
  ask for it.

### Rules

| Now | New |
|---|---|
| `rules` | `ls rules` |
| `rules add <rule>` | `add rule <rule>` |
| `rules delete <id>` | `rm rule <id>` |

### Base trades

| Now | New |
|---|---|
| `bb ls` | `ls basetrades` |
| `bb add <stock> price <price> count <count>` | `add basetrade <stock> price <price> count <count>` |
| `bb rm <stock>` | `rm basetrade <stock>` |

### Ladders

| Now | New |
|---|---|
| `ls ladder` | `ls ladders` |
| `run ladder <stock> <down\|up> <step> <price>` | `add ladder <stock> <down\|up> <step> from <price> [run]` |
| `run ladder <id>` | `run ladder <id>` |
| `stop ladder <id>` | `stop ladder <id>` |
| `rm ladder <id>` | `rm ladder <id>` |

- `add ladder` only saves the ladder and prints its id.
- With **`run`** as the last word it is also started
  right away, the way `run ladder <stock> ...` does
  today: `add ladder MRVL down 10 from 140 run`.
- `run ladder` takes only an id.

### Mail broker

| Now | New |
|---|---|
| `run mail-broker` | `run mail-broker` |
| `stop mail-broker` | `stop mail-broker` |

### Tasks

| Now | New |
|---|---|
| `ps` | `ls tasks` (running background tasks) |

### Top-level

- `status`: positions with gain/loss and the state of
  the background tasks
- `xtop [sec] [sip|iex] [al]`: live gain/loss
- `help`, `help <action>`, `help <object>`,
  `exit` / `quit` / `q`
- `help ladder` lists everything that works on ladders
  (`ls ladders`, `add ladder`, `run ladder`, ...),
  `help rm` lists everything that can be deleted.

### Left as it is

- `strategy`: stays unchanged for now, it is not part
  of this reorganisation.

### Later features

They follow the same rules when they are built:

- `ls metrics ...` (see `scripts/metrics.py`)

## Code structure

The commands are grouped by action, but the code stays
grouped by feature.

### The interface

The CLI defines the interface: the actions every
module can implement.

```python
class Commands:
    """One kind of data the shell works on."""

    name = ""      # singular: "ladder"
    plural = ""    # used after ls: "ladders"

    def ls(self, args): ...
    def add(self, args): ...
    def rm(self, args): ...
    def run(self, args): ...
    def stop(self, args): ...

    def complete(self, action, args): ...
    def tasks(self): ...   # rows for ls tasks
```

- A module implements only the actions it supports,
  the others stay unimplemented. The CLI knows which
  ones a module has, so `run trade` says `trade has no
  run, it has ls/add/rm`.
- The docstring of each implemented action is its help
  text, at most 48 characters wide.

### The modules

Every module implements the interface on its side, in
its own file:

```python
class LadderCommands(Commands):
    name = "ladder"
    plural = "ladders"

    def add(self, args):
        """add ladder <stock> <down|up> <step>
        from <price> [run]
            save a ladder, run starts it too"""
        ...
```

### Collecting the modules

When the CLI starts, it collects all the module
implementations:

1. imports every `*_cmd.py` in `scripts/shell/`,
2. finds the `Commands` subclasses in them,
3. builds the table: object name -> implementation,
   and for each action the objects that have it.

The CLI itself has only the verb commands, `do_ls`,
`do_add`, `do_rm`, `do_run`, `do_stop`, and they all
work the same way: take the object word, look it up in
the table, call its action with the rest of the line.
They also handle

- a missing object: list what the verb works on,
- an unknown one: `unknown object 'x' for rm, expected
  trade/rule/basetrade/ladder`,
- the wrong number: `use 'ls ladders'`.

A new feature is a new `*_cmd.py` file. Nothing in the
CLI changes to add it: its commands, help, completion
and `ls tasks` rows appear on their own.

### Files

```
scripts/
  commands.py       the shell: NxSigShell, banner,
                    prompt, help, the verb commands,
                    collecting the modules
  shell/
    __init__.py
    interface.py    the Commands class
    ui.py           colors, WIDTH, printing, tables,
                    completion and argument parsers
                    (_parse_stock, _parse_id, ...)
    stocks_cmd.py   stocks
    trade_cmd.py    trade
    rule_cmd.py     rule
    base_trade_cmd.py
                    basetrade
    ladder_cmd.py   ladder (the shell side;
                    the engine stays scripts/ladder.py)
    mail_cmd.py     mail-broker
    overview_cmd.py status, xtop (top-level)
```

The `_cmd` suffix keeps the shell files apart from the
engines with the same name (`ladder_cmd.py` vs
`ladder.py`).

`strategy` stays in `commands.py` as it is.

### Help and completion

- **Help is built from the docstrings**: `help ladder`
  shows the actions of ladder, `help rm` the `rm` of
  every module, and the overview of `help` joins them
  all. The hand-written `HELP` text goes away.
- **Completion**: `complete_rm` offers the objects
  that have `rm`, then calls that module's `complete`
  (stocks, ids, `down`/`up`, `from`, `count`, `price`,
  `run`).
- **`ls tasks`** joins the `tasks()` rows of every
  module that has background tasks.

## Steps

Each step is its own commit, so a problem is easy to
place.

1. **Move the code, keep the commands.** (done) Split
   `commands.py` into `scripts/shell/` as above, without
   changing any command. Check it by running every
   command before and after and comparing the output.
2. **Add the interface and the module classes,** and
   collect them at start, still with the old command
   names. (done) The commands as typed now (`tr`,
   `rules`, `bb`, `ls`, `run`, `stop`, `rm`) are in
   `shell/old_commands.py` and call the modules'
   actions; step 4 replaces that file with the verb
   commands. `ps` already joins the modules' `tasks()`.
   Until step 4 the actions of a module work as the old
   commands did (`ls` of trade is `tr get`, `rm` of
   trade is `tr del-last`, `run` of ladder also saves a
   new one).
3. **Rename transaction to trade and bb to
   basetrade** in code, data files
   (`<stock>_trades.csv`, `trades_total.csv`,
   `base_trades.csv`) and docs,
   and add the trade Id (the existing per-stock Index)
   to `ls trades`. (done) Only names inside the code and
   the files changed, the output stays the same until
   step 4. The Index column is now Id, `tr get` already
   showed it. `./migrate_data` renames old data files
   once.
4. **Switch to the new command set** with the verb
   commands, the `run` option of `add ladder` and
   `rm trade <stock> <id>`. Update the help, README,
   TODO.md and the docstring rule in CODE_STYLE.md.
   (done) `shell/old_commands.py` is gone, `ps` is
   `ls tasks` (`shell/tasks_cmd.py`), and `rm rule`
   asks for confirmation like every `rm`.
5. **Generate `COMMANDS.md`** from the docstrings with a
   small `scripts/gen_docs.py`. The README keeps a short
   overview and links to it. `check_style.py` warns
   when `COMMANDS.md` is out of date. (done) It fails
   then, like for a too long line, so the pre-commit
   check stops the commit.

## Tests

`tests/test_shell.py` (done) runs every command
through `NxSigShell.onecmd()` against a temporary data
folder, with faked prices, Telegram, ladder processes
and the mail broker, and checks the output and that every
line fits 48 characters. It tests the commands as they
are now, so steps 1 and 2 must leave it passing
unchanged, and steps 3 and 4 update it together with
the commands they rename.

## Open questions, for later

- ~~A `mail-broker` status with the last log lines, like
  `./mtsig status`?~~ (done, `ls mail-broker`; `./mtsig`
  is gone, the shell starts the mail broker)
- `status`: keep the `mail watcher:` line, or show all
  background tasks there (see the nx/mtsig split in
  TODO.md)?
