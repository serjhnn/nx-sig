# terminal_cmd: the terminal the shell runs in
#
#   terminal info
#
# the width and theme are config.json "width" and
# "theme"
#
# TerminalCmd is mixed into NxSigShell: a command of its
# own, not a kind of data

import importlib.util
import os
import platform
import subprocess
import sys
import textwrap

import tasks_owner
from shell.ui import (
    color_off_reason,
    complete_options,
    print_wrapped,
    theme,
    theme_setting,
    width,
    width_setting,
)

USAGE = "usage: terminal info, see 'help terminal'"
# the label column of 'terminal info'
LABEL = 12
# where Linux says what the computer is
DMI_DIR = "/sys/devices/virtual/dmi/id"


class TerminalCmd:
    def do_terminal(self, arg):
        """
        terminal info
            the terminal's size, the width and
            theme in use and where they come from,
            the phone or computer model; the width
            and theme are config.json "width" and
            "theme"
        """
        if arg.lower().split() == ["info"]:
            _print_info()
            return
        print_wrapped(USAGE)

    def complete_terminal(self, text, line, begidx, endidx):
        return complete_options(text, line, [["info"]])


def _describe_width():
    """'52, auto (config.json)'"""
    setting, source = width_setting()
    used = width()
    setting = str(setting).strip().lower()
    if setting == "auto":
        return f"{used}, auto ({source})"
    if setting != str(used):
        return f"{used}, not {setting} ({source})"
    return f"{used} ({source})"


def _describe_theme():
    """'plain (config.json)', and why there are no
    colors when the theme is colored"""
    _, source = theme_setting()
    line = f"{theme()} ({source})"
    reason = color_off_reason()
    if theme() == "colored" and reason:
        line += f", no colors now: {reason}"
    return line


def _size():
    """'52 x 38 (columns x rows)', or why there is no
    size"""
    try:
        size = os.get_terminal_size(sys.stdout.fileno())
    except (OSError, ValueError):
        return "- (the output is not a terminal)"
    return f"{size.columns} x {size.lines} (columns x rows)"


def _terminal_name():
    if os.environ.get("TERMUX_VERSION"):
        return f"Termux {os.environ['TERMUX_VERSION']}"
    name = os.environ.get("TERM_PROGRAM")
    if name:
        version = os.environ.get("TERM_PROGRAM_VERSION")
        return f"{name} {version}" if version else name
    return "-"


def _model():
    """the phone's name (Settings, About phone) and
    model, or its maker and model in Termux, the
    computer's maker and model on Linux, or '-'"""
    if os.environ.get("TERMUX_VERSION"):
        name = _device_name()
        maker = _getprop("ro.product.manufacturer")
        model = _getprop("ro.product.model")
        if name and model and model not in name:
            # 'Galaxy S23 Ultra (SM-S918B)'
            return f"{name} ({model})"
        if name:
            return name
    else:
        maker = _dmi("sys_vendor")
        model = _dmi("product_name")
    # some makers repeat their name in the model
    if maker.lower() in model.lower():
        maker = ""
    return " ".join(filter(None, [maker, model])) or "-"


def _device_name():
    """'Galaxy S23 Ultra', or '' where Android doesn't
    let Termux read it"""
    name = _output(
        ["settings", "get", "global", "device_name"]
    )
    return "" if name == "null" else name


def _getprop(name):
    return _output(["getprop", name])


def _output(args):
    """the command's output, or '' when it fails"""
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if result.returncode:
        return ""
    return result.stdout.strip()


def _dmi(name):
    try:
        with open(os.path.join(DMI_DIR, name)) as f:
            return f.read().strip()
    except OSError:
        return ""


def _colors():
    """how many colors the terminal says it shows"""
    term = os.environ.get("TERM", "")
    colorterm = os.environ.get("COLORTERM", "").lower()
    if colorterm in ("truecolor", "24bit"):
        count = "24-bit"
    elif "256color" in term:
        count = "256"
    elif term in ("", "dumb"):
        count = "none"
    else:
        count = "basic"
    return f"{count} (TERM {term or '-'})"


def _completion():
    if importlib.util.find_spec("readline") is None:
        return "off, no readline"
    return "on (Tab)"


def _info_rows():
    """(label, value) of 'terminal info'"""
    return [
        ("terminal", _terminal_name()),
        ("size", _size()),
        ("width", _describe_width()),
        ("theme", _describe_theme()),
        ("colors", _colors()),
        ("encoding", sys.stdout.encoding or "-"),
        ("completion", _completion()),
        ("python", platform.python_version()),
        ("device", tasks_owner.this_device()["name"]),
        ("model", _model()),
    ]


def _print_info():
    print()
    for label, value in _info_rows():
        # a long value wraps under the value column
        lines = _wrap_value(value, width() - LABEL)
        print_wrapped(f"{label + ':':<{LABEL}}{lines[0]}")
        for line in lines[1:]:
            print_wrapped(" " * LABEL + line)
    print()


def _wrap_value(value, room):
    return textwrap.wrap(
        value, room, break_on_hyphens=False
    ) or ["-"]
