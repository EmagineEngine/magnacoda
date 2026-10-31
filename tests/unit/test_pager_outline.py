"""The g list as a document's outline: its own contents list with group labels and subsections, or
its ## and ### headings (markdown.Document.outline, screen.PagerState.outline)."""

import re
from pathlib import Path

from magnacoda.pager import markdown
from magnacoda.pager.screen import Action, OutlineRow, PagerState

DOC = """# Guide

Welcome.

**Contents**

- **[Start here](#start-here)**
- **Getting going**
  - [Install](#install)
    - [On Windows](#on-windows)
  - [First scan](#first-scan)
- **Reference**
  - [Options](#options)

## Start here

Read me first.

## Install

Pip it.

More about pipx.

More about pipx.

More about pipx.

More about pipx.

More about pipx.

More about pipx.

More about pipx.

More about pipx.

More about pipx.

More about pipx.

More about pipx.

More about pipx.


### On Windows

Use py.

## First scan

Scan it.

## Options

All of them.

## Not listed

Extra.
"""


def _plain(rows):
    return [re.sub(r"\x1b\[[0-9;]*m", "", row) for row in rows]


def test_the_outline_follows_the_document_s_own_contents_with_groups_and_subsections():
    outline = markdown.parse(DOC).outline
    assert outline == [
        (0, "Introduction", "Introduction", ""),  # before the contents' first: kept in its place
        (0, "Start here", "Start here", ""),
        (0, "Getting going", "", ""),
        (1, "Install", "Install", ""),
        (2, "On Windows", "Install", "On Windows"),
        (1, "First scan", "First scan", ""),
        (0, "Reference", "", ""),
        (1, "Options", "Options", ""),
        (0, "Not listed", "Not listed", ""),  # a section the contents leave out comes at the end
    ]


def test_without_a_contents_list_the_outline_is_the_headings_and_without_subsections_none():
    text = "## One\n\nx\n\n### Part\n\ny\n\n```\n### not a heading\n```\n\n## Two\n\nz\n"
    assert markdown.parse(text).outline == [
        (0, "One", "One", ""),
        (1, "Part", "One", "Part"),
        (0, "Two", "Two", ""),
    ]
    assert markdown.parse("## One\n\nx\n\n## Two\n\ny\n").outline == []


def _state(width=100, height=20):
    document = markdown.parse(DOC)
    state = PagerState([(name, markdown.render(text, width)) for name, text in document.sections], height)
    numbers = {name: n for n, (name, _) in enumerate(state.sections)}
    state.outline = [OutlineRow(d, label, numbers.get(name), h) for d, label, name, h in document.outline]
    state.width = width
    state.handle("g")
    return state


def test_the_list_shows_group_labels_numbered_sections_and_indented_subsections():
    state = _state()
    rows = state.render(100)
    plain = _plain(rows)
    assert "   Getting going" in " ".join(plain)
    install = next(row for row in plain if row.strip() == "3    Install")
    windows = next(row for row in plain if row.strip() == "- On Windows")
    assert windows.index("-") == install.index("Install")  # a hyphen under its section's first letter
    assert not any("\x1b[1m" in row for row in rows)  # labels aren't bold
    getting = next(n for n, row in enumerate(plain) if row.strip() == "Getting going")
    assert plain[getting - 1].strip() == ""  # a blank row above a group label


def test_a_typed_subsection_name_is_marked_and_enter_opens_its_section_at_it():
    for typed in "windows", "On Win":
        state = _state()
        for key in typed:
            state.handle("space" if key == " " else key)
        assert any("\x1b[7m- On Windows" in row for row in state.render(100))
        state.handle("enter")
        shown = _plain(state.lines[state.top : state.top + state.body_height])
        assert state.index == 2 and state.top > 0 and "On Windows" in [line.strip() for line in shown]


