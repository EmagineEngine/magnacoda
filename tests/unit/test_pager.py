import ast
import importlib.util
import io
import shutil
import sys
from pathlib import Path

import pytest

from magnacoda.pager import screen as pager
from magnacoda.pager.screen import Action, PagerState, pager_available, read_key


def _state(sections=None, height=7):
    sections = sections or [("one", [f"a{i}" for i in range(12)]), ("two", ["b0", "b1"]), ("three", ["c0"])]
    return PagerState(sections, height)


# --- the state machine ---------------------------------------------------------------------------


def test_space_shows_the_next_screenful_then_the_next_section_then_finishes():
    state = _state()  # body height 5 (two rows of key hints); section one has 12 lines
    assert state.handle("space") is Action.REDRAW and (state.index, state.top) == (0, 4)  # a4 shows again
    assert state.handle("space") is Action.REDRAW and (state.index, state.top) == (0, 8)
    assert state.handle("space") is Action.REDRAW and (state.index, state.top) == (1, 0)
    assert state.handle("space") is Action.REDRAW and (state.index, state.top) == (2, 0)
    assert state.handle("space") is Action.FINISH_KEEP  # past the last screen of the last section


@pytest.mark.parametrize("back", ["p", "P", "N"])
def test_n_and_p_turn_the_page_like_space_and_b(back):
    state = _state()
    assert state.handle("n") is Action.REDRAW and (state.index, state.top) == (0, 4)
    assert state.handle(back) is Action.REDRAW and (state.index, state.top) == (0, 0)


def test_the_last_screen_starts_at_the_top_with_blank_rows_below_and_the_arrows_stop_there():
    state = _state()
    state.handle("space"), state.handle("space")
    assert state.render(40)[:5] == [pager._CARRIED_MARK + "a8", "a9", "a10", "a11", ""]
    assert state.handle("down") is Action.NOTHING
    assert state.handle("up") is Action.REDRAW and state.top == 7


def test_the_next_screen_repeats_the_last_line_of_text_not_a_blank_one():
    state = _state([("one", ["a0", "a1", "a2", "a3", "", "b0", "b1", "b2", "b3", "b4"])])
    state.handle("space")
    assert state.top == 3  # a3, then the blank line
    state.handle("space")
    assert state.top == 7  # b2
    assert state.handle("b") is Action.REDRAW and state.top == 3


def test_the_line_carried_over_from_the_screen_before_is_drawn_faint_only_after_paging_on():
    state = _state()
    state.handle("space")
    rows = state.render(40)
    assert rows[0] == pager._CARRIED_MARK + "a4" and rows[1] == "a5"
    out = io.StringIO()
    pager._draw(out, rows, 40, None, state.hint_rows, colors="\x1b[39m")
    assert "\x1b[39m\x1b[2ma4\x1b[22m" in out.getvalue() and "\x1b[2ma5" not in out.getvalue()
    state.handle("down"), state.handle("up")
    assert state.render(40)[0] == "a4"
    state.handle("space"), state.handle("b")
    assert state.render(40)[0] == "a4"


def test_with_a_themes_full_colors_the_carried_line_goes_halfway_to_the_background():
    theme = "\x1b[38;2;200;200;200;48;2;0;0;0m"
    assert pager._faded(theme + "a4", theme) == "\x1b[38;2;100;100;100;48;2;0;0;0ma4"
    assert pager._faded("\x1b[1ma4", "") == "\x1b[1ma4"
    out = io.StringIO()
    state = _state()
    state.handle("space")
    pager._draw(out, state.render(40), 40, None, state.hint_rows, theme)
    assert "\x1b[38;2;100;100;100;48;2;0;0;0m\x1b[2ma4" in out.getvalue()


def test_esc_q_and_ctrl_c_quit_and_restore():
    for key in ("esc", "q", "ctrl-c", "eof"):
        assert _state().handle(key) is Action.QUIT_RESTORE


def test_a_short_section_is_one_screen_and_space_moves_on():
    state = _state([("a", ["x"]), ("b", ["y"])])
    assert state.handle("space") is Action.REDRAW and state.index == 1
    assert state.handle("space") is Action.FINISH_KEEP


