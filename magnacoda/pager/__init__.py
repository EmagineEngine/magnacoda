"""A terminal pager for documents in sections: help, a README, any Markdown or text file.

One page per section (a short document is one page), g lists the sections, a number jumps to one.
It never erases the screen it found: it uses the terminal's alternate screen. Where there is no
terminal to page in, everything is printed at once. Self-contained, so it can become its own package.

    from magnacoda.pager import files, formats, markdown, options, show

    settings = options.resolve(title_bar="notes.md", start="section_list")
    document = markdown.parse(files.read("notes.md").text, settings)
    show(document.sections, settings, format=formats.MARKDOWN, title=document.title)

Every kind of document is laid out here (formats.py): Markdown, a command reference like a man page
(help), and plain text.
"""

from __future__ import annotations

import dataclasses
import shutil
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from magnacoda.pager import browser, colors, emphasis, files, links, markdown, screen, themes, winpalette
from magnacoda.pager.documents import Entry, Opening, read_list
from magnacoda.pager.formats import MARKDOWN, TEXT, Format
from magnacoda.pager.markdown import with_title
from magnacoda.pager.options import PagerOptions, resolve, save_setting
from magnacoda.pager.screen import (
    Outcome,
    find_place,
    find_section,
    page_sections,
    pager_available,
    restore_screen,
)

screen.windows_palette = winpalette.configured

__all__ = [
    "Entry",
    "Format",
    "Opening",
    "Outcome",
    "PagerOptions",
    "find_place",
    "find_section",
    "read_list",
    "resolve",
    "restore_screen",
    "show",
]


def show(
    sections: list[tuple[str, str]],
    options: PagerOptions | None = None,
    format: Format = TEXT,
    title: str | None = None,
    out: Any = None,
    start_at: int | None = None,
    outline: Sequence[tuple[int, str, str, str]] = (),
    fade_in: bool = True,
    documents: Sequence[Entry] | None = None,
    document: Path | None = None,
    came_from: Path | None = None,
    open_document: Callable[[Opening], str] | None = None,
    remember: Callable[[int, int], None] | None = None,
    start_line: int = 0,
    start_heading: str = "",
    shown: Callable[[int], None] | None = None,
) -> Outcome | None:
    """Page the sections, or print them all where paging is off or impossible (like man into a pipe).

    `format` says how the sections are written (formats.py). `title` is the document's own title,
    shown or dropped as options.document_title says. With `start_at` (a section's index), paging
    starts on that section (at `start_line`, or at `start_heading`; see find_place), and printing
    prints only it. Returns the pager's
    outcome, or None if everything was printed. Without `fade_in`, opening doesn't fade (coming from
    another document).

    The Open list (o) offers `documents`, or else those in options.documents' list file; `document`
    is the file showing. With `open_document` the program shows what is chosen (see page_sections);
    without it, the pager reads and shows it here, and goes back to where it was left. `shown` is
    told each section's index the first time it shows (in these sections, not another document).
    """
    options = options or PagerOptions()
    if documents is None:
        documents = read_list(options.documents) if options.documents else []
    if documents and open_document is None:
        return _browse(
            sections,
            options,
            format,
            title,
            out,
            start_at,
            outline,
            list(documents),
            document,
            start_heading,
            shown,
        )
    return _page(
        sections,
        options,
        format,
        title,
        out,
        start_at,
        outline,
        fade_in,
        documents,
        document,
        came_from,
        open_document,
        remember,
        start_line,
        start_heading,
        shown,
    )