def test_arrows_skip_group_labels_and_enter_on_a_subsection_opens_its_section_at_it():
    state = _state()
    state.handle("down")  # Introduction
    state.handle("down")  # Start here
    state.handle("down")  # Install (the group label is passed over)
    assert state.outline[state.menu_pick].label == "Install"
    state.handle("down")
    assert state.outline[state.menu_pick].heading == "On Windows"
    assert state.status_rows(100)[0].startswith("Links: 3, Install › On Windows | Go: Enter")
    state.handle("enter")
    assert not state.menu and state.index == 2
    shown = _plain(state.lines[state.top : state.top + state.body_height])
    assert "On Windows" in [line.strip() for line in shown] and state.top > 0


def test_left_and_right_go_to_the_nearest_row_in_the_next_column_and_stop_at_the_edges():
    state = _state(width=100, height=8)  # 5 rows for the list: two columns
    columns = state._outline_layout()[0]
    assert len(columns) >= 2 and all(c[0] is not None and c[-1] is not None for c in columns)  # no blank ends
    state.handle("down")
    assert state.handle("right") is Action.REDRAW
    assert state.menu_pick in columns[1]
    state.handle("left")
    assert state.menu_pick in columns[0]
    assert state.handle("left") is Action.NOTHING  # no column before the first


def test_tab_wraps_around_the_rows_that_go_somewhere_and_digits_still_jump():
    state = _state()
    state.handle("shift-tab")
    assert state.outline[state.menu_pick].label == "Not listed"
    state.handle("tab")
    assert state.outline[state.menu_pick].label == "Introduction"
    for key in "4", "enter":
        state.handle(key)
    assert not state.menu and state.index == 3  # section numbers as before


def test_long_names_are_shortened_to_keep_two_columns():
    many = "".join(
        f"- **Group {g}**\n" + "".join(f"  - [Section {g}{n}](#section-{g}{n})\n" for n in range(4))
        for g in range(4)
    )
    sections = "".join(
        f"## Section {g}{n}{' with a very long name indeed to cut' if n == 0 else ''}\n\nx\n\n"
        for g in range(4)
        for n in range(4)
    )
    contents = many.replace("](#section-00)", "](#section-00-with-a-very-long-name-indeed-to-cut)")
    document = markdown.parse("**Contents**\n\n" + contents + "\n" + sections)
    state = PagerState([(name, ["x"]) for name, _ in document.sections], 14)
    numbers = {name: n for n, (name, _) in enumerate(state.sections)}
    state.outline = [OutlineRow(d, label, numbers.get(name), h) for d, label, name, h in document.outline]
    state.width = 70
    state.handle("g")
    columns, widths = state._outline_layout()
    assert len(columns) >= 2 and sum(widths) <= 70
    assert any("…" in row for row in state.render(70))


def test_a_checklist_s_outline_follows_its_sections_renamed_with_their_progress(tmp_path):
    from magnacoda import viewer

    page = tmp_path / "checklist.md"
    page.write_text("# List\n\n## Fix\n\n- [x] one\n\n### Images\n\n- [ ] two\n\n## Check\n\n- [ ] three\n")
    shown = viewer.load(str(page))
    names = [name for name, _ in shown.sections]
    assert {name for _, _, name, _ in shown.outline} <= set(names)
    assert any(heading == "Images" for _, _, _, heading in shown.outline)


def test_the_manual_s_outline_fits_an_80_by_24_window_in_columns_without_scrolling():
    manual = Path(__file__).resolve().parents[2] / "docs" / "manual.md"
    document = markdown.parse(manual.read_text(encoding="utf-8"))
    state = PagerState([(name, ["x"]) for name, _ in document.sections], 22)
    numbers = {name: n for n, (name, _) in enumerate(state.sections)}
    state.outline = [OutlineRow(d, label, numbers.get(name), h) for d, label, name, h in document.outline]
    state.width = 76
    state.handle("g")
    columns, _ = state._outline_layout()
    assert len(columns) >= 3 and not state.menu_scrolls
    labels = [row for row in _plain(state.render(76)) if "Using magnacoda" in row]
    assert labels[0].index("Using") == 2  # where the numbers start