def test_back_goes_up_a_screen_then_to_the_end_of_the_previous_section():
    state = _state()
    state.handle("space"), state.handle("space"), state.handle("space")  # now in section two
    assert state.handle("b") is Action.REDRAW and (state.index, state.top) == (0, 8)  # its last screen
    assert state.handle("b") is Action.REDRAW and state.top == 4
    assert state.handle("b") is Action.REDRAW and state.top == 0
    assert state.handle("b") is Action.NOTHING  # already at the very start


def test_line_keys_scroll_one_line_and_stop_at_the_ends():
    state = _state()
    assert state.handle("down") is Action.REDRAW and state.top == 1
    assert state.handle("j") is Action.REDRAW and state.top == 2
    assert state.handle("up") is Action.REDRAW and state.handle("k") is Action.REDRAW and state.top == 0
    assert state.handle("up") is Action.NOTHING
    assert state.handle("end") is Action.REDRAW and state.top == 7
    assert state.handle("down") is Action.NOTHING
    assert state.handle("home") is Action.REDRAW and state.top == 0
    assert state.handle("home") is Action.NOTHING


def test_unknown_keys_do_nothing():
    assert _state().handle("other") is Action.NOTHING


def test_resize_keeps_the_section_and_roughly_the_place():
    state = _state()
    state.handle("space")
    lines = [f"a{i}" for i in range(24)]  # narrower terminal: the same section wraps to more lines
    state.set_sections([("one", lines), ("two", ["b0"]), ("three", ["c0"])], height=10)
    assert state.index == 0 and 0 < state.top <= state.max_top


# --- rendering ----------------------------------------------------------------------------------


def test_render_is_exactly_the_screen_height_with_the_key_hints_last():
    rows = _state().render(100)
    assert len(rows) == 7
    assert rows[:5] == ["a0", "a1", "a2", "a3", "a4"]
    assert rows[-2] == "Section 1 of 3: one | Go: g | Find: / | Back: ← | Next: → | Quit: Esc"
    assert rows[-1] == "Scroll: ↑ ↓ | lines 1-5 of 12"


def test_status_says_finish_on_the_last_screen_and_shortens_to_fit_a_narrow_width():
    state = _state()
    for _ in range(4):
        state.handle("space")
    assert state.at_last_section and "Finish: →" in state.status(100)
    assert "Section 3 of 3: three" not in state.status(70) and "3/3 three" in state.status(70)
    narrow = _state().status_rows(30)
    assert all(len(row) <= 30 for row in narrow) and "→" in narrow[0] and "Esc" in narrow[0]


def test_a_section_that_fits_shows_no_line_range():
    state = _state([("only", ["x", "y"])])
    assert "lines" not in state.status(80)


def test_the_arrow_keys_left_and_right_work_like_b_and_space():
    by_arrows, by_keys = _state(), _state()
    for arrow, key in [("right", "space"), ("right", "space"), ("right", "space"), ("left", "b")]:
        assert by_arrows.handle(arrow) is by_keys.handle(key)
        assert (by_arrows.index, by_arrows.top) == (by_keys.index, by_keys.top)


def test_a_digit_on_a_page_opens_the_section_list_with_it_typed_and_enter_goes_there():
    state = _state()
    state.handle("down")
    assert state.handle("3") is Action.REDRAW and state.menu and state.typed == "3"
    assert state.handle("enter") is Action.REDRAW and (state.index, state.top) == (2, 0) and not state.menu


def test_g_lists_the_sections_under_a_field_to_type_in():
    state = _state()
    assert state.handle("g") is Action.REDRAW and state.menu
    rows = state.render(80)
    assert rows[0] == "Go to: " + pager._FIELD_ON + " " * 30 + pager._FIELD_OFF
    assert rows[1:5] == ["", "  1  one", "  2  two", "  3  three"] and len(rows) == 7
    assert state.cursor() == (0, 7)  # at the start of the field
    assert rows[-1] == "Type a number or name, then Enter | Pick: ↑ ↓ ← → | Back: Esc"
    for key in "2", "enter":
        state.handle(key)
    assert not state.menu and state.index == 1


@pytest.mark.parametrize("keys", [["esc"], ["enter"], ["space", "enter"]])
def test_esc_or_enter_on_nothing_in_the_section_list_goes_back_instead_of_quitting(keys):
    state = _state()
    state.handle("g")
    for key in keys:
        state.handle(key)
    assert not state.menu and state.index == 0
    assert state.handle("esc") is Action.QUIT_RESTORE  # back on the page, Esc quits as usual


