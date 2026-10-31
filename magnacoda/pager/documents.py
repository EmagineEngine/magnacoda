"""The documents the Open list (o) offers, read from a list file in Markdown:

    ## Using myapp
    - [Manual](docs/manual.md) (also: docs)
    - [What's changed](CHANGELOG.md)

    ## Legal
    - [License](LICENSE.md)

Each `##` heading starts a group and each linked item is a document, its path relative to the list
file. "(also: ...)" gives more names it can be typed as. A document whose file is missing is left out.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

from magnacoda.pager.screen import Entry, Opening, index_of

__all__ = ["Entry", "Opening", "index_of", "read_list"]

_GROUP = re.compile(r"##\s+(.+?)\s*#*\s*$")
_ITEM = re.compile(r"[-*+]\s+\[([^\]]+)\]\(([^)\s]+)\)\s*(?:\(also:\s*([^)]*)\))?\s*$")


def read_list(path: Path, locate: Callable[[str], Path | None] | None = None) -> list[Entry]:
    """The documents in the list file at `path`; none if it can't be read. `locate` finds a link's
    file, where a program keeps its documents elsewhere; by default, beside the list file."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return []

    def beside(link: str) -> Path | None:
        return path.parent / link

    find = locate or beside
    entries, group = [], ""
    for line in text.splitlines():
        line = line.strip()
        if heading := _GROUP.fullmatch(line):
            group = heading.group(1)
            continue
        item = _ITEM.fullmatch(line)
        if not item:
            continue
        found = find(item.group(2))
        if found is None or not found.is_file():
            continue
        names = tuple(name.strip() for name in (item.group(3) or "").split(",") if name.strip())
        entries.append(Entry(item.group(1).strip(), found, group, names))
    return entries
