"""favorites.md: saved scan commands, one `##` heading (the name) and one command in a code block each."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from magnacoda.savedcommand import SavedScan, canonical
from magnacoda.userdir import config_dir, write_private

HEADER = """# magnacoda favorites

Each favorite is a `##` heading (its name) followed by one command in a code block. Edit this file freely: the wizard reads it when it starts and offers these as starting points. Notes written under a command are kept. The text above the first favorite is rewritten whenever the wizard saves one. How many favorites are kept is set in preferences.ini.
"""  # noqa: E501

_HEADING = re.compile(r"(?m)^##[ \t]+")


@dataclass
class Favorite:
    name: str
    command: str
    notes: str = ""


def favorites_path() -> Path:
    return config_dir() / "favorites.md"


def parse(text: str) -> tuple[list[Favorite], list[str]]:
    """(favorites, problems). An entry without a readable command is skipped and reported."""
    favorites: list[Favorite] = []
    problems: list[str] = []
    for section in _HEADING.split(text)[1:]:
        lines = section.splitlines()
        name = lines[0].strip() if lines else ""
        command_lines: list[str] = []
        after: list[str] = []
        state = "before"  # before the code block, inside it, after it
        for line in lines[1:]:
            if line.strip().startswith("```"):
                state = "inside" if state == "before" else "after"
            elif state == "inside":
                if line.strip():
                    command_lines.append(line.strip())
            elif state == "after":
                after.append(line)
        command = " ".join(command_lines)
        if not name or not command:
            problems.append(f"Skipped a favorite ({name or 'no name'}): no command found in a code block.")
            continue
        favorites.append(Favorite(name, command, "\n".join(after).strip()))
    return favorites, problems


def render(favorites: list[Favorite]) -> str:
    parts = [HEADER]
    for favorite in favorites:
        parts.append(f"\n## {favorite.name}\n\n```\n{favorite.command}\n```\n")
        if favorite.notes:
            parts.append(f"\n{favorite.notes}\n")
    return "".join(parts)


def load() -> tuple[list[Favorite], list[str]]:
    path = favorites_path()
    try:
        if not path.exists():
            return [], []
        return parse(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError):
        return [], ["Could not read favorites.md."]


def save_all(favorites: list[Favorite]) -> None:
    write_private(favorites_path(), render(favorites))


def ensure_file() -> None:
    """Create favorites.md (header only) if it does not exist. Never raises."""
    try:
        if not favorites_path().exists():
            write_private(favorites_path(), HEADER)
    except OSError:
        pass


def find_by_name(favorites: list[Favorite], name: str) -> int | None:
    for index, favorite in enumerate(favorites):
        if favorite.name.casefold() == name.casefold():
            return index
    return None


def find_by_command(favorites: list[Favorite], command: str) -> int | None:
    wanted = canonical(command)
    for index, favorite in enumerate(favorites):
        if canonical(favorite.command) == wanted:
            return index
    return None


MIN_NAME_LENGTH = 3  # so a name is never a single key, such as q (which cancels at any question)


def sanitize_name(text: str) -> str:
    """A favorite's name: one line, no leading `#` (it is a Markdown heading), a sensible length."""
    cleaned = " ".join(text.replace("`", "'").split()).lstrip("# ").strip()
    return cleaned[:80] or "Untitled"


def default_name(scan: SavedScan) -> str:
    host = urlparse(scan.url).netloc or scan.url
    parts = [p for p in (scan.color_scheme, scan.screen) if p != "system"]
    if scan.ai != "off":
        parts.append(f"AI {scan.ai}")
    return sanitize_name(host + (f" ({', '.join(parts)})" if parts else ""))