@pytest.mark.parametrize("opener,typed", [("g", "q"), ("g", "Q"), ("g", ":q"), (":", "q"), (":", "Q ")])
def test_q_and_enter_in_the_section_list_quits_as_in_less(opener, typed):
    state = _state()
    state.handle(opener)
    for key in typed:
        state.handle(key)
    assert state.handle("enter") is Action.QUIT_RESTORE


@pytest.mark.parametrize("typed,index", [("two", 1), ("Th", 2), ("1", 0), (":3", 2)])
def test_a_section_s_number_or_the_start_of_its_name_goes_there(typed, index):
    state = _state()
    state.handle("g")
    for key in typed:
        state.handle(key)
    assert state.typed == typed and state.handle("enter") is Action.REDRAW
    assert not state.menu and state.index == index


def test_every_key_types_in_the_list_and_backspace_takes_one_back():
    state = _state()
    state.handle("g")
    for key in ["b", "g", "q", "j", "k", "f", "c", "space", "x"]:
        state.handle(key)
    assert state.typed == "bgqjkfc x" and state.menu
    assert state.handle("backspace") is Action.REDRAW and state.typed == "bgqjkfc "


@pytest.mark.parametrize(
    "typed,notice",
    [
        ("4", "No section 4: they go from 1 to 3."),
        ("t", "Type two or more letters of a name."),  # one letter is a command, as q is
    ],
)
def test_a_number_out_of_range_or_a_name_that_fits_several_says_so_and_the_list_stays(typed, notice):
    state = _state()
    state.handle("g")
    state.handle(typed)
    assert state.handle("enter") is Action.REDRAW and state.menu and state.typed == typed
    assert state.render(80)[-1].startswith(notice)
    state.handle("backspace")
    assert not state.notice  # until the next key


@pytest.mark.parametrize("documents,more", [(False, ""), (True, " For other documents, type o, then Enter.")])
def test_text_that_names_no_section_says_so_and_points_to_the_open_list(documents, more, tmp_path):
    state = _state()
    if documents:
        state.documents = [pager.Entry("Manual", tmp_path / "manual.md")]
    state.handle("g")
    for key in "docs x":
        state.handle("space" if key == " " else key)
    assert state.handle("enter") is Action.REDRAW and state.menu
    assert state.notice == "No section named 'docs x'." + more


@pytest.mark.parametrize("typed,marked", [("t", []), ("tw", ["two"]), ("3", ["three"]), ("docs", [])])
def test_the_sections_what_is_typed_would_go_to_are_marked_as_it_is_typed(typed, marked):
    state = _state()
    state.handle("g")
    for key in typed:
        state.handle(key)
    rows = state.render(80)[2:5]
    assert [row.split()[-1].removesuffix("\x1b[27m") for row in rows if "\x1b[7m" in row] == marked


@pytest.mark.parametrize("code,shaded", [(("<ON>", "<OFF>"), "<ON>ab"), (("", ""), "\x1b[7mab")])
def test_the_field_is_shaded_like_code_or_else_reversed(code, shaded):
    out = io.StringIO()
    pager._draw(out, [f"Go to: {pager._FIELD_ON}ab{pager._FIELD_OFF}"], 40, None, 0, code=code)
    assert shaded in out.getvalue()


def test_the_cursor_is_a_blinking_block_in_the_field_and_its_own_shape_comes_back(monkeypatch):
    monkeypatch.setattr(pager, "alternate_screen_codes", lambda env=None: ("<ENTER>", "<LEAVE>"))
    monkeypatch.setattr(pager, "_terminal_size", lambda: (60, 12))
    for keys, shaped in ((["g", "d", "esc", "esc"], True), (["esc"], False)):
        out = io.StringIO()
        it = iter(keys)
        pager.page_sections([("a", "one"), ("b", "two")], out=out, key_source=lambda it=it: next(it))
        drawn = out.getvalue()
        assert ("\x1b[2;11H\x1b[1 q\x1b[?25h" in drawn) is shaped  # under the top margin, after "d"
        assert drawn.endswith(("\x1b[0 q" if shaped else "") + "\x1b[?25h<LEAVE>")


