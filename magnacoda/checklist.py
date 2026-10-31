"""Checklist progress for the pager: an overall count, per-section counts in the g list, and [✓] for ticks.

Read-only; the file is never changed. [✓] stands out more than [x], and screen readers say "check mark".
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_BOX = re.compile(r"^(\s*[-*+]\s+)\[([ xX])\]", re.MULTILINE)
CHECKED_MARK = "[✓]"


@dataclass(frozen=True)
class Progress:
    checked: int
    total: int

    def __str__(self) -> str:
        return f"{self.checked} of {self.total} checked"


def progress(text: str) -> Progress:
    boxes = [match.group(2) for match in _BOX.finditer(text)]
    return Progress(sum(1 for box in boxes if box in "xX"), len(boxes))


def _section_name(name: str, done: Progress) -> str:
    if done.checked == 0:
        return name
    if done.checked == done.total:
        return f"{name} - all {done.total} checked"
    return f"{name} - {done.checked} checked"


def _with_marks(text: str) -> str:
    return _BOX.sub(lambda m: m.group(1) + (CHECKED_MARK if m.group(2) in "xX" else "[ ]"), text)


def prepare(sections: list[tuple[str, str]], source: str | None = None) -> list[tuple[str, str]]:
    """Sections with progress added; unchanged if there are no checkboxes. `source` is shown as the
    file to edit, since ticking happens in a Markdown editor."""
    overall = progress("\n".join(text for _, text in sections))
    if overall.total == 0:
        return sections
    prepared = [(_section_name(name, progress(text)), _with_marks(text)) for name, text in sections]
    first_name, first_text = prepared[0]
    # The path on a line of its own (a two-space line end), so it can be copied in one piece.
    where = f" Tick items off by opening this file in a Markdown editor:  \n`{source}`" if source else ""
    prepared[0] = (first_name, f"**Progress:** {overall}.{where}\n\n{first_text}")
    return prepared