# --- groups: a ## heading with a short sentence over its ### pages -----------------------------------

GROUPED = """# Guide

## Getting going

How to start: install it, then scan.

### Install

Pip it. See [Scan](#scan).

#### On Windows

Use py.

### Scan

Run it.

## Reference

Everything about the options, in one long section with real text of its own.

### Options

All of them.
"""


def test_a_group_s_pages_are_its_subsections_and_its_sentence_opens_the_first():
    document = markdown.parse(GROUPED)
    assert [name for name, _ in document.sections] == ["Install", "Scan", "Reference"]
    first = document.sections[0][1]
    assert first.startswith("## Getting going\n\nHow to start") and "### Install" in first
    assert "(section\ue0002)" in first  # links count pages
    assert document.outline == [
        (0, "Getting going", "", ""),
        (1, "Install", "Install", ""),
        (2, "On Windows", "Install", "On Windows"),
        (1, "Scan", "Scan", ""),
        (0, "Reference", "Reference", ""),  # one ### only: a section as before
        (1, "Options", "Reference", "Options"),
    ]


def test_only_a_short_single_paragraph_of_prose_makes_a_group():
    pages = "### A\n\nx\n\n### B\n\ny\n"
    for intro in ("Two\n\nparagraphs.", "- a list", "| a | table |", "```\ncode\n```", "x" * 401):
        sections = markdown.parse(f"## Group\n\n{intro}\n\n{pages}").sections
        assert [name for name, _ in sections] == ["Group"], intro
    assert [name for name, _ in markdown.parse(f"## Group\n\n{pages}").sections] == ["A", "B"]  # no sentence


def test_a_document_of_only_level_two_sections_pages_and_numbers_as_before():
    document = markdown.parse("# Title\n\nIntro.\n\n## One\n\nSee [Two](#two).\n\n## Two\n\nText.\n")
    assert [name for name, _ in document.sections] == ["Introduction", "One", "Two"]
    assert "Two (section\ue0003)" in document.sections[1][1]
    assert document.outline == []  # the plain numbered g list


def test_the_readme_pages_by_its_subsections_under_its_group_labels():
    readme = Path(__file__).resolve().parents[2] / "README.md"
    document = markdown.parse(readme.read_text(encoding="utf-8"))
    names = [name for name, _ in document.sections]
    assert names[0] == "What is magnacoda?" and "Quick start" in names and "About the name" in names
    labels = [label for depth, label, name, _ in document.outline if not name]
    assert labels[:2] == ["Introducing magnacoda", "How do I get started?"] and "About" in labels


def test_a_short_document_is_one_page_and_its_g_list_a_table_of_contents_that_scrolls_to_a_heading(
    monkeypatch,
):
    monkeypatch.setattr(markdown, "ONE_PAGE_WORDS", 800)
    document = markdown.parse("# The *Name*\n\nIntro.\n\n## You may\n\nOne.\n\n## You may not\n\nTwo.\n")
    assert [name for name, _ in document.sections] == ["The Name"]
    assert document.outline == [
        (0, "Introduction", "The Name", ""),
        (0, "You may", "The Name", "You may"),
        (0, "You may not", "The Name", "You may not"),
    ]
    lines = ["Intro.", "", "You may", "", "One.", "", "You may not", "", "Two."]
    state = PagerState([("The Name", lines)], 4)
    state.outline = [OutlineRow(*row[:2], 0, row[3]) for row in document.outline]
    assert "Go: g" in state.render(80)[-2]
    state.handle("g")
    assert "You may not" in "".join(state.render(80)) and "Type a name" in state.render(80)[-1]
    for key in "you may not":
        state.handle("space" if key == " " else key)
    state.handle("enter")
    assert not state.menu and state.top == min(6, state.max_top)