def test_picking_with_the_arrows_replaces_what_was_typed():
    state = _state()
    state.handle("g")
    state.handle("3")
    state.handle("down")
    assert state.typed == "" and state.menu_pick == 0
    state.handle("t")
    assert state.typed == "t" and state.menu_pick is None


def test_a_single_section_that_fits_shows_only_how_to_quit():
    state = _state([("about", ["x", "y"])])
    assert state.render(80)[-1] == "Quit: Esc" and len(state.render(80)) == 7
    assert state.handle("g") is Action.NOTHING and state.handle("1") is Action.NOTHING
    assert state.handle("space") is Action.FINISH_KEEP  # still leaves it printed, unadvertised


def test_a_single_long_section_shows_paging_and_scrolling_but_not_go_to():
    rows = _state([("scan", [f"s{i}" for i in range(20)])]).render(100)
    assert rows[-2] == "scan | Find: / | Back: ← | Next: → | Quit: Esc"
    assert rows[-1] == "Scroll: ↑ ↓ | lines 1-5 of 20"


def test_a_title_stays_on_the_top_row_of_the_page_and_the_section_list():
    state = PagerState([("one", [f"a{i}" for i in range(12)]), ("two", ["b0"])], 8, title="magnacoda - Help")
    rows = state.render(100)
    assert rows[0] == "magnacoda - Help" and rows[1:6] == ["a0", "a1", "a2", "a3", "a4"] and len(rows) == 8
    state.handle("g")
    assert state.render(100)[0] == "magnacoda - Help"


def test_no_title_means_no_title_row():
    assert _state().render(80)[0] == "a0"


@pytest.mark.parametrize("background", [(0, 0, 0), (255, 255, 255), (253, 246, 227)])
def test_the_title_is_a_blue_that_reaches_7_to_1_on_the_terminals_background(background):
    style = pager.title_style({"COLORTERM": "truecolor"}, background=background)
    blue = tuple(int(n) for n in style.removeprefix("\x1b[1;3;38;2;").removesuffix("m").split(";"))
    assert pager._contrast(blue, background) >= 7


def test_the_title_is_plain_without_a_known_background_full_color_or_with_no_color():
    full = {"COLORTERM": "truecolor"}
    assert pager.title_style(full) == "\x1b[1;3m"
    assert pager.title_style({}, background=(0, 0, 0)) == "\x1b[1;3m"
    assert pager.title_style({**full, "NO_COLOR": "1"}, background=(0, 0, 0)) == "\x1b[1;3m"


def test_page_sections_draws_the_title_and_reverse_videos_every_key_hint_row(monkeypatch):
    monkeypatch.setattr(pager, "alternate_screen_codes", lambda env=None: ("<ENTER>", "<LEAVE>"))
    monkeypatch.setattr(pager, "_terminal_size", lambda: (60, 6))
    monkeypatch.delenv("NO_COLOR", raising=False)
    out = io.StringIO()
    keys = iter(["esc"])
    text = "\n".join(f"line {i}" for i in range(10))
    pager.page_sections([("a", text)], out=out, key_source=lambda: next(keys), title="Help")
    drawn = out.getvalue()
    assert "\x1b[1;1H  \x1b[1;3mHelp\x1b[0m" in drawn  # a short window: side margins only
    assert "\x1b[5;1H  \x1b[7m" in drawn and "\x1b[6;1H  \x1b[7m" in drawn


def _many(count=12):
    return PagerState([(f"s{n}", [f"line {n}"]) for n in range(1, count + 1)], 20)


def test_with_ten_or_more_sections_numbers_wait_for_enter_too():
    state = _many(12)
    for key in "1", "2":
        state.handle(key)
    assert pager._visible(state.render(80)[0]).startswith("Go to: 12 ") and state.cursor() == (0, 9)
    assert state.handle("enter") is Action.REDRAW and not state.menu and state.index == 11


def test_the_section_list_shows_every_section_with_aligned_numbers_and_says_to_press_enter():
    state = _many(12)
    state.handle("g")
    rows = state.render(80)
    assert rows[2] == "   1  s1" and rows[13] == "  12  s12"
    assert rows[-1] == "Type a number or name, then Enter | Pick: ↑ ↓ ← → | Back: Esc"


