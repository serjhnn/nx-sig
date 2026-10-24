# gen_shots: writes the demo pictures of README.md
# (assets/demo-*.svg) from a real run of ./nxdemo, so
# they can be made again when the output changes
#
#   python scripts/gen_shots.py          all of them
#   python scripts/gen_shots.py chart    only one
#
# each picture is a fresh demo in a copy of the repo in
# a temp folder (so demo_data/ is never touched), run in
# a pseudo-terminal of COLUMNS columns, so it prints its
# colors and wraps as on a phone. rich turns the output
# into a terminal-like SVG. Linux and macOS only (pty);
# the prices are made up anew each time
#
# public functions:
#   run_demo(steps)   the output of ./nxdemo given the
#                     commands of steps
#   save_svg(text, path, title)
#                     text with color codes as an SVG

import fcntl
import io
import os
import pty
import re
import select
import shutil
import struct
import sys
import tempfile
import termios
import time

from rich.console import Console
from rich.text import Text

ROOT_DIR = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)
COLUMNS = 50
ROWS = 60
# seconds to wait for the demo to start
START_WAIT = 4
# name: (title, drop the banner, [(command, seconds
# to wait for its output)])
SHOTS = {
    "start": (
        "./nxdemo",
        False,
        [("ls stocks", 2), ("status", 2)],
    ),
    "chart": ("chart", True, [("chart SOXL", 3)]),
    "ladder": (
        "a ladder and the demo command",
        True,
        [
            ("run ladder 1", 6),
            # the next check of the ladder sends it
            ("demo move SOXL -5%", 9),
            ("", 1),
            ("ls ladders", 2),
            ("stop tasks all", 3),
        ],
    ),
}
# the repo files the demo needs
COPIED = ("scripts", "demo", "nxdemo", "config.json")
PROMPT = "nX-sig demo>"


def _copy_repo(folder):
    ignore = shutil.ignore_patterns("__pycache__")
    for name in COPIED:
        source = os.path.join(ROOT_DIR, name)
        target = os.path.join(folder, name)
        if os.path.isdir(source):
            shutil.copytree(source, target, ignore=ignore)
        else:
            shutil.copy2(source, target)


def _read_for(fd, seconds):
    out = b""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        ready, _, _ = select.select([fd], [], [], 0.1)
        if not ready:
            continue
        try:
            out += os.read(fd, 65536)
        except OSError:
            break
    return out


def run_demo(steps):
    with tempfile.TemporaryDirectory() as folder:
        _copy_repo(folder)
        env = dict(
            os.environ,
            TERM="xterm-256color",
            COLUMNS=str(COLUMNS),
            LINES=str(ROWS),
            NXSHELL_PYTHON=sys.executable,
        )
        env.pop("NO_COLOR", None)
        pid, fd = pty.fork()
        if pid == 0:
            os.chdir(folder)
            os.execvpe("./nxdemo", ["./nxdemo"], env)
        size = struct.pack("HHHH", ROWS, COLUMNS, 0, 0)
        fcntl.ioctl(fd, termios.TIOCSWINSZ, size)
        out = _read_for(fd, START_WAIT)
        for command, wait in steps:
            os.write(fd, (command + "\r").encode())
            out += _read_for(fd, wait)
        os.write(fd, b"q\r")
        # until the prices process has ended too
        _read_for(fd, 3)
        os.waitpid(pid, 0)
    return out.decode(errors="replace")


def _clean(text, drop_banner):
    """the output without the terminal's line ends and
    the cursor and readline codes; the colors stay"""
    text = text.replace("\r\n", "\n").replace("\r", "")
    text = re.sub(r"\x1b\[\?[0-9;]*[a-zA-Z]", "", text)
    text = re.sub(r"\x1b\[[0-9;]*[A-LN-Za-ln-z]", "", text)
    text = re.sub(r"[\x01\x02]", "", text)
    if drop_banner:
        text = text[text.find(PROMPT) :]
    # the q typed at the last prompt
    lines = text.rstrip().split("\n")
    if lines[-1].endswith(" q"):
        lines[-1] = lines[-1][: -len(" q")]
    return "\n".join(lines).strip("\n") + "\n"


def save_svg(text, path, title):
    console = Console(
        record=True,
        width=COLUMNS,
        file=io.StringIO(),
        force_terminal=True,
        color_system="truecolor",
    )
    console.print(Text.from_ansi(text), end="")
    console.save_svg(path, title=title)


def _main(names):
    unknown = [n for n in names if n not in SHOTS]
    if unknown:
        print(
            f"unknown: {', '.join(unknown)}, expected "
            + ", ".join(SHOTS)
        )
        return 1
    for name in names or SHOTS:
        title, drop_banner, steps = SHOTS[name]
        text = _clean(run_demo(steps), drop_banner)
        path = os.path.join(
            ROOT_DIR, "assets", f"demo-{name}.svg"
        )
        save_svg(text, path, title)
        print("wrote", os.path.relpath(path, ROOT_DIR))
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
