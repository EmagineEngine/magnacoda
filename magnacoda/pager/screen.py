"""The screen: a small man-style pager with numbered sections (g lists them; type a number or a name).

PagerState holds the logic so it can be tested without a terminal. Standard library only.
"""

from __future__ import annotations

import bisect
import os
import re
import select
import shutil
import sys
import textwrap
import time
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

OFF_VALUES = {"off", "0", "false", "no"}
_CURSOR_HIDE = "\x1b[?25l"
_CURSOR_SHOW = "\x1b[?25h"
_CURSOR_BLOCK = "\x1b[1 q"  # a blinking block, where the terminal can
_CURSOR_USUAL = "\x1b[0 q"  # the terminal's own cursor shape again
_TITLE_PLAIN = "\x1b[1;3m"  # bold italic
_ESC_WAIT = 0.05  # how long to wait for the rest of an arrow-key sequence before calling it a bare Esc


class Action(Enum):
    NOTHING = "nothing"
    REDRAW = "redraw"
    QUIT_RESTORE = "quit_restore"  # leave the pager and restore the earlier screen
    FINISH_KEEP = "finish_keep"  # leave the pager and keep the last section printed on screen
    SAVE_COLORS = "save_colors"  # a color was chosen in the color list: redraw, then save it
    OPEN_LINK = "open_link"  # Enter on a web link: open `opening` in the browser, then redraw
    GO = "go"  # Enter in the Open list on another document: `opening_doc`, for the caller


@dataclass(frozen=True)
class Link:
    """A link on a page, as Tab visits it: its pieces as (line, start, end) in characters on screen
    (more than one when it wraps), and where it goes: a web address, or a section's number."""

    parts: tuple[tuple[int, int, int], ...]
    url: str = ""
    section: int = 0


class Outcome(Enum):
    QUIT = "quit"
    FINISHED = "finished"
    # The same, when the window changed size while paging: the screen it found may have reflowed.
    QUIT_RESIZED = "quit_resized"
    FINISHED_RESIZED = "finished_resized"
    GO = "go"  # left to show another document: the caller's `open_document` accepted it

    @property
    def resized(self) -> bool:
        return self.value.endswith("_resized")


@dataclass(frozen=True)
class OutlineRow:
    """One row of the g list when it shows a document's outline: a section (numbered), a subsection
    in it (`heading`), or a group label (`section` None), indented by `depth`."""

    depth: int
    label: str
    section: int | None = None  # an index into the sections
    heading: str = ""


