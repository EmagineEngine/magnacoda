"""Markdown for the pager: one section per `##` heading, laid out as plain terminal text with Rich.

A document's own table of contents and pictures in HTML (a logo) are left out, its `# Title` is taken out
for the program to show or drop (PagerOptions.document_title), a link to another section gets that
section's number in the g list (type it to go there), long code lines wrap with extra indent so
they don't look like new commands, and a loose list (blank lines between its items) keeps a blank line
between them, as Markdown defines it.
"""

from __future__ import annotations

import io
import re
import textwrap
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from rich.console import Console, ConsoleOptions, RenderResult
from rich.markdown import ListElement, Markdown
from rich.segment import Segment

from magnacoda.pager.links import CODE_MARK
from magnacoda.pager.options import PagerOptions

if TYPE_CHECKING:  # markdown-it's Token, as Rich uses it
    from rich.markdown import Token

_FENCE = re.compile(r"^\s*(```|~~~)")
_SECTION = re.compile(r"^##\s+(.+?)\s*#*\s*$")
_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$")
_SUBHEADING = re.compile(r"^#{2,6}\s+(.+?)\s*#*\s*$")
_TITLE = re.compile(r"^#\s+(.+?)\s*#*\s*$")
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
# A line of nothing but the tags around a picture, such as a logo in <picture>: a terminal can't show it.
_PICTURE_TAGS = re.compile(r"^\s*(?:</?(?:h1|p|div|picture|source|img)\b[^>]*>\s*)+$", re.IGNORECASE)
# A line of HTML above the first heading, such as a tagline under a logo, is part of the banner.
_BANNER_LINE = re.compile(r"^\s*<[a-z][^>]*>.*</[a-z][a-z0-9]*>\s*$", re.IGNORECASE)
_IMAGE = re.compile(r"!\[([^\]]*)\]\(<?([^)>]+)>?\)")  # ![alt](path) or ![alt](<path with spaces>)
_ANCHOR_LINK = re.compile(r"\[([^\]]+)\]\(#([^)]*)\)")  # [Quick start](#quick-start)
_SAME_TEXT_LINK = re.compile(r"\[(https?://[^\]]+)\]\(\1\)")  # [https://x](https://x)
_INLINE_CODE = re.compile(r"`([^`\n]+)`")
_MARKERS = re.compile(r"[*_`]")
_CODE_INDENT = "  "
_CONTINUATION_INDENT = _CODE_INDENT + "  "
# A space Rich won't wrap at (it wraps at a no-break space): one cell wide, put back after wrapping.
_KEEP_SPACE = ""
# Around a heading while it's laid out (a character Rich gives no width), then HEADING_MARK on each of
# its lines: a code that shows nothing, which the pager's screen turns into the accent color.
_HEADING_EDGE = "\u2063"
HEADING_MARK = "\x1b[11m"
# The same for #### and below, with HEADING_MARK twice: the screen draws
# them a shade dimmer.
_SUBHEADING_EDGE = "\u2064"

# Contents detection: a list nearly all of whose items link to headings in the same document is a table
# of contents, whatever it is called, if it has at least 3 items; 2 under a short label ending in a
# colon ("On this page:"); 1 under a heading or a bold line (## Contents, **Contents**).
_CONTENTS_MIN_ITEMS = 3
_CONTENTS_MIN_UNDER_COLON = 2
_CONTENTS_MIN_UNDER_HEADING = 1
_CONTENTS_SHARE = 0.8
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.*)$")
_ITEM_LINK = re.compile(r"^[*_]*\[[^\]]+\]\(#([^)\s]+)\)[*_]*\s*$")  # [Text](#anchor), maybe in bold
_BOLD_LABEL = re.compile(r"^\s*(?:\*\*[^*]+\*\*|__[^_]+__)\s*$")  # **Contents**
_COLON_LABEL = re.compile(r"^\s*[^\s#*_-].{0,40}:\s*$")  # On this page:
# Markers that ask a site to draw a table of contents there: GitLab's [[_TOC_]], [TOC], {:toc}.
_CONTENTS_MARKER = re.compile(r"^\s*(\[\[_TOC_\]\]|\[TOC\]|\{:toc\}|\*\s*TOC\s*\{:toc\})\s*$", re.IGNORECASE)


