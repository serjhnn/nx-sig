# Code style

nX-sig is written and read on a phone (Termux), so the
code has to fit a phone screen. These rules apply to the
Python scripts in `scripts/` and the shell scripts
`nxshell` and `watcher`.

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
  (`WIDTH` in `scripts/commands.py`), so tables and
  messages fit the screen without wrapping. Wrap long
  messages with `_print_wrapped()` / `_print_error()`.

## Wrapping long lines in Python

Prefer brackets over `\` to continue a line:

```python
log.info("recorded %s (email %r)",
         description, subject)

transactions_add_one(
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
- Docstrings of `do_<command>` methods in `commands.py`
  are the shell's `help <command>` text: keep them within
  48 characters after the indentation.

## Names

- `snake_case` for functions and variables,
  `UPPER_CASE` for constants, `CamelCase` for classes.
- A leading `_` marks a helper used only inside its
  module.

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
- Colors come from the constants in `commands.py`
  (the logo gradient, `PRICE_COLOR`, `DIM`, ...), and
  output must still work without color (`NO_COLOR`, or
  output that is not a terminal).
- Python 3.12+ for everything except
  `order_watcher.py` / `mail_reader.py`, which need 3.14+.
- Tests live at the end of their module, under
  `if __name__ == "__main__":`; run them after a change:

  ```bash
  python scripts/storage.py
  python scripts/order_parser.py
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
