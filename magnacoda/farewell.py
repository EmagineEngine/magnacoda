"""The shell's goodbye line (from data/goodbyes.md), and an occasional feedback request.

The request needs both FEEDBACK_GOODBYES goodbyes and FEEDBACK_DAYS days since the last one (or since the
first goodbye), so daily users see it about weekly and weekly users far less.
"""

from __future__ import annotations

import json
import re
from datetime import date
from importlib import resources
from pathlib import Path

from rich.markup import escape

from magnacoda import plugins
from magnacoda.userdir import config_dir, write_private

FEEDBACK_URL = "https://magnacoda.dev/feedback"
FEEDBACK_GOODBYES = 7
FEEDBACK_DAYS = 7


def state_path() -> Path:
    return config_dir() / "farewell-state.json"


_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_ITEM = re.compile(r"^[-*]\s+(\S.*?)\s*$")  # an item with real text; blank lines never count
_FALLBACK = "Well done checking accessibility with {name}."


def goodbyes() -> list[str]:
    """The goodbye lines, in order, from data/goodbyes.md (the first one alone if it can't be read)."""
    try:
        text = (resources.files("magnacoda") / "data" / "goodbyes.md").read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return [_FALLBACK]
    found = [item.group(1) for line in _COMMENT.sub("", text).splitlines() if (item := _ITEM.match(line))]
    return found or [_FALLBACK]


def _next_line() -> int:
    try:
        value = json.loads(state_path().read_text(encoding="utf-8")).get("line", 0)
    except (OSError, ValueError, AttributeError):
        return 0
    return value if isinstance(value, int) and value >= 0 else 0


def _read_state() -> tuple[date, int] | None:
    """(the day counting started, goodbyes since then), or None if there is no usable state."""
    try:
        data = json.loads(state_path().read_text(encoding="utf-8"))
        since, goodbyes = date.fromisoformat(data["since"]), data["goodbyes"]
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None
    return (since, goodbyes) if isinstance(goodbyes, int) and goodbyes >= 0 else None


def lines(today: date | None = None) -> list[str]:
    """The goodbye lines. Bad state resets the count, so problems never mean more requests."""
    today = today or date.today()
    name = f"[italic]{escape(plugins.edition().display_name)}[/italic]"
    said = goodbyes()
    index = _next_line() % len(said)
    out = [escape(said[index]).replace("{name}", name)]
    state = _read_state()
    since, count = (today, 1) if state is None else (state[0], state[1] + 1)
    if state is not None and count >= FEEDBACK_GOODBYES and (today - since).days >= FEEDBACK_DAYS:
        out.append(f"Feedback or suggestions: {FEEDBACK_URL}")
        since, count = today, 0
    try:
        saved = {"since": since.isoformat(), "goodbyes": count, "line": (index + 1) % len(said)}
        write_private(state_path(), json.dumps(saved) + "\n")
    except OSError:
        pass
    return out
