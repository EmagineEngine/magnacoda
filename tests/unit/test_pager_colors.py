"""Colors in the pager: the schemes, the c list, drawing them, and saving the choice."""

import io

import pytest

from magnacoda.pager import colors, options, show
from magnacoda.pager import screen as pager
from magnacoda.pager.screen import Action, PagerState

CHOICES = [(s.name, s.description) for s in colors.SCHEMES]


def _state(**changes) -> PagerState:
    state = PagerState([("One", ["text"] * 3), ("Two", ["more"])], height=12, colors=CHOICES)
    for name, value in changes.items():
        setattr(state, name, value)
    return state


# --- the schemes -----------------------------------------------------------------------------------


@pytest.mark.parametrize("scheme", colors.SCHEMES[1:], ids=lambda s: s.name)
def test_every_scheme_is_easy_to_read_in_full_color_and_in_256_colors(scheme):
    assert colors.contrast(scheme.fg, scheme.bg) >= 7  # WCAG AAA
    assert colors.contrast(colors.xterm256(scheme.fg256), colors.xterm256(scheme.bg256)) >= 7
    if scheme.accent:  # the title row's color, on the same background
        assert colors.contrast(scheme.accent, scheme.bg) >= 7
        assert colors.contrast(colors.xterm256(scheme.accent256), colors.xterm256(scheme.bg256)) >= 7


def test_a_scheme_with_an_accent_gets_its_codes_and_the_others_none(monkeypatch):
    accented = colors.Scheme("test", "test", "#cccccc", "#1f1f1f", 252, 234, accent="#d59be4", accent256=182)
    monkeypatch.setattr(colors, "SCHEMES", (*colors.SCHEMES, accented))
    assert colors.accent_codes("test", {"COLORTERM": "truecolor"}) == (
        "\x1b[38;2;213;155;228m",
        "\x1b[38;2;31;31;31;48;2;213;155;228m",
    )
    assert colors.accent_codes("test", {}) == ("\x1b[38;5;182m", "\x1b[38;5;234;48;5;182m")
    assert colors.accent_codes("test", {"NO_COLOR": "1"}) == ("", "")
    assert colors.accent_codes("amber", {"COLORTERM": "truecolor"}) == ("", "")
    assert colors.accent_codes("default", {}) == ("", "")


ACCENT, REVERSE, TEXT = "\x1b[38;5;182m", "\x1b[38;5;234;48;5;182m", "\x1b[38;5;252;48;5;234m"


def test_headings_and_links_take_the_accent_and_reverse_video_the_accent_behind():
    heading = pager._accented("\x1b[11m\x1b[1mUsage\x1b[22m", TEXT, ACCENT, REVERSE)
    assert heading == f"{ACCENT}\x1b[1m{ACCENT}Usage\x1b[22m{ACCENT}{TEXT}"
    link = pager._accented("see \x1b[4mdocs\x1b[24m here", TEXT, ACCENT, REVERSE)
    assert link == f"{TEXT}see \x1b[4m{ACCENT}docs\x1b[24m{TEXT} here{TEXT}"
    tabbed = pager._accented("a \x1b[4m\x1b[7mlink\x1b[27m\x1b[24m", TEXT, ACCENT, REVERSE)
    assert "\x1b[7m" not in tabbed and f"{REVERSE}link" in tabbed and tabbed.endswith(f"{TEXT}{TEXT}")


def test_drawing_with_an_accent_colors_the_hints_and_drops_the_heading_mark_without_one():
    out = io.StringIO()
    pager._draw(out, ["\x1b[11mHeading", "hints"], 40, None, 1, TEXT, ACCENT, REVERSE)
    assert f"{ACCENT}Heading" in out.getvalue() and f"{REVERSE}hints\x1b[0m{TEXT}" in out.getvalue()
    out = io.StringIO()
    pager._draw(out, ["\x1b[11mHeading", "hints"], 40, None, 1)
    assert "\x1b[11m" not in out.getvalue() and "\x1b[7mhints" in out.getvalue()


