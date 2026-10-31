from __future__ import annotations

import re
import shutil
import textwrap
from typing import IO

_LEAD = re.compile(r"^(\s*)(\d+\.\s+|[-*]\s+)?")
# Indented command lines are meant to be copied; a line break we insert would corrupt them, whereas
# the terminal's own soft wrap does not.
_COMMAND_PREFIXES = ("export ", "magnacoda ", "$ ")


def wrap_text(text: str, width: int) -> str:
    """Word-wrap to `width` without breaking words, keeping indents and list hanging indents.

    Command lines are left alone.
    """
    out: list[str] = []
    for line in text.split("\n"):
        match = _LEAD.match(line)
        assert match is not None  # every group in _LEAD is optional, so it always matches
        indent, marker = match.group(1), match.group(2) or ""
        body = line[match.end() :]
        if not body.strip() or (indent and body.startswith(_COMMAND_PREFIXES)):
            out.append(line)
            continue
        out.append(
            textwrap.fill(
                body,
                width=max(width, 20),
                initial_indent=indent + marker,
                subsequent_indent=indent + " " * len(marker),
                break_long_words=False,
                break_on_hyphens=False,
            )
        )
    return "\n".join(out)


def wrap_for_stream(text: str, stream: IO[str]) -> str:
    """Wrap to the terminal width, but leave piped output alone."""
    try:
        if not stream.isatty():
            return text
    except (AttributeError, ValueError):
        return text
    return wrap_text(text, shutil.get_terminal_size((80, 24)).columns - 1)
