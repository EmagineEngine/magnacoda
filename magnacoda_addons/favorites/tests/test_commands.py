import pytest
from click.testing import CliRunner

from magnacoda import cli, plugins
from magnacoda.cli import main
from magnacoda_addons.favorites import store
from magnacoda_addons.favorites.store import Favorite

HOME = Favorite("Home page", "scan https://home.test --level AA", "Checked monthly.")
BLOG = Favorite("Blog (dark)", "scan https://home.test/blog --color-scheme dark")


def _run(*args, input=None):
    return CliRunner().invoke(main, list(args), input=input)


def test_magnacoda_finds_favorites_through_its_entry_point_as_a_built_in_add_on():
    assert [(p.name, p.package, p.bundled) for p in plugins.loaded()] == [("favorites", "magnacoda", True)]


def test_with_no_favorites_it_says_how_to_save_one_and_creates_nothing():
    result = _run("favorites")
    assert result.exit_code == 0
    assert "No favorites yet" in result.output and "Save this as a favorite?" in result.output
    assert not store.favorites_path().exists()


def test_it_lists_favorites_numbered_with_their_commands_and_nothing_else():
    store.save_all([HOME, BLOG])
    output = _run("favorites").output
    assert output.startswith("Favorites (2 of 10):\n")
    assert "  1. Home page\n     scan https://home.test --level AA" in output
    assert "  2. Blog (dark)" in output and "delete" not in output


def test_delete_by_number_asks_first_and_keeps_the_others_notes():
    store.save_all([BLOG, HOME])
    result = _run("favorites", "delete", "1", input="y\n")
    assert "Delete favorite 1, 'Blog (dark)'?" in result.output
    assert "Deleted 'Blog (dark)' (1 left)." in result.output
    assert store.load()[0] == [HOME]  # notes kept


def test_answering_no_keeps_the_favorite():
    store.save_all([HOME])
    result = _run("favorites", "delete", "1", input="n\n")
    assert "Not deleted." in result.output and store.load()[0] == [HOME]


def test_delete_by_name_ignores_capitalization_and_yes_skips_the_question():
    store.save_all([HOME, BLOG])
    result = _run("favorites", "delete", "home PAGE", "--yes")
    assert result.exit_code == 0 and "Delete favorite" not in result.output
    assert store.load()[0] == [BLOG]


def test_deleting_the_last_one_says_none_are_left():
    store.save_all([HOME])
    assert "(no favorites left)" in _run("favorites", "delete", "1", "-y").output


def test_an_unknown_favorite_is_a_clear_error():
    store.save_all([HOME])
    for which in ("2", "0", "Nope"):
        result = _run("favorites", "delete", which, "-y")
        assert result.exit_code == 2 and f"There is no favorite '{which}'" in result.output
    assert store.load()[0] == [HOME]


def test_the_command_works_inside_the_shell_and_is_listed_in_the_banner(monkeypatch):
    store.save_all([HOME])
    lines = iter(['favorites delete "Home page" --yes'])

    def fake_input(self, prompt=""):
        try:
            return next(lines)
        except StopIteration:
            raise EOFError from None

    monkeypatch.setattr(cli.Console, "input", fake_input)
    output = _run().output
    assert "Add-on commands: favorites" in output
    assert "Deleted 'Home page'" in output and store.load()[0] == []


@pytest.mark.parametrize("typed", ["favorites", "favs"])
def test_in_the_shell_favorites_is_a_section_underlined_in_the_banner_with_its_heading(monkeypatch, typed):
    monkeypatch.setattr(cli.Console, "is_terminal", property(lambda self: True))
    env = {"FORCE_COLOR": "1", "TERM": "xterm"}
    output = CliRunner().invoke(main, ["shell"], input=f"{typed}\nexit\n", env=env).output
    page = output.split("accessibility scanner - type a command")[-1]
    assert "\x1b[1mAdd-on commands:\x1b[0m \x1b[1;4mfavorites\x1b[0m" in page  # the listed word, for favs too
    assert page.index("\x1b[1mFavorites\x1b[0m\n\n") < page.index("No favorites yet")


def test_about_lists_the_command():
    assert "favorites (built in; commands: favorites)" in _run("about").output


