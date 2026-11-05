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


def _no_connection(url, max_bytes):
    raise OSError("no connection in tests")


def _notes_online(monkeypatch, text="## 0.5.0\n\nFive is here.\n\n## 0.4.0\n\nFour is out.\n"):
    monkeypatch.setattr(news, "_fetch", lambda url, max_bytes: text.encode())


@pytest.fixture
def setup(monkeypatch):
    """magnacoda 0.4.0 with checks on; returns a function that saves a state."""
    monkeypatch.delenv("MAGNACODA_NEWS", raising=False)
    monkeypatch.setattr(news, "__version__", "0.4.0")
    monkeypatch.setattr(cli, "__version__", "0.4.0")
    monkeypatch.setattr(news, "installed_packages", lambda: [MAGNACODA])
    packaged = {"0.4.0": "Four is out.\n\n- `news`\n  See this."}
    parse = news.release_notes
    monkeypatch.setattr(news, "release_notes", lambda text=None: packaged if text is None else parse(text))
    monkeypatch.setattr(news, "refresh", lambda fetch=None, force=False, now=None: None)  # keep what's saved
    monkeypatch.setattr(news, "_fetch", _no_connection)  # the new version's notes: none unless a test says

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


def test_news_shows_the_update_and_numbers_its_notes_and_the_news_then_marks_them_seen(setup, monkeypatch):
    _notes_online(monkeypatch)
    setup(latest={"magnacoda": "0.5.0"}, feed=[ITEM], notes_seen="0.3.0")
    output = CliRunner().invoke(main, ["news"]).output  # no terminal: printed plainly, every item
    assert (
        "Updates available\n\n • magnacoda 0.4.0 -> 0.5.0\n\nType `update` from the shell to install it."
        in output
    )
    assert "News\n\n 1 What's new in 0.5.0\n 2 2026-11-02 · Version 1.0 is here (new)\n\n" in output
    assert "What's new in 0.5.0\n\nFive is here." in output and "Four is out" not in output
    assert "2026-11-02\n\nmagnacoda 1.0 adds dark-mode scans." in output and "type its number" not in output
    state = news.load_state()
    assert state.seen == [ITEM.id] and state.notes_seen == "0.4.0"
    assert "(new)" not in CliRunner().invoke(main, ["news"]).output


def _paged(monkeypatch, *args):
    """`news` as the pager gets it: (sections, start_at, shown, front_page)."""
    got = []

    def show(ctx, sections, options, start_at=None, shown=None, **kw):
        got.append((sections, start_at, shown, options.front_page))

    monkeypatch.setattr(cli, "show_pages", show)
    monkeypatch.setattr(cli, "pager_available", lambda off_switch=None: True)
    result = CliRunner().invoke(main, ["news", *args])
    return result, (got[0] if got else None)


def test_news_lists_the_items_numbered_on_its_first_page_and_each_on_its_own(setup, monkeypatch):
    other = FeedItem("2026-11-01 Older", "2026-11-01", "Older", "Before.")
    setup(feed=[ITEM, other], seen=[other.id], notes_seen="0.4.0")
    _, (sections, start_at, _, front_page) = _paged(monkeypatch)
    assert front_page and start_at is None and [name for name, _ in sections] == ["News", ITEM.title, "Older"]
    assert "1. 2026-11-02 · Version 1.0 is here (new)\n2. 2026-11-01 · Older\n" in sections[0][1]
    assert "type its number and press Enter" in sections[0][1] and "What's new" not in sections[0][1]
    assert sections[1][1].startswith("## Version 1.0 is here\n\n*2026-11-02*\n\nmagnacoda 1.0")


def test_after_updating_what_s_new_comes_first_until_it_is_read_and_items_count_once_opened(
    setup, monkeypatch
):
    other = FeedItem("2026-11-01 Older", "2026-11-01", "Older", "Before.")
    setup(feed=[ITEM, other], notes_seen="0.3.0")
    _, (sections, start_at, shown, _) = _paged(monkeypatch, "3")
    assert start_at == 3 and "1. What's new in 0.4.0 (new)\n2. 2026-11-02" in sections[0][1]
    assert sections[1][1].startswith("## What's new in 0.4.0\n\nFour is out.")
    shown(0)
    assert news.load_state().seen == [] and news.load_state().notes_seen == "0.3.0"
    shown(1)
    shown(3)
    assert news.load_state().seen == [other.id] and news.load_state().notes_seen == "0.4.0"
    _, (sections, *_) = _paged(monkeypatch)
    assert "What's new" not in sections[0][1]  # read: no longer news
    result, _ = _paged(monkeypatch, "3")
    assert result.exit_code == 1 and "No news item 3: they go from 1 to 2." in result.output


def test_notes_for_several_new_versions_are_one_item_newest_first(setup, monkeypatch):
    _notes_online(monkeypatch, "## 0.6.0\n\nSix.\n\n## 0.5.0\n\nFive.\n\n## 0.4.0\n\nFour is out.\n")
    setup(latest={"magnacoda": "0.6.0"}, notes_seen="0.4.0")
    _, (sections, *_) = _paged(monkeypatch)
    assert sections[1] == (
        "What's new since 0.4.0",
        "## What's new since 0.4.0\n\n### 0.6.0\n\nSix.\n\n### 0.5.0\n\nFive.",
    )


