"""*Italic* and **bold** in text that isn't laid out as Markdown (help, news), for the pager.

The emphasis is marked before the text is wrapped, with one private character at each end, and
turned into the terminal's styles after, so a phrase that wraps onto the next line stays styled.
Printed instead of paged, the asterisks are just left out. Standard library only.
"""

from __future__ import annotations

import re

_EMPHASIS = re.compile(r"(\*\*|\*)(?=\S)(.+?)(?<=\S)\1")
_BOLD_ON, _BOLD_OFF, _ITALIC_ON, _ITALIC_OFF = "", "", "", ""
_CODES = {_BOLD_ON: "\x1b[1m", _BOLD_OFF: "\x1b[22m", _ITALIC_ON: "\x1b[3m", _ITALIC_OFF: "\x1b[23m"}


def plain(text: str) -> str:
    """The text without its emphasis markers."""
    return _EMPHASIS.sub(r"\2", text)


def mark(text: str) -> str:
    """The text with each *italic* and **bold** marked for style(), ready to be wrapped."""

    def marked(match: re.Match[str]) -> str:
        on, off = (_BOLD_ON, _BOLD_OFF) if match.group(1) == "**" else (_ITALIC_ON, _ITALIC_OFF)
        return on + match.group(2) + off

    return _EMPHASIS.sub(marked, text)


def style(lines: list[str]) -> list[str]:
    """Wrapped lines with their marks turned into styles. A style still on at the end of a line is
    turned off there and on again at the start of the next, so nothing spills over the screen."""
    bold = italic = False
    out = []
    for line in lines:
        styled = ("\x1b[1m" if bold else "") + ("\x1b[3m" if italic else "")
        for char in line:
            if char in (_BOLD_ON, _BOLD_OFF):
                bold = char == _BOLD_ON
            elif char in (_ITALIC_ON, _ITALIC_OFF):
                italic = char == _ITALIC_ON
            styled += _CODES.get(char, char)
        out.append(styled + ("\x1b[22;23m" if bold or italic else ""))
    return out