@pytest.mark.parametrize("pair", [((224, 224, 224), (0, 0, 0)), ((16, 16, 16), (232, 228, 216))])
def test_the_dimmer_shade_moves_toward_the_background_and_keeps_7_to_1(pair):
    text, back = pair
    shade = pager.dimmer(text, back)
    assert shade is not None and shade != text
    assert pager._contrast(shade, back) >= 7 > pager._contrast(pager.dimmer(shade, back) or back, back)
    assert pager.dimmer((118, 118, 118), (0, 0, 0)) is None


def test_subheadings_take_the_dimmer_shade_and_section_headings_keep_theirs():
    dim = "\x1b[38;2;150;150;150m"
    out = io.StringIO()
    pager._draw(out, ["\x1b[11m\x1b[11mSub", "\x1b[11mSection", "hints"], 40, None, 1, dimmer=dim)
    drawn = out.getvalue()
    assert f"{dim}Sub" in drawn and f"{dim}Section" not in drawn and "\x1b[11m" not in drawn
    accented = pager._accented("\x1b[11m\x1b[11mSub", TEXT, ACCENT, REVERSE, dimmer=dim)
    assert accented.startswith(dim) and ACCENT not in accented


def test_the_schemes_start_with_the_terminals_own_and_have_unique_names():
    assert colors.NAMES[0] == "default" and len(set(colors.NAMES)) == len(colors.NAMES) == 6


def test_codes_use_full_color_where_the_terminal_has_it_else_256_and_none_with_no_color():
    assert colors.codes("amber", {"COLORTERM": "truecolor"}) == "\x1b[38;2;224;154;0;48;2;0;0;0m"
    assert colors.codes("amber", {}) == "\x1b[38;5;172;48;5;16m"
    assert colors.codes("amber", {"NO_COLOR": "1", "COLORTERM": "truecolor"}) == ""
    assert colors.codes("default", {"COLORTERM": "truecolor"}) == ""
    assert colors.codes("nonsense", {}) == ""  # an unknown name is the default


def test_the_256_color_table():
    assert colors.xterm256(16) == "#000000" and colors.xterm256(172) == "#d78700"
    assert colors.xterm256(232) == "#080808" and colors.xterm256(15) == "#ffffff"


# --- the c list ------------------------------------------------------------------------------------


def test_c_opens_the_list_with_the_color_in_use_marked():
    state = _state(color=2)
    assert state.handle("c") is Action.REDRAW and state.color_list
    rows = state.render(70)
    assert rows[0] == "Colors:"
    assert rows[2].startswith("  1  default")
    assert rows[4].startswith("\x1b[7m› 3  green") and rows[4].endswith("\x1b[27m")
    assert rows[-1] == "Choose: ↑ ↓ or 1-6 | Keep: Enter | Esc to go back"


def test_up_and_down_change_the_color_at_once_and_enter_keeps_it():
    state = _state()
    state.handle("c")
    assert state.handle("down") is Action.REDRAW and state.color_name == "amber"
    assert state.handle("up") is Action.REDRAW and state.handle("up") is Action.NOTHING  # at the top
    state.handle("j")
    assert state.handle("enter") is Action.SAVE_COLORS
    assert state.color_name == "amber" and not state.color_list


@pytest.mark.parametrize("key", ["esc", "q", "c"])
def test_going_back_puts_the_earlier_color_back(key):
    state = _state(color=1)
    state.handle("c")
    state.handle("down")
    assert state.handle(key) is Action.REDRAW
    assert state.color_name == "amber" and not state.color_list


def test_a_number_chooses_and_keeps_that_color():
    state = _state()
    state.handle("c")
    assert state.handle("5") is Action.SAVE_COLORS and state.color_name == "paper"
    assert state.handle("9") is not Action.SAVE_COLORS  # back on the page: 9 is no section


