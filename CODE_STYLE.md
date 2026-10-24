# Code style

nX-sig is written and read on a phone (Termux), so the
code has to fit a phone screen. These rules apply to the
Python scripts in `scripts/` and the shell scripts
`nxshell` and `mtsig`.

Check them with:

```bash
python scripts/check_style.py
```

It prints every line that breaks the width rule and exits
with 1, so it can run before each commit (see
[Pre-commit check](#pre-commit-check)).

## Line width

- **Code lines are at most 60 characters**, comments and
  docstrings included. Characters are counted, not bytes,
  so Armenian or other non-latin text is measured right.
- **What the shell prints is at most 48 characters**
  (`DEFAULT_WIDTH` in `scripts/shell/ui.py`), so tables
  and messages fit the screen without wrapping. Wrap
  long messages with `print_wrapped()` /
  `print_error()`. The width can be set wider
  (`width()`, config `width`), so use `width()` instead
  of a number, and build table gaps with
  `column_separator(color, columns)` or
  `space_separator(columns, base)` so they grow with
  it. The dashed line under a table header is
  `rule(header)`, as wide as the columns.

## Wrapping long lines in Python

Prefer brackets over `\` to continue a line:

```python
log.info("recorded %s (email %r)",
         description, subject)

trade_add(
    stock, side, quantity, price
)
```

Split long strings into adjacent literals; Python joins
them into one string, so the value doesn't change. Split
f-strings at a space or between two `{...}`, never inside
the braces:

```python
description = (f"{side.name} {quantity} "
               f"{stock.name} @ {price}")
```

When a line is still too long:

- give a long expression its own name first
  (`pct = diff / previous * 100`)
- move a deeply nested block into a small function, so
  the code doesn't start 30 columns to the right
- put a comment on its own line above the code instead
  of at the end of it

## Formatting

[black](https://black.readthedocs.io) does most of the
wrapping. Use the project's settings, 60 columns and
quotes left as they are:

```bash
pip install black
black -l 60 -S scripts/
```

black doesn't wrap comments, docstrings or long strings,
so fix what `check_style.py` still reports by hand.

## Shell scripts

- Use `\` at the end of a line to continue a command, or
  end the line after `|`, `&&` or `||`.
- Put long inline Python or messages into a variable
  first.
- Start with `cd "$(dirname "$0")"`, so the script works
  from any folder.

## Comments and docstrings

- Each script starts with a comment saying what it does
  and lists its public functions.
- Comments explain *why*, short and lowercase, like the
  rest of the code.
- The docstrings of the actions (`ls`, `add`, ...) of
  the `Commands` classes in `scripts/shell/` and of the
  `do_<command>` methods are the shell's help: the
  usage first, continued with a 2-space indent, then
  the description indented by 4 spaces. `help` lists
  the usage lines, `help <command>` the whole text.
  Keep them within 48 characters:

  ```python
  def add(self, arg):
      """
      add trade <stock> <buy|sell>
        count <count> price <price>
          record a trade, e.g. 'add trade SOXL
          buy count 10 price 20.5'
      """
  ```

  `COMMANDS.md` is made from the same texts: after
  changing one, run `python scripts/gen_docs.py`
  (`check_style.py` fails while `COMMANDS.md` is out
  of date). The same for the module map: after
  adding, removing or renaming an import or a module,
  run `python scripts/gen_deps.py` to rewrite
  `assets/modules.html`.

## Names

- `snake_case` for functions and variables,
  `UPPER_CASE` for constants, `CamelCase` for classes.
- A leading `_` marks a helper used only inside its
  module. A name other modules import has none, like
  the shell's shared helpers in `shell/ui.py`
  (`print_wrapped`, `parse_stock`, ...).
- A file in `services/` (a background process) is named
  `<engine>_service.py` after the engine in `engines/`
  that starts and stops it: `ladder_service.py` runs
  the ladders of `engines/ladder.py`.

## Project rules

- Python scripts live in `scripts/`; `config.json`,
  `.env` and `data/` stay in the repo root. Build paths
  from `ROOT_DIR` (the folder above `scripts/`), never
  from the current directory.
- All data files are read and written through
  `scripts/storage.py`, which locks them and writes them
  atomically.
- Secrets (API keys, passwords) go in `.env` only, never
  in the code or `config.json`.
- Colors come from the constants in `shell/ui.py`
  (the logo gradient, `PRICE_COLOR`, `DIM`, ...), and
  output must still work without color (`NO_COLOR`, the
  plain theme, or output that is not a terminal): check
  `supports_color()` each time, not once at start.
- Python 3.14+ (`order_watcher.py` / `mail_reader.py`
  need it for IMAP IDLE, CI tests only 3.14).
- Tests live in `tests/`, one file per module:
  `tests/test_storage.py` tests `scripts/storage.py`,
  `tests/test_shell.py` every shell command (so they
  stay the same while the shell is split into
  modules). `tests/paths.py` puts `scripts/` on
  `sys.path`, import it before the modules. Run them
  after a change:

  ```bash
  python -m unittest discover tests
  python tests/test_storage.py
  ```

## Pre-commit check

To run the check before every commit:

```bash
printf '#!/bin/sh\nexec python3 scripts/check_style.py\n' \
    > .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit
```

A commit with a too long line then stops with the list of
lines to fix.
