"""history.md: the most recent scans, newest first, capped at the number in preferences.ini."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from magnacoda import preferences
from magnacoda.userdir import config_dir, write_private

HEADER = """# magnacoda history

The most recent scans, newest first. Cookie and header values are never stored. Each line is a command you can paste into the interactive shell, or run from a terminal by putting the program name (magnacoda) in front. How many scans are kept is set in preferences.ini (0 turns history off).

"""  # noqa: E501

_LINE = re.compile(r"^- (\d{4}-\d{2}-\d{2} \d{2}:\d{2}) `(.*)`\s*$")


@dataclass
class Entry:
    when: str
    command: str


def history_path() -> Path:
    return config_dir() / "history.md"


def read() -> list[Entry]:
    try:
        text = history_path().read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return []
    entries = []
    for line in text.splitlines():
        match = _LINE.match(line)
        if match:
            entries.append(Entry(match.group(1), match.group(2)))
    return entries


def _render(entries: list[Entry]) -> str:
    return HEADER + "".join(f"- {entry.when} `{entry.command}`\n" for entry in entries)


def record(command: str, now: datetime | None = None) -> None:
    """Prepend a scan and trim to the cap. Never raises (a read-only home must not stop a scan)."""
    try:
        limit = preferences.load().history_max
        if limit <= 0:
            return
        entry = Entry((now or datetime.now()).strftime("%Y-%m-%d %H:%M"), command)
        write_private(history_path(), _render(([entry] + read())[:limit]))
    except (OSError, ValueError, UnicodeError):
        pass


def recent(count: int) -> list[Entry]:
    return read()[:count]


def ensure_file() -> None:
    """Create history.md (header only) if it does not exist and history is on. Never raises."""
    try:
        if preferences.load().history_max > 0 and not history_path().exists():
            write_private(history_path(), _render([]))
    except OSError:
        pass
