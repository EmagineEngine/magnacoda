"""The `news` and `update` commands and the banner's news line, with no network: news state is
written directly, and the update check is answered by a fake."""

import pytest
from click.testing import CliRunner

from magnacoda import cli, news, updater
from magnacoda.cli import main
from magnacoda.news import FeedItem, Package, State

MAGNACODA = Package("magnacoda", "0.4.0", frozenset({"github.com/emagineengine/magnacoda"}))
ITEM = FeedItem(
    "2026-11-02 Version 1.0 is here",
    "2026-11-02",
    "Version 1.0 is here",
    "magnacoda 1.0 adds dark-mode scans.",
)


@pytest.fixture
def setup(monkeypatch):
    """magnacoda 0.4.0 with checks on; returns a function that saves a state."""
    monkeypatch.delenv("MAGNACODA_NEWS", raising=False)
    monkeypatch.setattr(news, "__version__", "0.4.0")
    monkeypatch.setattr(cli, "__version__", "0.4.0")
    monkeypatch.setattr(news, "installed_packages", lambda: [MAGNACODA])
    monkeypatch.setattr(news, "release_notes", lambda: {"0.4.0": "Four is out.\n\n- `news`\n  See this."})
    monkeypatch.setattr(news, "refresh", lambda fetch=None, force=False, now=None: None)  # keep what's saved

    def save(**fields):
        news.save_state(State(checked="2026-11-02T00:00:00+00:00", **fields))

    return save


def _shell(monkeypatch, *lines):
    queue = iter(lines)

    def fake_input(self, prompt=""):
        try:
            return next(queue)
        except StopIteration:
            raise EOFError from None

    monkeypatch.setattr(cli.Console, "input", fake_input)
    return CliRunner().invoke(main, []).output


# --- news ---------------------------------------------------------------------------------------


def test_news_shows_updates_notes_and_news_then_marks_them_seen(setup):
    setup(latest={"magnacoda": "0.5.0"}, feed=[ITEM], notes_seen="0.3.0")
    output = CliRunner().invoke(main, ["news"]).output  # no terminal: printed plainly
    assert "Updates available\n  magnacoda 0.4.0 -> 0.5.0" in output and "Type `update`" in output
    assert "What's new in 0.4.0\n\nFour is out.\n  news\n      See this." in output
    assert "2026-11-02  Version 1.0 is here (new)\n\nmagnacoda 1.0 adds dark-mode scans." in output
    state = news.load_state()
    assert state.seen == [ITEM.id] and state.notes_seen == "0.4.0"
    assert "(new)" not in CliRunner().invoke(main, ["news"]).output


def test_news_with_nothing_to_show_says_so(setup, monkeypatch):
    monkeypatch.setattr(news, "release_notes", lambda: {})
    setup()
    assert CliRunner().invoke(main, ["news"]).output == "Nothing new to show.\n"


def test_with_checks_off_news_shows_only_the_notes(setup, monkeypatch):
    setup(latest={"magnacoda": "0.5.0"}, feed=[ITEM])
    monkeypatch.setenv("MAGNACODA_NEWS", "off")
    output = CliRunner().invoke(main, ["news"]).output
    assert "What's new in 0.4.0" in output and "Updates" not in output and "Version 1.0 is here" not in output


# --- the banner ------------------------------------------------------------------------------------


def test_the_banner_mentions_news_in_the_days_first_shell_until_it_is_read(setup, monkeypatch):
    setup(latest={"magnacoda": "0.5.0"}, feed=[ITEM], notes_seen="0.4.0")
    monkeypatch.setattr(news, "_local_date", lambda: "2026-11-02")
    line = "News: magnacoda 0.5.0 is available (you have 0.4.0; type update) · 1 news item - type news"
    first = " ".join(_shell(monkeypatch, "news").split())  # (Rich wraps long lines at 80 columns)
    assert line in first and "Tip:" not in first  # no tip beside the news
    assert "News:" not in _shell(monkeypatch)  # a second shell the same day
    monkeypatch.setattr(news, "_local_date", lambda: "2026-11-03")
    again = " ".join(_shell(monkeypatch).split())
    assert "magnacoda 0.5.0 is available" in again and "news item" not in again  # the update stays until done


