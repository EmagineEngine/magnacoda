from __future__ import annotations

import re
from collections.abc import Sequence
from importlib import metadata, resources
from pathlib import Path
from typing import Any

import click

from magnacoda import documents, plugins, preferences, readme, viewer
from magnacoda.pager import (
    Format,
    Opening,
    Outcome,
    PagerOptions,
    find_place,
    markdown,
    reference,
    resolve,
    restore_screen,
    show,
)
from magnacoda.pager.formats import REFERENCE
from magnacoda.pager.options import Start


def help_file_text() -> str:
    return (resources.files("magnacoda") / "data" / "help.md").read_text(encoding="utf-8")


CLOSING_SECTIONS = ("more info", "about the name")  # the help's closing pages, after add-ons' sections too
ADDON_MARK = " (add-on)"  # after an add-on's section names, in the section list and on its page
_ACTIVE = re.compile(r"[*`\x00-\x1f\x7f]")  # emphasis, code and control characters: plain text only


def _author(package: str) -> str:
    """The add-on package's author as its metadata gives it, or ""."""
    try:
        md = metadata.metadata(package)
    except metadata.PackageNotFoundError:
        return ""
    author = (md.get_all("Author") or [""])[0]
    if not author:  # "Jane Doe <jane@example.org>, ..." gives Jane Doe
        email = (md.get_all("Author-email") or [""])[0]
        author = email.split(",")[0].split("<")[0].strip().strip('"')
    return author


def _source_line(plugin: plugins.Plugin) -> str:
    """Where an add-on's help section comes from; magnacoda adds it, so no add-on can leave it out."""
    if plugin.bundled:
        return f"From the {plugin.name} add-on, which comes with *magnacoda*."
    author = _ACTIVE.sub("", _author(plugin.package)).strip()
    by = f", by {author}" if author else ""
    source = _ACTIVE.sub("", f"{plugin.package} {plugin.version}")
    return f"From the add-on {source}{by}. It isn't part of *magnacoda*'s own help."


def _with_source(body: str, line: str) -> str:
    """The section with `line` under its title (a ### line first), or at its top."""
    body = body.lstrip("\n")
    first, _, rest = body.partition("\n")
    if first.startswith("### "):
        return "\n\n".join((first, line, rest.lstrip("\n")))
    return "\n\n".join((line, body))


def load_help() -> tuple[list[str], dict[str, str]]:
    """Built-in sections, then add-ons', then CLOSING_SECTIONS. Re-read each time, so edits show at once."""
    bodies = reference.sections(help_file_text())
    names = list(bodies)
    if not names or names[0] != "overview":
        raise click.ClickException('help.md is malformed: its first section must be "overview".')
    closing = [name for name in names if name in CLOSING_SECTIONS]
    names = [name for name in names if name not in CLOSING_SECTIONS]
    for plugin, text in plugins.help_texts():  # add-ons' sections come after magnacoda's own
        for name, body in reference.sections(text).items():
            if name in bodies or name == "all":
                plugins.warn(
                    f"The add-on {plugin.label} has a help section named '{name}', which magnacoda "
                    "already uses; skipped it."
                )
                continue
            marked = name + ADDON_MARK  # typing the name alone still finds it (section_matches)
            bodies[marked] = _with_source(body, _source_line(plugin))
            names.append(marked)
    return names + closing, bodies


# Paging off for one run, for example for screen-reader users: MAGNACODA_PAGER=off.
PAGER_OFF_SWITCH = "MAGNACODA_PAGER"


def pager_options(what: str, **launch: Any) -> PagerOptions:
    """The pager's options for one screen: the [pager] section of preferences.ini, then `launch`.

    The title bar reads, for example, "magnacoda - Help".
    """
    return resolve(
        settings_file=preferences.preferences_path(),
        section="pager",
        title_bar=f"{plugins.edition().display_name} - {what}",
        off_switch_env=PAGER_OFF_SWITCH,
        **launch,
    )


