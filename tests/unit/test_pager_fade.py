"""Fading between a dark and a light background in the pager (screen.py)."""

import io

from magnacoda.pager import colors, options
from magnacoda.pager import screen as pager

DARK = ((204, 204, 204), (16, 16, 16))
PRINT = colors.codes("print", {"COLORTERM": "truecolor"})
PAPER = colors.codes("paper", {"COLORTERM": "truecolor"})


def test_the_terminal_s_answer_gives_its_own_colors_in_any_digit_count():
    reply = b"\x1b]10;rgb:ffff/ffff/ffff\x1b\\\x1b]11;rgb:30/30/30\x07\x1b[?62;22c"
    assert pager.parse_terminal_colors(reply) == ((255, 255, 255), (48, 48, 48))
    assert pager.parse_terminal_colors(b"\x1b[?62;22c") is None  # only the last answer: no colors


def test_full_color_codes_give_their_pair_and_others_none():
    assert pager.scheme_pair(PRINT) == ((16, 16, 16), (232, 228, 216))
    assert pager.scheme_pair(colors.codes("print", {})) is None  # 256 colors: no fade
    assert pager.scheme_pair("") is None


def test_a_fade_blends_dark_to_light_in_steps_and_skips_small_changes():
    steps = pager.fade_frames(DARK, pager.scheme_pair(PRINT))
    assert len(steps) == pager.FADE_STEPS - 1
    assert steps[0] != steps[-1] and all(step.startswith("\x1b[38;2;") for step in steps)
    assert pager.fade_frames(DARK, pager.scheme_pair(PAPER)) == []  # dark to dark: switch at once
    assert pager.fade_frames(None, pager.scheme_pair(PRINT)) == []  # the terminal's colors unknown


def test_a_late_answer_from_the_terminal_is_read_as_one_key_not_many():
    data = iter([b"\x1b", b"]", *(bytes([c]) for c in b"11;rgb:30/30/30"), b"\x1b", b"\\", b"q"])
    read = lambda timeout: next(data, b"")  # noqa: E731
    assert pager.read_key(read) == "other"
    assert pager.read_key(read) == "q"


def _page(monkeypatch, keys, **kwargs):
    monkeypatch.setattr(pager, "alternate_screen_codes", lambda env=None: ("<E>", "<L>"))
    monkeypatch.setattr(pager, "_terminal_size", lambda: (60, 12))
    monkeypatch.setattr(pager.time, "sleep", lambda seconds: None)
    out = io.StringIO()
    keys = iter(keys)
    choices = [("default", "own", ""), ("paper", "p", PAPER), ("print", "p", PRINT)]
    pager.page_sections([("One", "text")], out=out, key_source=lambda: next(keys), colors=choices, **kwargs)
    return out.getvalue()


def test_opening_and_leaving_in_print_fade_from_and_back_to_the_terminal_s_colors(monkeypatch):
    drawn = _page(monkeypatch, ["q"], color="print", fade=True, own_colors=DARK)
    steps = pager.fade_frames(DARK, pager.scheme_pair(PRINT))
    back = pager.fade_frames(pager.scheme_pair(PRINT), DARK)
    assert drawn.index(steps[0]) < drawn.index(steps[-1]) < drawn.index(PRINT)
    leaving = drawn[drawn.rindex(PRINT) :]  # the same blend, the other way
    assert leaving.index(back[0]) < leaving.index(back[-1]) < leaving.index("<L>")


def test_choosing_print_under_c_fades_from_paper(monkeypatch):
    drawn = _page(monkeypatch, ["c", "down", "q", "q"], color="paper", fade=True)
    assert pager.fade_frames(pager.scheme_pair(PAPER), pager.scheme_pair(PRINT))[0] in drawn


def test_without_fade_or_between_dark_colors_nothing_is_blended(monkeypatch):
    assert "38;2;" not in _page(monkeypatch, ["q"], color="print", fade=False, own_colors=DARK).replace(
        PRINT, ""
    )
    assert "38;2;" not in _page(monkeypatch, ["q"], color="paper", fade=True, own_colors=DARK).replace(
        PAPER, ""
    )


def test_the_fade_setting_is_read_from_the_settings_file(tmp_path):
    path = tmp_path / "app.ini"
    assert options.resolve(path).fade is True
    path.write_text("[pager]\nfade = off\n")
    assert options.resolve(path).fade is False


def test_with_the_terminals_own_colors_the_carried_line_goes_halfway_to_its_background(monkeypatch):
    monkeypatch.setenv("COLORTERM", "truecolor")
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setattr(pager, "alternate_screen_codes", lambda env=None: ("<E>", "<L>"))
    monkeypatch.setattr(pager, "_terminal_size", lambda: (60, 12))
    out, keys = io.StringIO(), iter(["space", "q"])
    text = "\n".join(f"line {n}" for n in range(30))
    own = {"colors": [("default", "own", "")], "own_colors": ((0, 0, 0), (255, 255, 255))}
    pager.page_sections([("One", text)], out=out, key_source=lambda: next(keys), **own)
    assert "\x1b[38;2;128;128;128mline 7\x1b[39m" in out.getvalue()