def test_fav_is_a_hidden_short_form_that_lists_and_deletes(monkeypatch):
    store.save_all([HOME, BLOG])
    assert "  1. Home page" in _run("fav").output
    result = _run("fav", "delete", "2", input="y\n")
    assert "Deleted 'Blog (dark)' (1 left)." in result.output
    assert store.load()[0] == [HOME]
    monkeypatch.setattr(cli.Console, "input", lambda self, prompt="": (_ for _ in ()).throw(EOFError()))
    banner = _run().output
    assert "Add-on commands: favorites\n" in banner and "fav " not in banner
    about = _run("about").output
    assert "favorites (built in; commands: favorites)" in about


def test_favs_is_another_hidden_short_form():
    store.save_all([HOME, BLOG])
    assert "  1. Home page" in _run("favs").output
    assert "Deleted 'Blog (dark)' (1 left)." in _run("favs", "delete", "2", "--yes").output
    assert "favs" not in _run("about").output


def test_a_number_written_with_a_hash_sign_works_too():
    store.save_all([HOME, BLOG])
    result = _run("fav", "delete", "#2", "--yes")
    assert result.exit_code == 0 and store.load()[0] == [HOME]


def _picking(monkeypatch):
    from magnacoda_addons.favorites import commands
    from magnacoda_addons.favorites.tests.helpers import fake_run

    seen: list = []
    monkeypatch.setattr(cli, "run_scan", fake_run(seen))
    monkeypatch.setattr(commands, "_interactive", lambda: True)
    store.save_all([HOME, BLOG])
    return seen


def test_picking_a_favorite_by_number_shows_it_asks_and_runs_its_scan(monkeypatch):
    seen = _picking(monkeypatch)
    output = _run("favorites", input="2\n\n").output  # pick 2, run it
    assert "Type a number to run that scan, or help for more [back]" in output
    assert "Ctrl+C" not in output
    assert "Run 'Blog (dark)' now? [Y/n]" in output
    assert [c.url for c in seen] == ["https://home.test/blog"] and seen[0].color_scheme == "dark"


def test_enter_or_no_runs_nothing(monkeypatch):
    seen = _picking(monkeypatch)
    _run("favorites", input="\n")
    _run("fav", input="1\nn\n")  # pick 1, don't run
    assert seen == []


def test_without_a_terminal_favorites_only_lists(monkeypatch):
    store.save_all([HOME])
    output = _run("favorites").output
    assert "1. Home page" in output and "Enter a number" not in output


def test_running_a_favorite_shows_its_command_and_never_asks_about_saving(monkeypatch):
    seen = _picking(monkeypatch)
    output = _run("favorites", input="1\n\n").output  # pick 1, run
    assert HOME.command in output and "Save this scan?" not in output
    assert len(seen) == 1 and store.load()[0][0].command == HOME.command  # the favorite is unchanged


def test_running_a_favorite_says_how_long_and_offers_faster_settings(monkeypatch):
    import dataclasses

    from magnacoda import estimate, preferences

    probe = estimate.PageProbe(
        startup=2.0, settle=0.6, elements=2000, images=4, forms=1, fields=3, focusable=60, hover=4, toggles=5,
        speed=1.0,
    )  # fmt: skip
    from magnacoda import cli
    from magnacoda.browser import redirects

    seen = _picking(monkeypatch)
    monkeypatch.setattr(estimate, "probe_page", lambda config: probe)
    monkeypatch.setattr(cli, "_is_interactive", lambda: True)  # the scan's own estimate step
    monkeypatch.setattr(redirects, "check_address", lambda url, **kw: None)
    load = preferences.load
    monkeypatch.setattr(preferences, "load", lambda: dataclasses.replace(load(), estimate=True, quick=False))
    store.save_all([Favorite("Both", "scan https://home.test --color-scheme both --screen both")])
    # pick 1, run it, then the scan's estimate: choose "Quick scan", then Enter at the new estimate
    output = " ".join(_run("favorites", input="1\n\n1\n\n").output.split())
    assert output.index("Run 'Both' now?") < output.index("Estimated time: about")
    assert "(desktop and mobile, about" in output and "--quick" in output.split("Equivalent command:")[-1]
    assert len(seen) == 2 and all(config.quick for config in seen)  # a full scan per screen
    assert store.load()[0][0].command == "scan https://home.test --color-scheme both --screen both"


def test_help_at_the_question_shows_the_favorites_help_then_asks_again(monkeypatch):
    seen = _picking(monkeypatch)
    monkeypatch.setenv("MAGNACODA_PAGER", "off")
    output = _run("favorites", input="help\n\n").output
    after = output.split("or help for more [back]: help", 1)[1]
    assert "favorites delete NUMBER" in after and "or help for more [back]:" in after and seen == []