# One entry of the g list's outline: (depth, label, section, heading). `section` is the name of the
# `##` section it goes to ("" for a group label, such as "How do I get started?"), `heading` the `###`
# heading in it ("" for the section itself).
OutlineEntry = tuple[int, str, str, str]
_LEVEL3 = re.compile(r"^###\s+(.+?)\s*#*\s*$")
_LEVEL4 = re.compile(r"^####\s+(.+?)\s*#*\s*$")
# A `##` heading with only a short sentence or two before its `###` headings is a group: they become
# its pages, and it a label in the g list (as in this project's README).
_GROUP_INTRO_MAX = 400
_GROUP_MIN_PAGES = 2
_NOT_PROSE = re.compile(r"^\s*(?:[-*+]\s|\d+[.)]\s|\||>|```|~~~|#|    )")
_CONTENTS_LINK = re.compile(r"\[([^\]]+)\]\(#([^)\s]+)\)")


@dataclass(frozen=True)
class Document:
    title: str | None  # the document's own `# Title`, if its first line is one
    sections: list[tuple[str, str]]  # (name, markdown) per `##` section, as the g list shows them
    # How the g list lays the sections out: the document's own contents list, with its group labels
    # and subsections, or else its `##` and `###` headings; empty when there are no `###` headings.
    outline: list[OutlineEntry] = field(default_factory=list)


def slug(heading: str) -> str:
    """A heading's anchor, as GitHub and GitLab make it."""
    return re.sub(r"\s", "-", re.sub(r"[^\w\s-]", "", heading.strip().lower()))


def _outside_code(lines: list[str]) -> list[bool]:
    """For each line, whether it is outside a fenced code block (fences count as inside)."""
    flags, in_code = [], False
    for line in lines:
        if _FENCE.match(line):
            in_code = not in_code
            flags.append(False)
            continue
        flags.append(not in_code)
    return flags


def _anchors(lines: list[str]) -> set[str]:
    found: set[str] = set()
    seen: dict[str, int] = {}
    for line, outside in zip(lines, _outside_code(lines), strict=True):
        heading = _HEADING.match(line) if outside else None
        if heading:
            anchor = slug(heading.group(1))
            count = seen.get(anchor, 0)
            seen[anchor] = count + 1
            found.add(f"{anchor}-{count}" if count else anchor)
    return found


def _nothing_after(lines: list[str], end: int) -> bool:
    """Only blank lines between line `end` and the next heading (or the end of the text)."""
    for line in lines[end + 1 :]:
        if line.strip():
            return bool(_HEADING.match(line))
    return True


