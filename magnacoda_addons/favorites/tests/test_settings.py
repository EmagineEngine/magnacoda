"""The [favorites] setting in preferences.ini."""

import pytest
from click.testing import CliRunner

from magnacoda import preferences
from magnacoda.cli import main
from magnacoda_addons.favorites import settings


def _write(text: str) -> None:
    path = preferences.preferences_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_the_section_is_added_once_and_the_rest_of_the_file_is_kept():
    _write("# mine\n[history]\nmax = 7\n")
    settings.ensure_section()
    settings.ensure_section()
    text = preferences.preferences_path().read_text()
    assert text.startswith("# mine\n[history]\nmax = 7\n")
    assert text.count("[favorites]") == 1
    assert preferences.load().history_max == 7
    assert settings.favorites_max() == 10


def test_a_new_preferences_file_gets_both_sections():
    assert settings.favorites_max() == 10
    text = preferences.preferences_path().read_text()
    assert "[history]" in text and "[favorites]" in text


@pytest.mark.parametrize(
    ("value", "expected"), [("25  # more", 25), ("0", 1), ("500", 100), ("lots", 10), ("", 10)]
)
def test_favorites_max_is_read_clamped_or_defaulted(value, expected):
    _write(f"[favorites]\nmax = {value}\n")
    assert settings.favorites_max() == expected


def test_no_addons_turns_favorites_off_too():
    output = CliRunner().invoke(main, ["--no-addons", "about"]).output
    assert "favorites" not in output
    assert CliRunner().invoke(main, ["--no-addons", "favorites"]).exit_code == 2  # no such command
