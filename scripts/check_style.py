# check the code style rules of CODE_STYLE.md
#
#   python scripts/check_style.py [file ...]
#
# without files it checks the python scripts (scripts/,
# scripts/shell/ and scripts/mtsig/) and the shell
# scripts of the repo, and that COMMANDS.md matches the
# shell's help texts (scripts/gen_docs.py). prints
# every line longer than MAX_WIDTH characters and exits
# with 1 if there are any or COMMANDS.md is out of
# date, so it can also run before a commit.

import os
import sys

MAX_WIDTH = 60

ROOT_DIR = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)
SHELL_SCRIPTS = ["nxshell", "mtsig", "migrate_data"]


def default_files():
    files = []
    for folder in (
        "scripts",
        os.path.join("scripts", "shell"),
        os.path.join("scripts", "mtsig"),
    ):
        folder = os.path.join(ROOT_DIR, folder)
        files += [
            os.path.join(folder, name)
            for name in sorted(os.listdir(folder))
            if name.endswith(".py")
        ]
    files += [
        os.path.join(ROOT_DIR, name)
        for name in SHELL_SCRIPTS
        if os.path.exists(os.path.join(ROOT_DIR, name))
    ]
    return files


def long_lines(path):
    """(line number, width, line) of each line longer
    than MAX_WIDTH; width is counted in characters,
    not bytes, so non-latin text is measured right"""
    with open(path, encoding="utf-8") as f:
        for number, line in enumerate(f, 1):
            line = line.rstrip("\n")
            if len(line) > MAX_WIDTH:
                yield number, len(line), line


def main(paths):
    found = 0
    for path in paths or default_files():
        name = os.path.relpath(path, ROOT_DIR)
        for number, width, line in long_lines(path):
            print(f"{name}:{number}: {width} > {MAX_WIDTH}")
            print(f"    {line}")
            found += 1
    if found:
        print(f"{found} line(s) longer than {MAX_WIDTH}")
    else:
        print(
            f"ok: all lines fit in {MAX_WIDTH} characters"
        )
    docs_ok = paths or commands_md_ok()
    return 0 if not found and docs_ok else 1


def commands_md_ok():
    """True if COMMANDS.md matches the help texts; it
    needs the shell's packages, without them the check
    is skipped"""
    try:
        import gen_docs
    except Exception as e:
        print(f"skipped the COMMANDS.md check: {e}")
        return True
    if gen_docs.up_to_date():
        print("ok: COMMANDS.md is up to date")
        return True
    print(
        "COMMANDS.md is out of date, run "
        "python scripts/gen_docs.py"
    )
    return False


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
