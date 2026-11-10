import pytest

from magnacoda.pager import winpalette


def _config(home, text, name=".minttyrc"):
    path = home / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_console_colors_come_from_the_palette_and_the_default_attributes():
    table = [0x000000, 0xFF0000, 0, 0, 0, 0, 0, 0xC0C0C0, 0, 0, 0, 0, 0, 0, 0, 0xFFFFFF]  # 0x00BBGGRR
    assert winpalette.palette_pair(table, 0xF0) == ((0, 0, 0), (255, 255, 255))  # black on white
    assert winpalette.palette_pair(table, 0x07) == ((192, 192, 192), (0, 0, 0))
    assert winpalette.palette_pair(table, 0x01) == ((0, 0, 255), (0, 0, 0))  # blue is the red channel's end


def test_off_windows_there_is_no_console_palette():
    assert winpalette.console_palette() is None


@pytest.mark.parametrize(
    "text",
    [
        "BackgroundColour=250,250,250\nForegroundColour=51, 51, 51\n",
        "ForegroundColour=#333333\nBackgroundColour=#fafafa",
    ],
)
def test_mintty_colors_come_from_its_settings(tmp_path, text):
    _config(tmp_path, text)
    assert winpalette.mintty({}, tmp_path) == ((51, 51, 51), (250, 250, 250))


def test_mintty_colors_come_from_the_theme_its_settings_name_unless_they_set_their_own(tmp_path):
    _config(tmp_path, "Theme=paper\n")
    _config(tmp_path, "BackgroundColour=250,250,250\nForegroundColour=0,0,0\n", ".config/mintty/themes/paper")
    assert winpalette.mintty({}, tmp_path) == ((0, 0, 0), (250, 250, 250))
    _config(tmp_path, "Theme=paper\nBackgroundColour=255,255,240\n")
    assert winpalette.mintty({}, tmp_path) == ((0, 0, 0), (255, 255, 240))


@pytest.mark.parametrize(
    "text", ["", "BackgroundColour=250,250,250\n", "BackgroundColour=300,0,0\nForegroundColour=0,0,0"]
)
def test_mintty_without_both_colors_says_nothing(tmp_path, text):
    _config(tmp_path, text)
    assert winpalette.mintty({}, tmp_path) is None


def test_mintty_settings_are_found_in_appdata(tmp_path):
    _config(tmp_path / "AppData", "BackgroundColour=1,2,3\nForegroundColour=4,5,6\n", "mintty/config")
    assert winpalette.mintty({"APPDATA": str(tmp_path / "AppData")}, tmp_path) == ((4, 5, 6), (1, 2, 3))


def test_inside_mintty_its_settings_are_used_and_not_the_console(tmp_path, monkeypatch):
    _config(tmp_path, "BackgroundColour=250,250,250\nForegroundColour=0,0,0\n")
    monkeypatch.setattr(winpalette, "console_palette", lambda: ((1, 1, 1), (2, 2, 2)))
    assert winpalette.configured({"TERM_PROGRAM": "mintty"}, tmp_path) == ((0, 0, 0), (250, 250, 250))
    assert winpalette.configured({}, tmp_path) == ((1, 1, 1), (2, 2, 2))


def test_mintty_finds_the_themes_that_come_with_git_for_windows(tmp_path):
    _config(tmp_path, "ThemeFile=kohlrausch\n")
    colors = "ForegroundColour=51,51,51\nBackgroundColour=230,230,230\n"
    _config(tmp_path / "Git", colors, "usr/share/mintty/themes/kohlrausch")
    env = {"EXEPATH": str(tmp_path / "Git")}
    assert winpalette.mintty(env, tmp_path) == ((51, 51, 51), (230, 230, 230))