def test_without_colors_there_is_no_c_key_and_no_hint():
    state = PagerState([("One", ["text"])], height=12)
    assert state.handle("c") is Action.NOTHING and not state.color_list
    assert "Colors" not in state.status(200)


def test_the_page_offers_colors_in_an_80_column_window_and_drops_it_only_when_narrower():
    state = _state()
    assert "| Go: g | Find: / | Colors: c | Back:" in state.status(200)
    assert state.status(76).startswith("1/2 One | Go: g | Find: / | Colors: c | Back: ←")  # 80 less margins
    assert "colors" not in state.status(40).lower()


def test_ctrl_c_in_the_list_leaves_the_pager():
    state = _state()
    state.handle("c")
    assert state.handle("ctrl-c") is Action.QUIT_RESTORE


# --- drawing ---------------------------------------------------------------------------------------


def test_drawing_sets_the_colors_again_after_every_reset_and_fills_each_line():
    out = io.StringIO()
    amber = "\x1b[38;5;172;48;5;16m"
    pager._draw(out, ["Title", "text", "hints"], 40, "\x1b[1;3m", 1, amber)
    drawn = out.getvalue()
    assert drawn.startswith(amber) and drawn.endswith("\x1b[0m")
    assert drawn.count(f"\x1b[0m{amber}") == 2  # after the title and after the hints
    assert drawn.count("\x1b[K") == 3


def test_without_colors_drawing_is_as_before():
    out = io.StringIO()
    pager._draw(out, ["Title", "text", "hints"], 40, None, 1)
    assert "38;" not in out.getvalue() and not out.getvalue().endswith("\x1b[0m\x1b[0m")


def test_the_pager_saves_a_color_chosen_with_enter(monkeypatch):
    saved = []
    keys = iter(["c", "down", "down", "enter", "q"])
    monkeypatch.setattr(pager, "alternate_screen_codes", lambda env=None: ("", ""))
    monkeypatch.setattr(pager, "_terminal_size", lambda: (60, 12))
    choices = [(s.name, s.description, colors.codes(s.name, {})) for s in colors.SCHEMES]
    out = io.StringIO()
    pager.page_sections(
        [("One", "text")], out=out, key_source=lambda: next(keys), colors=choices, save_color=saved.append
    )
    assert saved == ["green"]
    assert "\x1b[38;5;41;48;5;16m\x1b[2J" in out.getvalue()  # the new background fills the screen
    assert out.getvalue().endswith("\x1b[?25h")  # colors reset, cursor back


def test_the_title_row_takes_the_schemes_accent(monkeypatch):
    keys = iter(["c", "down", "enter", "q"])
    monkeypatch.setattr(pager, "alternate_screen_codes", lambda env=None: ("", ""))
    monkeypatch.setattr(pager, "_terminal_size", lambda: (60, 12))
    choices = [("default", "own", ""), ("test", "test", TEXT, ACCENT, REVERSE)]
    out = io.StringIO()
    pager.page_sections(
        [("One", "text")], out=out, key_source=lambda: next(keys), colors=choices, title="Help"
    )
    assert "\x1b[1;3m\x1b[38;5;182mHelp" in out.getvalue()


def test_a_save_that_fails_is_ignored(monkeypatch):
    keys = iter(["c", "down", "enter", "q"])
    monkeypatch.setattr(pager, "alternate_screen_codes", lambda env=None: ("", ""))
    monkeypatch.setattr(pager, "_terminal_size", lambda: (60, 12))

    def fail(name):
        raise OSError("read-only")

    choices = [(s.name, s.description, "") for s in colors.SCHEMES]
    outcome = pager.page_sections(
        [("One", "text")], out=io.StringIO(), key_source=lambda: next(keys), colors=choices, save_color=fail
    )
    assert outcome is pager.Outcome.QUIT


# --- saving the choice -----------------------------------------------------------------------------