# --- reading keys ---------------------------------------------------------------------------------


def _reader(data: bytes):
    queue = list(data)

    def read(timeout):
        if not queue:
            return b""
        return bytes([queue.pop(0)])

    return read


@pytest.mark.parametrize(
    "data,key",
    [
        (b" ", "space"),
        (b"\r", "enter"),
        (b"q", "q"),
        (b"Q", "Q"),
        (b"b", "b"),
        (b"\x7f", "backspace"),
        (b"j", "j"),
        (b"\x03", "ctrl-c"),
        (b"\x1b", "esc"),
        (b"\x1b[A", "up"),
        (b"\x1b[B", "down"),
        (b"\x1b[5~", "pgup"),
        (b"\x1b[6~", "pgdn"),
        (b"\x1b[H", "home"),
        (b"\x1b[F", "end"),
        (b"\x1bOA", "up"),
        (b"\x1bOB", "down"),
        (b"\x1b[C", "right"),
        (b"\x1b[D", "left"),
        (b"g", "g"),
        (b"1", "1"),
        (b"9", "9"),
        (b"0", "0"),
        (b"\x1b[1;5C", "other"),
        (b"x", "x"),
        (b"\x01", "other"),
    ],
)
def test_read_key_names_each_key(data, key):
    assert read_key(_reader(data)) == key


def test_a_lone_escape_is_not_confused_with_an_arrow_key_that_follows_it():
    reader = _reader(b"\x1b[A\x1b")
    assert read_key(reader) == "up"
    assert read_key(reader) == "esc"


def test_end_of_input_is_a_key_too():
    assert read_key(_reader(b"")) == "eof"


# --- when paging is allowed --------------------------------------------------------------------------


class _Tty(io.StringIO):
    def __init__(self, tty: bool):
        super().__init__()
        self._tty = tty

    def isatty(self):
        return self._tty


def test_paging_needs_a_real_terminal_on_both_ends(monkeypatch):
    monkeypatch.setattr(pager, "alternate_screen_codes", lambda env=None: ("<", ">"))
    assert pager_available(_Tty(True), _Tty(True), {"TERM": "xterm"}) is True
    assert pager_available(_Tty(False), _Tty(True), {"TERM": "xterm"}) is False
    assert pager_available(_Tty(True), _Tty(False), {"TERM": "xterm"}) is False


@pytest.mark.parametrize("value", ["off", "OFF", "0", "false", "no"])
def test_the_off_switch_disables_paging(monkeypatch, value):
    monkeypatch.setattr(pager, "alternate_screen_codes", lambda env=None: ("<", ">"))
    env = {"TERM": "xterm", "MAGNACODA_PAGER": value}
    assert pager_available(_Tty(True), _Tty(True), env, off_switch="MAGNACODA_PAGER") is False
    assert pager_available(_Tty(True), _Tty(True), env) is True  # no switch named: nothing turns it off


def test_no_alternate_screen_means_no_paging(monkeypatch):
    monkeypatch.setattr(pager, "alternate_screen_codes", lambda env=None: None)
    assert pager_available(_Tty(True), _Tty(True), {"TERM": "xterm"}) is False


def test_a_dumb_or_missing_terminal_has_no_alternate_screen(monkeypatch):
    monkeypatch.setattr(pager.sys, "platform", "linux")
    assert pager.alternate_screen_codes({"TERM": "dumb"}) is None
    assert pager.alternate_screen_codes({}) is None


def test_page_sections_walks_scripted_keys_and_reports_the_outcome(monkeypatch):
    monkeypatch.setattr(pager, "alternate_screen_codes", lambda env=None: ("<ENTER>", "<LEAVE>"))
    monkeypatch.setattr(pager, "_terminal_size", lambda: (60, 8))

    def run(keys):
        out = io.StringIO()
        it = iter(keys)
        outcome = pager.page_sections(
            [("a", "one\n\ntwo"), ("b", "three")], out=out, key_source=lambda: next(it)
        )
        return outcome, out.getvalue()

    outcome, text = run(["space", "space"])
    assert outcome is pager.Outcome.FINISHED
    assert text.startswith("<ENTER>") and text.endswith("<LEAVE>")
    assert "2/2 b | g go" in text

    outcome, text = run(["esc"])
    assert outcome is pager.Outcome.QUIT and text.endswith("<LEAVE>")