def _drop_contents(lines: list[str], contents: list[str] | None = None) -> list[str]:
    """Without any table of contents: list runs whose items nearly all link to headings here, with a
    label just above (**Contents**, ### Contents, "On this page:"), and markers such as [[_TOC_]].
    The first one's item lines are added to `contents`, for the g list's outline."""
    anchors = _anchors(lines)
    outside = _outside_code(lines)
    drop = [False] * len(lines)
    number = 0
    while number < len(lines):
        if not outside[number]:
            number += 1
            continue
        if _CONTENTS_MARKER.match(lines[number]):
            drop[number] = True
            number += 1
            continue
        if not _LIST_ITEM.match(lines[number]):
            number += 1
            continue
        start = end = number  # a run of list items, which may have single blank lines between them
        while end + 1 < len(lines) and outside[end + 1]:
            if _LIST_ITEM.match(lines[end + 1]):
                end += 1
            elif not lines[end + 1].strip() and end + 2 < len(lines) and _LIST_ITEM.match(lines[end + 2]):
                end += 2
            else:
                break
        run = [line for line in lines[start : end + 1] if _LIST_ITEM.match(line)]
        depths = [len(line) - len(line.lstrip()) for line in run]
        items = [match.group(1) for line in run if (match := _LIST_ITEM.match(line))]
        links = [link.group(1) for item in items if (link := _ITEM_LINK.match(item))]
        inside = [anchor for anchor in links if anchor.lower() in anchors]
        # A group label (**Getting started**, with linked items under it) is part of the list's shape,
        # so it doesn't count against it.
        items = [
            item
            for n, item in enumerate(items)
            if _ITEM_LINK.match(item) or not (n + 1 < len(items) and depths[n + 1] > depths[n])
        ]
        above = start - 1
        while above >= 0 and not lines[above].strip():
            above -= 1
        label = lines[above] if above >= 0 and outside[above] else ""
        heading = _SUBHEADING.match(label)
        if heading or _BOLD_LABEL.match(label):
            enough = _CONTENTS_MIN_UNDER_HEADING
        elif _COLON_LABEL.match(label):
            enough = _CONTENTS_MIN_UNDER_COLON
        else:
            enough, label = _CONTENTS_MIN_ITEMS, ""
        if len(items) >= enough and len(inside) >= _CONTENTS_SHARE * len(items):
            if contents is not None and not contents:
                contents += [line for line in lines[start : end + 1] if line.strip()]
            for index in range(start, end + 1):
                drop[index] = True
            # The label goes too. A ## heading stays (parse() drops a section left empty), and so does
            # any heading with more under it than the list, so no text moves to another section.
            if label and not (heading and (label.startswith("## ") or not _nothing_after(lines, end))):
                drop[above] = True
        number = end + 1
    kept = [(line, inside) for line, inside, dropped in zip(lines, outside, drop, strict=True) if not dropped]
    # No double blank line where something was taken out.
    return [
        line
        for index, (line, inside) in enumerate(kept)
        if line.strip() or not inside or index == 0 or kept[index - 1][0].strip()
    ]


def parse(text: str, options: PagerOptions | None = None) -> Document:
    """The document's title and its sections, with the options' hide_contents and number_links applied."""
    options = options or PagerOptions()
    lines = _COMMENT.sub("", text).splitlines()
    lines = [
        line
        for line, in_text in zip(lines, _outside_code(lines), strict=True)
        if not (in_text and _PICTURE_TAGS.match(line))
    ]
    top = next((index for index, line in enumerate(lines) if _HEADING.match(line)), len(lines))
    lines = [line for line in lines[:top] if not _BANNER_LINE.match(line)] + lines[top:]
    first = next((index for index, line in enumerate(lines) if line.strip()), None)
    title = None
    if first is not None and (match := _TITLE.match(lines[first])):
        title = match.group(1)
        lines = lines[:first] + lines[first + 1 :]
    contents: list[str] = []
    if options.hide_contents:
        lines = _drop_contents(lines, contents)
    found: list[tuple[str, list[str]]] = [(options.first_section, [])]
    for line, outside in zip(lines, _outside_code(lines), strict=True):
        heading = _SECTION.match(line) if outside else None
        if heading:
            found.append((_MARKERS.sub("", heading.group(1)).strip(), [line]))
        else:
            found[-1][1].append(line)
    sections = [
        (name, "\n".join(body).strip())
        for name, body in found
        # A section left with only its heading (its contents list was dropped) goes too.
        if "\n".join(body[1:] if body and _SECTION.match(body[0]) else body).strip()
    ]
    sections, groups = _split_groups(sections)
    outline = _outline(contents, sections, groups)
    if len(sections) > 1 and sum(len(text.split()) for _, text in sections) <= ONE_PAGE_WORDS:
        sections, outline = _one_page(sections, outline, title)
    if options.number_links:
        sections = number_links(sections)
    return Document(title=title, sections=sections, outline=outline)


