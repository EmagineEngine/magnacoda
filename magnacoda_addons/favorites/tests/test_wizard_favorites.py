import shlex
import stat
import sys

import pytest
from click.testing import CliRunner

from magnacoda import cli, history, preferences
from magnacoda.cli import main
from magnacoda_addons.favorites import store
from magnacoda_addons.favorites.store import Favorite
from magnacoda_addons.favorites.tests.helpers import fake_run

BLANKS = ["", "", ""]  # level, AI, screens: keep every default


def _wizard(monkeypatch, *answers: str):
    seen: list = []
    monkeypatch.setattr(cli, "run_scan", fake_run(seen))
    result = CliRunner().invoke(main, ["wizard"], input="\n".join(answers) + "\n")
    return result, seen


def _prefs(text: str) -> None:
    preferences.preferences_path().parent.mkdir(parents=True, exist_ok=True)
    preferences.preferences_path().write_text(text)


def _defaults_then(*rest: str) -> list[str]:
    return [*BLANKS, *rest]


def test_the_files_are_created_when_the_wizard_starts(monkeypatch):
    _wizard(monkeypatch, "https://a.test", *_defaults_then("", "n"))
    assert store.favorites_path().exists()
    assert history.history_path().exists()
    assert "[favorites]" in preferences.preferences_path().read_text()


def test_no_picker_appears_when_there_is_nothing_saved(monkeypatch):
    result, _ = _wizard(monkeypatch, "https://a.test", *_defaults_then("", "n"))
    assert "Start from a saved scan" not in result.output


def test_saving_a_favorite_writes_the_stored_command(monkeypatch):
    result, seen = _wizard(monkeypatch, "https://a.test/?x=1&y=2", *_defaults_then("y", "My site", "n"))
    assert "Saved to" in result.output
    saved, problems = store.load()
    assert problems == [] and [f.name for f in saved] == ["My site"]
    assert shlex.split(saved[0].command)[:2] == ["scan", "https://a.test/?x=1&y=2"]
    assert seen == []  # declined to run


def test_the_same_command_is_not_saved_twice(monkeypatch):
    _wizard(monkeypatch, "https://a.test", *_defaults_then("y", "One", "n"))
    result, _ = _wizard(monkeypatch, "new", "https://a.test", *_defaults_then("y", "n"))
    assert "Already saved as 'One'" in result.output
    assert len(store.load()[0]) == 1


def test_loading_a_favorite_keeps_its_values_and_lets_the_url_change(monkeypatch):
    store.save_all(
        [Favorite("Dark blog", "scan https://old.test --level AAA --color-scheme dark --fail-on minor")]
    )
    result, seen = _wizard(monkeypatch, "fav", "1", "https://new.test", "", "n", "", "y")
    assert "Dark blog" in result.output
    assert "magnacoda scan https://new.test --level AAA" in result.output
    assert "--color-scheme dark" in result.output and "--fail-on minor" in result.output
    assert "Change anything? [y/N]" in result.output
    assert "WCAG level" not in result.output  # none of the questions were asked
    assert result.output.count("Equivalent command:") == 1  # shown once, not again after "no"
    assert [c.url for c in seen] == ["https://new.test"]
    assert seen[0].color_scheme == "dark"


def test_saying_yes_to_more_changes_asks_every_question_defaulting_to_the_favorite(monkeypatch):
    store.save_all(
        [Favorite("Dark blog", "scan https://old.test --level AAA --color-scheme dark --fail-on minor")]
    )
    result, seen = _wizard(monkeypatch, "fav", "1", "https://new.test", "y", "A", *BLANKS[1:], "n", "", "y")
    assert "WCAG level (A, AA, AAA) [AAA]" in result.output
    assert "Color scheme" not in result.output  # not asked; the favorite's dark is kept
    assert "Fail on" not in result.output and seen[0].fail_on == "minor"  # not asked, but kept
    assert [(c.url, c.color_scheme) for c in seen] == [("https://new.test", "dark")]
    assert seen[0].level == "A"


def test_options_the_wizard_does_not_ask_about_are_kept_and_used(monkeypatch):
    store.save_all([Favorite("Firefox", "scan https://a.test --browser firefox")])
    result, seen = _wizard(monkeypatch, "fav", "1", "", "", "", "y")  # unchanged: not offered for saving
    assert "--browser firefox" in result.output and "Save this as a favorite?" not in result.output
    assert seen and seen[0].browser_name == "firefox"