def test_a_document_the_caller_opens_leaves_with_go_and_one_it_cant_says_why(monkeypatch, tmp_path):
    monkeypatch.setattr(pager, "alternate_screen_codes", lambda env=None: ("<ENTER>", "<LEAVE>"))
    monkeypatch.setattr(pager, "_terminal_size", lambda: (60, 12))
    for name in "help.md", "manual.md":
        (tmp_path / name).write_text("text")
    documents = [pager.Entry("Help", tmp_path / "help.md"), pager.Entry("Manual", tmp_path / "manual.md")]
    asked, left = [], []

    def run(typed):
        out = io.StringIO()
        keys = iter(["space", "o", *typed, "enter", "esc", "esc"])
        outcome = pager.page_sections(
            [("a", "one"), ("b", "two")],
            out=out,
            key_source=lambda: next(keys),
            documents=documents,
            document=tmp_path / "help.md",
            open_document=lambda opening: asked.append(opening) or ("" if opening.section else "Not today."),
            remember=lambda section, line: left.append((section, line)),
        )
        return outcome, out.getvalue()

    outcome, text = run(["m", "a", "n", "space", "x"])
    assert outcome is pager.Outcome.GO and "<LEAVE>" not in text  # kept for the next one, so nothing flashes
    assert asked[-1] == pager.Opening(documents[1], "x") and left[-1] == (1, 0)  # where it was left
    out = io.StringIO()
    pager.restore_screen(out)  # the next one never came
    assert out.getvalue().endswith("<LEAVE>")
    outcome, text = run("manual")
    assert outcome is pager.Outcome.QUIT and "Not today." in text


# --- standing alone ----------------------------------------------------------------------------------

PAGER_FILE = Path(pager.__file__)