# A document this short scrolls as one page; the g list is then its table of contents.
ONE_PAGE_WORDS = 800


def _one_page(
    sections: list[tuple[str, str]], outline: list[OutlineEntry], title: str | None
) -> tuple[list[tuple[str, str]], list[OutlineEntry]]:
    page = _MARKERS.sub("", title).strip() if title else sections[0][0]
    # Where each section starts on the page: its heading, or the top for text before the first one.
    starts = {name: name if _SECTION.match(text.split("\n", 1)[0]) else "" for name, text in sections}
    outline = outline or [(0, name, name, "") for name, _ in sections]
    toc = [
        (depth, label, page if name else "", heading or starts.get(name, ""))
        for depth, label, name, heading in outline
    ]
    return [(page, "\n\n".join(text for _, text in sections))], toc


def _subheadings(markdown: str, level: re.Pattern[str] = _LEVEL3) -> list[str]:
    """One section's headings of one level (`###` by default), outside code."""
    lines = markdown.splitlines()
    return [
        _MARKERS.sub("", match.group(1)).strip()
        for line, outside in zip(lines, _outside_code(lines), strict=True)
        if outside and (match := level.match(line))
    ]


def _split_groups(sections: list[tuple[str, str]]) -> tuple[list[tuple[str, str]], dict[str, str]]:
    """Each group (see _GROUP_INTRO_MAX) split into its `###` pages, the `##` heading and its sentence
    opening the first; other sections as they are. Also {page: its group's name}."""
    out: list[tuple[str, str]] = []
    groups: dict[str, str] = {}
    for name, text in sections:
        lines = text.splitlines()
        outside = _outside_code(lines)
        starts = [n for n, line in enumerate(lines) if outside[n] and _LEVEL3.match(line)]
        intro = "\n".join(lines[1 : starts[0]]).strip() if starts else ""
        is_group = (
            bool(lines)
            and _SECTION.match(lines[0]) is not None
            and len(starts) >= _GROUP_MIN_PAGES
            and len(intro) <= _GROUP_INTRO_MAX
            and "\n\n" not in intro
            and not any(_NOT_PROSE.match(line) for line in intro.splitlines())
        )
        if not is_group:
            out.append((name, text))
            continue
        for number, start in enumerate(starts):
            end = starts[number + 1] if number + 1 < len(starts) else len(lines)
            match = _LEVEL3.match(lines[start])
            assert match is not None
            page = _MARKERS.sub("", match.group(1)).strip()
            body = lines[:end] if number == 0 else lines[start:end]
            out.append((page, "\n".join(body).strip()))
            groups[page] = name
    return out, groups


def _outline(
    contents: list[str], sections: list[tuple[str, str]], groups: dict[str, str] | None = None
) -> list[OutlineEntry]:
    """The g list's outline (see Document.outline). From a contents list: each item at its depth, a
    linked one going to its section, subsection or group, one without a link a group label; sections
    it doesn't name keep their place before or after it. Without one: the headings, groups first."""
    groups = groups or {}
    subheadings = {
        name: _subheadings(text, _LEVEL4 if name in groups else _LEVEL3) for name, text in sections
    }
    if not contents:
        if not any(subheadings.values()) and not groups:
            return []
        outline: list[OutlineEntry] = []
        last_group = None
        for name, _ in sections:
            group = groups.get(name)
            if group and group != last_group:
                outline.append((0, _MARKERS.sub("", group).strip(), "", ""))
            last_group = group
            depth = 1 if group else 0
            outline.append((depth, name, name, ""))
            outline += [(depth + 1, heading, name, heading) for heading in subheadings[name]]
        return outline
    targets: dict[str, tuple[str, str]] = {}
    for group in dict.fromkeys(groups.values()):
        targets.setdefault(slug(group), ("", _MARKERS.sub("", group).strip()))
    for name, _ in sections:
        targets.setdefault(slug(name), (name, ""))
        for heading in subheadings[name]:
            targets.setdefault(slug(heading), (name, heading))
    indents = sorted({len(line) - len(line.lstrip()) for line in contents})
    entries: list[OutlineEntry] = []
    for line in contents:
        item = _LIST_ITEM.match(line)
        if item is None:
            continue
        depth = indents.index(len(line) - len(line.lstrip()))
        link = _CONTENTS_LINK.search(item.group(1))
        if link is None:
            entries.append((depth, _MARKERS.sub("", item.group(1)).strip(), "", ""))
        elif (target := targets.get(link.group(2).lower())) is not None:
            name, heading = target
            if not name:  # a group: a label
                entries.append((depth, heading, "", ""))
            else:
                entries.append((depth, heading or name, name, heading))
    named = {name for _, _, name, heading in entries if name and not heading}
    before = []  # sections before the first one the contents names, such as the Introduction
    for name, _ in sections:
        if name in named:
            break
        before.append((0, name, name, ""))
    listed = named | {name for _, name, _, _ in before}
    after = [(0, name, name, "") for name, _ in sections if name not in listed]
    return [*before, *entries, *after]