def test_recent_scans_are_offered_after_favorites_and_duplicates_show_once(monkeypatch):
    store.save_all([Favorite("Home", "scan https://home.test --level AA")])
    history.record("scan https://home.test --level AA")  # same as the favorite: shown once
    history.record("scan https://blog.test --level A")
    result, seen = _wizard(monkeypatch, "recent", "1", "", "", "n", "", "y")
    assert "favorites (1) or recent scans (1)?" in " ".join(result.output.split())  # favorites first
    listed = result.output.split("Recent scans", 1)[1].split("Type a number", 1)[0]
    assert "blog.test" in listed and "home.test" not in listed  # the favorite isn't repeated
    assert [c.url for c in seen] == ["https://blog.test"]
    assert seen[0].level == "A"


def test_a_number_outside_the_list_is_asked_again(monkeypatch):
    store.save_all([Favorite("Home", "scan https://home.test")])
    result, _ = _wizard(monkeypatch, "fav", "7", "1", "", "", "n", "", "n")
    assert "type one of the numbers above" in result.output.lower()


def test_when_the_list_is_full_the_user_picks_one_to_replace(monkeypatch):
    _prefs("[favorites]\nmax = 2\n")
    store.save_all([Favorite("A", "scan https://a.test"), Favorite("B", "scan https://b.test")])
    result, _ = _wizard(monkeypatch, "new", "https://c.test", *_defaults_then("y", "Cee", "2", "n"))
    assert "favorites are full (2)" in result.output
    names = [f.name for f in store.load()[0]]
    assert names == ["A", "Cee"]


def test_a_full_list_can_be_left_alone(monkeypatch):
    _prefs("[favorites]\nmax = 1\n")
    store.save_all([Favorite("A", "scan https://a.test")])
    result, _ = _wizard(monkeypatch, "new", "https://c.test", *_defaults_then("y", "Cee", "", "n"))
    assert "Not saved." in result.output
    assert [f.name for f in store.load()[0]] == ["A"]


def test_the_same_name_replaces_that_favorite_and_keeps_its_notes(monkeypatch):
    store.save_all([Favorite("Home", "scan https://old.test", "Keep me.")])
    _wizard(monkeypatch, "new", "https://new.test", *_defaults_then("y", "home", "n"))
    saved = store.load()[0]
    assert len(saved) == 1 and "new.test" in saved[0].command and saved[0].notes == "Keep me."


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
def test_wizard_created_files_are_owner_only(monkeypatch):
    _wizard(monkeypatch, "https://a.test", *_defaults_then("y", "Xyz", "n"))
    for path in (store.favorites_path(), history.history_path()):
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.parametrize("word", ["fav", "favs", "f", "favorites", "Favorite"])
def test_favorites_open_with_fav_and_are_numbered_from_one(monkeypatch, word):
    store.save_all([Favorite("Home", "scan https://home.test"), Favorite("Blog", "scan https://blog.test")])
    history.record("scan https://other.test --level A")
    result, _ = _wizard(monkeypatch, word, "", "q")
    text = " ".join(result.output.split())
    assert "favorites (2) or recent scans (1)? " in text
    assert "Type new, fav, recent, or press Enter to cancel" in text
    assert "Favorites 1. Home 2. Blog Type a number [back]" in text


def test_a_name_needs_three_characters_and_q_cancels(monkeypatch):
    result, _ = _wizard(monkeypatch, "https://a.test", *_defaults_then("y", "ab", "Abc", "n"))
    assert "a name needs at least 3 characters." in result.output
    assert [f.name for f in store.load()[0]] == ["Abc"]
    result, _ = _wizard(monkeypatch, "https://b.test", *_defaults_then("y", "q"))
    assert "Cancelled" in result.output and len(store.load()[0]) == 1  # nothing saved, nothing run


def test_a_changed_favorite_is_offered_for_updating_and_keeps_its_name_and_notes(monkeypatch):
    store.save_all([Favorite("Home", "scan https://home.test --level AA --ai off", "my note")])
    # fav 1, the URL as it was, change: yes, level AAA, AI and screens as they were, update: yes, run: yes
    result, seen = _wizard(monkeypatch, "fav", "1", "", "y", "AAA", "", "", "", "")
    assert "Update the favorite 'Home' with these settings? [Y/n]" in result.output
    assert "Save this as a favorite?" not in result.output
    (home,) = store.load()[0]
    assert seen and seen[0].level == "AAA"
    assert home.name == "Home" and "--level AAA" in home.command and home.notes == "my note"


def test_not_updating_a_changed_favorite_offers_to_save_it_as_a_new_one(monkeypatch):
    store.save_all([Favorite("Home", "scan https://home.test --level AA --ai off")])
    result, _ = _wizard(monkeypatch, "fav", "1", "", "y", "AAA", "", "", "n", "n", "n")
    assert "Update the favorite" in result.output and "Save this as a favorite?" in result.output
    assert [f.command for f in store.load()[0]] == ["scan https://home.test --level AA --ai off"]