def test_pager_uses_only_the_standard_library():
    stdlib = set(sys.stdlib_module_names)
    tree = ast.parse(PAGER_FILE.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imported.add(node.module.split(".")[0])
    assert imported <= stdlib, f"pager.py imports non-standard-library modules: {imported - stdlib}"


def test_the_file_works_when_copied_on_its_own_to_another_place(tmp_path):
    copy = tmp_path / "standalone_pager.py"
    shutil.copy(PAGER_FILE, copy)
    spec = importlib.util.spec_from_file_location("standalone_pager", copy)
    module = importlib.util.module_from_spec(spec)
    sys.modules["standalone_pager"] = module
    try:
        spec.loader.exec_module(module)
        state = module.PagerState([("a", ["x"] * 30)], height=11)
        assert state.handle("space") is module.Action.REDRAW and state.top == 8  # the last line shows again
        assert module.default_wrap("one two three four", 9) == ["one two", "three", "four"]
    finally:
        sys.modules.pop("standalone_pager", None)


def test_the_off_switch_variable_is_whatever_name_the_program_passes(monkeypatch):
    monkeypatch.setattr(pager, "alternate_screen_codes", lambda env=None: ("<", ">"))
    on = {"TERM": "xterm", "MAGNACODA_PAGER": "off"}
    assert pager_available(_Tty(True), _Tty(True), on, off_switch="MY_OTHER_PROJECT_PAGER") is True
    off = {"TERM": "xterm", "MY_OTHER_PROJECT_PAGER": "off"}
    assert pager_available(_Tty(True), _Tty(True), off, off_switch="MY_OTHER_PROJECT_PAGER") is False


# --- wrapping --------------------------------------------------------------------------------------


def test_default_wrap_keeps_blank_lines_indents_and_never_splits_a_word():
    text = "alpha beta gamma delta\n\n  indented words that need wrapping\nhttps://example.com/" + "a" * 40
    lines = pager.default_wrap(text, 14)
    assert "" in lines
    assert all(
        line.startswith("  ") for line in lines if "indented" in line or "wrapping" in line or "need" in line
    )
    assert "https://example.com/" + "a" * 40 in lines  # a long unbreakable word stays whole
    assert all(len(line) <= 14 for line in lines if not line.startswith("https"))


def test_a_caller_can_pass_its_own_wrapper(monkeypatch):
    monkeypatch.setattr(pager, "alternate_screen_codes", lambda env=None: ("<E>", "<L>"))
    monkeypatch.setattr(pager, "_terminal_size", lambda: (60, 8))
    seen = []

    def my_wrap(text, width):
        seen.append(width)
        return ["CUSTOM " + line for line in text.splitlines()]

    out = io.StringIO()
    keys = iter(["esc"])
    pager.page_sections([("a", "hello")], out=out, key_source=lambda: next(keys), wrap=my_wrap)
    assert "CUSTOM hello" in out.getvalue() and seen == [56]  # 60 less two margins of 2


def test_margins_grow_with_the_window_and_leave_small_ones_their_room():
    assert pager.margins(100, 30) == pager.Margins(side=2, top=1, gap=1)
    assert pager.margins(50, 30) == pager.Margins(side=1, top=1, gap=1)
    assert pager.margins(25, 11) == pager.Margins()
    assert pager.text_width(100, pager.Margins(side=2)) == 96
    assert pager.text_width(100, pager.Margins()) == 99  # the last column stays empty


def test_the_page_has_a_blank_row_on_top_and_above_the_hints_but_none_below(monkeypatch):
    monkeypatch.setattr(pager, "alternate_screen_codes", lambda env=None: ("", ""))
    monkeypatch.setattr(pager, "_terminal_size", lambda: (80, 12))
    out = io.StringIO()
    keys = iter(["esc"])
    text = "\n".join(f"line {i}" for i in range(30))
    pager.page_sections([("a", text)], out=out, key_source=lambda: next(keys), title="Help")
    drawn = out.getvalue()
    assert "\x1b[1;1H\x1b[K" in drawn and "\x1b[2;1H  \x1b[1;3mHelp" in drawn
    assert "\x1b[3;1H  line 0" in drawn and "\x1b[9;1H  line 6" in drawn
    assert "\x1b[10;1H\x1b[K" in drawn  # the gap above the hints
    assert "\x1b[11;1H  \x1b[7m" in drawn and "\x1b[12;1H  \x1b[7m" in drawn  # down to the last row


# The section list when it is taller than the screen: columns first, then scrolling


def _names(*names, height=10):
    state = PagerState([(name, ["text"]) for name in names], height=height, title="Title")
    state.handle("g")
    return state


def test_a_list_that_fits_stays_one_column():
    state = _names("one", "two", "three")
    assert state.render(80)[3:6] == ["  1  one", "  2  two", "  3  three"]


def test_a_tall_list_spreads_over_columns_filled_top_to_bottom():
    state = _names(*[f"Section {n}" for n in range(1, 13)], height=10)  # 6 rows for the list
    rows = state.render(80)[3:9]
    assert rows[0] == "   1  Section 1    7  Section 7"
    assert rows[5] == "   6  Section 6   12  Section 12"
    assert "More" not in state.render(80)[-1]


def test_each_column_is_as_wide_as_its_longest_name_and_only_the_widest_are_shortened():
    names = ["a"] * 6 + ["What the report shows besides violations"] + ["b"] * 5
    state = _names(*names, height=10)
    rows = state.render(40)[3:9]
    assert rows[0].startswith("   1  a    7  What the report")
    assert rows[0].endswith("…") and all(len(row) <= 40 for row in rows)
    assert state.render(80)[3].endswith("What the report shows besides violations")


def test_when_columns_are_not_enough_the_list_scrolls():
    state = _names(*[f"A rather long section name {n}" for n in range(1, 13)], height=7)  # 3 rows
    screen = state.render(60)
    assert screen[3].startswith("   1  A rather") and "More: PgDn" in screen[-1]
    assert state.handle("pgdn") is Action.REDRAW
    assert not state.render(60)[3].startswith("   1  A rather")
    state.handle("end")
    assert state.handle("pgdn") is Action.NOTHING  # at the bottom of the list
    assert "Less: PgUp" in state.render(60)[-1]
    assert any(" 12  A rather" in row for row in state.render(60)[3:6])
    assert state.handle("home") is Action.REDRAW and state.handle("pgup") is Action.NOTHING
    for key in "1", "2", "enter":
        state.handle(key)
    assert not state.menu and state.index == 11


def test_closing_the_list_forgets_how_far_it_was_scrolled():
    state = _names(*[f"A rather long section name {n}" for n in range(1, 13)], height=7)
    state.render(60)
    state.handle("pgdn")
    state.handle("esc")
    state.handle("g")
    assert state.render(60)[3].startswith("   1  ")


def test_a_resize_the_key_reader_missed_is_caught_at_the_next_key(monkeypatch):
    """On Windows the key reader once never reported resizes, so the page kept the old size; now any key
    after a size change re-measures, re-lays out and redraws (the section list too)."""
    monkeypatch.setattr(pager, "alternate_screen_codes", lambda env=None: ("<ENTER>", "<LEAVE>"))
    size = [(60, 8)]
    monkeypatch.setattr(pager, "_terminal_size", lambda: size[0])
    sections = [(f"Section {n}", f"text {n}") for n in range(1, 13)]
    frames = []

    def keys():
        yield "g"  # the list in a short window
        size[0] = (60, 20)  # the window grows, and nothing reports it...
        yield "other"  # ...until the next key, even one that does nothing
        yield "esc"
        yield "q"

    it = keys()

    class Out(io.StringIO):
        def flush(self):
            frames.append(self.getvalue())

    out = Out()
    pager.page_sections(sections, out=out, key_source=lambda: next(it))
    before, after = frames[1], frames[2][len(frames[1]) :]
    assert "\x1b[8;1H" in before and "\x1b[9;1H" not in before  # 8 rows
    assert "\x1b[20;1H" in after and "\x1b[2J" in after  # cleared and drawn at 20 rows
    assert "  12  Section 12" in after  # the whole list fits in one column now


def test_a_long_section_name_gives_way_before_the_g_hint_does():
    state = PagerState([("staging.example.com_20260922-171927.md", ["x"]), ("Next part", ["y"])], 10)
    assert state.status_rows(80)[0].startswith("1/2 staging.example.com_20260922-171927.md | g go |")
    assert state.status_rows(70)[0] == "1/2 | g go | ← back | → next | Esc quit"


def test_open_list_starts_on_the_section_list_and_esc_shows_the_first_page(monkeypatch):
    monkeypatch.setattr(pager, "alternate_screen_codes", lambda env=None: ("<ENTER>", "<LEAVE>"))
    monkeypatch.setattr(pager, "_terminal_size", lambda: (60, 12))
    for sections, listed in (
        ([("one", "first page"), ("two", "second page")], True),
        ([("one", "only")], False),
    ):
        out = io.StringIO()
        keys = iter(["esc", "esc"])
        pager.page_sections(sections, out=out, key_source=lambda keys=keys: next(keys), open_list=True)
        drawn = out.getvalue()
        assert ("Go to:" in drawn) is listed  # one section: nothing to choose, its page at once
        assert drawn.index(sections[0][1]) > (drawn.index("Go to:") if listed else -1)


def test_the_outcome_says_whether_the_window_was_resized_while_paging(monkeypatch):
    sizes = iter([(60, 12), (60, 12), (60, 12)])
    monkeypatch.setattr(pager, "alternate_screen_codes", lambda env=None: ("", ""))
    monkeypatch.setattr(pager, "_terminal_size", lambda: next(sizes, (60, 12)))
    keys = iter(["q"])
    outcome = pager.page_sections([("One", "text")], out=io.StringIO(), key_source=lambda: next(keys))
    assert outcome is pager.Outcome.QUIT and not outcome.resized
    sizes = iter([(60, 12), (80, 20)])
    keys = iter(["resize", "q"])
    outcome = pager.page_sections([("One", "text")], out=io.StringIO(), key_source=lambda: next(keys))
    assert outcome is pager.Outcome.QUIT_RESIZED and outcome.resized


def test_after_paging_the_shell_feeds_a_page_only_when_the_window_was_resized(monkeypatch):
    from magnacoda import help_sections

    fed = []
    ctx = type(
        "Ctx",
        (),
        {"obj": {"after_pager": lambda: fed.append(True)}, "meta": {}, "find_root": lambda self: self},
    )()
    for outcome, expected in [(pager.Outcome.QUIT, []), (pager.Outcome.QUIT_RESIZED, [True]), (None, [True])]:
        monkeypatch.setattr(help_sections, "show", lambda *a, outcome=outcome, **k: outcome)
        help_sections.show_pages(ctx, [("One", "text")], help_sections.pager_options("Help"))
        assert fed == expected