@dataclass
class PagerState:
    """Current section and scroll position. `lines` are already wrapped.

    Layout: optional title row, the text, then one or two hint rows (the second only when scrolling).
    """

    sections: list[tuple[str, list[str]]]
    height: int
    index: int = 0
    top: int = 0
    title: str | None = None
    menu: bool = False
    typed: str = ""  # what is typed in the section list or the Open list
    menu_top: int = 0  # first row of the section list showing, when even in columns it is too tall
    width: int = 80  # the width of the last render, which lays out the section list
    # Color choices as (name, description), the first being the terminal's own; empty: no c key.
    colors: Sequence[tuple[str, str]] = ()
    color: int = 0  # the color in use (an index into colors)
    color_list: bool = False
    color_notes: list[str] = field(default_factory=list)  # themes left out of the colors file, and why
    color_before: int = 0  # the color when the list opened, put back by Esc
    focus: int | None = None  # the link Tab has highlighted (an index into links)
    opening: str = ""  # the address Enter is about to open
    notice: str = ""  # one line for the hint row until the next key ("Opened in your browser.")
    arrived: str = ""  # the document just opened from another, named on the hint row until a key
    menu_pick: int | None = None  # the section Tab has highlighted in the section list (with an
    # outline: the row)
    outline: list[OutlineRow] = field(default_factory=list)  # the g list as a document's outline
    carried: tuple[int, int] | None = None
    finding: bool = False  # the Find field is open (typing goes to `typed`)
    search: str = ""  # what was found last; n and p go through its matches
    match: int | None = None  # the match the page shows (an index into _found(search))
    search_note: str = ""  # added to the search hint until the next key ("back at the top")
    documents: list[Entry] = field(default_factory=list)  # the Open list (o); empty: no o key
    document: int | None = None  # the one showing (an index into documents)
    came_from: int | None = None  # the one just come from: the Open list's pick starts there
    typed_files: bool = True  # the Open list also opens a .md or .txt file typed by name
    doc_list: bool = False  # the Open list is showing (typing goes to `typed`)
    doc_pick: int | None = None
    doc_top: int = 0  # first row of the Open list showing, when it is too tall
    opening_doc: Opening | None = None  # what Enter in the Open list asks the caller to show
    front_page: bool = False  # see use_front_page
    _links: tuple[object, list[Link]] | None = field(default=None, repr=False)
    _matches: tuple[object, list[tuple[int, tuple[tuple[int, int, int], ...]]]] | None = field(
        default=None, repr=False
    )

    @property
    def color_name(self) -> str:
        return self.colors[self.color][0] if self.colors else ""

    @property
    def lines(self) -> list[str]:
        return self.sections[self.index][1]

    @property
    def single(self) -> bool:
        return len(self.sections) == 1

    @property
    def title_rows(self) -> int:
        return 2 if self.title else 0  # the title, and a blank row under it

    @property
    def fits(self) -> bool:
        """True if the whole section shows at once (with a single row of key hints)."""
        return len(self.lines) <= max(self.height - self.title_rows - 1, 1)

    @property
    def hint_rows(self) -> int:
        """The rows below the text: the key hints, and the scroll position or the Find field."""
        if self.menu or self.color_list or self.doc_list:
            return 1
        return 2 if self.searching or not self.fits else 1

    @property
    def searching(self) -> bool:
        """In search mode, from / to Esc: only the search's keys work."""
        return self.finding or bool(self.search)

    @property
    def body_height(self) -> int:
        return max(self.height - self.title_rows - self.hint_rows, 1)

    @property
    def max_top(self) -> int:
        return max(len(self.lines) - self.body_height, 0)

    def _next_top(self, top: int) -> int:
        """Where the next screen starts: on this screen's last line of text, so it shows again."""
        shown = range(top, min(top + self.body_height, len(self.lines)))
        last = next((n for n in reversed(shown) if _visible(self.lines[n]).strip()), top)
        return last if last > top else top + self.body_height

    def _page_tops(self) -> list[int]:
        """Where each screen starts when paging from the top; the last may end in blank rows."""
        tops = [0]
        while tops[-1] + self.body_height < len(self.lines):
            tops.append(self._next_top(tops[-1]))
        return tops

    @property
    def at_section_end(self) -> bool:
        return self.top + self.body_height >= len(self.lines)

    @property
    def at_last_section(self) -> bool:
        return self.index == len(self.sections) - 1

    @property
    def _count(self) -> int:
        return len(self.sections)

    def use_front_page(self) -> None:
        """The first section lists the others: it is number 0, kept out of the g list (b goes back to
        it), and they go from 1."""
        self.front_page = len(self.sections) > 1
        if self.front_page and not self.outline:
            self.outline = [OutlineRow(0, name, n) for n, (name, _) in enumerate(self.sections) if n]

    @property
    def _first(self) -> int:
        """The first section's number."""
        return 0 if self.front_page else 1

    @property
    def _last(self) -> int:
        return self._count - 1 + self._first

    def set_sections(self, sections: list[tuple[str, list[str]]], height: int) -> None:
        """Re-wrap after a resize, keeping the same section and roughly the same place in it."""
        ratio = self.top / max(len(self.lines), 1)
        self.sections = sections
        self.height = height
        self.carried = None
        self.top = min(int(ratio * len(self.lines)), self.max_top)

    def _next_screen(self) -> Action:
        if not self.at_section_end:
            top = self._next_top(self.top)
            self.carried = (self.index, top) if top < self.top + self.body_height else None
            self.top = top
            return Action.REDRAW
        if not self.at_last_section:
            self.index += 1
            self.top = 0
            return Action.REDRAW
        return Action.FINISH_KEEP

    def _previous_screen(self) -> Action:
        if self.top > 0:
            self.top = max(top for top in self._page_tops() if top < self.top)
            return Action.REDRAW
        if self.index > 0:
            self.index -= 1
            self.top = self._page_tops()[-1]
            return Action.REDRAW
        return Action.NOTHING

    def _close_menu(self) -> None:
        self.menu, self.typed, self.menu_top, self.menu_pick = False, "", 0, None

    @property
    def links(self) -> list[Link]:
        """The links in the current section, in reading order."""
        key = (self.index, id(self.lines))
        if self._links is None or self._links[0] != key:
            found = _section_links(self.lines)
            if self.front_page and self.index == 0:
                found = sorted(found + _listed_links(self.lines, self._last), key=lambda link: link.parts[0])
            self._links = (key, found)
        return self._links[1]

    def _tab(self, step: int) -> Action:
        """Highlight the next (or previous) link, scrolling it into view; round again at the end."""
        links = self.links
        if not links:
            return Action.NOTHING
        if self.focus is None:
            bottom = self.top + self.body_height
            if step > 0:
                self.focus = next((n for n, link in enumerate(links) if link.parts[0][0] >= self.top), 0)
            else:
                before = [n for n, link in enumerate(links) if link.parts[0][0] < bottom]
                self.focus = before[-1] if before else len(links) - 1
        else:
            self.focus = (self.focus + step) % len(links)
        first, last = links[self.focus].parts[0][0], links[self.focus].parts[-1][0]
        if first < self.top:
            self.top = first
        elif last >= self.top + self.body_height:
            self.top = min(max(last - self.body_height + 1, 0), self.max_top)
        return Action.REDRAW

    def _on_listed_link(self) -> bool:
        """Tab is on an item of a front page's list."""
        on = self.front_page and self.index == 0 and self.focus is not None
        return on and bool(self.links[self.focus or 0].section)

    def _follow(self) -> Action:
        link = self.links[self.focus or 0]
        self.focus = None
        if link.section:
            return self._go_to(link.section)
        self.opening = link.url
        return Action.OPEN_LINK

    def _found(self, term: str) -> list[tuple[int, tuple[tuple[int, int, int], ...]]]:
        """Every place `term` shows in the page, as (section, parts) like a Link's parts; case is
        ignored, and any run of spaces matches a line break, so a phrase that wraps is found."""
        key = (term.lower(), id(self.sections))
        if self._matches is None or self._matches[0] != key:
            self._matches = (key, _find(self.sections, term))
        return self._matches[1]

    def _find(self) -> Action:
        term = " ".join(self.typed.split())
        if not term:
            self._leave_search()
            return Action.REDRAW
        if not self._found(term):
            self.notice = f'No "{term}" in this document.'
            return Action.REDRAW
        self.finding, self.typed, self.search, self.match = False, "", term, None
        return self._next_match(1)

    def _next_match(self, step: int) -> Action:
        """The next (or previous) match after the one showing; if it isn't showing, after what the
        page shows. Past the last, round again from the top."""
        found, here = self._found(self.search), (self.index, self.top)
        places = [(section, parts[0][0]) for section, parts in found]
        if self.match is not None and self.match < len(found) and self._match_showing():
            n = self.match + step
        elif step > 0:
            n = next((n for n, place in enumerate(places) if place >= here), len(found))
        else:
            n = max((n for n, place in enumerate(places) if place < here), default=-1)
        if n >= len(found):
            n, self.search_note = 0, ", back at the top"
        elif n < 0:
            n, self.search_note = len(found) - 1, ", back at the end"
        return self._show_match(n)

    def _match_showing(self) -> bool:
        assert self.match is not None
        section, parts = self._found(self.search)[self.match]
        return section == self.index and self.top <= parts[0][0] < self.top + self.body_height

    def _show_match(self, n: int) -> Action:
        """Show match `n`, scrolling it into view a little below the top if it isn't."""
        self.match, self.focus = n, None
        section, parts = self._found(self.search)[n]
        if section != self.index:
            self.index, self.top = section, 0
        first, last = parts[0][0], parts[-1][0]
        if first < self.top or last >= self.top + self.body_height:
            self.top = min(max(first - 2, 0), self.max_top)
        return Action.REDRAW

    def _leave_search(self) -> None:
        self.finding, self.typed, self.search, self.match = False, "", "", None

    def _handle_search(self, key: str) -> Action:
        """Going through the matches: nothing else works until Esc."""
        if key in ("q", "ctrl-c", "eof"):
            return Action.QUIT_RESTORE
        if key == "esc":
            self._leave_search()
            return Action.REDRAW
        if key in ("n", "right", "enter"):
            return self._next_match(1)
        if key in ("p", "left"):
            return self._next_match(-1)
        if key in ("down", "j", "up", "k"):
            return self._scroll_line(1 if key in ("down", "j") else -1)
        if key == "/":
            self.finding, self.typed = True, self.search
            return Action.REDRAW
        if key == "resize":
            return Action.REDRAW
        return Action.NOTHING

    def _handle_find(self, key: str) -> Action:
        if key in ("ctrl-c", "eof"):
            return Action.QUIT_RESTORE
        if key == "esc":
            self._leave_search()
            return Action.REDRAW
        if key == "enter":
            return self._find()
        if key == "backspace":
            if not self.typed:
                return Action.NOTHING
            self.typed = self.typed[:-1]
            return Action.REDRAW
        char = " " if key == "space" else key
        if len(char) == 1 and char.isprintable():
            if char == " " and not self.typed:
                return Action.NOTHING
            self.typed += char
            return Action.REDRAW
        if key == "resize":
            return Action.REDRAW
        return Action.NOTHING

    def _menu_tab(self, step: int) -> Action:
        if self.outline:
            rows = self._pickable
            if self.menu_pick is None:
                self.menu_pick = rows[0] if step > 0 else rows[-1]
            else:
                self.menu_pick = rows[(rows.index(self.menu_pick) + step) % len(rows)]
            return self._show_pick()
        count = self._count
        if self.menu_pick is None:
            self.menu_pick = 0 if step > 0 else count - 1
        else:
            self.menu_pick = (self.menu_pick + step) % count
        return self._show_pick()

    def _typed_pick(self) -> int | None:
        """The first entry, in reading order, that what is typed highlights; None if none."""
        matched = self._matched()
        if self.outline:
            return next(
                (n for n in self._pickable if (self.outline[n].section, self.outline[n].heading) in matched),
                None,
            )
        return next((n for n in range(self._count) if (n, "") in matched), None)

    def _menu_arrow(self, key: str) -> Action:
        """Move the pick like in a grid: up and down within a column, left and right to the same row
        in the next column (the list fills each column top to bottom); stop at the edges."""
        if self.outline:
            return self._outline_arrow(key)
        count, rows = self._count, self._menu_layout()[1]
        forward = key in ("down", "j", "right")
        if self.menu_pick is None:
            self.menu_pick = 0 if forward else count - 1
            return self._show_pick()
        pick = self.menu_pick
        if key in ("left", "right"):
            new = pick + (rows if forward else -rows)
        else:
            new = pick + (1 if forward else -1)
            if new // rows != pick // rows:
                new = -1  # off the end of the column
        if not 0 <= new < count:
            return Action.NOTHING
        self.menu_pick = new
        return self._show_pick()

    @property
    def _pickable(self) -> list[int]:
        """The outline's rows that go somewhere (not group labels)."""
        return [n for n, row in enumerate(self.outline) if row.section is not None]

    def _outline_arrow(self, key: str) -> Action:
        """Up and down: the previous or next row in reading order; left and right: the nearest row in
        the column beside it. Group labels are passed over; the edges stop."""
        rows, forward = self._pickable, key in ("down", "j", "right")
        if self.menu_pick is None:
            self.menu_pick = rows[0] if forward else rows[-1]
            return self._show_pick()
        if key in ("up", "down", "j", "k"):
            at = rows.index(self.menu_pick) + (1 if forward else -1)
            if not 0 <= at < len(rows):
                return Action.NOTHING
            self.menu_pick = rows[at]
            return self._show_pick()
        columns = self._outline_layout()[0]
        column = next(c for c, entries in enumerate(columns) if self.menu_pick in entries)
        row = columns[column].index(self.menu_pick)
        beside = column + (1 if forward else -1)
        if not 0 <= beside < len(columns):
            return Action.NOTHING
        choices = [(abs(r - row), n) for r, n in enumerate(columns[beside]) if n is not None and n in rows]
        self.menu_pick = min(choices)[1]
        return self._show_pick()

    def _outline_rows(self) -> list[int | None]:
        """The outline's rows, with a blank row (None) before each group label after the first."""
        rows: list[int | None] = []
        for n, row in enumerate(self.outline):
            if row.section is None and rows:
                rows.append(None)
            rows.append(n)
        return rows

    def _outline_layout(self) -> tuple[list[list[int | None]], list[int]]:
        """The outline's rows per column, filled top to bottom like ls, and each column's width: as
        few columns as fit the window's height, the longest names shortened (…) if needed; when even
        the most that fit its width are too tall, the list scrolls. No column starts or ends blank."""
        rows, room = self._outline_rows(), self._menu_room()

        def columns_of(count: int) -> list[list[int | None]]:
            height = -(-len(rows) // count)
            columns = []
            for start in range(0, len(rows), height):
                column = rows[start : start + height]
                while column and column[0] is None:
                    column = column[1:]
                while column and column[-1] is None:
                    column = column[:-1]
                columns.append(column)
            return [column for column in columns if column]

        one = columns_of(1)
        best = (one, [min(self._outline_width(one[0]), max(self.width - _MENU_INDENT, 1))])
        for count in range(2, len(rows) + 1):
            if max(len(column) for column in best[0]) <= room:
                break
            columns = columns_of(count)
            widths = _capped(
                [self._outline_width(column) for column in columns],
                self.width - _MENU_INDENT - _MENU_GAP * (len(columns) - 1),
            )
            if widths is None:
                break
            best = (columns, widths)
        return best

    def _outline_text(self, n: int) -> str:
        row, digits = self.outline[n], len(str(self._last))
        if row.section is None or self.single:  # a group label, or a one-page table of contents
            return "  " * row.depth + row.label
        if row.heading:  # a subsection: a hyphen under the first letter of its section's name
            return f"{'':>{digits}}  {'  ' * max(row.depth - 1, 0)}- {row.label}"
        return f"{row.section + self._first:>{digits}}  {'  ' * row.depth}{row.label}"

    def _outline_width(self, column: list[int | None]) -> int:
        return max(len(self._outline_text(n)) for n in column if n is not None)

    def _menu_height(self) -> int:
        """Rows the section list takes, in its columns."""
        if self.outline:
            return max(len(column) for column in self._outline_layout()[0])
        return self._menu_layout()[1]

    def _heading_line(self, heading: str) -> int:
        """The line of the section where its `###` heading starts (0 if not found)."""
        shown = [_visible(line).strip() for line in self.lines]
        if heading in shown:
            return shown.index(heading)
        for number, text in enumerate(shown):  # a heading wrapped onto more lines
            if text and heading.startswith(text) and len(text) * 2 > len(heading):
                return number
        return 0

    def _scroll_line(self, step: int) -> Action:
        new = min(max(self.top + step, 0), max(self.max_top, self.top))
        if new == self.top:
            return Action.NOTHING
        self.top = new
        return Action.REDRAW

    def _show_pick(self) -> Action:
        """Scroll the section list so the pick is in view."""
        assert self.menu_pick is not None
        room = self._menu_room()
        if self.outline:
            row = next(c.index(self.menu_pick) for c in self._outline_layout()[0] if self.menu_pick in c)
        else:
            row = self.menu_pick % self._menu_layout()[1]
        if row < self.menu_top:
            self.menu_top = row
        elif row >= self.menu_top + room:
            self.menu_top = row - room + 1
        return Action.REDRAW

    def _menu_room(self) -> int:
        """Rows available for the section list."""
        return max(self.height - self.title_rows - 3, 1)

    def _menu_layout(self) -> tuple[int, int, list[int]]:
        """(columns, rows, name width) for the section list: as few columns as fit, shortening the
        widest names with "…" if needed; scrolls if it's still too tall."""
        names = [len(name) for name, _ in self.sections]
        room = self._menu_room()
        best = (1, len(names), _name_rooms(names, 1, self.width, len(str(self._last))))
        for columns in range(1, len(names) + 1):
            rows = -(-len(names) // columns)
            widths = _name_rooms(names, columns, self.width, len(str(self._last)))
            if columns > 1 and min(widths) < min(_MENU_MIN_NAME, *_column_longest(names, columns)):
                break  # too narrow: keep the last layout that wasn't, and let it scroll
            best = (columns, rows, widths)
            if rows <= room:
                break
        return best

    @property
    def menu_scrolls(self) -> bool:
        return self.menu and self._menu_height() > self._menu_room()

    def _menu_last_top(self) -> int:
        return max(self._menu_height() - self._menu_room(), 0)  # rows past the screen

    def _menu_scroll_end(self) -> bool:
        return self.menu_top >= self._menu_last_top()

    def _menu_scroll(self, step: int) -> Action:
        new = min(max(self.menu_top + step, 0), self._menu_last_top())
        if new == self.menu_top:
            return Action.NOTHING
        self.menu_top = new
        return Action.REDRAW

    def _go_to(self, number: int) -> Action:
        self.index, self.top, self.focus = number - 1, 0, None
        self._close_menu()
        return Action.REDRAW

    def _enter(self) -> Action:
        """Go where the typed text says: a section's number or name. Nothing typed: the pick, or back
        to the page. q quits, and a leading colon is dropped, so vi's and less's :q works too."""
        text = self.typed.strip().removeprefix(":").strip()
        if text.lower() == "q":
            return Action.QUIT_RESTORE
        if not text and self.menu_pick is not None:
            return self._go_to_pick()
        if not text:
            self._close_menu()
            return Action.REDRAW
        if text.isdigit():
            if 1 <= int(text) <= self._last:
                return self._go_to(int(text) - self._first + 1)
            self.notice = f"No section {text}: they go from 1 to {self._last}."
            return Action.REDRAW
        if text.lower() == "o" and self.documents:
            self._close_menu()
            self._open_doc_list()
            return Action.REDRAW
        if not _long_enough(text):
            self.notice = _TOO_SHORT
            return Action.REDRAW
        targets = self._targets()
        matches = section_matches([name for _, _, name in targets], text)
        if len(matches) == 1:
            section, heading, _ = targets[matches[0]]
            return self._go_to_place(section, heading)
        if matches:
            names = ", ".join(dict.fromkeys(targets[n][2] for n in matches))
            self.notice = f"'{text}' fits more than one section: {names}. Type more of it."
            return Action.REDRAW
        self.notice = f"No section named '{text}'." + (
            " For other documents, type o, then Enter." if self.documents else ""
        )
        return Action.REDRAW

    def _targets(self) -> list[tuple[int, str, str]]:
        """Where a typed name can go, as (section, heading, name): each section, and with an outline
        the subsections in it too."""
        sections = [(n, "", name) for n, (name, _) in enumerate(self.sections)]
        return sections + [
            (row.section, row.heading, row.label)
            for row in self.outline
            if row.section is not None and row.heading
        ]

    def _go_to_place(self, section: int, heading: str = "") -> Action:
        action = self._go_to(section + 1)
        if heading:
            self.top = min(self._heading_line(heading), self.max_top)
        return action

    def _go_to_pick(self) -> Action:
        assert self.menu_pick is not None
        if not self.outline:
            return self._go_to(self.menu_pick + 1)
        row = self.outline[self.menu_pick]
        assert row.section is not None
        return self._go_to_place(row.section, row.heading)

    def _handle_menu(self, key: str) -> Action:
        if key in ("ctrl-c", "eof"):
            return Action.QUIT_RESTORE
        if key == "esc":
            self._close_menu()
            return Action.REDRAW
        if key == "enter":
            return self._enter()
        if key == "backspace":
            if not self.typed:
                return Action.NOTHING
            self.typed = self.typed[:-1]
            return Action.REDRAW
        if key == "/":  # a search of the whole document, from the page Esc would return to
            self._close_menu()
            self.finding = True
            return Action.REDRAW
        char = " " if key == "space" else key
        if len(char) == 1 and char.isprintable():  # letters, digits and the rest are typed
            if char == " " and not self.typed:
                return Action.NOTHING
            self.typed, self.menu_pick = self.typed + char, None
            return Action.REDRAW
        if key in ("tab", "shift-tab", "up", "down", "left", "right") and self.menu_pick is None:
            start = self._typed_pick()
            if start is not None:  # what was typed has picked an entry, as Tab would: go on from it
                self.typed, self.menu_pick = "", start
                if key in ("tab", "shift-tab"):
                    return self._show_pick()
        if key in ("tab", "shift-tab", "up", "down", "left", "right"):
            self.typed = ""  # picking replaces what was typed
            if key in ("tab", "shift-tab"):
                return self._menu_tab(1 if key == "tab" else -1)
            return self._menu_arrow(key)
        if key in ("pgdn", "pgup", "home", "end"):
            page = self._menu_room()
            steps = {"pgdn": page, "pgup": -page}
            return self._menu_scroll(steps.get(key, -self._count if key == "home" else self._count))
        if key == "resize":
            self.menu_top = 0
            return Action.REDRAW
        return Action.NOTHING

    def _open_doc_list(self) -> None:
        self.doc_list, self.typed, self.doc_top = True, "", 0
        self.doc_pick = self.came_from if self.came_from is not None else self.document
        if self.doc_pick is not None:
            self._show_doc_pick()

    def _close_doc_list(self) -> Action:
        self.doc_list, self.typed, self.doc_top, self.doc_pick = False, "", 0, None
        return Action.REDRAW

    def _doc_rows(self) -> list[int | str | None]:
        """The Open list's rows: a group's name, a document (its index), or a blank row between groups."""
        rows: list[int | str | None] = []
        group: str | None = None
        for n, entry in enumerate(self.documents):
            if entry.group != group:
                if rows:
                    rows.append(None)
                if entry.group:
                    rows.append(entry.group)
                group = entry.group
            rows.append(n)
        return rows

    def _doc_lines(self) -> list[str]:
        matched = self._doc_matched()
        lines = []
        for row in self._doc_rows():
            if row is None or isinstance(row, str):
                lines.append(" " * _MENU_INDENT + row if row else "")
                continue
            entry = self.documents[row]
            indent = _MENU_INDENT * 2 if entry.group else _MENU_INDENT
            mark = " (open)" if row == self.document else ""
            name = _shorten(entry.title, max(self.width - indent - len(mark), 1))
            if row == self.doc_pick or row in matched:
                lines.append(" " * (indent - 2) + f"\x1b[7m{_PICKED}{name}\x1b[27m" + mark)
            else:
                lines.append(" " * indent + name + mark)
        visible = lines[self.doc_top : self.doc_top + self._menu_room()]
        return [self._field_line(), "", *visible]

    def _show_doc_pick(self) -> Action:
        assert self.doc_pick is not None
        row, room = self._doc_rows().index(self.doc_pick), self._menu_room()
        if row < self.doc_top:
            self.doc_top = max(row - 1, 0)  # its group's name too
        elif row >= self.doc_top + room:
            self.doc_top = row - room + 1
        return Action.REDRAW

    def _doc_scrolls(self) -> bool:
        return len(self._doc_rows()) > self._menu_room()

    def _doc_named(self, text: str) -> tuple[list[int], str]:
        """The documents the typed text's first words could name, and the rest (a section in it)."""
        words = text.split()
        if not words or not _long_enough(words[0]):
            return [], ""
        for count in range(len(words), 0, -1):
            found = _document_matches(self.documents, " ".join(words[:count]))
            if found:
                return found, " ".join(words[count:])
        return [], ""

    def _doc_matched(self) -> set[int]:
        text = self.typed.strip()
        if not text or (self.typed_files and looks_like_a_file(text)):
            return set()
        return set(self._doc_named(text)[0])

    def _open_doc(self, n: int, section: str = "") -> Action:
        if n == self.document:
            if not section:
                return self._close_doc_list()
            targets = self._targets()
            found = section_matches([name for _, _, name in targets], section)
            if len(found) != 1:
                self.notice = f"No section named '{section}' in {self.documents[n].title}."
                return Action.REDRAW
            self._close_doc_list()
            place, heading, _ = targets[found[0]]
            return self._go_to_place(place, heading)
        self.opening_doc = Opening(self.documents[n], section, back=n == self.came_from and not section)
        return Action.GO

    def _open_typed_file(self, text: str) -> Action:
        path = Path(text).expanduser()
        if path.suffix.lower() not in TYPED_SUFFIXES:
            self.notice = f"Only {' and '.join(TYPED_SUFFIXES)} files open here."
            return Action.REDRAW
        if not path.is_file():
            self.notice = f"No file named '{text}'."
            return Action.REDRAW
        known = index_of(self.documents, path)
        if known is not None:
            return self._open_doc(known)
        self.opening_doc = Opening(Entry(path.name, path))
        return Action.GO

    def _doc_enter(self) -> Action:
        """Open what the typed text names: a document on the list (and a section in it), or a file.
        Nothing typed: the pick. The one showing goes back to it, as Esc does."""
        text = self.typed.strip().removeprefix(":").strip()
        if text.lower() == "q":
            return Action.QUIT_RESTORE
        if not text:
            return self._close_doc_list() if self.doc_pick is None else self._open_doc(self.doc_pick)
        if text.lower() == "g":
            self._close_doc_list()
            self.menu = True
            return Action.REDRAW
        if self.typed_files and looks_like_a_file(text):
            return self._open_typed_file(text)
        if not _long_enough(text.split()[0]):
            self.notice = _TOO_SHORT
            return Action.REDRAW
        found, section = self._doc_named(text)
        if len(found) == 1:
            return self._open_doc(found[0], section)
        if found:
            names = ", ".join(self.documents[n].title for n in found)
            self.notice = f"'{text}' fits more than one document: {names}. Type more of it."
        elif self.typed_files and Path(text).expanduser().is_file():
            self.notice = f"Only {' and '.join(TYPED_SUFFIXES)} files open here."
        else:
            self.notice = f"No document named '{text}'."
        return Action.REDRAW

    def _move_doc_pick(self, key: str) -> Action:
        last, forward = len(self.documents) - 1, key in ("tab", "down", "right")
        if self.doc_pick is None:
            self.doc_pick = 0 if forward else last
        elif key in ("tab", "shift-tab"):
            self.doc_pick = (self.doc_pick + (1 if forward else -1)) % len(self.documents)
        else:
            new = self.doc_pick + (1 if forward else -1)
            if not 0 <= new <= last:
                return Action.NOTHING
            self.doc_pick = new
        return self._show_doc_pick()

    def _handle_doc_list(self, key: str) -> Action:
        if key in ("ctrl-c", "eof"):
            return Action.QUIT_RESTORE
        if key == "esc":
            return self._close_doc_list()
        if key == "enter":
            return self._doc_enter()
        if key == "backspace":
            if not self.typed:
                return Action.NOTHING
            self.typed = self.typed[:-1]
            return Action.REDRAW
        char = " " if key == "space" else key
        if len(char) == 1 and char.isprintable():
            if char == " " and not self.typed:
                return Action.NOTHING
            self.typed, self.doc_pick = self.typed + char, None
            return Action.REDRAW
        if key in ("tab", "shift-tab", "up", "down", "left", "right"):
            self.typed = ""
            return self._move_doc_pick(key)
        if key in ("pgdn", "pgup", "home", "end"):
            room, rows = self._menu_room(), len(self._doc_rows())
            steps = {"pgdn": room, "pgup": -room, "home": -rows, "end": rows}
            new = min(max(self.doc_top + steps[key], 0), max(rows - room, 0))
            if new == self.doc_top:
                return Action.NOTHING
            self.doc_top = new
            return Action.REDRAW
        if key == "resize":
            self.doc_top = 0
            if self.doc_pick is not None:
                self._show_doc_pick()
            return Action.REDRAW
        return Action.NOTHING

    def _handle_color_list(self, key: str) -> Action:
        if key in ("ctrl-c", "eof"):
            return Action.QUIT_RESTORE
        if key in ("down", "j", "up", "k"):
            step = 1 if key in ("down", "j") else -1
            new = min(max(self.color + step, 0), len(self.colors) - 1)
            if new == self.color:
                return Action.NOTHING
            self.color = new
            return Action.REDRAW
        if key.isdigit() and 1 <= int(key) <= min(len(self.colors), 9):
            self.color = int(key) - 1
            self.color_list = False
            return Action.SAVE_COLORS
        if key == "enter":
            self.color_list = False
            return Action.SAVE_COLORS
        if key in ("esc", "q", "c"):
            self.color, self.color_list = self.color_before, False
            return Action.REDRAW
        if key == "resize":
            return Action.REDRAW
        return Action.NOTHING

    def handle(self, key: str) -> Action:
        had_notice, self.notice = bool(self.notice or self.search_note or self.arrived), ""
        self.arrived = ""
        self.search_note = ""
        action = self._handle(key)
        if self.carried != (self.index, self.top):
            self.carried = None
        return Action.REDRAW if had_notice and action is Action.NOTHING else action

    def _handle(self, key: str) -> Action:
        if self.color_list:
            return self._handle_color_list(_PAGE_KEYS.get(key, key))
        if self.doc_list:
            return self._handle_doc_list(key)
        if self.menu:
            return self._handle_menu(key)
        if self.finding:
            return self._handle_find(key)
        key = _PAGE_KEYS.get(key, key)
        if self.search:
            return self._handle_search(key)
        if key in ("tab", "shift-tab"):
            return self._tab(1 if key == "tab" else -1)
        if self.focus is not None:
            if key == "enter":
                return self._follow()
            if key in ("up", "down") and self._on_listed_link():
                step = 1 if key == "down" else -1
                ahead = self.focus + step
                inside = 0 <= ahead < len(self.links) and self.links[ahead].section
                return self._tab(step) if inside else Action.NOTHING  # item to item, as in the g list
            if key in ("up", "down", "j", "k"):  # scroll and keep the link, as a browser does
                return self._scroll_line(1 if key in ("down", "j") else -1)
            self.focus = None  # any other key lets go of the link first
            if key == "esc":
                return Action.REDRAW
            action = self._handle(key)
            return Action.REDRAW if action is Action.NOTHING else action
        if key == "c":
            if not self.colors:
                return Action.NOTHING
            self.color_list, self.color_before = True, self.color
            return Action.REDRAW
        if key == "/":
            self.finding = True
            return Action.REDRAW
        if key == "o":
            if not self.documents:
                return Action.NOTHING
            self._open_doc_list()
            return Action.REDRAW
        if key in ("esc", "q", "ctrl-c", "eof"):
            return Action.QUIT_RESTORE
        if key in ("space", "pgdn", "f", "enter", "right", "n"):
            return self._next_screen()
        if key == "b" and self.front_page and self.index > 0:
            self.index, self.top, self.focus = 0, 0, None
            return Action.REDRAW
        if key in ("b", "pgup", "left", "p"):
            return self._previous_screen()
        if key in ("g", ":"):
            if self.single and not self.documents and not self.outline:
                return Action.NOTHING
            self.menu = True  # with one section too, where its list leads to the Open list
            return Action.REDRAW
        if key.isdigit():
            if self.single:
                return Action.NOTHING
            self.menu, self.typed = True, key  # the list opens with the digit typed; Enter goes
            return Action.REDRAW
        if key in ("down", "j", "up", "k"):
            return self._scroll_line(1 if key in ("down", "j") else -1)
        if key == "home":
            changed = self.top != 0
            self.top = 0
            return Action.REDRAW if changed else Action.NOTHING
        if key == "end":
            changed = self.top != self.max_top
            self.top = self.max_top
            return Action.REDRAW if changed else Action.NOTHING
        if key == "resize":
            return Action.REDRAW
        return Action.NOTHING

    def status_rows(self, width: int) -> list[str]:
        """The key hints: each row is the longest of its wordings that fits `width`."""
        if self.color_list:
            return [
                _fit(
                    width,
                    f"Choose: ↑ ↓ or 1-{min(len(self.colors), 9)} | Keep: Enter | Esc to go back",
                    "↑ ↓ choose | Enter keep | Esc back",
                    "↑↓ Enter Esc",
                )
            ]
        if self.doc_list:
            return [self._doc_list_hint(width)]
        if self.menu and self.notice:
            return [_fit(width, self.notice)]
        if self.menu and self.menu_pick is not None and not self.typed and self.outline:
            row = self.outline[self.menu_pick]
            assert row.section is not None
            name = self.sections[row.section][0]
            where = f"{row.section + self._first}, {name}" + (f" › {row.heading}" if row.heading else "")
            return [
                _fit(
                    width,
                    f"Links: {where} | Go: Enter | Move: ↑ ↓ ← → Tab | Back: Esc",
                    f"Links: {where} | Enter go | Esc back",
                    f"Links: {row.section + self._first} | Enter go | ↑↓←→ move | Esc back",
                    f"{row.section + self._first} Enter ↑↓←→ Esc",
                )
            ]
        if self.menu and self.menu_pick is not None and not self.typed:
            name = self.sections[self.menu_pick][0]
            return [
                _fit(
                    width,
                    f"Links: {self.menu_pick + 1}, {name} | Go: Enter | Move: ↑ ↓ ← → Tab | Back: Esc",
                    f"Links: {self.menu_pick + 1} | Enter go | ↑↓←→ move | Esc back",
                    f"{self.menu_pick + 1} Enter ↑↓←→ Esc",
                )
            ]
        if self.menu:
            key, word = ("PgUp", "less") if self._menu_scroll_end() else ("PgDn", "more")
            more, short_more = (
                (f" | {word.title()}: {key}", f" | {key} {word}") if self.menu_scrolls else ("", "")
            )
            what, short = ("a name", "Name") if self.single else ("a number or name", "Number or name")
            other, short_other = (" | Open: o, Enter", " | o, Enter open") if self.documents else ("", "")
            if self.arrived:
                return [
                    _fit(
                        width,
                        f"Opened {self.arrived} | Back: o, Enter | Go: type {what}, then Enter",
                        f"Opened {self.arrived} | Back: o, Enter | Go: {short.lower()}, then Enter",
                        f"Opened {self.arrived} | o, Enter back | Type, then Enter",
                        "o, Enter back | Type, then Enter",
                        "o, Enter back",
                    )
                ]
            return [
                _fit(
                    width,
                    f"Type {what}, then Enter{other} | Pick: ↑ ↓ ← → Tab | Search: /{more} | Back: Esc",
                    f"Type {what}, then Enter{other} | Pick: ↑ ↓ ← → Tab{more} | Back: Esc",
                    f"Type {what}, then Enter{other}{more} | Back: Esc",
                    f"{short}, then Enter{short_other} | ↑↓←→ pick{short_more} | Esc back",
                    f"{short}, then Enter{short_other}{short_more} | Esc back",
                    f"{short}, then Enter{short_other} | Esc back",
                    f"Type, then Enter{short_other} | Esc back",
                    f"Enter go{short_other} | Esc back",
                )
            ]
        if self.searching:
            return [self._find_row(width), self._search_keys(width)]
        if self.notice:
            return [_fit(width, self.notice), *self._page_rows(width)[1:]]
        if self.arrived:
            return [self._arrival_row(width), *self._page_rows(width)[1:]]
        if self.focus is not None:
            return [self._link_row(width), *self._page_rows(width)[1:]]
        return self._page_rows(width)

    def _arrival_row(self, width: int) -> str:
        """Where the page came from and how to go back, keeping g where there is a Go to list."""
        name = self.arrived
        if self.single and not self.outline:
            return _fit(
                width, f"Opened {name} | Back: o, Enter", f"Opened {name} | o, Enter back", "o, Enter back"
            )
        return _fit(
            width,
            f"Opened {name} | Back: o, Enter | Go: g",
            f"Opened {name} | o, Enter back | g go",
            "o, Enter back | g go",
            "o, Enter back",
        )

    def _doc_list_hint(self, width: int) -> str:
        if self.notice:
            return _fit(width, self.notice)
        if self.doc_pick is not None and not self.typed:
            title = self.documents[self.doc_pick].title
            if self.doc_pick == self.document:
                return _fit(
                    width,
                    f"{title} is open | Back to it: Enter or Esc | Go to: g, Enter | Move: ↑ ↓ Tab",
                    f"{title} is open | Back to it: Enter or Esc | Go to: g, Enter",
                    f"{title} is open | Enter or Esc back | g, Enter go to",
                    "Enter or Esc back | g, Enter go to",
                    "Enter Esc ↑↓",
                )
            return _fit(
                width,
                f"Open {title}: Enter | Go to: g, Enter | Move: ↑ ↓ Tab | Back: Esc",
                f"Open {title}: Enter | Go to: g, Enter | Back: Esc",
                f"{title} | Enter open | g, Enter go to | Esc back",
                "Enter open | g, Enter go to | Esc back",
                "Enter ↑↓ Esc",
            )
        what, short = (
            ("a name or a file (.md, .txt)", "Name or file") if self.typed_files else ("a name", "Name")
        )
        if self._doc_scrolls():
            key, word = ("PgUp", "less") if self.doc_top else ("PgDn", "more")
            more, short_more = f" | {word.title()}: {key}", f" | {key} {word}"
        else:
            more = short_more = ""
        other, short_other = " | Go to: g, Enter", " | g, Enter go to"
        return _fit(
            width,
            f"Type {what}, then Enter{other} | Pick: ↑ ↓{more} | Back: Esc",
            f"Type {what}, then Enter{other}{more} | Back: Esc",
            f"{short}, then Enter{short_other} | ↑↓ pick{short_more} | Esc back",
            f"{short}, then Enter{short_other} | Esc back",
            f"Type, then Enter{short_other} | Esc back",
            f"Enter open{short_other} | Esc back",
        )

    def _find_row(self, width: int) -> str:
        """The Find field, with what is being typed or what was found and where the page is in it."""
        row = _PLAIN_ROW + self._field_line()
        if not self.finding and self.match is not None:
            count = len(self._found(self.search))
            row += f"  {self.match + 1} of {count}{self.search_note}"
        return row

    def _search_keys(self, width: int) -> str:
        if self.notice:
            return _fit(width, self.notice)
        if self.finding:
            return _fit(
                width,
                "Type a word or phrase, then Enter | Done: Esc",
                "Word or phrase, then Enter | Esc done",
                "Type, then Enter | Esc done",
                "Enter find | Esc done",
            )
        return _fit(
            width,
            "Next: n or → | Previous: p or ← | Scroll: ↑ ↓ | Change: / | Done: Esc",
            "n/→ next | p/← previous | ↑↓ scroll | / change | Esc done",
            "n next | p previous | / change | Esc done",
            "n p / Esc",
        )

    def _link_row(self, width: int) -> str:
        link, n, count = self.links[self.focus or 0], (self.focus or 0) + 1, len(self.links)
        if link.section and self.front_page and self.index == 0:
            name = self.sections[link.section - 1][0] if link.section <= self._count else ""
            return _fit(
                width,
                f"{link.section - 1}, {name} | Read: Enter | Move: ↑ ↓ Tab | Back: Esc",
                f"{link.section - 1} | Enter read | ↑↓ Tab move | Esc back",
                f"{link.section - 1} Enter ↑↓ Esc",
            )
        if link.section:
            name = self.sections[link.section - 1][0] if link.section <= self._count else ""
            return _fit(
                width,
                f"Links {n} of {count}: section {link.section}, {name} | Go: Enter | Next: Tab | Esc: cancel",
                f"Links {n}/{count}: section {link.section} | Enter go | Tab next | Esc cancel",
                f"Links {n}/{count} | Enter go | Tab next | Esc cancel",
                f"{n}/{count} Enter Tab Esc",
            )
        return _fit(
            width,
            f"Links {n} of {count}: {link.url} | Open: Enter | Next: Tab | Esc: cancel",
            f"Links {n} of {count} | Open in your browser: Enter | Next: Tab | Back: Shift+Tab | Esc: cancel",
            f"Links {n}/{count} | Enter open | Tab next | Esc cancel",
            f"{n}/{count} Enter Tab Esc",
        )

    def _page_rows(self, width: int) -> list[str]:
        g, short_g = (" | Go: g", " | g go") if self.outline else ("", "")
        if self.single and self.fits:
            if self.documents:
                return [
                    _fit(
                        width,
                        f"Open: o{g} | Quit: Esc",
                        f"o open{short_g} | Esc quit",
                        f"{short_g[3:]} | Esc quit" if g else "Esc quit",
                        "Esc quit",
                    )
                ]
            return [_fit(width, f"Quit: Esc{g}", f"Esc quit{short_g}", "Esc quit")]
        name = self.sections[self.index][0]
        if self.front_page:
            return self._front_page_rows(width, name)
        step = "Finish" if self.at_section_end and self.at_last_section else "Next"
        # One key each, the one a newcomer would try; Space, b and q work too, for those who know them.
        keys = f"Back: ← | {step}: → | Quit: Esc"
        short = f"← back | → {step.lower()} | Esc quit"
        tiny = f"→ {step.lower()}  Esc quit"
        long_c, short_c = (" | Colors: c", " | c colors") if self.colors else ("", "")
        where = f"Section {self.index + 1} of {len(self.sections)}: {name}"
        brief = f"{self.index + 1}/{len(self.sections)}"
        opens = []  # with an Open list, its hint stays while it can
        if self.documents and self.single:
            opens = [
                f"{name}{g} | Open: o | Find: /{long_c} | {keys}",
                f"{name}{short_g} | o open | / find{short_c} | {short}",
            ]
        elif self.documents:
            opens = [
                f"{where} | Go: g | Open: o | Find: /{long_c} | {keys}",
                f"{brief} {name} | Go: g | Open: o | Find: /{long_c} | {keys}",
                f"{brief} {name} | g go | o open | / find{short_c} | {short}",
                f"{brief} {name} | g go | o open{short_c} | {short}",  # find goes first, then the name
                f"{brief} | g go | o open{short_c} | {short}",
                f"{brief} | g go | o open | {short}",
            ]
        if self.single:
            first = _fit(
                width,
                *opens,
                f"{name}{g} | Find: /{long_c} | {keys}",
                f"{name}{short_g} | / find{short_c} | {short}",
                f"{name}{g} | {keys}{long_c}",
                f"{name}{short_g} | {short}{short_c}",
                f"{name}{g} | {keys}",
                *([f"{short_g[3:]} | {short}"] if g else []),
                keys,
                short,
                tiny,
            )
        else:
            first = _fit(
                width,
                *opens,
                f"{where} | Go: g | Find: /{long_c} | {keys}",
                f"{brief} {name} | Go: g | Find: /{long_c} | {keys}",
                f"{brief} {name} | g go | / find{short_c} | {short}",  # find goes before the name does
                f"{where} | Go: g{long_c} | {keys}",
                f"{brief} {name} | Go: g{long_c} | {keys}",
                f"{brief} {name} | g go{short_c} | {short}",
                f"{brief} | g go{short_c} | {short}",  # the colors hint goes only after this
                f"{where} | Go: g | {keys}",
                f"{brief} {name} | Go: g | {keys}",
                f"{brief} {name} | g go | {short}",
                f"{brief} | g go | {short}",  # a long section name goes before the g hint does
                f"{brief} | {short}",
                tiny,
            )
        if self.fits:
            return [first]
        last = min(self.top + self.body_height, len(self.lines))
        where = f"{self.top + 1}-{last} of {len(self.lines)}"
        return [first, _fit(width, f"Scroll: ↑ ↓ | lines {where}", f"↑↓ lines {where}", where)]

    def _front_page_rows(self, width: int, name: str) -> list[str]:
        if self.index == 0:
            first = _fit(
                width,
                "Read one: its number then Enter, or Tab | Scroll: ↑ ↓ | Quit: Esc",
                "Read: number Enter, or Tab | ↑↓ scroll | Esc quit",
                "Read: number Enter | ↑↓ scroll | Esc quit",
                "number Enter | Esc quit",
                "Esc quit",
            )
        else:
            brief = f"{self.index}/{self._last}"
            first = _fit(
                width,
                f"{brief} {name} | Back to the list: b | Previous: ← | Next: → | Quit: Esc",
                f"{brief} {name} | b list | ← previous | → next | Esc quit",
                f"{brief} | b list | ← previous | → next | Esc quit",
                f"{brief} | b list | ← → | Esc quit",
                "b list  Esc quit",
            )
        if self.fits:
            return [first]
        last = min(self.top + self.body_height, len(self.lines))
        where = f"{self.top + 1}-{last} of {len(self.lines)}"
        return [first, _fit(width, f"Scroll: ↑ ↓ | lines {where}", f"↑↓ lines {where}", where)]

    def status(self, width: int) -> str:
        """All the key hints on one line (for tests and simple callers)."""
        return " / ".join(self.status_rows(width))

    def _outline_lines(self) -> list[str]:
        """The outline in columns: group labels with a blank row above, sections numbered under them,
        subsections indented under those."""
        columns, widths = self._outline_layout()
        matched = self._matched()
        lines = []
        for row in range(max(len(column) for column in columns)):
            parts = []
            for column, entries in enumerate(columns):
                n = entries[row] if row < len(entries) else None
                if n is None:
                    parts.append(" " * (widths[column] + len(_PICKED)))
                    continue
                text = _shorten(self._outline_text(n), widths[column])
                pad = " " * (widths[column] - len(text))
                picked = n == self.menu_pick or (self.outline[n].section, self.outline[n].heading) in matched
                lead = "  " + text[: len(text) - len(text.lstrip())]  # the slot, number column and indent
                if picked:  # the mark in the last two spaces before the name
                    parts.append(f"{lead[:-2]}\x1b[7m{_PICKED}{text.lstrip()}\x1b[27m{pad}")
                else:
                    parts.append(f"  {text}{pad}")
            lines.append((" " * (_MENU_INDENT - 2) + (" " * (_MENU_GAP - 2)).join(parts)).rstrip())
        visible = lines[self.menu_top : self.menu_top + self._menu_room()]
        return [self._field_line(), "", *visible]

    def _menu_lines(self) -> list[str]:
        """The section list in columns, filled top to bottom like ls."""
        if self.outline:
            return self._outline_lines()
        columns, rows, widths = self._menu_layout()
        digits = len(str(self._last))
        matched = self._matched()
        lines = []
        for row in range(rows):
            parts = []
            for column in range(columns):
                n = column * rows + row
                if n < self._count:
                    name = _shorten(self.sections[n][0], widths[column])
                    entry = f"{n + self._first:>{digits}}  {name}"
                    pad = " " * (digits + 2 + widths[column] - len(entry))
                    marked = n == self.menu_pick or (n, "") in matched
                    parts.append(f"\x1b[7m{_PICKED}{entry}\x1b[27m{pad}" if marked else f"  {entry}{pad}")
            lines.append((" " * (_MENU_INDENT - 2) + (" " * (_MENU_GAP - 2)).join(parts)).rstrip())
        visible = lines[self.menu_top : self.menu_top + self._menu_room()]
        return [self._field_line(), "", *visible]

    def _matched(self) -> set[tuple[int, str]]:
        """Where what is typed would go, as (section, heading); more than one: it fits several."""
        text = self.typed.strip()
        if text.isdigit():
            return {(int(text) - self._first, "")} if 1 <= int(text) <= self._last else set()
        if not _long_enough(text):
            return set()
        targets = self._targets()
        return {targets[n][:2] for n in section_matches([name for _, _, name in targets], text)}

    @property
    def _label(self) -> str:
        if self.doc_list:
            return _OPEN_LABEL
        return _FIELD_LABEL if self.menu else _FIND_LABEL

    def _field(self) -> tuple[str, int]:
        """What shows of the typed text (its end, if it's longer than the field) and the field's width;
        in search mode, between searches, what was found."""
        text = self.typed if self.menu or self.finding or self.doc_list else self.search
        size = min(max(len(text) + 1, _FIELD_WIDTH), max(self.width - len(self._label), 2))
        return text[len(text) - (size - 1) :] if len(text) >= size else text, size

    def _field_line(self) -> str:
        shown, size = self._field()
        return f"{self._label}{_FIELD_ON}{shown.ljust(size)}{_FIELD_OFF}"

    def cursor(self) -> tuple[int, int] | None:
        """Where the typing cursor goes, as (row, column) in the rows render() gives; None but in the
        section list or the Find field."""
        column = len(self._label) + len(self._field()[0])
        if self.finding:
            return self.height - 2, column
        if not (self.menu or self.doc_list) or self.color_list:
            return None
        return self.title_rows, column

    def _marked(self, window: list[str]) -> list[str]:
        """The window with the search's matches marked (as they're typed, too), the one showing in
        reverse video."""
        term = " ".join(self.typed.split()) if self.finding else self.search
        if not term:
            return window
        window = list(window)
        found = self._found(term)
        spans: dict[int, list[tuple[int, int, bool]]] = {}
        for n, (section, parts) in enumerate(found):
            if section == self.index:
                for line, start, end in parts:
                    if self.top <= line < self.top + len(window):
                        spans.setdefault(line - self.top, []).append((start, end, n == self.match))
        for row, marks in spans.items():
            for start, end, current in sorted(marks, reverse=True):  # from the right: indexes hold
                text = window[row]
                if current and not self.finding:
                    window[row] = _highlight(text, start, end)
                else:
                    a, b = _raw_index(text, start), _raw_index(text, end)
                    window[row] = text[:a] + _MATCH_ON + text[a:b] + _MATCH_OFF + text[b:]
        return window

    def _color_lines(self) -> list[str]:
        """The color list, the one in use marked and in reverse video; the screen shows it as it is
        chosen."""
        digits = 1 if len(self.colors) > 9 else len(str(len(self.colors)))
        names = [name.replace("_", " ") for name, _ in self.colors]  # slate_2 shows as slate 2
        longest = max(len(name) for name in names)
        rows = []
        for n, (name, (_, about)) in enumerate(zip(names, self.colors, strict=True)):
            number = n + 1 if n < 9 else ""  # digits pick the first nine
            mark = "›" if n == self.color else " "
            row = f"{mark} {number:>{digits}}  {name.ljust(longest)}   {about}".rstrip()
            rows.append(f"\x1b[7m{row}\x1b[27m" if n == self.color else row)  # as the g list marks its pick
        notes = ["", "Left out of pager-colors.ini:", *(f"  {note}" for note in self.color_notes)]
        return ["Colors:", "", *rows, *(notes if self.color_notes else [])]

    def render(self, width: int) -> list[str]:
        """Exactly `height` rows: the title (if any), the visible window, blank-padded, then the key hints."""
        self.width = width
        hints = self.status_rows(width)
        body = max(self.height - self.title_rows - len(hints), 1)
        if self.color_list:
            window = self._color_lines()[:body]
        elif self.doc_list:
            window = self._doc_lines()[:body]
        elif self.menu:
            window = self._menu_lines()[:body]
        else:
            window = self._marked(self.lines[self.top : self.top + body])
            if self.focus is not None:
                window = list(window)
                for line, start, end in self.links[self.focus].parts:
                    if self.top <= line < self.top + body:
                        window[line - self.top] = _highlight(window[line - self.top], start, end)
            if window and self.carried == (self.index, self.top):
                window = [_CARRIED_MARK + window[0], *window[1:]]
        rows = [self.title, ""] if self.title else []
        return rows + list(window) + [""] * (body - len(window)) + hints


_FIELD_LABEL = "Go to: "
_FIND_LABEL = "Find: "
_OPEN_LABEL = "Open: "
_FIELD_WIDTH = 30  # the typing field's width, wider as more is typed
_MENU_INDENT = 2  # spaces before the section list
_MENU_GAP = 3  # spaces between its columns
_PICKED = "› "  # in the 2 spaces before a list's pick, as the color list marks the one in use
_MENU_MIN_NAME = 12  # a narrower column would show too little of a name to be worth it


def _column_longest(names: list[int], columns: int) -> list[int]:
    """The longest name length in each column, with the list filled top to bottom."""
    rows = -(-len(names) // columns)
    return [max(names[c * rows : (c + 1) * rows]) for c in range(columns) if names[c * rows : (c + 1) * rows]]


def _name_rooms(names: list[int], columns: int, width: int, digits: int) -> list[int]:
    """Name width per column, shortening the widest first if they don't all fit."""
    longest = _column_longest(names, columns)
    available = width - _MENU_INDENT - _MENU_GAP * (len(longest) - 1) - len(longest) * (digits + 2)
    if sum(longest) <= available:
        return longest
    cap = max(longest)
    while cap > 1 and sum(min(n, cap) for n in longest) > available:
        cap -= 1
    return [min(n, cap) for n in longest]


_OUTLINE_MIN = 20  # an outline column narrower than this would cut too many names


def _capped(widths: list[int], room: int) -> list[int] | None:
    """Column widths that fit `room`, the widest cut down first; None if that leaves one too narrow."""
    cap = max(widths)
    while cap > _OUTLINE_MIN and sum(min(w, cap) for w in widths) > room:
        cap -= 1
    capped = [min(w, cap) for w in widths]
    return capped if sum(capped) <= room else None


def _shorten(name: str, room: int) -> str:
    return name if len(name) <= room else name[: max(room - 1, 0)].rstrip() + "…"


def _fit(width: int, *wordings: str) -> str:
    for text in wordings:
        if len(text) <= width:
            return text
    return wordings[-1][:width]


def _name_words(name: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", name.lower()).split())


_TOO_SHORT = "Type two or more letters of a name."


def _long_enough(text: str) -> bool:
    """A name is matched from two letters on: one letter on its own is a command (q, o, g)."""
    return len(_name_words(text).replace(" ", "")) >= 2


def section_matches(names: list[str], wanted: str) -> list[int]:
    """The sections `wanted` could name. Capitals and punctuation don't matter. The whole name wins;
    otherwise the names that start with the words, or else the ones that have them all."""
    words = _name_words(wanted)
    if not words:
        return []
    plain = [_name_words(name) for name in names]
    if words in plain:
        return [plain.index(words)]
    for test in (
        lambda name: name.startswith(words),
        lambda name: all(w in name.split() for w in words.split()),
    ):
        matches = [n for n, name in enumerate(plain) if test(name)]
        if matches:
            return matches
    return []


def find_section(names: list[str], wanted: str) -> tuple[int | None, list[str]]:
    """The section `wanted` names, as (index, []); or (None, the names it could mean)."""
    matches = section_matches(names, wanted)
    if len(matches) == 1:
        return matches[0], []
    return None, [names[n] for n in matches]


def find_place(
    sections: Sequence[str], outline: Sequence[tuple[int, str, str, str]], wanted: str
) -> tuple[int | None, str, list[str]]:
    """Where `wanted` goes, as (section index, heading, []): a section, or a heading of the outline
    (one in a one-page document, say); or (None, "", the names it could mean)."""
    places = [(n, "", name) for n, name in enumerate(sections)]
    places += [
        (sections.index(name), heading, label)
        for _, label, name, heading in outline
        if heading and name in sections
    ]
    index, could_be = find_section([label for _, _, label in places], wanted)
    if index is None:
        return None, "", could_be
    return places[index][0], places[index][1], []


# The files a typed name may open, when the Open list takes typed files.
TYPED_SUFFIXES = (".md", ".txt")


@dataclass(frozen=True)
class Entry:
    title: str
    path: Path
    group: str = ""
    names: tuple[str, ...] = ()  # more names it can be typed as, such as a command's


@dataclass(frozen=True)
class Opening:
    """What the Open list asks the program to show: a document, the section typed after its name ("" for
    none), and whether it's the one just come from (`back`), to show where it was left."""

    entry: Entry
    section: str = ""
    back: bool = False


def index_of(entries: list[Entry], path: Path | None) -> int | None:
    """Which entry is the file at `path`, if any."""
    if path is None:
        return None
    wanted = _same(path)
    return next((n for n, entry in enumerate(entries) if _same(entry.path) == wanted), None)


def _same(path: Path) -> Path:
    try:
        return path.expanduser().resolve()
    except OSError:
        return path


def _document_matches(entries: list[Entry], wanted: str) -> list[int]:
    """The entries `wanted` could name, by title or another name (as sections are matched)."""
    names, owners = [], []
    for n, entry in enumerate(entries):
        for name in (entry.title, *entry.names):
            names.append(name)
            owners.append(n)
    return list(dict.fromkeys(owners[i] for i in section_matches(names, wanted)))


def looks_like_a_file(text: str) -> bool:
    """Typed text that names a file rather than a document on the list."""
    return "/" in text or "\\" in text or text.startswith(("~", ".")) or text.lower().endswith(TYPED_SUFFIXES)


# --------------------------------------------------------------------------- keys


def read_key(read: Callable[[float | None], bytes]) -> str:
    """Read one key; a short wait tells a lone Esc from an escape sequence. read() gives b"" on timeout."""
    first = read(None)
    if not first:
        return "eof"
    byte = first
    if byte == b"\x1b":
        second = read(_ESC_WAIT)
        if not second:
            return "esc"
        if second == b"]":  # a terminal's late answer to the color question (see terminal_colors)
            previous = b""
            while (nxt := read(_ESC_WAIT)) and nxt != b"\x07" and previous + nxt != b"\x1b\\":
                previous = nxt
            return "other"
        if second not in (b"[", b"O"):
            return "other"
        seq = b""
        while True:
            nxt = read(_ESC_WAIT)
            if not nxt:
                return "other"
            seq += nxt
            if 0x40 <= nxt[0] <= 0x7E:
                break
        return _CSI_KEYS.get(seq, "other")
    return _byte_key(byte)


def _byte_key(byte: bytes) -> str:
    """A key's name, or a printable character as itself (typed in the g list)."""
    if byte in _BYTE_KEYS:
        return _BYTE_KEYS[byte]
    char = byte.decode("latin-1")
    return char if len(char) == 1 and char.isprintable() and byte < b"\x7f" else "other"


_PAGE_KEYS = {
    "Q": "q",
    "C": "c",
    "O": "o",
    "P": "p",
    "N": "p",
    "backspace": "b",
}  # on a page; fields type them
_BYTE_KEYS = {
    b" ": "space",
    b"\r": "enter",
    b"\n": "enter",
    b"\x7f": "backspace",
    b"\x08": "backspace",
    b"\t": "tab",
    b"\x03": "ctrl-c",
    b"\x04": "eof",
}
_CSI_KEYS = {
    b"A": "up",
    b"B": "down",
    b"C": "right",
    b"D": "left",
    b"H": "home",
    b"F": "end",
    b"5~": "pgup",
    b"6~": "pgdn",
    b"1~": "home",
    b"7~": "home",
    b"4~": "end",
    b"8~": "end",
    b"Z": "shift-tab",
}


# ---------------------------------------------------------------- terminal handling


def _windows_vt_enabled() -> bool:  # pragma: no cover - only runs on Windows
    """True if this console understands ANSI escape codes (turning that mode on if it can)."""
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.GetStdHandle(-11)  # standard output
        mode = wintypes.DWORD()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        enable_vt = 0x0004  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        return bool(mode.value & enable_vt) or bool(kernel32.SetConsoleMode(handle, mode.value | enable_vt))
    except Exception:  # noqa: BLE001 - if unsure, do not page
        return False


def alternate_screen_codes(env: Mapping[str, str] | None = None) -> tuple[str, str] | None:
    """(enter, leave) strings for the terminal's alternate screen, or None if it has none."""
    env = os.environ if env is None else env
    if sys.platform == "win32":
        return ("\x1b[?1049h", "\x1b[?1049l") if _windows_vt_enabled() else None
    term = env.get("TERM", "")
    if term in ("", "dumb"):
        return None
    try:
        import curses

        curses.setupterm(term=term, fd=sys.__stdout__.fileno() if sys.__stdout__ else 1)
        enter, leave = curses.tigetstr("smcup"), curses.tigetstr("rmcup")
    except Exception:  # noqa: BLE001 - no terminfo entry, no curses: do not page
        return None
    if not enter or not leave:
        return None
    return enter.decode("latin-1"), leave.decode("latin-1")


def pager_available(
    stdin: Any = None, stdout: Any = None, env: Mapping[str, str] | None = None, off_switch: str | None = None
) -> bool:
    """A real interactive terminal with an alternate screen, and paging not switched off.

    `off_switch` names an environment variable that turns paging off when set to off, 0, false or no
    (for example for screen-reader users); see PagerOptions.off_switch_env.
    """
    env = os.environ if env is None else env
    if off_switch and env.get(off_switch, "").strip().lower() in OFF_VALUES:
        return False
    stdin = sys.stdin if stdin is None else stdin
    stdout = sys.stdout if stdout is None else stdout
    try:
        if not (stdin.isatty() and stdout.isatty()):
            return False
    except (AttributeError, ValueError):
        return False
    return alternate_screen_codes(env) is not None


def _terminal_size() -> tuple[int, int]:
    size = shutil.get_terminal_size((80, 24))
    return size.columns, size.lines


Wrapper = Callable[[str, int], "list[str]"]


def default_wrap(text: str, width: int) -> list[str]:
    """Word-wrap keeping indents and never breaking words (URLs, flags)."""
    out: list[str] = []
    for line in text.split("\n"):
        if not line.strip():
            out.append("")
            continue
        indent = line[: len(line) - len(line.lstrip())]
        out.extend(
            textwrap.wrap(
                line.strip(),
                width=width,
                initial_indent=indent,
                subsequent_indent=indent,
                break_long_words=False,
                break_on_hyphens=False,
            )
        )
    return out


_CODE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
_LINK_CLOSE = "\x1b]8;;\x1b\\"
_STYLE_OFF = {"22": "1", "23": "3", "24": "4", "27": "7"}  # the code that turns each style off


_OSC_LINK = re.compile(r"\x1b\]8;[^;\x07\x1b]*;([^\x07\x1b]*)(?:\x07|\x1b\\)")
_BARE_URL = re.compile(r"(?<![\w/])https?://[A-Za-z0-9][^\s<>()\[\]`\"']*")
_PLACEHOLDERS = ("example", "mysite")  # placeholder addresses, never links (see links.PLACEHOLDERS)
_CODE_MARK = "\x1b[10m"  # starts a line of a code block (see links.CODE_MARK)
_HEADING_MARK = "\x1b[11m"  # starts a line of a heading (see markdown.HEADING_MARK)
_SUBHEADING = _HEADING_MARK * 2  # starts a line of #### and below (see markdown._SUBHEADING_EDGE)
_TINT_ON, _TINT_OFF = "\x1b[12m", "\x1b[13m"  # around code (see tint.py); never drawn
_CARRIED_MARK = "\x1b[14m"  # starts the line repeated from the screen before; never drawn
_FIELD_ON, _FIELD_OFF = "\x1b[15m", "\x1b[16m"  # around the typing field: code's shading, or else reverse
_FAINT = "\x1b[2m"
_SGR = re.compile(r"\x1b\[([0-9;]*)m")
_REVERSE = "\x1b[7m"
_SECTION_REF = re.compile(r"\(section[ \u00a0](\d+)\)")


_MATCH_ON, _MATCH_OFF = "\x1b[17m", "\x1b[18m"  # around a search match; never drawn
_PLAIN_ROW = "\x1b[19m"  # starts a row under the text that isn't in reverse video; never drawn


def _find(
    sections: Sequence[tuple[str, Sequence[str]]], term: str
) -> list[tuple[int, tuple[tuple[int, int, int], ...]]]:
    pattern = re.compile(r"\s+".join(re.escape(word) for word in term.split()), re.IGNORECASE)
    found = []
    for number, (_, lines) in enumerate(sections):
        texts = [_visible(line) for line in lines]
        starts, at = [], 0
        for text in texts:
            starts.append(at)
            at += len(text) + 1
        for match in pattern.finditer("\n".join(texts)):
            parts, line = [], bisect.bisect_right(starts, match.start()) - 1
            while line < len(texts) and starts[line] < match.end():
                text, first = texts[line], starts[line]
                start = match.start() - first if first <= match.start() else len(text) - len(text.lstrip())
                end = min(match.end() - first, len(text))
                if start < end:  # a wrapped line's indent isn't part of it
                    parts.append((line, start, end))
                line += 1
            found.append((number, tuple(parts)))
    return found


_MARKS = re.compile("(" + "|".join(map(re.escape, (_MATCH_ON, _MATCH_OFF, _TINT_ON, _TINT_OFF))) + ")")


def _show_matches(text: str, tint: bool) -> str:
    """Marked matches shaded like code; underlined in code, or where there is no shading."""
    if _MATCH_ON not in text:
        return text
    block = text.startswith(_CODE_MARK)
    out, code, shaded = [], block, False
    for piece in _MARKS.split(text):
        if piece in (_TINT_ON, _TINT_OFF):
            code = block or piece == _TINT_ON
        elif piece == _MATCH_ON:
            shaded = tint and not code
            piece = _TINT_ON if shaded else "\x1b[4m"
        elif piece == _MATCH_OFF:
            piece = _TINT_OFF if shaded else "\x1b[24m"
        out.append(piece)
    return "".join(out)


def _visible(line: str) -> str:
    return _CODE.sub("", line)


def _line_links(line: str) -> list[tuple[int, int, str, int]]:
    """(start, end, address, section) for each link in one laid-out line, in characters on screen:
    hyperlinks in its codes, addresses in its text, and "(section N)"."""
    spans: list[tuple[int, int, str, int]] = []
    if line.startswith(_CODE_MARK):
        return spans  # a line of a code block: nothing in it is a link
    shown, position, opened, url = 0, 0, None, ""
    for match in _CODE.finditer(line):
        shown += match.start() - position
        position = match.end()
        link = _OSC_LINK.match(match.group(0))
        if link is None:
            continue
        if opened is not None and opened < shown:
            spans.append((opened, shown, url, 0))
        opened, url = (shown, link.group(1)) if link.group(1) else (None, "")
    shown += len(line) - position
    if opened is not None and opened < shown:
        spans.append((opened, shown, url, 0))
    text = _visible(line)
    code = [match.span() for match in re.finditer(r"`[^`]*`", text)]
    for match in _BARE_URL.finditer(text):
        start, end = match.span()
        while end > start and text[end - 1] in ".,;:!?*_":
            end -= 1
        placeholder = any(word in text[start:end].lower() for word in _PLACEHOLDERS)
        if placeholder or any(a <= start < b for a, b in code):
            continue  # a placeholder address, or one in inline code: not a link
        if not any(a < end and start < b for a, b, _, _ in spans):
            spans.append((start, end, text[start:end], 0))
    spans += [(m.start(), m.end(), "", int(m.group(1))) for m in _SECTION_REF.finditer(text)]
    return sorted(spans)


_LISTED = re.compile(r"^\s*(\d+)[.)]?\s+\S")


def _listed_links(lines: Sequence[str], last: int) -> list[Link]:
    """A front page's list of the other sections (under its last heading): each numbered line goes to
    that section, from its number to the end of the line."""
    start = max((n for n, line in enumerate(lines) if line.startswith(_HEADING_MARK)), default=-1) + 1
    found = []
    for number in range(start, len(lines)):
        text = _visible(lines[number]).rstrip()
        match = _LISTED.match(text)
        if match and 1 <= int(match.group(1)) <= last:
            found.append(Link(((number, match.start(1), len(text)),), section=int(match.group(1)) + 1))
    return found


def _section_links(lines: Sequence[str]) -> list[Link]:
    """The links of a section; one that wraps onto the next line is one link."""
    found: list[Link] = []
    for number, line in enumerate(lines):
        text = _visible(line)
        for start, end, url, section in _line_links(line):
            if found:
                last = found[-1]
                previous, _, last_end = last.parts[-1]
                continues = (
                    previous == number - 1
                    and last_end >= len(_visible(lines[previous]).rstrip())
                    and start == len(text) - len(text.lstrip())
                    and (last.url, last.section) == (url, section)
                )
                if continues:
                    found[-1] = Link((*last.parts, (number, start, end)), url, section)
                    continue
            found.append(Link(((number, start, end),), url, section))
    return found


def _raw_index(line: str, wanted: int) -> int:
    """Where, in a line with codes, the character `wanted` places from its start on screen begins."""
    shown, position = 0, 0
    for match in _CODE.finditer(line):
        text = match.start() - position
        if shown + text >= wanted:
            break
        shown += text
        position = match.end()
    lead = 0
    while line.startswith((_CODE_MARK, _HEADING_MARK), lead):
        lead += len(_CODE_MARK)
    return max(position + wanted - shown, lead)  # after a line's marks, which must stay first


def _highlight(line: str, start: int, end: int) -> str:
    """The line with characters start to end (on screen) in reverse video: the link Tab is on."""
    a, b = _raw_index(line, start), _raw_index(line, end)
    return line[:a] + "\x1b[7m" + line[a:b] + "\x1b[27m" + line[b:]


def _cut(row: str, room: int) -> str:
    """The row cut to `room` characters on screen. Codes take no room and are kept; a hyperlink or a
    style (bold, italic, underline, reverse) still on at the cut is turned off, so it can't spill over
    the rest of the screen."""
    if "\x1b" not in row:
        return row[:room]
    out: list[str] = []
    shown, link, on = 0, False, set()
    position = 0
    for match in _CODE.finditer(row):
        text = row[position : match.start()]
        take = text[: max(room - shown, 0)]
        out.append(take)
        shown += len(take)
        if shown >= room and len(take) < len(text):
            break
        code = match.group(0)
        if code.startswith("\x1b]8;"):
            link = code != _LINK_CLOSE
        elif code.endswith("m"):
            for number in code[2:-1].split(";"):
                if number in _STYLE_OFF:
                    on.discard(_STYLE_OFF[number])
                elif number in ("0", ""):
                    on.clear()
                elif number in _STYLE_OFF.values():
                    on.add(number)
        out.append(code)
        position = match.end()
    else:
        rest = row[position:]
        out.append(rest[: max(room - shown, 0)])
    off = ";".join(off for off, style in _STYLE_OFF.items() if style in on)
    return "".join(out) + (f"\x1b[{off}m" if off else "") + (_LINK_CLOSE if link else "")


_CODES = r"(?:\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\))*"
_TICK_AFTER_ON = re.compile(f"({re.escape(_TINT_ON)}{_CODES})`")
_TICK_BEFORE_OFF = re.compile(f"`({_CODES}{re.escape(_TINT_OFF)})")


def _prepare_code(line: str, on: str, width: int, hide: bool | None = None) -> str:
    """A code block's line filled to `width`, and marked backticks dropped; the marks stay."""
    hide = bool(on) if hide is None else hide
    if line.startswith(_CODE_MARK) and on:
        line = _TINT_ON + line + " " * max(width - len(_visible(line)), 0) + _TINT_OFF
    if hide:  # other codes (a highlight's start or end) may come between a backtick and its mark
        line = _TICK_AFTER_ON.sub(r"\1", line)
        line = _TICK_BEFORE_OFF.sub(r"\1", line)
    return line


def _paint_code(line: str, on: str, off: str, width: int, hide: bool | None = None) -> str:
    """The row with code on `on` (`off` ends it). Without `on`, backticks stay unless `hide`."""
    line = _prepare_code(line, on, width, hide)
    if not on:
        return line.replace(_TINT_ON, "").replace(_TINT_OFF, "")
    tinted = False

    def swap(match: re.Match[str]) -> str:
        nonlocal tinted
        tinted = match.group(0) == _TINT_ON
        return on if tinted else off

    line = re.sub(re.escape(_TINT_ON) + "|" + re.escape(_TINT_OFF), swap, line)
    return line + off if tinted else line


def _accented(line: str, colors: str, accent: str, reverse: str, tint: str = "", dimmer: str = "") -> str:
    """One row with its headings and links (underlined) in the accent color, and reverse video (the
    link Tab is on, the g list's pick) as `reverse`: the background color on the accent. Marked code
    gets `tint`; #### and below, `dimmer` if given."""
    underline = inverse = tinted = False
    heading = line.startswith(_HEADING_MARK)
    shade = dimmer if dimmer and line.startswith(_SUBHEADING) else accent

    def color() -> str:
        base = reverse if inverse else shade if heading and not underline else accent if underline else colors
        return base + tint if tinted and not inverse else base

    def recolor(match: re.Match[str]) -> str:
        nonlocal underline, inverse, tinted
        if match.group(0) == _HEADING_MARK:
            return ""
        if match.group(0) in (_TINT_ON, _TINT_OFF):
            tinted = match.group(0) == _TINT_ON and bool(tint)
            return color()
        kept = []
        for code in match.group(1).split(";"):
            if code in ("", "0"):
                underline = inverse = False
            elif code in ("4", "24"):
                underline = code == "4"
            elif code in ("7", "27"):
                inverse = code == "7"
                continue
            kept.append(code)
        return (f"\x1b[{';'.join(kept)}m" if kept else "") + color()

    return color() + _SGR.sub(recolor, line) + colors


@dataclass(frozen=True)
class Margins:
    """Blank space around the pager's text: `side` columns left and right, `top` rows above the
    title, `gap` rows above the key hints (none below them)."""

    side: int = 0
    top: int = 0
    gap: int = 0


NO_MARGINS = Margins()


def margins(columns: int, height: int) -> Margins:
    """A fixed rule by window size, so a small window keeps its room for text."""
    side = 2 if columns >= 60 else 1 if columns >= 30 else 0
    rows = 1 if height >= 12 else 0
    return Margins(side, rows, rows)


def text_width(columns: int, space: Margins) -> int:
    """Columns left for text; without side margins the last column stays empty, as terminals wrap
    when a character lands there."""
    return columns - 2 * space.side if space.side else columns - 1


def _draw(
    out: Any,
    rows: Sequence[str],
    columns: int,
    style: str | None,
    hint_rows: int,
    colors: str = "",
    accent: str = "",
    reverse: str = "",
    space: Margins = NO_MARGINS,
    code: tuple[str, str] = ("", ""),
    hide_ticks: bool | None = None,
    faint: str = "",
    tail: str = "",
    dimmer: str = "",
) -> None:
    """Draw every row, then write `tail` (such as where the cursor goes). Styling is optional; the
    text works without it.

    `colors` sets the text and background colors for everything (a code like "\x1b[38;5;214;48;5;16m",
    or "" for the terminal's own); it is set again after every reset, so clearing to the end of a line
    fills it with the background too. `accent` colors headings and links, and `reverse` (the
    background color on the accent) is used for the key hints and other reverse video; without them
    these keep the text color. `space` puts blank margins around it all (see Margins); the rows
    are the window less its top and gap rows. `code` is (on, off) for code's background (tint.py).
    `dimmer` is the text color for #### and below.
    """
    parts = [colors]
    first_hint = len(rows) - hint_rows
    blank = [
        *range(1, space.top + 1),
        *range(space.top + first_hint + 1, space.top + first_hint + space.gap + 1),
    ]
    parts += [f"\x1b[{number};1H\x1b[K" for number in blank]
    indent = " " * space.side
    width = max(text_width(columns, space), 1)
    on, off = code
    for number, row in enumerate(rows, start=1):
        carried, plain = row.startswith(_CARRIED_MARK), row.startswith(_PLAIN_ROW)
        text = _cut(row.removeprefix(_CARRIED_MARK).removeprefix(_PLAIN_ROW), width)
        if _FIELD_ON in text:  # shaded, not reversed, so the block cursor in it stays visible
            text = text.replace(_FIELD_ON, _TINT_ON if on else _REVERSE)
            text = text.replace(_FIELD_OFF, _TINT_OFF if on else "\x1b[27m")
        text = _show_matches(text, bool(on))
        if number == 1 and style is not None:
            text = f"{style}{text}\x1b[0m{colors}"
        elif number > first_hint and not plain:
            text = f"{reverse or _REVERSE}{text}\x1b[0m{colors}"
        elif accent:
            text = _accented(_prepare_code(text, on, width, hide_ticks), colors, accent, reverse, on, dimmer)
        else:
            sub = text.startswith(_SUBHEADING)
            text = text.replace(_HEADING_MARK, "")
            text = _paint_code(text, on, off or colors, width, hide_ticks)
            if sub and dimmer:
                text = dimmer + _SGR.sub(lambda match: match.group(0) + dimmer, text) + (colors or "\x1b[39m")
        if carried and faint:
            text = faint + _SGR.sub(lambda match: match.group(0) + faint, text) + "\x1b[39m"
        elif carried:  # faint is set again after every code, which may turn it off
            text = _SGR.sub(lambda match: match.group(0) + _FAINT, _faded(colors + text, colors))
            text = _FAINT + text + "\x1b[22m" + colors
        line = space.top + number + (space.gap if number > first_hint else 0)
        parts.append(f"\x1b[{line};1H{indent}{text}\x1b[K")
    if colors:
        parts.append("\x1b[0m")
    out.write("".join(parts) + tail)
    out.flush()


# ------------------------------------------------------------------- fading

RGB = tuple[int, int, int]
Pair = tuple[RGB, RGB]  # (text, background)
FADE_STEPS = 8
FADE_STEP_SECONDS = 0.025  # 8 steps: a fifth of a second
_FADE_CONTRAST = 3.0  # fade only between backgrounds this far apart (a dark and a light one)
_COLOR_QUESTION = "\x1b]10;?\x1b\\\x1b]11;?\x1b\\\x1b[c"  # text color, background, then any reply
_COLOR_ANSWER = re.compile(rb"\x1b\](1[01]);rgb:([0-9a-fA-F]{1,4})/([0-9a-fA-F]{1,4})/([0-9a-fA-F]{1,4})")
_ACCENT_COLOR = re.compile(r"\x1b\[38;2;(\d+);(\d+);(\d+)m")
_TRUE_COLORS = re.compile(r"\x1b\[38;2;(\d+);(\d+);(\d+);48;2;(\d+);(\d+);(\d+)m")


def _channel(digits: bytes) -> int:
    return round(int(digits, 16) * 255 / (16 ** len(digits) - 1))


def parse_terminal_colors(reply: bytes) -> Pair | None:
    """The terminal's own (text, background) from its answers to _COLOR_QUESTION, if it gave both."""
    found = {
        m.group(1): tuple(_channel(m.group(n)) for n in (2, 3, 4)) for m in _COLOR_ANSWER.finditer(reply)
    }
    text, background = found.get(b"10"), found.get(b"11")
    return (text, background) if text and background else None  # type: ignore[return-value]


def terminal_colors(fd: int, out: Any, wait: float = 0.3) -> Pair | None:
    """Ask the terminal for its own colors (OSC 10 and 11). Every terminal answers the last question
    (DA1), so one that doesn't know colors costs no waiting; none at all gives up after `wait`."""
    out.write(_COLOR_QUESTION)
    out.flush()
    reply, deadline = b"", time.monotonic() + wait
    while not re.search(rb"\x1b\[\?[0-9;]*c", reply):
        left = deadline - time.monotonic()
        ready = select.select([fd], [], [], left)[0] if left > 0 else []
        if not ready:
            break
        reply += os.read(fd, 256)
    return parse_terminal_colors(reply)


# Windows Terminal's default scheme (Campbell) and the classic console's: what a Windows terminal that
# doesn't answer the color question most likely shows.
WINDOWS_COLORS: Pair = ((204, 204, 204), (12, 12, 12))


def windows_terminal_colors(out: Any, wait: float = 0.2) -> Pair:
    """The terminal's own (text, background) on Windows: its answer, or Windows' default colors."""
    try:
        reply = windows_console_reply(_COLOR_QUESTION, out, wait)
    except (AttributeError, OSError, ValueError):
        reply = ""
    return parse_terminal_colors(reply.encode("latin-1", "replace")) or WINDOWS_COLORS


def windows_console_reply(question: str, out: Any, wait: float) -> str:  # pragma: no cover - Windows only
    """Ask the Windows console a question and read its answer, up to the reply every terminal sends
    last (DA1). "" when stdin or stdout isn't a console, or nothing came within `wait`."""
    import ctypes
    import msvcrt
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    k32.GetStdHandle.restype = wintypes.HANDLE
    k32.GetConsoleMode.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    k32.SetConsoleMode.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    handles = k32.GetStdHandle(-10), k32.GetStdHandle(-11)  # stdin, stdout
    modes = [wintypes.DWORD(), wintypes.DWORD()]
    if not all(k32.GetConsoleMode(h, ctypes.byref(m)) for h, m in zip(handles, modes, strict=True)):
        return ""
    line_input, echo_input, vt_input, vt_output = 0x0002, 0x0004, 0x0200, 0x0004
    reply = ""
    try:
        k32.SetConsoleMode(handles[0], (modes[0].value | vt_input) & ~(line_input | echo_input))
        k32.SetConsoleMode(handles[1], modes[1].value | vt_output)
        while msvcrt.kbhit():  # type: ignore[attr-defined]
            msvcrt.getwch()  # type: ignore[attr-defined]
        out.write(question)
        out.flush()
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline and not re.search(r"\x1b\[\?[0-9;]*c", reply):
            if msvcrt.kbhit():  # type: ignore[attr-defined]
                reply += msvcrt.getwch()  # type: ignore[attr-defined]
            else:
                time.sleep(0.001)
    finally:
        for handle, mode in zip(handles, modes, strict=True):
            k32.SetConsoleMode(handle, mode.value)
    return reply


def scheme_pair(codes: str) -> Pair | None:
    """(text, background) of a full-color code; None for the terminal's own or the 256 colors."""
    match = _TRUE_COLORS.fullmatch(codes)
    if match is None:
        return None
    n = [int(value) for value in match.groups()]
    return (n[0], n[1], n[2]), (n[3], n[4], n[5])


def _luminance(color: RGB) -> float:
    def linear(channel: int) -> float:
        c = channel / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (linear(channel) for channel in color)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def fade_frames(start: Pair | None, end: Pair | None, steps: int = FADE_STEPS) -> list[str]:
    """The color codes for the steps between two (text, background) pairs, without the last one;
    none unless both are known and the backgrounds are far apart (dark to light or back)."""
    if start is None or end is None:
        return []
    light, dark = sorted((_luminance(start[1]), _luminance(end[1])), reverse=True)
    if (light + 0.05) / (dark + 0.05) < _FADE_CONTRAST:
        return []

    def mix(a: RGB, b: RGB, share: float) -> str:
        return ";".join(str(round(x + (y - x) * share)) for x, y in zip(a, b, strict=True))

    return [
        f"\x1b[38;2;{mix(start[0], end[0], n / steps)};48;2;{mix(start[1], end[1], n / steps)}m"
        for n in range(1, steps)
    ]


_FADED = 0.5


def _faded(line: str, colors: str) -> str:
    """Text colors moved toward the background: terminals don't make a theme's exact colors faint."""
    pair = scheme_pair(colors)
    if pair is None:
        return line
    back = pair[1]

    def fade(match: re.Match[str]) -> str:
        params, out = match.group(1).split(";"), []
        while params:
            if params[0] in ("38", "48") and params[1:2] == ["2"] and len(params) >= 5:
                rgb = [int(value) for value in params[2:5]]
                if params[0] == "38":
                    rgb = [round(c + (b - c) * _FADED) for c, b in zip(rgb, back, strict=True)]
                out += [params[0], "2", *map(str, rgb)]
                params = params[5:]
            elif params[0] in ("38", "48") and params[1:2] == ["5"]:
                out, params = out + params[:3], params[3:]
            else:
                out, params = out + params[:1], params[1:]
        return f"\x1b[{';'.join(out)}m"

    return _SGR.sub(fade, line)


_LIGHT_BLUE, _DARK_BLUE = (95, 175, 255), (0, 87, 183)
_TITLE_CONTRAST = 7.0


def _contrast(a: RGB, b: RGB) -> float:
    light, dark = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


_DIMMER_STEPS = (0.4, 0.35, 0.3, 0.25, 0.2, 0.15)  # toward the background; the first that keeps 7:1


def dimmer(text: RGB, background: RGB) -> RGB | None:
    """The text a shade toward the background, for #### and below: as far as keeps 7:1.
    None when the text has no room to spare."""
    for step in _DIMMER_STEPS:
        mixed = tuple(round(t + (b - t) * step) for t, b in zip(text, background, strict=True))
        if _contrast(mixed, background) >= _TITLE_CONTRAST:  # type: ignore[arg-type]
            return mixed  # type: ignore[return-value]
    return None


def title_blue(background: RGB) -> RGB | None:
    """A light blue on a dark background, a dark one on a light background, lightened or darkened until
    it reaches 7:1; None if none does (a mid-gray background)."""
    dark = _contrast(background, (255, 255, 255)) >= _contrast(background, (0, 0, 0))
    blue, toward = (_LIGHT_BLUE, (255, 255, 255)) if dark else (_DARK_BLUE, (0, 0, 0))
    for step in range(11):
        r, g, b = (round(c + (t - c) * step / 10) for c, t in zip(blue, toward, strict=True))
        if _contrast((r, g, b), background) >= _TITLE_CONTRAST:
            return r, g, b
    return None


def title_style(
    env: Mapping[str, str] | None = None, colored: bool = False, background: RGB | None = None
) -> str:
    """Bold italic for the title row; with the terminal's own colors in full color and its background
    known, in title_blue. Chosen colors color it themselves."""
    env = os.environ if env is None else env
    full_color = env.get("COLORTERM", "").lower() in ("truecolor", "24bit")
    blue = title_blue(background) if background and full_color and not colored else None
    if env.get("NO_COLOR") or blue is None:
        return _TITLE_PLAIN
    return f"\x1b[1;3;38;2;{';'.join(map(str, blue))}m"


def _posix_key_reader(fd: int) -> Callable[[], str]:
    def read(timeout: float | None) -> bytes:
        if timeout is not None:
            ready, _, _ = select.select([fd], [], [], timeout)
            if not ready:
                return b""
        return os.read(fd, 1)

    def wait_and_read() -> str:
        last = _terminal_size()
        while True:
            ready, _, _ = select.select([fd], [], [], 0.25)
            if ready:
                return read_key(read)
            if _terminal_size() != last:
                return "resize"

    return wait_and_read


_WINDOWS_KEYS = {
    "H": "up",
    "P": "down",
    "M": "right",
    "K": "left",
    "I": "pgup",
    "Q": "pgdn",
    "G": "home",
    "O": "end",
}


def _windows_key_reader() -> Callable[[], str]:  # pragma: no cover - only runs on Windows
    """Like _posix_key_reader, but returns "resize" as soon as the window changes size."""
    import msvcrt

    def wait_and_read() -> str:
        last = _terminal_size()
        while True:
            if msvcrt.kbhit():  # type: ignore[attr-defined]
                return _windows_key()
            if _terminal_size() != last:
                return "resize"
            time.sleep(_RESIZE_POLL)

    return wait_and_read


_RESIZE_POLL = 0.1  # seconds between checks of the window size while waiting for a key on Windows


def _windows_key() -> str:  # pragma: no cover - only runs on Windows
    import msvcrt

    ch = msvcrt.getwch()  # type: ignore[attr-defined]
    if ch in ("\x00", "\xe0"):
        special = msvcrt.getwch()  # type: ignore[attr-defined]
        return {
            "H": "up",
            "P": "down",
            "M": "right",
            "K": "left",
            "I": "pgup",
            "Q": "pgdn",
            "G": "home",
            "O": "end",
            "\x0f": "shift-tab",
        }.get(special, "other")
    if ch == "\x1b":
        return "esc"
    if ch == "\x03":
        return "ctrl-c"
    return _BYTE_KEYS.get(ch.encode("latin-1", "ignore")) or (ch if ch.isprintable() else "other")


def visible_sections(sections: list[tuple[str, str]], hide: Collection[str]) -> list[tuple[str, str]]:
    """Sections minus `hide` (case-insensitive); all of them if that would leave none."""
    hidden = {name.strip().lower() for name in hide}
    kept = [(name, text) for name, text in sections if name.strip().lower() not in hidden]
    return kept or sections


_KEPT: list[str] = []  # the code that leaves the screen a document left for the next one to draw on
_UNDRAWN = "\x00"  # never a color's codes: the first draw clears the screen


def restore_screen(out: Any = None) -> None:
    """Leave the screen a document kept for the next one, if the next one never came (call after
    showing it, whatever happened)."""
    if _KEPT:
        out = sys.stdout if out is None else out
        out.write(_CURSOR_SHOW + _KEPT.pop())
        out.flush()
        _KEPT.clear()


def page_sections(
    sections: list[tuple[str, str]],
    *,
    out: Any = None,
    key_source: Callable[[], str] | None = None,
    wrap: Wrapper | None = None,
    title: str | None = None,
    hide: Collection[str] = (),
    open_list: bool = False,
    colors: Sequence[tuple[str, ...]] = (),
    color_notes: Sequence[str] = (),
    outline: Sequence[tuple[int, str, str, str]] = (),
    color: str = "",
    save_color: Callable[[str], None] | None = None,
    open_link: Callable[[str], str] | None = None,
    documents: Sequence[Entry] = (),
    document: Path | None = None,
    came_from: Path | None = None,
    typed_files: bool = True,
    open_document: Callable[[Opening], str] | None = None,
    remember: Callable[[int, int], None] | None = None,
    start_section: int = 0,
    start_line: int = 0,
    start_heading: str = "",
    fade: bool = False,
    fade_in: bool = True,
    own_colors: Pair | None = None,
    own_code: Callable[[Pair | None], tuple[str, str]] = lambda own: ("", ""),
    front_page: bool = False,
    shown: Callable[[int], None] | None = None,
) -> Outcome:
    """Page through (name, text) sections and restore the screen afterwards.

    Returns FINISHED if the user paged past the end, QUIT otherwise. Only call if pager_available().
    `title` stays on the top row; `hide` lists sections to skip (case-insensitive); `open_list` starts
    on the section list (as if g were pressed), when there is more than one section.
    `colors` offers color choices under c, as (name, description, codes) or (name, description, codes,
    accent, reverse, code on, code off) (see _draw), the first with no codes (the terminal's own);
    `own_code` gives code's background for the terminal's own colors. `color` names the one to start
    with, and `save_color` is called with the name of one chosen with Enter. Without `colors` there is
    no c key.
    Tab and Shift+Tab move through the page's links; Enter goes to a section link, or calls
    `open_link` with a web address (it returns a line to show, such as "Opened in your browser.").
    `documents` are the Open list's (o): `document` is the file showing, `came_from` the one just left
    (the list's pick starts there, and a notice says how to go back), and with `typed_files` a .md or
    .txt file can be typed by name. What is chosen goes to `open_document`, which returns "" if it
    shows it (the pager then leaves, returning GO, and the caller shows it) or a line saying why not,
    shown in the list. `remember` is told the section and line the pager was left on, and `shown` each
    section the first time it shows.
    `start_section` is the index of the section to open on (and then the section list doesn't open),
    `start_line` the line in it, or `start_heading` a heading in it.
    `outline` lays the section list out as the document's own outline (see markdown.Document.outline).
    With `fade`, a change between a dark and a light background (opening, choosing under c, leaving)
    blends over a fifth of a second, in full color only (opening too, unless not `fade_in`, as when
    coming from another page); `own_colors` are the terminal's own (text,
    background), asked of the terminal when it isn't given.
    """
    out = sys.stdout if out is None else out
    sections = visible_sections(sections, hide)
    codes = alternate_screen_codes()
    if codes is None:
        raise RuntimeError("no alternate screen available; check pager_available() first")
    enter, leave = codes

    wrap_lines = wrap or default_wrap

    def wrapped(text: str, columns: int) -> list[str]:
        return wrap_lines(text, max(text_width(columns, space), 20))

    def rows_for_text(height: int) -> int:
        return height - space.top - space.gap

    columns, height = _terminal_size()
    space = margins(columns, height)
    state = PagerState(
        [(name, wrapped(text, columns)) for name, text in sections], rows_for_text(height), title=title
    )
    state.colors = [(choice[0], choice[1]) for choice in colors]
    state.color_notes = list(color_notes)
    numbers = {name: n for n, (name, _) in enumerate(state.sections)}
    state.outline = [
        OutlineRow(depth, label, numbers.get(name), heading)
        for depth, label, name, heading in outline
        if not name or name in numbers
    ]
    if front_page:
        state.use_front_page()
    state.color = next((n for n, choice in enumerate(colors) if choice[0] == color), 0)
    state.documents, state.typed_files = list(documents), typed_files
    state.document = index_of(state.documents, document)
    left = index_of(state.documents, came_from)
    if came_from is not None and left != state.document:
        state.came_from = left
        if left is not None and document is not None:
            state.arrived = (
                state.documents[state.document].title if state.document is not None else document.name
            )
    color_codes = [choice[2] for choice in colors]
    accents = [(choice[3], choice[4]) if len(choice) > 4 else ("", "") for choice in colors]
    code_codes = [(choice[5], choice[6]) if len(choice) > 6 else ("", "") for choice in colors]

    def code_for(codes: str) -> tuple[str, str]:
        chosen = code_codes[color_codes.index(codes)] if codes in color_codes else ("", "")
        return chosen if codes else own_code(own_colors)

    def draw() -> None:
        out.write(_CURSOR_HIDE)
        now = color_codes[state.color] if color_codes else ""
        accent, reverse = accents[state.color] if accents else ("", "")
        code = code_for(now) if colors else ("", "")
        style = None
        if title:
            own = own_colors[1] if own_colors else None
            style = _TITLE_PLAIN + accent if accent else title_style(colored=bool(now), background=own)
        rows = state.render(text_width(columns, space))
        if now != drawn[0]:
            hide = bool(code_for(drawn[0])[0] and code[0])
            fading = fade and (fade_in or opened[0])
            for step in fade_frames(pair_of(drawn[0]), pair_of(now)) if fading else []:
                out.write(f"\x1b[0m{step}\x1b[2J")
                _draw(out, rows, columns, None, state.hint_rows, step, space=space, hide_ticks=hide)
                time.sleep(FADE_STEP_SECONDS)
            out.write(f"\x1b[0m{now}\x1b[2J")  # a new background fills the whole screen
            drawn[0] = now
        opened[0] = True
        place, tail = state.cursor(), ""
        if place is not None:
            row, column = place
            row += space.gap if row >= len(rows) - state.hint_rows else 0
            tail = f"\x1b[{space.top + row + 1};{space.side + column + 1}H{_CURSOR_BLOCK}{_CURSOR_SHOW}"
            shaped[0] = True
        _draw(
            out,
            rows,
            columns,
            style,
            state.hint_rows,
            now,
            accent,
            reverse,
            space,
            code,
            faint=own_faint(now),
            tail=tail,
            dimmer=dimmer_code(now, accent),
        )

    def dimmer_code(codes: str, accent: str) -> str:
        """Full color only, where the text and background colors are known."""
        full_color = os.environ.get("COLORTERM", "").lower() in ("truecolor", "24bit")
        pair = pair_of(codes)
        if pair is None or not full_color or os.environ.get("NO_COLOR"):
            return ""
        text = pair[0]
        accented = _ACCENT_COLOR.fullmatch(accent)
        if accented:
            text = tuple(int(value) for value in accented.groups())  # type: ignore[assignment]
        shade = dimmer(text, pair[1])
        return f"\x1b[38;2;{';'.join(map(str, shade))}m" if shade else ""

    def own_faint(codes: str) -> str:
        """The terminal's own text halfway to its background: not every terminal makes it faint."""
        full_color = os.environ.get("COLORTERM", "").lower() in ("truecolor", "24bit")
        if codes or own_colors is None or not full_color or os.environ.get("NO_COLOR"):
            return ""
        text, back = own_colors
        mixed = (str(round(t + (b - t) * _FADED)) for t, b in zip(text, back, strict=True))
        return f"\x1b[38;2;{';'.join(mixed)}m"

    def pair_of(codes: str) -> Pair | None:
        return scheme_pair(codes) if codes else own_colors

    def fade_out() -> None:
        rows = state.render(text_width(columns, space))
        hide = bool(code_for(drawn[0])[0])
        for step in fade_frames(pair_of(drawn[0]), own_colors):
            out.write(f"\x1b[0m{step}\x1b[2J")
            _draw(out, rows, columns, None, state.hint_rows, step, space=space, hide_ticks=hide)
            time.sleep(FADE_STEP_SECONDS)

    drawn = [""]
    opened = [False]  # until the first draw
    shaped = [False]  # the cursor was made a block
    raw_text = dict(sections)
    if 0 < start_section < len(state.sections):
        state.index = start_section
    if start_line:
        state.top = min(start_line, state.max_top)
    elif start_heading:
        state.top = min(state._heading_line(start_heading), state.max_top)
    elif start_section <= 0 and open_list and not state.single:
        arrived, state.arrived = state.arrived, ""
        state.handle("g")
        state.arrived = arrived

    old_settings = None
    if key_source is None:
        if sys.platform == "win32":
            key_source = _windows_key_reader()
        else:
            import termios
            import tty

            fd = sys.stdin.fileno()
            old_settings = termios.tcgetattr(fd)
            tty.setcbreak(fd)
            key_source = _posix_key_reader(fd)

    outcome = Outcome.QUIT
    was_resized = False
    kept = bool(_KEPT)  # still on the screen another document left, so nothing flashes between them
    _KEPT.clear()
    out.write(("" if kept else enter + "\x1b[2J") + _CURSOR_HIDE)
    if kept:
        drawn[0] = _UNDRAWN  # the first draw clears the screen, in this document's colors
    if own_colors is None and old_settings is not None and colors:
        own_colors = terminal_colors(sys.stdin.fileno(), out)
    elif own_colors is None and sys.platform == "win32" and colors:
        own_colors = windows_terminal_colors(out)
    left_normally = False
    told: set[int] = set()

    def tell() -> None:
        if shown is not None and state.index not in told:
            told.add(state.index)
            shown(state.index)

    try:
        draw()
        tell()
        while True:
            try:
                key = key_source()
            except KeyboardInterrupt:
                key = "ctrl-c"
            resized = _terminal_size() != (columns, height)  # also a resize the key reader missed
            if key == "resize" or resized:
                was_resized = True
                columns, height = _terminal_size()
                space = margins(columns, height)
                state.set_sections(
                    [(n, wrapped(raw_text[n], columns)) for n, _ in state.sections], rows_for_text(height)
                )
                out.write(f"{drawn[0]}\x1b[2J")
                if key != "resize":
                    state.handle("resize")  # the section list starts again from its top
            action = state.handle(key)
            if resized and action is Action.NOTHING:
                action = Action.REDRAW  # the screen was cleared: draw it again even if the key did nothing
            if action is Action.QUIT_RESTORE:
                outcome, left_normally = Outcome.QUIT, True
                break
            if action is Action.FINISH_KEEP:
                outcome, left_normally = Outcome.FINISHED, True
                break
            if action is Action.GO:
                asked = state.opening_doc
                problem = (
                    open_document(asked) if open_document and asked else "Documents can't be opened here."
                )
                if not problem:
                    outcome = Outcome.GO
                    break
                state.notice, action = problem, Action.REDRAW
            if action is Action.OPEN_LINK:
                state.notice = open_link(state.opening) if open_link else "Links can't be opened from here."
            if action in (Action.REDRAW, Action.SAVE_COLORS, Action.OPEN_LINK):
                draw()
                tell()
            if action is Action.SAVE_COLORS and save_color is not None:
                try:
                    save_color(state.color_name)
                except OSError:
                    pass  # it still applies until the pager closes
        if fade and left_normally:
            fade_out()
    finally:
        going = outcome is Outcome.GO
        out.write("\x1b[0m" + (_CURSOR_USUAL if shaped[0] else "") + ("" if going else _CURSOR_SHOW + leave))
        if going:
            _KEPT.append(leave)
        out.flush()
        if old_settings is not None:
            import termios

            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old_settings)
    if remember is not None:
        remember(state.index, state.top)
    if was_resized and outcome is not Outcome.GO:
        return Outcome.FINISHED_RESIZED if outcome is Outcome.FINISHED else Outcome.QUIT_RESIZED
    return outcome
