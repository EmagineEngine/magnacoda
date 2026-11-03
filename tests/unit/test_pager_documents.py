"""The Open list (o): documents from a list file, picking and typing, and the open one marked."""

import pytest

from magnacoda.pager.documents import read_list
from magnacoda.pager.screen import Action, Entry, Opening, PagerState


def _documents(tmp_path):
    for name in "help.md", "manual.md", "LICENSE.md", "notes.txt", "data.csv":
        (tmp_path / name).write_text("text")
    return [
        Entry("Help", tmp_path / "help.md", "Using it"),
        Entry("Manual", tmp_path / "manual.md", "Using it", ("docs",)),
        Entry("License", tmp_path / "LICENSE.md", "Legal"),
    ]


def _state(tmp_path, document=0, came_from=None, height=14):
    state = PagerState([("one", ["a", "### Starting", "b"]), ("two", ["c"])], height)
    state.documents, state.document, state.came_from = _documents(tmp_path), document, came_from
    return state


def _type(state, text):
    for key in text:
        state.handle("space" if key == " " else key)


def test_the_list_file_gives_groups_titles_other_names_and_leaves_out_missing_files(tmp_path):
    (tmp_path / "docs").mkdir()
    for name in "docs/manual.md", "LICENSE.md":
        (tmp_path / name).write_text("text")
    listed = tmp_path / "documents.md"
    listed.write_text(
        "# Documents\n\nSome words.\n\n## Using it\n\n- [Manual](docs/manual.md) (also: docs, guide)\n"
        "- [Gone](gone.md)\n\n## Legal\n\n* [License](LICENSE.md)\n"
    )
    assert read_list(listed) == [
        Entry("Manual", tmp_path / "docs/manual.md", "Using it", ("docs", "guide")),
        Entry("License", tmp_path / "LICENSE.md", "Legal"),
    ]
    assert read_list(tmp_path / "none.md") == []


def test_o_shows_the_groups_with_the_open_document_marked_and_its_field_at_the_top(tmp_path):
    state = _state(tmp_path)
    assert state.handle("o") is Action.REDRAW and state.doc_list
    rows = state.render(80)
    assert rows[0].startswith("Open: ") and state.cursor() == (0, 6)
    picked = "  \x1b[7m› Help\x1b[27m (open)"
    assert rows[2:9] == ["  Using it", picked, "    Manual", "", "  Legal", "    License", ""]
    assert rows[-1].startswith("Help is open | Back to it: Enter or Esc")
    assert state.handle("enter") is Action.REDRAW and not state.doc_list  # back to the page


def test_after_a_switch_the_pick_starts_on_the_document_come_from_so_enter_goes_back(tmp_path):
    state = _state(tmp_path, document=2, came_from=0)
    state.handle("o")
    assert state.doc_pick == 0 and "Open Help: Enter" in state.render(80)[-1]
    assert state.handle("enter") is Action.GO and state.opening_doc == Opening(state.documents[0], back=True)


@pytest.mark.parametrize(
    "typed,opening",
    [
        ("lic", ("License", "")),
        ("docs", ("Manual", "")),
        ("manual starting", ("Manual", "starting")),
        ("notes.txt", ("notes.txt", "")),
    ],
)
def test_typing_a_name_a_section_after_it_or_a_file_opens_it(tmp_path, monkeypatch, typed, opening):
    monkeypatch.chdir(tmp_path)
    state = _state(tmp_path)
    state.handle("o")
    _type(state, typed)
    assert state.handle("enter") is Action.GO
    assert (state.opening_doc.entry.title, state.opening_doc.section) == opening