def show_pages(
    ctx: click.Context,
    sections: list[tuple[str, str]],
    options: PagerOptions,
    format: Format = REFERENCE,
    title: str | None = None,
    section: str | None = None,
    outline: Sequence[tuple[int, str, str, str]] = (),
    document: Path | None = None,
) -> None:
    """Page the sections in a terminal, or print them all where there's no pager (like man into a pipe).

    `title` is a document's own title (see PagerOptions.document_title). `section` names the section
    to open on (`help scan`); one that matches none, or several, is an error with what it could be.
    `document` is the file shown, for the Open list (o), which opens another document from here.
    The pager leaves the screen as it found it. Only when the window changed size while paging (the
    screen underneath then reflows, and may look broken) does an "after_pager" callable in the
    shell's ctx.obj run, to feed a fresh page with the banner.
    """
    start_at, start_heading = None, ""
    if section is not None:
        start_at, start_heading = _place([name for name, _ in sections], outline, section, options)
    preferences.ensure_file()
    root = ctx.find_root()
    fade_in = not root.meta.pop(_FROM_PAGE, False)
    came_from = root.meta.pop(_CAME_FROM, None)
    start_line = 0
    if place := root.meta.pop(_PLACE, None):
        start_at, start_line = place
    places: dict[Path, tuple[int, int]] = root.meta.setdefault(_PLACES, {})
    asked: list[Opening] = []

    def open_document(opening: Opening) -> str:
        problem = _opening_problem(opening)
        if not problem:
            asked.append(opening)
        return problem

    def remember(section: int, line: int) -> None:
        if document is not None:
            places[document] = (section, line)

    outcome = show(
        sections,
        options,
        format=format,
        title=title,
        start_at=start_at,
        outline=outline,
        fade_in=fade_in,
        documents=documents.entries(),
        document=document,
        came_from=came_from,
        open_document=open_document,
        remember=remember,
        start_line=start_line,
        start_heading=start_heading,
    )
    if outcome is Outcome.GO:
        opening = asked[-1]
        root.meta[_FROM_PAGE], root.meta[_CAME_FROM] = True, document
        if opening.back and opening.entry.path in places:
            root.meta[_PLACE] = places[opening.entry.path]
        try:
            _open_document(root, opening)
        finally:
            restore_screen()  # if this one was left for one that never came
        return
    if outcome is None or not outcome.resized:
        return  # printed, or the screen came back as it was
    state: dict[str, Any] = ctx.obj if isinstance(ctx.obj, dict) else {}
    after_pager = state.get("after_pager")
    if callable(after_pager):
        after_pager()


# Kept in the root context while one document opens another from the Open list.
_FROM_PAGE = "magnacoda.from_page"  # the next pager opens straight from another (no fade in)
_CAME_FROM = "magnacoda.came_from"  # the document just left
_PLACES = "magnacoda.places"  # where each document was left, as (section, line)
_PLACE = "magnacoda.place"  # where the next one opens, going back to it


def show_file(
    ctx: click.Context, file: str, what: str, section: str | None = None, start: Start = "first_page"
) -> None:
    """A Markdown or text file in the viewer, its title bar naming `what`. Raises CannotView."""
    # The title bar names it, so the file's own title heads the first page.
    options = pager_options(what, start=start, document_title="first_page")
    shown = viewer.load(file, options)
    show_pages(
        ctx,
        shown.sections,
        options,
        format=shown.format,
        title=shown.title,
        section=section,
        outline=shown.outline,
        document=Path(file).expanduser(),
    )


def _page_names(command: str) -> list[str] | None:
    if command == "help":
        return load_help()[0]
    text = readme.manual_text() if command == "docs" else readme.readme_text()
    if text is None:
        return None
    document = markdown.parse(text, pager_options(command, document_title="drop"))
    return [name for name, _ in document.sections]


def _opening_problem(opening: Opening) -> str:
    """ "" if the Open list's choice can be shown, else why not (shown in the list)."""
    command = documents.command_for(opening.entry.path)
    outline: list[tuple[int, str, str, str]] = []
    if command is not None:
        names = _page_names(command)
    else:
        try:
            shown = viewer.load(str(opening.entry.path))
        except viewer.CannotView as exc:
            return str(exc)
        names, outline = [name for name, _ in shown.sections], shown.outline
    if not opening.section or names is None:
        return ""
    index, _, could_be = find_place(names, outline, opening.section)
    if index is not None:
        return ""
    if could_be:
        return f"'{opening.section}' fits more than one section: {', '.join(could_be)}. Type more of it."
    return f"No section named '{opening.section}' in {opening.entry.title}."


def _open_document(root: click.Context, opening: Opening) -> None:
    """Help, the manual and the README through their commands, as if typed; any other file here."""
    command = documents.command_for(opening.entry.path)
    if command is None:
        # A text file's sections are new to the reader, as in `view`: it starts on its section list.
        text = opening.entry.path.suffix.lower() != ".md"
        start: Start = "section_list" if text else "first_page"
        show_file(root, str(opening.entry.path), opening.entry.title, opening.section or None, start)
        return
    group = root.command
    assert isinstance(group, click.Group)
    found = group.get_command(root, command)
    assert found is not None
    with found.make_context(command, opening.section.split(), parent=root) as sub:
        found.invoke(sub)


def _place(
    names: list[str], outline: Sequence[tuple[int, str, str, str]], wanted: str, options: PagerOptions
) -> tuple[int, str]:
    """The section `wanted` names, or a heading in one (see find_place), as (index, heading)."""
    index, heading, could_be = find_place(names, outline, wanted)
    if index is not None:
        return index, heading
    what = (options.title_bar or "This").split(" - ")[-1]
    if could_be:
        raise click.ClickException(
            f"'{wanted}' fits more than one section: {', '.join(could_be)}. Type more of the name."
        )
    headings = [label for _, label, _, heading in outline if heading]
    listed = names if len(names) > 1 or not headings else headings  # one page: its headings
    raise click.ClickException(f"{what} has no section named '{wanted}'. Its sections: {', '.join(listed)}.")


def show_help(ctx: click.Context, section: str | None = None) -> None:
    """Entry point for `help` and `--help`: all sections, starting at the overview (or at `section`)."""
    names, bodies = load_help()
    show_pages(
        ctx,
        [(n, bodies[n]) for n in names],
        pager_options("Help"),
        section=section,
        document=documents.locate("help.md"),
    )