def _browse(
    sections: list[tuple[str, str]],
    options: PagerOptions,
    format: Format,
    title: str | None,
    out: Any,
    start_at: int | None,
    outline: Sequence[tuple[int, str, str, str]],
    documents: list[Entry],
    document: Path | None,
    start_heading: str,
    shown: Callable[[int], None] | None = None,
) -> Outcome | None:
    """Page from one document to another as the Open list asks, on the pager's own."""
    places: dict[Path, tuple[int, int]] = {}
    asked: list[tuple[Opening, files.TextFile, markdown.Document | None]] = []
    showing: list[Path | None] = [document]
    settings = [options]

    def accept(opening: Opening) -> str:
        try:
            file = files.read(str(opening.entry.path))
        except files.CannotView as exc:
            return str(exc)
        parsed = markdown.parse(file.text, settings[0]) if file.markdown else None
        if opening.section and parsed is None:
            return f"{opening.entry.title} has no sections."
        if opening.section and parsed is not None:
            if find_place([name for name, _ in parsed.sections], parsed.outline, opening.section)[0] is None:
                return f"No section named '{opening.section}' in {opening.entry.title}."
        asked.append((opening, file, parsed))
        return ""

    def keep(section: int, line: int) -> None:
        if showing[0] is not None:
            places[showing[0]] = (section, line)

    came_from: Path | None = None
    start_line, fade_in = 0, True
    try:
        while True:
            asked.clear()
            outcome = _page(
                sections,
                settings[0],
                format,
                title,
                out,
                start_at,
                outline,
                fade_in,
                documents,
                showing[0],
                came_from,
                accept,
                keep,
                start_line,
                start_heading,
                shown,
            )
            shown = None  # only the first document's sections
            if outcome is not Outcome.GO:
                return outcome
            opening, file, parsed = asked[-1]
            came_from, showing[0], fade_in = showing[0], opening.entry.path, False
            settings[0] = dataclasses.replace(settings[0], title_bar=opening.entry.title, front_page=False)
            if parsed is None:
                sections, format, title, outline = [(file.path.name, file.text)], TEXT, None, ()
            else:
                sections, format, title, outline = parsed.sections, MARKDOWN, parsed.title, parsed.outline
            start_at, start_line, start_heading = None, 0, ""
            if opening.back and opening.entry.path in places:
                start_at, start_line = places[opening.entry.path]
            elif opening.section:
                start_at, start_heading, _ = find_place(
                    [name for name, _ in sections], outline, opening.section
                )
    finally:
        restore_screen()  # if a document was left for one that never came


def _page(
    sections: list[tuple[str, str]],
    options: PagerOptions,
    format: Format,
    title: str | None,
    out: Any,
    start_at: int | None,
    outline: Sequence[tuple[int, str, str, str]],
    fade_in: bool,
    documents: Sequence[Entry],
    document: Path | None,
    came_from: Path | None,
    open_document: Callable[[Opening], str] | None,
    remember: Callable[[int, int], None] | None,
    start_line: int,
    start_heading: str,
    shown: Callable[[int], None] | None = None,
) -> Outcome | None:
    # An opening section of a line or two (a license's "Abbreviation") looks like something is
    # missing, so such a document starts on its section list.
    short = bool(sections) and len(_text_only(sections[0][1])) < _SHORT_OPENING and not options.front_page
    if options.document_title == "first_page":
        sections = with_title(title, sections)
    if not (options.paging and pager_available(off_switch=options.off_switch_env)):
        width = shutil.get_terminal_size((80, 24)).columns - 1
        printed = sections if start_at is None else sections[start_at : start_at + 1]
        if format.emphasis:
            printed = [(name, emphasis.plain(body)) for name, body in printed]
        text = "\n\n".join("\n".join(format.render(body, width)) for _, body in printed)
        print(text, file=sys.stdout if out is None else out)
        for index in range(len(sections)) if start_at is None else [start_at]:
            if shown is not None:
                shown(index)
        return None
    loaded = themes.load(options.colors_file) if colors.enabled() else themes.Loaded()
    choices = (
        [
            (s.name, s.description, colors.codes(s), *colors.accent_codes(s), *colors.code_codes(s))
            for s in (*colors.SCHEMES, *loaded.themes)
        ]
        if colors.enabled()
        else []
    )
    path, section = options.settings_path, options.settings_section

    def save_color(name: str) -> None:
        if path is not None:
            save_setting(path, section, "colors", name)

    wrap = links.wrapper(
        format.render,
        hyperlinks=options.hyperlinks and links.supported(),
        emphasis=format.emphasis,
        code=format.code,
    )
    return page_sections(
        sections,
        out=out,
        wrap=wrap,
        title=options.title_bar,
        open_list=(options.start == "section_list" or short) and start_at is None,
        start_section=start_at or 0,
        start_line=start_line,
        start_heading=start_heading,
        open_link=browser.open_link,
        documents=documents,
        document=document,
        came_from=came_from,
        typed_files=options.typed_files,
        open_document=open_document,
        remember=remember,
        colors=choices,
        color=options.colors,
        color_notes=loaded.problems,
        outline=outline,
        fade=options.fade,
        fade_in=fade_in,
        own_code=colors.own_code_codes,
        save_color=save_color,
        front_page=options.front_page,
        shown=shown,
    )


_SHORT_OPENING = 160  # characters, about two lines


def _text_only(body: str) -> str:
    return " ".join(
        line.strip() for line in body.splitlines() if line.strip() and not line.lstrip().startswith("#")
    )
