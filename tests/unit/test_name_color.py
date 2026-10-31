"""The blue of magnacoda's name in the shell (name_color.py)."""

import pytest

from magnacoda.name_color import PLAIN, for_background
from magnacoda.pager.colors import contrast


@pytest.mark.parametrize("background", ["#000000", "#ffffff", "#fdf6e3", "#293955"])
@pytest.mark.parametrize("color_system", ["truecolor", "256"])
def test_the_name_keeps_7_to_1_on_dark_and_light_backgrounds(background, color_system):
    style = for_background(background, color_system)
    assert style != PLAIN and contrast(style.split()[1], background) >= 7


def test_without_enough_colors_or_contrast_the_name_is_just_bold():
    assert for_background("#ffffff", "standard") == PLAIN
    assert for_background("#808080", "truecolor") == PLAIN