def with_title(title: str | None, sections: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """The title in bold at the top of the first section, for document_title = first_page."""
    if not title or not sections:
        return sections
    name, body = sections[0]
    return [(name, f"**{title}**\n\n{body}"), *sections[1:]]


def number_links(sections: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Links to another section's heading become "text (section N)", N as in the g list.

    Pass the sections as they will be shown (after any are hidden), so the numbers match.
    """
    where: dict[str, int] = {}
    seen: dict[str, int] = {}
    for number, (_, text) in enumerate(sections, start=1):
        lines = text.splitlines()
        for line, outside in zip(lines, _outside_code(lines), strict=True):
            heading = _SUBHEADING.match(line) if outside else None
            if heading:
                anchor = slug(heading.group(1))
                count = seen.get(anchor, 0)
                seen[anchor] = count + 1
                where.setdefault(f"{anchor}-{count}" if count else anchor, number)

    def numbered(number: int, text: str) -> str:
        def link(match: re.Match[str]) -> str:
            target = where.get(match.group(2).lower())
            if target is None or target == number:
                return match.group(0)  # unknown, or in this section: render() keeps just the text
            return f"{match.group(1)} (section{_KEEP_SPACE}{target})"

        lines = text.splitlines()
        return "\n".join(
            _ANCHOR_LINK.sub(link, line) if outside else line
            for line, outside in zip(lines, _outside_code(lines), strict=True)
        )

    return [(name, numbered(number, text)) for number, (name, text) in enumerate(sections, start=1)]


_PUNCTUATION = re.compile(r"([!-/:-@\[-`{-~])")


def _code_as_text(match: re.Match[str]) -> str:
    """Inline code as plain text, backticks kept and everything inside escaped."""
    return "\\`" + _PUNCTUATION.sub(r"\\\1", match.group(1)) + "\\`"


_SGR = re.compile(r"\x1b\[([0-9;]*)m")


_KEPT_STYLES = ("1", "3", "4")  # bold, italic, underline
STYLES_OFF = "\x1b[22;23;24m"


def _styles_only(match: re.Match[str]) -> str:
    """Of Rich's codes, only bold, italic and a link's underline are kept, and a reset turns just
    those off: Rich's colors, or a full reset, would undo the pager's own colors."""
    codes = match.group(1).split(";")
    if codes in (["0"], [""]):
        return STYLES_OFF
    kept = [code for code in codes if code in _KEPT_STYLES]
    return f"\x1b[{';'.join(kept)}m" if kept else ""


# A link to a placeholder address (https://example.com) stays text with its address: not a link.
_EXAMPLE_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]*(?:example|mysite)[^)\s]*)\)", re.IGNORECASE)


def _markdown_lines(markdown: str, width: int, hyperlinks: bool = False, styled: bool = False) -> list[str]:
    # A terminal can't show a picture: say which file it is, in place (a checklist's screenshots).
    markdown = _IMAGE.sub(lambda m: f"{m.group(1) or 'Image'}: `{m.group(2)}`", markdown)
    markdown = _ANCHOR_LINK.sub(r"\1", markdown)  # what number_links left: unknown, or this section
    markdown = _SAME_TEXT_LINK.sub(r"\1", markdown)
    if hyperlinks:
        markdown = _EXAMPLE_LINK.sub(r"\1 (\2)", markdown)
    markdown = _INLINE_CODE.sub(_code_as_text, markdown)  # shown with its backticks

    # The marks go inside the asterisks: outside, they'd keep a heading that ends in punctuation
    # ("What is it?") from closing its bold or italic.
    # Bold for # and ##, italic for ###, and italic a shade dimmer for #### and below.
    def heading(match: re.Match[str]) -> str:
        level = len(match.group(0)) - len(match.group(0).lstrip("#"))
        edge = (_SUBHEADING_EDGE if level > 3 else _HEADING_EDGE) if styled else ""
        marker = "**" if level <= 2 else "*"
        return f"{marker}{edge}{match.group(1)}{edge}{marker}"

    markdown = "\n".join(_HEADING.sub(heading, line) for line in markdown.splitlines())
    out = io.StringIO()
    if hyperlinks or styled:  # bold, italic and hyperlinks need a terminal's codes
        console = Console(
            file=out, width=width, color_system="standard", legacy_windows=False, force_terminal=True
        )
    else:
        console = Console(
            file=out, width=width, color_system=None, legacy_windows=False, force_terminal=False
        )
    console.print(_Markdown(markdown, hyperlinks=hyperlinks))
    text = _SGR.sub(_styles_only, out.getvalue()) if hyperlinks or styled else out.getvalue()
    lines, in_heading, in_sub = [], False, False
    for line in text.splitlines():
        sub = in_sub or _SUBHEADING_EDGE in line
        marked = sub or in_heading or _HEADING_EDGE in line
        in_heading = line.count(_HEADING_EDGE) % 2 != in_heading
        in_sub = line.count(_SUBHEADING_EDGE) % 2 != in_sub
        line = line.rstrip().replace(_KEEP_SPACE, " ").replace(_HEADING_EDGE, "")
        line = line.replace(_SUBHEADING_EDGE, "")
        mark = HEADING_MARK * 2 if sub else HEADING_MARK
        lines.append(mark + line if marked and line else line)
    return lines


class _ListElement(ListElement):
    """Rich's list, with a blank line between the items of a loose list."""

    loose = False

    @classmethod
    def create(cls, markdown: Markdown, token: Token) -> ListElement:
        element = super().create(markdown, token)
        element.loose = bool(token.meta.get("loose"))  # type: ignore[attr-defined]
        return element

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        number = 1 if self.list_start is None else self.list_start
        for index, item in enumerate(self.items):
            if index and self.loose:
                yield Segment.line()
            if self.list_type == "bullet_list_open":
                yield from item.render_bullet(console, options)
            else:
                yield from item.render_number(console, options, number + index, number + len(self.items))


class _Markdown(Markdown):
    """Rich's Markdown, with loose lists spaced. markdown-it hides the paragraphs of a tight list's
    items; a list whose own items have a paragraph that isn't hidden is loose."""

    elements = {**Markdown.elements, "bullet_list_open": _ListElement, "ordered_list_open": _ListElement}

    def __init__(self, markup: str, hyperlinks: bool = True) -> None:
        super().__init__(markup, hyperlinks=hyperlinks)
        opened: list[Token] = []
        for token in self.parsed:
            if token.type in ("bullet_list_open", "ordered_list_open"):
                opened.append(token)
            elif token.type in ("bullet_list_close", "ordered_list_close"):
                opened.pop()
            elif token.type == "paragraph_open" and opened and token.level == opened[-1].level + 2:
                if not token.hidden:
                    opened[-1].meta["loose"] = True


def _code_lines(code: list[str], width: int) -> list[str]:
    out: list[str] = []
    for line in code:
        if len(_CODE_INDENT + line) <= width:
            out.append((_CODE_INDENT + line).rstrip())
            continue
        out += textwrap.wrap(
            line,
            width,
            initial_indent=_CODE_INDENT,
            subsequent_indent=_CONTINUATION_INDENT,
            break_long_words=True,
            break_on_hyphens=False,
        )
    return out


def render(markdown: str, width: int, hyperlinks: bool = False, mark_code: bool = False) -> list[str]:
    """One section as lines at most `width` wide (see the module docstring). With `hyperlinks`, a
    link shows its text, marked as a terminal hyperlink, instead of "text (address)". With `mark_code`,
    each line of a code block starts with links.CODE_MARK and each line of a heading with HEADING_MARK,
    codes that show nothing, and bold and italic are kept as the terminal's own (for the pager's
    screen; printed text stays plain)."""
    mark = CODE_MARK if mark_code else ""
    lines: list[str] = []
    prose: list[str] = []
    code: list[str] | None = None
    # A fence indented inside a list item: its code, and the rest of the item after it, line up with the
    # item's text. Laid out on their own, the rest would otherwise end the list.
    indent = 0
    rest: list[str] | None = None

    def end_rest() -> None:
        nonlocal rest
        if rest is not None:
            pad = " " * indent
            inner = _markdown_lines("\n".join(rest), width - indent, hyperlinks, mark_code)
            lines.extend(pad + line if line else line for line in inner)
            rest = None

    for line in markdown.splitlines():
        if code is not None:
            if _FENCE.match(line):
                pad = [mark] if mark else []  # a row of code's background above and below
                shown = (
                    mark + (" " * indent + line if line else "") for line in _code_lines(code, width - indent)
                )
                lines += ["", *pad, *shown, *pad, ""]
                code = None
                rest = [] if indent else None
            else:
                code.append(line[indent:] if not line[:indent].strip() else line.lstrip())
            continue
        if rest is not None:
            if not _FENCE.match(line) and (not line.strip() or not line[:indent].strip()):
                rest.append(line[indent:])
                continue
            end_rest()
        if _FENCE.match(line):
            lines += _markdown_lines("\n".join(prose), width, hyperlinks, mark_code)
            prose = []
            code = []
            indent = len(line) - len(line.lstrip())
        else:
            prose.append(line)
    if code is not None:  # an unclosed block: show it as code anyway
        lines += [
            "",
            *(mark + (" " * indent + line if line else "") for line in _code_lines(code, width - indent)),
        ]
    end_rest()
    lines += _markdown_lines("\n".join(prose), width, hyperlinks, mark_code)
    tidy: list[str] = []
    for line in lines:
        if line or (tidy and tidy[-1]):  # no runs of blank lines, none at the top
            tidy.append(line)
    while tidy and not tidy[-1]:
        tidy.pop()
    return tidy


def looks_like_markdown(text: str) -> bool:
    """At least two headings with a blank line above and below, one of them ## or deeper.

    For a file whose name doesn't say (LICENSE, notes.txt). Comment lines in scripts and settings files
    also start with "# ", but rarely stand alone between blank lines; scripts (#!) are never Markdown.
    Tried on 4,000 files without an extension or ending in .txt: only a Markdown LICENSE matched.
    """
    if text.startswith("#!"):
        return False
    lines = text.splitlines()
    found = 0
    deeper = False
    for number, (line, outside) in enumerate(zip(lines, _outside_code(lines), strict=True)):
        if not outside or not re.match(r"^#{1,6} \S", line):
            continue
        alone_above = number == 0 or not lines[number - 1].strip()
        alone_below = number + 1 == len(lines) or not lines[number + 1].strip()
        if alone_above and alone_below:
            found += 1
            deeper = deeper or line.startswith("##")
    return found >= 2 and deeper
