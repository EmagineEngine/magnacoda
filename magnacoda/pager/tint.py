"""Code on a background of its own instead of between backticks: mark() finds it, and the screen
drops the marked backticks and draws the code on code's background (screen._paint_code). Where
there's no background to use, the backticks stay. Standard library only.
"""

from __future__ import annotations

import re

ON, OFF = "\x1b[12m", "\x1b[13m"  # replaced or dropped before drawing
_CODE_MARK = "\x1b[10m"  # starts a line of a code block (see links.CODE_MARK)
_ESCAPE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")


def _ticks(line: str) -> list[int]:
    """The backticks' positions, codes skipped."""
    found, position = [], 0
    for match in _ESCAPE.finditer(line + "\x1b[m"):
        found += [position + n for n, char in enumerate(line[position : match.start()]) if char == "`"]
        position = match.end()
    return found


def mark(lines: list[str]) -> list[str]:
    """Each pair of backticks in a paragraph marked as code; a lone backtick is just a backtick."""
    out = list(lines)
    paragraph: list[int] = []

    def close_paragraph() -> None:
        ticks = [(number, at) for number in paragraph for at in _ticks(lines[number])]
        pairs = ticks[: len(ticks) - len(ticks) % 2]
        opened: dict[int, list[tuple[int, str]]] = {}  # line: (position, mark)
        for (first, start), (last, end) in zip(pairs[::2], pairs[1::2], strict=True):
            opened.setdefault(first, []).append((start, ON))
            opened.setdefault(last, []).append((end + 1, OFF))
            for number in range(first, last):
                opened[number].append((len(lines[number]), OFF))
                opened.setdefault(number + 1, []).append((0, ON))
        for number, marks in opened.items():
            line = out[number]
            for position, code in sorted(marks, key=lambda m: m[0], reverse=True):
                line = line[:position] + code + line[position:]
            out[number] = line
        paragraph.clear()

    for number, line in enumerate(lines):
        if not _ESCAPE.sub("", line).strip() or line.startswith(_CODE_MARK):
            close_paragraph()
        else:
            paragraph.append(number)
    close_paragraph()
    return out