def test_no_news_line_when_there_is_nothing_new(setup, monkeypatch):
    setup(notes_seen="0.4.0")
    assert "News:" not in _shell(monkeypatch)


# --- update --------------------------------------------------------------------------------------


@pytest.fixture
def installed_with(monkeypatch):
    def install(kind):
        monkeypatch.setattr(updater, "install_kind", lambda: kind)

    return install


def test_update_in_a_development_install_points_to_git_pull(setup):
    assert "update it with git pull" in CliRunner().invoke(main, ["update"]).output


def test_update_says_when_it_couldnt_check(setup, installed_with):
    installed_with(updater.VENV)
    setup()
    output = CliRunner().invoke(main, ["update"]).output
    assert "Couldn't check for updates just now" in output and "Nothing was changed." in output


def test_update_says_when_you_have_the_latest(setup, installed_with):
    installed_with(updater.VENV)
    setup(latest={"magnacoda": "0.4.0"})
    assert "You have the latest version (0.4.0)." in CliRunner().invoke(main, ["update"]).output


def test_an_install_it_doesnt_recognize_gets_the_command_to_run_itself(setup, installed_with, monkeypatch):
    installed_with(updater.SHOW)
    setup(latest={"magnacoda": "0.5.0"})
    monkeypatch.setattr(updater, "run", lambda commands, log=None: pytest.fail("must not run anything"))
    output = CliRunner().invoke(main, ["update"]).output
    assert "magnacoda 0.4.0 -> 0.5.0" in output and "pipx upgrade magnacoda" in output
    assert "Update now?" not in output


def test_update_asks_and_answering_no_changes_nothing(setup, installed_with, monkeypatch):
    installed_with(updater.VENV)
    setup(latest={"magnacoda": "0.5.0"})
    monkeypatch.setattr(updater, "run", lambda commands, log=None: pytest.fail("must not run"))
    output = CliRunner().invoke(main, ["update"], input="n\n").output
    assert "This will run:" in output and "-m pip install --upgrade magnacoda" in output
    assert "Nothing was changed." in output


def test_a_successful_update_in_the_shell_ends_the_session(setup, installed_with, monkeypatch):
    installed_with(updater.VENV)
    setup(latest={"magnacoda": "0.5.0"}, notes_seen="0.4.0")
    ran = []
    monkeypatch.setattr(updater, "run", lambda commands, log: ran.append(commands) or True)
    output = _shell(monkeypatch, "update --yes", "about")
    assert ran and "Updated. Start magnacoda again" in output
    assert "magnacoda 0.4.0\n" not in output.split("Updated.")[1]  # `about` never ran: the shell ended


def test_a_failed_update_keeps_the_shell_and_the_old_version(setup, installed_with, monkeypatch):
    installed_with(updater.VENV)
    setup(latest={"magnacoda": "0.5.0"}, notes_seen="0.4.0")
    monkeypatch.setattr(updater, "run", lambda commands, log: False)
    output = _shell(monkeypatch, "update --yes", "about")
    assert (
        "The update didn't finish. The last lines of its log:" in output and "The whole log is in" in output
    )
    assert "If magnacoda no longer starts, repair it with:" in output
    assert output.split("didn't finish")[1].count("Author") == 1  # `about` still ran


def test_update_outside_the_shell_fails_with_an_error_code(setup, installed_with, monkeypatch):
    installed_with(updater.VENV)
    setup(latest={"magnacoda": "0.5.0"})
    monkeypatch.setattr(updater, "run", lambda commands, log: False)
    assert CliRunner().invoke(main, ["update", "-y"]).exit_code == 1


def test_use_saved_skips_the_fresh_check(setup, installed_with, monkeypatch):
    installed_with(updater.VENV)
    setup(latest={"magnacoda": "9.9.9"})
    monkeypatch.setattr(news, "refresh", lambda **kwargs: pytest.fail("must not check"))
    output = CliRunner().invoke(main, ["update", "--use-saved"], input="n\n").output
    assert "magnacoda 0.4.0 -> 9.9.9" in output and "Checking" not in output
