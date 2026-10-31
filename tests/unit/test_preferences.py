import os

import pytest

from magnacoda import preferences


def test_load_creates_the_file_with_the_defaults():
    assert not preferences.preferences_path().exists()
    prefs = preferences.load()
    assert prefs.history_max == 100
    assert "[history]" in preferences.preferences_path().read_text()


def _write(text: str) -> None:
    path = preferences.preferences_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_values_are_read_comments_ignored_and_other_sections_left_alone():
    _write("[history]\nmax = 300  # more\n[an-addon]\nmax = 25\n")
    assert preferences.load().history_max == 300


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("[history]\nmax = 5000\n", 1000),
        ("[history]\nmax = -3\n", 0),
        ("[history]\nmax = lots\n", 100),
        ("[history]\nmax =\n", 100),
        ("this is not an ini file", 100),
        ("[history]\nmax = 0\n", 0),
    ],
)
def test_bad_values_are_clamped_or_fall_back(text, expected):
    _write(text)
    assert preferences.load().history_max == expected


def test_an_existing_file_is_never_overwritten():
    _write("[an-addon]\nmax = 3\n")
    preferences.load()
    assert preferences.preferences_path().read_text() == "[an-addon]\nmax = 3\n"


def test_an_unwritable_config_folder_gives_defaults(monkeypatch):
    def refuse(*args, **kwargs):
        raise OSError("read-only")

    monkeypatch.setattr(os, "makedirs", refuse)
    monkeypatch.setattr(preferences.Path, "mkdir", refuse)
    assert preferences.load() == preferences.Preferences()


def test_quick_scans_are_off_unless_turned_on_under_scan():
    assert preferences.load().quick is False
    path = preferences.preferences_path()
    assert "[scan]" in path.read_text() and "quick = off" in path.read_text()
    path.write_text(path.read_text().replace("quick = off", "quick = on"))
    assert preferences.load().quick is True