def test_news_with_nothing_to_show_says_so(setup, monkeypatch):
    monkeypatch.setattr(news, "release_notes", lambda text=None: {})
    setup()
    assert CliRunner().invoke(main, ["news"]).output == "Nothing new to show.\n"


def test_with_checks_off_news_shows_only_unread_notes(setup, monkeypatch):
    setup(latest={"magnacoda": "0.5.0"}, feed=[ITEM], notes_seen="0.3.0")
    monkeypatch.setenv("MAGNACODA_NEWS", "off")
    output = CliRunner().invoke(main, ["news"]).output
    assert "What's new in 0.4.0" in output and "Updates" not in output and "Version 1.0 is here" not in output
    assert CliRunner().invoke(main, ["news"]).output == "Nothing new to show.\n"


# --- the banner ------------------------------------------------------------------------------------


def test_the_banner_mentions_news_in_the_days_first_shell_until_it_is_read(setup, monkeypatch):
    setup(latest={"magnacoda": "0.5.0"}, feed=[ITEM], notes_seen="0.4.0")
    monkeypatch.setattr(news, "_local_date", lambda: "2026-11-02")
    line = "News: magnacoda 0.5.0 is available (you have 0.4.0; type update) · 1 news item - type news"
    first = " ".join(_shell(monkeypatch, "news").split())  # (Rich wraps long lines at 80 columns)
    assert line in first
    assert "News:" not in _shell(monkeypatch)  # a second shell the same day
    monkeypatch.setattr(news, "_local_date", lambda: "2026-11-03")
    again = " ".join(_shell(monkeypatch).split())
    assert "magnacoda 0.5.0 is available" in again and "news item" not in again  # the update stays until done


def test_the_news_is_mentioned_once_a_session_not_again_under_menu(setup, monkeypatch):
    setup(latest={"magnacoda": "0.5.0"}, notes_seen="0.4.0")
    output = _shell(monkeypatch, "menu", "menu")
    assert output.count("accessibility scanner") == 2 and output.count("News:") == 1


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
    assert ran and "Updated. Closing magnacoda now. Start it again" in output
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


def test_the_welcome_carries_the_news_and_the_tip_waits_for_menu(setup, monkeypatch):
    from magnacoda import tips

    setup(latest={"magnacoda": "0.5.0"}, feed=[ITEM], notes_seen="0.4.0")
    monkeypatch.setattr(cli, "_interactive", lambda console: True)
    monkeypatch.setattr(tips, "next_tip", lambda: "Type help.")
    output = _shell(monkeypatch, "menu")
    start, menu = output.split("Commands:")
    assert "Welcome to" in start and "News:" in start and "0.5.0 is available" in start
    assert "Tip:" not in start and "Tip:" in menu and "News:" not in menu


@pytest.fixture
def leaving(setup, installed_with, monkeypatch):
    """A person at the shell, with 0.5.0 available; returns the questions asked."""
    installed_with(updater.VENV)
    setup(latest={"magnacoda": "0.5.0"}, notes_seen="0.4.0")
    monkeypatch.setattr(cli, "_is_interactive", lambda: True)
    asked = []

    def answer(question, default=False, **kwargs):
        asked.append(question)
        return answer.reply

    answer.reply = False
    monkeypatch.setattr(cli, "_ask_yes_no", answer)
    return asked, answer


def test_leaving_offers_the_update_once_a_day(leaving, monkeypatch):
    asked, _ = leaving
    monkeypatch.setattr(news, "_local_date", lambda: "2026-11-02")
    _shell(monkeypatch, "exit")
    _shell(monkeypatch, "exit")
    assert asked.count("magnacoda 0.5.0 is available. Update before you go?") == 1
    monkeypatch.setattr(news, "_local_date", lambda: "2026-11-03")
    _shell(monkeypatch, "exit")
    assert asked.count("magnacoda 0.5.0 is available. Update before you go?") == 2


def test_saying_yes_on_leaving_runs_the_update(leaving, monkeypatch):
    _, answer = leaving
    answer.reply = True
    ran = []
    monkeypatch.setattr(updater, "run", lambda commands, log: ran.append(commands) or True)
    output = _shell(monkeypatch, "exit")
    assert ran and "Updated. Closing magnacoda now. Start it again" in output


def test_update_shows_the_new_versions_notes_before_asking(setup, installed_with, monkeypatch):
    installed_with(updater.VENV)
    setup(latest={"magnacoda": "0.5.0"}, notes_seen="0.4.0")
    monkeypatch.setattr(
        news, "notes_before_update", lambda installed, latest: [("0.5.0", "- `scan`\n  Scans are faster.")]
    )
    monkeypatch.setattr(updater, "run", lambda commands, log=None: True)
    output = CliRunner().invoke(main, ["update"], input="y\n").output
    assert (
        output.index("What's new in 0.5.0:") < output.index("Scans are faster.") < output.index("Update now?")
    )
    assert "   • scan\n     Scans are faster." in output  # laid out as on the news page
    assert news.load_state().notes_seen == "0.5.0"  # not announced again after the update


def test_without_news_items_news_is_one_page(setup, monkeypatch):
    setup(latest={"magnacoda": "0.5.0"}, notes_seen="0.4.0")  # the new version's notes can't be fetched
    _, (sections, *_) = _paged(monkeypatch)
    assert len(sections) == 1 and "Updates available" in sections[0][1] and "News" not in sections[0][1]
