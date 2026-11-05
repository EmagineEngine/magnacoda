"""The blue of magnacoda's name in the shell (name_color.py)."""

import pytest

from magnacoda import name_color, winconsole
from magnacoda.name_color import PLAIN, WINDOWS_DEFAULT, for_background
from magnacoda.pager.colors import contrast


@pytest.mark.parametrize("background", ["#000000", "#ffffff", "#fdf6e3", "#293955"])
@pytest.mark.parametrize("color_system", ["truecolor", "256"])
def test_the_name_keeps_7_to_1_on_dark_and_light_backgrounds(background, color_system):
    style = for_background(background, color_system)
    assert style != PLAIN and contrast(style.split()[1], background) >= 7


def test_without_enough_colors_or_contrast_the_name_is_just_bold():
    assert for_background("#ffffff", "standard") == PLAIN
    assert for_background("#808080", "truecolor") == PLAIN


@pytest.mark.parametrize(
    ("reply", "color"),
    [
        ("\x1b]11;rgb:0c0c/0c0c/0c0c\x1b\\\x1b[?61;6;7c", (12, 12, 12)),
        ("\x1b]11;rgb:fa/fa/fa\x07", (250, 250, 250)),
        ("\x1b]11;rgb:f/0/8\x1b\\", (255, 0, 136)),
        ("\x1b[?1;0c", None),
    ],
)
def test_the_windows_answer_gives_the_background(reply, color):
    assert winconsole.parse_background(reply) == color


@pytest.mark.parametrize(("answer", "expected"), [((250, 250, 250), "#fafafa"), (None, WINDOWS_DEFAULT)])
def test_on_windows_a_terminal_that_doesnt_answer_counts_as_dark(monkeypatch, answer, expected):
    monkeypatch.setattr(name_color.sys, "platform", "win32")
    monkeypatch.setattr(winconsole, "background", lambda: answer)
    assert name_color._background() == expected
