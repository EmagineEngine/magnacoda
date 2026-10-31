"""On-screen wording, read from messages.md (one "## name" per message; see the notes in that file)."""

from __future__ import annotations

import re
from importlib import resources

_PACKAGE = __name__.rpartition(".")[0]  # this add-on's folder, wherever it is copied to
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_NAME = re.compile(r"^##[ \t]+([a-z][a-z0-9-]*)[ \t]*$")


def load() -> dict[str, str]:
    """{name: message}, read fresh each time so an edited messages.md shows at once."""
    text = (resources.files(_PACKAGE) / "messages.md").read_text(encoding="utf-8")
    messages: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in _COMMENT.sub("", text).splitlines():
        name = _NAME.match(line)
        if name:
            current = messages.setdefault(name.group(1), [])
        elif current is not None:
            current.append(line.rstrip())
    return {name: "\n".join(lines).strip("\n") for name, lines in messages.items()}


def text(key: str, /, **values: object) -> str:
    """Message `key` with its placeholders filled (positional-only, so {key} can be a placeholder)."""
    return load()[key].format(**values)
