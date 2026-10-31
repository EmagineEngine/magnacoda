"""`view FILE`: Markdown laid out like the README (a page per `##` section, or one for a short
file), other text word-wrapped.

The pager package reads and lays out the file (pager.files, pager.markdown); this adds a checklist's
progress (checklist.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from magnacoda import checklist
from magnacoda.pager import Format, PagerOptions, files, formats, markdown
from magnacoda.pager.files import CannotView
from magnacoda.report import paths

__all__ = ["CannotView", "Shown", "load"]


@dataclass(frozen=True)
class Shown:
    name: str  # the file's name, for the title bar
    sections: list[tuple[str, str]]
    format: Format
    title: str | None  # a Markdown file's own `# Title`
    outline: list[tuple[int, str, str, str]] = field(default_factory=list)  # for the g list


def load(typed: str, options: PagerOptions | None = None) -> Shown:
    """What to show for `typed`, relative to the cwd; `~` works. Raises CannotView."""
    file = files.read(typed)
    if not file.markdown:
        return Shown(file.path.name, [(file.path.name, file.text)], formats.TEXT, None)
    document = markdown.parse(file.text, options)
    # A checklist also shows how far along it is, and which file to edit to tick items off.
    sections = checklist.prepare(document.sections, paths.short(file.path))
    renamed = {old: new for (old, _), (new, _) in zip(document.sections, sections, strict=True)}
    outline = [
        (depth, renamed.get(label, label) if not heading else label, renamed.get(name, name), heading)
        for depth, label, name, heading in document.outline
    ]
    return Shown(file.path.name, sections, formats.MARKDOWN, document.title, outline)
