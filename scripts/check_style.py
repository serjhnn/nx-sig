# check the code style rules of CODE_STYLE.md
#
#   python scripts/check_style.py [file ...]
#
# without files it checks the python scripts and the
# shell scripts of the repo. prints every line longer
# than MAX_WIDTH characters and exits with 1 if there
# are any, so it can also run before a commit.

import os
import sys

MAX_WIDTH = 60

ROOT_DIR = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)
SHELL_SCRIPTS = ["nxshell", "watcher"]


def default_files():
    scripts = os.path.join(ROOT_DIR, "scripts")
    files = [
        os.path.join(scripts, name)
        for name in sorted(os.listdir(scripts))
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
        return 1
    print(f"ok: all lines fit in {MAX_WIDTH} characters")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
