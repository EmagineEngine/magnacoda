"""A command reference for the pager, laid out like a man page: a program's help, its news.

The text is ordinary Markdown, of which only a few forms are understood:

- `## name` starts a section; the name is short and isn't shown above it (`sections`).
- `### Label` is shown as a plain line.
- A list item that starts with a term in backticks (or several, `a`, `b`) is a command or option.
  The term gets a line of its own, never wrapped, and the text indented under it is its
  description. Text after the term on the same line is shown beside it instead, lined up with the
  other items in that list.
- HTML comments are notes to editors and never shown. *Italic* and **bold** are left for the pager
  to style (emphasis.py).

Standard library only.
"""

from __future__ import annotations

import re
import textwrap

_SECTION_HEADER = re.compile(r"^##\s+([A-Za-z][\w -]*?)\s*$")
_LABEL = re.compile(r"^###\s+(.*?)\s*#*\s*$")
_TERM = re.compile(r"^[-*]\s+(`[^`]+`(?:,\s*`[^`]+`)*)\s*(.*)$")  # one term, or several: `a`, `b`
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_TERM_INDENT = "  "  # a term line: never wrapped
_DESCRIPTION_INDENT = "      "
_BESIDE_GAP = 3  # spaces between the longest term and a description written beside it
_LEAD = re.compile(r"^(\s*)(\d+\.\s+|[-*]\s+)?")


def sections(text: str) -> dict[str, str]:
    """{name: text} for each `## name` section, in order, names in lower case; anything above the
    first section (such as a title) and HTML comments dropped."""
    found: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in _COMMENT.sub("", text).splitlines():
        header = _SECTION_HEADER.match(line)
        if header:
            current = found.setdefault(header.group(1).lower(), [])
        elif current is not None:
            current.append(line.rstrip())
    return {name: "\n".join(lines) for name, lines in found.items()}


def layout(text: str) -> str:
    """The text as terminal lines, before wrapping: labels, then term lists like man pages."""
    out: list[str] = []
    beside: list[tuple[int, str, str]] = []  # (index in out, term, text) for the current list

    def line_up() -> None:
        if beside:
            width = max(len(term) for _, term, _ in beside) + _BESIDE_GAP
            for index, term, text in beside:
                out[index] = _TERM_INDENT + term.ljust(width) + text
            beside.clear()

    in_item = False
    for line in _COMMENT.sub("", text).splitlines():
        if not line.strip():
            in_item = False
            out.append("")
            continue
        term = _TERM.match(line)
        if term:
            while out and not out[-1]:
                out.pop()
            name = term.group(1).replace("`", "")
            if term.group(2):
                beside.append((len(out), name, term.group(2)))
            out.append(_TERM_INDENT + name)
            in_item = True
            continue
        if in_item and line[:1].isspace():
            out.append(_DESCRIPTION_INDENT + line.strip())
            continue
        line_up()
        in_item = False
        label = _LABEL.match(line)
        out.append(label.group(1) if label else line.strip())
    line_up()
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip("\n")


def _wrap(text: str, width: int) -> list[str]:
    """Word-wrap laid-out text without breaking words, keeping indents and hanging indents; term
    lines are left whole."""
    out: list[str] = []
    for line in text.split("\n"):
        match = _LEAD.match(line)
        assert match is not None  # every group in _LEAD is optional, so it always matches
        indent, marker = match.group(1), match.group(2) or ""
        body = line[match.end() :]
        if not body.strip() or (indent == _TERM_INDENT and not marker):
            out.append(line)
            continue
        out.extend(
            textwrap.wrap(
                body,
                width=max(width, 20),
                initial_indent=indent + marker,
                subsequent_indent=indent + " " * len(marker),
                break_long_words=False,
                break_on_hyphens=False,
            )
        )
    return out


def render(text: str, width: int) -> list[str]:
    """One section as screen lines `width` wide."""
    return _wrap(layout(text), width)