def test_the_color_is_read_from_the_settings_file_and_a_bad_one_ignored(tmp_path):
    path = tmp_path / "app.ini"
    path.write_text("[pager]\ncolors = Amber\n")
    assert options.resolve(path).colors == "amber"
    path.write_text("[pager]\ncolors = #ff00ff\n")
    assert options.resolve(path).colors == "default"
    path.write_text("[pager]\ncolors = purple\n")  # maybe from the colors file; the pager checks
    assert options.resolve(path).colors == "purple"


def test_saving_changes_the_line_in_place_and_keeps_everything_else(tmp_path):
    path = tmp_path / "app.ini"
    text = "# mine\n[pager]\n# Colors.\ncolors = default  # a note\npaging = on\n\n[other]\ncolors = x\n"
    path.write_text(text)
    assert options.save_setting(path, "pager", "colors", "amber")
    assert path.read_text() == text.replace("colors = default  # a note", "colors = amber")


def test_saving_adds_the_line_under_the_heading_or_adds_the_section(tmp_path):
    path = tmp_path / "app.ini"
    path.write_text("[pager]\npaging = on\n[other]\nx = 1")
    assert options.save_setting(path, "pager", "colors", "green")
    assert path.read_text() == "[pager]\ncolors = green\npaging = on\n[other]\nx = 1"
    path.write_text("[other]\nx = 1")
    assert options.save_setting(path, "pager", "colors", "blue")
    assert path.read_text() == "[other]\nx = 1\n\n[pager]\ncolors = blue\n"
    missing = tmp_path / "new" / "pager.ini"
    assert options.save_setting(missing, "pager", "colors", "paper")
    assert missing.read_text() == "\n[pager]\ncolors = paper\n"


@pytest.mark.parametrize(
    "broken", ["[pager]\ncolors = a\n[pager]\ncolors = b\n", "colors = a\n", "[pager\ncolors = a\n"]
)
def test_a_file_that_doesnt_read_cleanly_is_never_touched(tmp_path, broken):
    path = tmp_path / "app.ini"
    path.write_text(broken)
    assert not options.save_setting(path, "pager", "colors", "amber")
    assert path.read_text() == broken


def test_nothing_is_written_when_other_values_would_change(tmp_path):
    path = tmp_path / "app.ini"
    text = "[pager]\npaging = on\n colors = continued\n"  # a continued value that holds the key's name
    path.write_text(text)
    options.save_setting(path, "pager", "colors", "amber")
    assert options.read_settings(path).get("paging") is not False
    assert "\n[pager]" not in path.read_text()[1:]  # never a second section


@pytest.mark.parametrize("value", ["amber\n[ai]", "a b", "", "x" * 31])
def test_only_one_short_word_is_ever_written(tmp_path, value):
    path = tmp_path / "app.ini"
    path.write_text("[pager]\n")
    assert not options.save_setting(path, "pager", "colors", value)
    assert path.read_text() == "[pager]\n"


def test_show_saves_to_the_settings_file_it_read(tmp_path, monkeypatch):
    path = tmp_path / "app.ini"
    path.write_text("[pager]\ncolors = blue\n")
    seen = {}

    def fake_page(sections, **kwargs):
        seen.update(kwargs)
        kwargs["save_color"]("paper")
        return pager.Outcome.QUIT

    import magnacoda.pager as package

    monkeypatch.setattr(package, "pager_available", lambda off_switch=None: True)
    monkeypatch.setattr(package, "page_sections", fake_page)
    monkeypatch.delenv("NO_COLOR", raising=False)
    show([("One", "text")], options.resolve(path))
    assert seen["color"] == "blue" and [c[0] for c in seen["colors"]] == list(colors.NAMES)
    assert options.resolve(path).colors == "paper"
    monkeypatch.setenv("NO_COLOR", "1")
    show([("One", "text")], options.resolve(path))
    assert seen["colors"] == []
