"""One tip each time `menu` shows the commands, in turn from data/tips.md; the position is kept in
tips-state.json."""

from __future__ import annotations

import json
import re
from importlib import resources
from pathlib import Path

from rich.markup import escape

from magnacoda.userdir import config_dir, write_private

_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_ITEM = re.compile(r"^[-*]\s+(\S.*?)\s*$")  # an item with real text; blank lines never count
_EMPHASIS = re.compile(r"(\*\*|\*)(?=\S)(.+?)(?<=\S)\1")
_CODE = re.compile(r"`([^`]+)`")


def state_path() -> Path:
    return config_dir() / "tips-state.json"


def tips_text() -> str:
    return (resources.files("magnacoda") / "data" / "tips.md").read_text(encoding="utf-8")


def load(text: str | None = None) -> list[str]:
    """Every tip, in order, as plain text."""
    text = _COMMENT.sub("", tips_text() if text is None else text)
    return [_EMPHASIS.sub(r"\2", item.group(1)) for line in text.splitlines() if (item := _ITEM.match(line))]


def _next_index() -> int:
    try:
        value = json.loads(state_path().read_text(encoding="utf-8")).get("next", 0)
    except (OSError, ValueError, AttributeError):
        return 0
    return value if isinstance(value, int) and value >= 0 else 0


def next_tip() -> str | None:
    """The tip to show now, moving on to the next one for next time. None if there are no tips."""
    try:
        tips = load()
    except (OSError, UnicodeError):
        return None
    if not tips:
        return None
    index = _next_index() % len(tips)
    try:
        write_private(state_path(), json.dumps({"next": (index + 1) % len(tips)}) + "\n")
    except OSError:
        pass
    return tips[index]


def markup(tip: str) -> str:
    """The tip as Rich markup: `code` in bold, without its backticks."""
    return _CODE.sub(r"[bold]\1[/bold]", escape(tip))
