import io

import pytest

from magnacoda.pager import screen as pager
from magnacoda.pager.screen import Action, PagerState

SECTIONS = [
    ("one", ["Hello world", "the quick", "brown fox", *[f"a{i}" for i in range(10)], "a Brown fox"]),
    ("two", ["a brown", "  fox jumps"]),
    ("three", ["nothing here"]),
]


def _state(height=7):
    return PagerState([(name, list(lines)) for name, lines in SECTIONS], height)


def _find(state, text):
    state.handle("/")
    for char in text:
        state.handle("space" if char == " " else char)
    return state.handle("enter")


def _field(text):
    return pager._PLAIN_ROW + "Find: " + pager._FIELD_ON + text.ljust(30) + pager._FIELD_OFF


def test_slash_opens_a_find_field_above_the_key_hints_and_marks_matches_as_you_type():
    state = _state()
    assert state.handle("/") is Action.REDRAW and state.finding
    for char in "fox":
        state.handle(char)
    rows = state.render(60)
    assert rows[2] == f"brown {pager._MATCH_ON}fox{pager._MATCH_OFF}"
    assert rows[-2:] == [_field("fox"), "Type a word or phrase, then Enter | Done: Esc"]
    assert state.cursor() == (5, 9)


def test_enter_shows_the_first_match_from_here_and_the_keys_go_through_them_all():
    state = _state()
    assert _find(state, "brown fox") is Action.REDRAW and not state.finding
    rows = state.render(80)
    assert rows[2] == "\x1b[7mbrown fox\x1b[27m" and state.cursor() is None
    assert rows[-2:] == [
        _field("brown fox") + "  1 of 3",
        "Next: n or → | Previous: p or ← | Scroll: ↑ ↓ | Change: / | Done: Esc",
    ]
    state.handle("n")
    assert (state.index, state.top, state.match) == (0, 9, 1)  # scrolled to show it
    state.handle("right")
    assert (state.index, state.match) == (1, 2)
    assert state.render(80)[:2] == ["a \x1b[7mbrown\x1b[27m", "  \x1b[7mfox\x1b[27m jumps"]  # it wraps
    state.handle("enter")
    assert state.match == 0 and state.render(80)[-2].endswith("1 of 3, back at the top")
    state.handle("left")
    assert state.match == 2 and state.render(80)[-2].endswith("back at the end")
    state.handle("p")
    assert state.match == 1 and "back" not in state.render(80)[-2]


@pytest.mark.parametrize("key", ["p", "P", "N", "left"])
def test_p_less_s_capital_n_and_the_left_arrow_go_back(key):
    state = _state()
    _find(state, "fox")
    state.handle("n")
    state.handle(key)
    assert state.match == 0


def test_until_esc_only_the_search_keys_work_and_the_arrows_up_and_down_scroll():
    state = _state()
    _find(state, "fox")
    for key in ["space", "b", "pgdn", "pgup", "g", "c", "tab", "home", "end", "1"]:
        assert state.handle(key) is Action.NOTHING
    assert (state.index, state.top, state.match) == (0, 0, 0)
    assert state.handle("down") is Action.REDRAW and state.top == 1
    assert state.handle("esc") is Action.REDRAW and not state.searching
    assert pager._MATCH_ON not in "".join(state.render(80)) and "\x1b[7m" not in "".join(
        state.render(80)[:-1]
    )
    assert state.handle("esc") is Action.QUIT_RESTORE


def test_slash_again_changes_the_search_starting_from_what_was_found():
    state = _state()
    _find(state, "fox")
    state.handle("/")
    assert state.finding and state.typed == "fox"
    for key in ["backspace", "backspace", "backspace", "j", "u", "m", "p", "enter"]:
        state.handle(key)
    assert state.search == "jump" and state.index == 1


def test_the_search_starts_from_what_the_page_shows():
    state = _state()
    state.handle("space"), state.handle("space")
    _find(state, "fox")
    assert state.match == 1


def test_nothing_found_says_so_and_keeps_the_field_open_with_what_was_typed():
    state = _state()
    assert _find(state, "zebra") is Action.REDRAW
    assert state.finding and state.typed == "zebra"
    assert state.status_rows(80) == [_field("zebra"), 'No "zebra" in this document.']
    assert state.handle("esc") is Action.REDRAW and not state.searching


def test_drawn_matches_are_shaded_like_code_or_underlined_inside_code_and_without_shading():
    code = ("\x1b[48;5;236m", "\x1b[49m")
    lines = [
        f"a {pager._MATCH_ON}fox{pager._MATCH_OFF}",
        f"{pager._CODE_MARK}{pager._MATCH_ON}fox{pager._MATCH_OFF} = 1",
        f"say {pager._TINT_ON}`{pager._MATCH_ON}fox{pager._MATCH_OFF}`{pager._TINT_OFF}",
    ]
    out = io.StringIO()
    pager._draw(out, lines, 40, None, 0, code=code)
    drawn = out.getvalue()
    assert f"a {code[0]}fox{code[1]}" in drawn
    assert "\x1b[4mfox\x1b[24m = 1" in drawn and "\x1b[4mfox\x1b[24m`" not in drawn  # ticks hidden
    plain = io.StringIO()
    pager._draw(plain, lines[:1], 40, None, 0)
    assert "a \x1b[4mfox\x1b[24m" in plain.getvalue()


def test_a_match_at_the_start_of_a_heading_or_code_line_keeps_the_line_s_mark_first():
    state = PagerState([("one", [f"{pager._HEADING_MARK}Fox facts", f"{pager._CODE_MARK}fox()"])], 7)
    _find(state, "fox")
    rows = state.render(40)
    assert rows[0].startswith(pager._HEADING_MARK + "\x1b[7mFox")
    assert rows[1].startswith(pager._CODE_MARK + pager._MATCH_ON + "fox")


def test_the_find_field_s_row_is_drawn_without_reverse_video_and_the_cursor_goes_in_it():
    state = _state()
    state.handle("/")
    out = io.StringIO()
    pager._draw(out, state.render(40), 40, None, state.hint_rows, space=pager.margins(40, 7))
    drawn = out.getvalue()
    assert "\x1b[7mFind" not in drawn and "Find: \x1b[7m " in drawn and "\x1b[7mWord or phrase" in drawn
