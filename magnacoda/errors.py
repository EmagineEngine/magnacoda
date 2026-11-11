"""What happens when something goes wrong that magnacoda didn't expect.

By default a person sees one short message, not a traceback; the details are saved (errors.log, in
magnacoda's folder) and `errors` shows them, to look into or to report. With `show_errors = on` in
preferences.ini, or MAGNACODA_DEBUG set, the traceback is printed as it happens too. Errors in
background threads and ones nothing else caught come here too (install). Never raises.
"""

from __future__ import annotations

import os
import platform
import re
import sys
import threading
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import TextIO

from magnacoda import __version__, preferences
from magnacoda.userdir import config_dir, write_private

KEEP = 10  # the log keeps this many errors, the newest
REPORT_AT = "magnacoda.dev/contact"
_START = "=== "
_HEADER = re.compile(r"^=== (?P<when>\S+ \S+) \| (?P<system>.*) ===$")

in_shell = False  # set by the shell: what to type to see the details


@dataclass(frozen=True)
class Entry:
    when: str
    system: str
    command: str
    details: str


def log_path() -> Path:
    return config_dir() / "errors.log"


def showing() -> bool:
    """Whether to print the traceback as it happens: `show_errors = on`, or MAGNACODA_DEBUG set."""
    if os.environ.get("MAGNACODA_DEBUG", "").strip().lower() not in ("", "0", "off", "false", "no"):
        return True
    try:
        return preferences.load().show_errors
    except Exception:  # noqa: BLE001 - never fail while handling a failure
        return False


def message() -> str:
    word = "errors" if in_shell else "magnacoda errors"
    return (
        f"Something went wrong. Please report it at {REPORT_AT} and say what you were doing. "
        f"Type {word} to see the details."
    )


def _tidy(text: str) -> str:
    """The traceback without the user's home folder (it holds their name)."""
    home = str(Path.home())
    return text.replace(home, "~") if home and home != "/" else text


def record(
    exc: BaseException, command: str = "", tb: TracebackType | None = None
) -> None:  # pragma: no branch - best effort
    """Save an error to the log (the newest KEEP are kept). `command` is what was typed, already
    without cookie or header values. Never raises."""
    try:
        details = "".join(
            traceback.format_exception(type(exc), exc, tb if tb is not None else exc.__traceback__)
        )
        system = f"magnacoda {__version__}, Python {platform.python_version()}, {platform.platform()}"
        header = f"{_START}{datetime.now():%Y-%m-%d %H:%M} | {system} ==="
        block = f"{header}\ncommand: {command}\n{_tidy(details).rstrip()}\n"
        kept = [_block(entry) for entry in read()][: KEEP - 1]
        write_private(log_path(), "".join([block, *kept]))
    except Exception:  # noqa: BLE001 - a log that can't be written must not hide the real problem
        pass


def _block(entry: Entry) -> str:
    return f"{_START}{entry.when} | {entry.system} ===\ncommand: {entry.command}\n{entry.details}\n"


def read() -> list[Entry]:
    """The saved errors, newest first. Empty if there are none or the log can't be read."""
    try:
        text = log_path().read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return []
    entries: list[Entry] = []
    for chunk in re.split(rf"(?m)^(?={re.escape(_START)})", text):
        lines = chunk.rstrip("\n").split("\n")
        header = _HEADER.match(lines[0]) if lines and lines[0] else None
        if header is None:
            continue
        command = lines[1].removeprefix("command: ") if len(lines) > 1 else ""
        entries.append(Entry(header["when"], header["system"], command, "\n".join(lines[2:]).rstrip()))
    return entries


def report(exc: BaseException, command: str = "", out: TextIO | None = None) -> None:
    """Handle an unexpected error: save it, then say so in one line (and show the traceback too when
    errors are shown). `out` is where to write, stderr by default."""
    record(exc, command)
    stream = out if out is not None else sys.stderr
    try:
        if showing():
            traceback.print_exception(type(exc), exc, exc.__traceback__, file=stream)
        print(message(), file=stream)
    except Exception:  # noqa: BLE001 - nothing more to do if even the message can't be written
        pass


def text() -> str:
    """What `errors` shows: the latest error with its details, and how many older ones are saved."""
    entries = read()
    if not entries:
        return "No errors are saved: nothing unexpected has gone wrong."
    latest = entries[0]
    older = len(entries) - 1
    more = (
        f"\n\n{older} older error{'s are' if older != 1 else ' is'} saved in {_tidy(str(log_path()))}."
        if older
        else ""
    )
    return (
        f"The last error, {latest.when}\nFrom: {latest.command or '(not a typed command)'}\n"
        f"{latest.system}\n\n{latest.details}\n\n"
        f"If it looks like a bug, please report it at {REPORT_AT}, say what you were doing, and "
        f"include the details above.{more}"
    )


def install() -> None:
    """Make errors that nothing catches, in the main program or in a thread, end up in report()."""
    previous = sys.excepthook
    previous_thread = threading.excepthook

    def uncaught(kind: type[BaseException], exc: BaseException, tb: TracebackType | None) -> None:
        if issubclass(kind, (KeyboardInterrupt, SystemExit)):
            previous(kind, exc, tb)
            return
        exc.__traceback__ = tb
        report(exc)

    def in_thread(args: threading.ExceptHookArgs) -> None:
        if args.exc_value is None or issubclass(args.exc_type, SystemExit):
            previous_thread(args)
            return
        args.exc_value.__traceback__ = args.exc_traceback
        report(args.exc_value)

    sys.excepthook = uncaught
    threading.excepthook = in_thread
