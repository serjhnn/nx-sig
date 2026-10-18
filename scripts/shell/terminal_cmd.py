# terminal_cmd: the terminal the shell runs in
#
#   terminal info
#   terminal set width <auto|number|default>
#   terminal set theme <colored|plain|default>
#
# 'set' saves NX_WIDTH / NX_THEME in .env, so it is for
# this device only and applies right away; 'default'
# removes the line, so config.json "width" / "theme"
# (or the default) applies again.
#
# TerminalCmd is mixed into NxSigShell: a command of its
# own, not a kind of data

import importlib.util
import os
import platform
import subprocess
import sys
import textwrap

from dotenv import dotenv_values, set_key, unset_key

import tasks_owner
from storage import ROOT_DIR
from shell.ui import (
    MIN_WIDTH,
    THEMES,
    color_off_reason,
    complete_options,
    print_error,
    print_wrapped,
    theme,
    theme_setting,
    width,
    width_setting,
)

ENV_PATH = os.path.join(ROOT_DIR, ".env")
USAGE = (
    "usage: terminal info, or terminal set "
    "width|theme <value>, see 'help terminal'"
)
# the label column of 'terminal info'
LABEL = 12
# where Linux says what the computer is
DMI_DIR = "/sys/devices/virtual/dmi/id"


class TerminalCmd:
    def do_terminal(self, arg):
        """
        terminal info
        terminal set width <auto|number|default>
        terminal set theme <colored|plain|default>
            info: the terminal's size, the width
            and theme in use and where they come
            from, the phone or computer model;
            set: save the width (auto or 48 or
            more) or the theme for this device in
            .env, default goes back to config.json
        """
        args = arg.lower().split()
        if args == ["info"]:
            _print_info()
            return
        if len(args) == 3 and args[0] == "set":
            if args[1] == "width":
                self._set_width(args[2])
                return
            if args[1] == "theme":
                self._set_theme(args[2])
                return
        print_wrapped(USAGE)

    def complete_terminal(self, text, line, begidx, endidx):
        args = line.split()
        options = [["info", "set"], ["width", "theme"]]
        if len(args) > 2 and args[1] == "set":
            values = {
                "width": ["auto", "default"],
                "theme": [*THEMES, "default"],
            }
            options.append(values.get(args[2], []))
        return complete_options(text, line, options)

    def _set_width(self, value):
        if value not in ("auto", "default"):
            if not value.isdigit():
                print_wrapped(USAGE)
                return
            if int(value) < MIN_WIDTH:
                print_error(
                    f"error: the narrowest width is "
                    f"{MIN_WIDTH}, the tables don't fit "
                    "in less"
                )
                return
        if not _save("NX_WIDTH", value):
            return
        print_wrapped(f"width: {_describe_width()}")

    def _set_theme(self, value):
        if value not in (*THEMES, "default"):
            print_wrapped(USAGE)
            return
        if not _save("NX_THEME", value):
            return
        # the prompt was made in the old theme
        self.set_prompt()
        print_wrapped(f"theme: {_describe_theme()}")


def _save(name, value):
    """write name=value to .env, or remove it for
    default, and use it right away; False after printing
    why it couldn't be saved"""
    try:
        if value == "default":
            if name in dotenv_values(ENV_PATH):
                unset_key(
                    ENV_PATH, name, quote_mode="never"
                )
        else:
            set_key(
                ENV_PATH, name, value, quote_mode="never"
            )
    except OSError as e:
        print_error(f"error: can't write .env: {e}")
        return False
    if value == "default":
        os.environ.pop(name, None)
    else:
        os.environ[name] = value
    return True


def _describe_width():
    """'52, auto (NX_WIDTH in .env)'"""
    setting, source = width_setting()
    used = width()
    setting = str(setting).strip().lower()
    if setting == "auto":
        return f"{used}, auto ({source})"
    if setting != str(used):
        return f"{used}, not {setting} ({source})"
    return f"{used} ({source})"


def _describe_theme():
    """'plain (NX_THEME in .env)', and why there are no
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
    """the phone's maker and model in Termux, the
    computer's on Linux, or '-'"""
    if os.environ.get("TERMUX_VERSION"):
        maker = _getprop("ro.product.manufacturer")
        model = _getprop("ro.product.model")
    else:
        maker = _dmi("sys_vendor")
        model = _dmi("product_name")
    # some makers repeat their name in the model
    if maker.lower() in model.lower():
        maker = ""
    return " ".join(filter(None, [maker, model])) or "-"


def _getprop(name):
    try:
        result = subprocess.run(
            ["getprop", name],
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
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