@pytest.mark.parametrize(
    "typed,notice",
    [
        ("data.csv", "Only .md and .txt files open here."),
        ("gone.md", "No file named 'gone.md'."),
        ("nothing", "No document named 'nothing'."),
        ("help nowhere", "No section named 'nowhere' in Help."),
    ],
)
def test_what_cant_open_says_why_and_the_list_stays(tmp_path, monkeypatch, typed, notice):
    monkeypatch.chdir(tmp_path)
    state = _state(tmp_path)
    state.handle("o")
    _type(state, typed)
    assert state.handle("enter") is Action.REDRAW and state.doc_list and state.notice == notice


def test_the_open_document_with_a_section_goes_there_without_leaving(tmp_path):
    state = _state(tmp_path)
    state.handle("o")
    _type(state, "help two")
    assert state.handle("enter") is Action.REDRAW and not state.doc_list and state.index == 1


def test_what_is_typed_marks_the_documents_it_would_open(tmp_path):
    state = _state(tmp_path)
    state.handle("o")
    _type(state, "ma")
    assert "\x1b[7m› Manual\x1b[27m" in "".join(state.render(80)) and state.doc_pick is None


def test_without_typed_files_a_file_name_is_just_a_name(tmp_path):
    state = _state(tmp_path)
    state.typed_files = False
    state.handle("o")
    _type(state, "notes.txt")
    assert "Type a name, then Enter" in state.render(80)[-1]
    assert state.handle("enter") is Action.REDRAW and state.notice == "No document named 'notes.txt'."


def test_o_does_nothing_without_documents_or_while_searching(tmp_path):
    state = _state(tmp_path)
    state.documents = []
    assert state.handle("o") is Action.NOTHING
    state = _state(tmp_path)
    state.handle("/"), _type(state, "a"), state.handle("enter")
    state.handle("o")
    assert not state.doc_list


@pytest.mark.parametrize(
    "width,shown,left_out",
    [(120, "Open: o | Find: /", ""), (60, "1/2 one | g go | o open", "/ find"), (40, "g go", "o open")],
)
def test_the_page_says_o_opens_documents_down_to_narrow_windows(tmp_path, width, shown, left_out):
    hints = _state(tmp_path).render(width)[-1]
    assert shown in hints and (not left_out or left_out not in hints)


def test_o_then_enter_in_the_go_to_list_and_g_then_enter_in_the_open_list_switch_between_them(tmp_path):
    state = _state(tmp_path)
    state.handle("g")
    assert "Open: o, Enter" in state.render(120)[-1]
    state.handle("o"), state.handle("enter")
    assert state.doc_list and not state.menu and "Go to: g, Enter" in state.render(120)[-1]
    state.handle("g"), state.handle("enter")
    assert state.menu and not state.doc_list


@pytest.mark.parametrize("opening", ["g", "o"])
def test_one_letter_is_too_short_for_a_name_in_either_list(tmp_path, opening):
    state = _state(tmp_path)
    state.handle(opening)
    state.handle("l")
    assert "\x1b[7m" not in "".join(state.render(80)[2:])  # nothing marked yet
    assert state.handle("enter") is Action.REDRAW and state.notice == "Type two or more letters of a name."


def test_g_opens_its_list_on_a_one_section_page_when_there_are_documents(tmp_path):
    state = _state(tmp_path)
    state.sections = state.sections[:1]
    assert state.handle("g") is Action.REDRAW and state.menu
    state.documents = []
    state.handle("esc")
    assert state.handle("g") is Action.NOTHING


def test_the_arrival_notice_keeps_g_beside_it_and_names_the_way_back_in_the_go_to_list(tmp_path):
    state = _state(tmp_path, document=2, came_from=0)
    state.arrived = "License"
    assert state.render(80)[-1].startswith("Opened License | Back: o, Enter | Go: g")
    state.sections = state.sections[:1]
    assert "g go" not in state.render(80)[-1]  # one section: no Go to list to draw
    state = _state(tmp_path, document=2, came_from=0)
    state.handle("g")
    state.arrived = "License"
    assert state.render(80)[-1].startswith("Opened License | Back: o, Enter | Go: type")
    state.handle("down")
    assert not state.arrived
