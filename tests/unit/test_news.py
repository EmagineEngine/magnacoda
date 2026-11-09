import json
import threading
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from magnacoda import news
from magnacoda.news import FeedItem, Package, State

HOME = "https://github.com/emagineengine/magnacoda"
MAGNACODA = Package("magnacoda", "0.4.0", frozenset({"github.com/emagineengine/magnacoda"}))
FEED = """# magnacoda news
<!-- a note for whoever edits the feed -->

## 2026-11-02 Version 1.0 is here

magnacoda 1.0 adds dark-mode scans.

## Not an item

## 2026-12-01 WCAG 2.2 notes

- `scan`
  Now checks target sizes.
"""


def _pypi(version="0.5.0", urls=(HOME,)):
    return json.dumps(
        {"info": {"version": version, "project_urls": {f"Link {n}": u for n, u in enumerate(urls)}}}
    ).encode()


def fake_fetch(answers):
    """answers: {url: bytes or an exception}; anything else fails like a missing page."""
    calls = []

    def fetch(url, max_bytes):
        calls.append(url)
        answer = answers.get(url, OSError("404"))
        if isinstance(answer, BaseException):
            raise answer
        return answer

    fetch.calls = calls
    return fetch


@pytest.fixture
def checks_on(monkeypatch):
    monkeypatch.delenv("MAGNACODA_NEWS", raising=False)
    monkeypatch.setattr(news, "__version__", "0.4.0")
    monkeypatch.setattr(news, "installed_packages", lambda: [MAGNACODA])


def _answers():
    return {news.PYPI_URL.format(name="magnacoda"): _pypi(), news.NEWS_URL: FEED.encode()}


# --- the feed and the notes --------------------------------------------------------------------


def test_the_feed_has_dated_items_newest_first_and_ignores_the_rest():
    items = news.parse_feed(FEED)
    assert [item.id for item in items] == ["2026-12-01 WCAG 2.2 notes", "2026-11-02 Version 1.0 is here"]
    assert items[1].body == "magnacoda 1.0 adds dark-mode scans."
    assert "note for whoever" not in "".join(item.body for item in items)


def test_text_from_outside_cant_drive_the_terminal():
    nasty = "## 2026-01-01 Hi\x1b[2J\x1b]0;title\x07\n\nclick ‮moc.live‬ here\x00\n"
    item = news.parse_feed(nasty)[0]
    for character in ("\x1b", "\x07", "\x00", "‮", "‬"):
        assert character not in item.title + item.body
    assert news.clean("line one\nline two\ttab") == "line one\nline two\ttab"


def test_at_most_twenty_items_are_kept():
    many = "".join(f"## 2026-01-{n:02d} Item {n}\n\ntext\n" for n in range(1, 31))
    items = news.parse_feed(many)
    assert len(items) == 20 and items[0].title == "Item 30"


def test_release_labels_and_numbers():
    assert news.release_label("0.4.0.dev3+gabc123") == "0.4.0"
    assert news.release_label("not a version") == "not a version"
    assert news.release_numbers("0.4.0") == news.release_numbers("0.4") == (0, 4)
    assert news.release_numbers("nonsense") is None


def test_release_notes_are_found_for_the_installed_version(monkeypatch):
    monkeypatch.setattr(news, "release_notes", lambda: {"0.4.0": "Notes for four.", "0.3.0": "Older."})
    assert news.notes_for("0.4.0") == "Notes for four."
    assert news.notes_for("0.4") == "Notes for four."
    assert news.notes_for("0.4.0.dev3+gabc") == "Notes for four."
    assert news.notes_for("0.5.0") == ""


def test_the_packaged_notes_file_reads():
    notes = news.release_notes()
    assert notes and all(news.release_numbers(version) for version in notes)


# --- versions ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "latest,installed,newer",
    [
        ("0.5.0", "0.4.0", True),
        ("0.4.1", "0.4", True),
        ("0.4.0", "0.4", False),
        ("1.0", "0.9.9", True),
        ("0.5.0rc1", "0.4.0", False),  # pre-releases are never offered
        ("0.5.0", "0.4.0.dev3+gabc", False),  # a development install stays quiet
        ("0.5.0", "0.4.0+local", False),
        ("nonsense", "0.4.0", False),
        # Forms that need the full version rules (the `packaging` library):
        ("1.0.post1", "1.0", True),  # a post-release is newer
        ("0.5.0", "0.5.0rc1", True),  # the final release after its release candidate
        ("1!0.1", "2.0", True),  # a later epoch wins
        ("0.5.0.dev1", "0.4.0", False),  # a development build on PyPI is never offered
        ("0.4.0.post1", "0.4.0.post1", False),
        ("v0.5.0", "0.4.0", True),  # a leading v is allowed
    ],
)
def test_newer_compares_releases(latest, installed, newer):
    assert news.is_newer(latest, installed) is newer


# --- asking PyPI ---------------------------------------------------------------------------------


def test_pypi_is_believed_only_when_the_project_links_to_the_same_place():
    url = news.PYPI_URL.format(name="magnacoda")
    assert news.latest_on_pypi(MAGNACODA, fake_fetch({url: _pypi("0.5.0")})) == "0.5.0"
    squatter = _pypi("9.9.9", urls=("https://example.com/not-magnacoda",))
    assert news.latest_on_pypi(MAGNACODA, fake_fetch({url: squatter})) is None


def test_pypi_failures_and_odd_answers_are_silent():
    url = news.PYPI_URL.format(name="magnacoda")
    for answer in (OSError("offline"), b"not json", b'{"info": {}}', _pypi("1.0b2")):
        assert news.latest_on_pypi(MAGNACODA, fake_fetch({url: answer})) is None
    assert news.latest_on_pypi(Package("x", "1.0", frozenset()), fake_fetch({})) is None


def _dist(name, version, classifiers=(), urls=()):
    headers = {"Classifier": list(classifiers), "Project-URL": [f"Home, {u}" for u in urls], "Home-page": []}
    md = type(
        "Meta",
        (),
        {"get_all": lambda self, key: headers.get(key) or None, "__getitem__": lambda self, key: name},
    )()
    return SimpleNamespace(metadata=md, version=version)


def test_private_packages_are_never_looked_up(monkeypatch):
    dists = {
        "magnacoda": _dist("magnacoda", "0.4.0", urls=[HOME]),
        "public-addon": _dist("public-addon", "1.0", urls=["https://example.org/addon"]),
        "secret-addon": _dist("secret-addon", "1.0", classifiers=["Private :: Do Not Upload"]),
    }
    monkeypatch.setattr(news.metadata, "distribution", lambda name: dists[name])
    loaded = [SimpleNamespace(package="public-addon"), SimpleNamespace(package="secret-addon")]
    monkeypatch.setattr(news.plugins, "loaded", lambda: loaded)
    assert [p.name for p in news.installed_packages()] == ["magnacoda", "public-addon"]


# --- the daily check -----------------------------------------------------------------------------


def test_a_check_saves_versions_and_news(checks_on):
    news.refresh(fake_fetch(_answers()))
    state = news.load_state()
    assert state.latest == {"magnacoda": "0.5.0"} and len(state.feed) == 2 and state.checked


def test_it_checks_at_most_once_a_day_unless_forced(checks_on):
    now = datetime(2026, 11, 2, 12, tzinfo=UTC)
    news.refresh(fake_fetch(_answers()), now=now)
    later = fake_fetch(_answers())
    news.refresh(later, now=now + timedelta(hours=23))
    assert later.calls == []
    news.refresh(later, now=now + timedelta(hours=23), force=True)
    assert later.calls
    tomorrow = fake_fetch(_answers())
    news.refresh(tomorrow, now=now + timedelta(hours=23 + 25))  # a day after the forced check
    assert tomorrow.calls


def test_a_failed_check_is_silent_and_waits_a_day(checks_on):
    news.refresh(fake_fetch({}))  # nothing answers: no PyPI project yet, no news site
    state = news.load_state()
    assert state.checked and state.latest == {} and state.feed == []
    assert news.notice_line() == ""


def test_a_failed_feed_keeps_the_news_already_saved(checks_on):
    news.refresh(fake_fetch(_answers()), force=True)
    news.refresh(fake_fetch({}), force=True)
    assert len(news.load_state().feed) == 2


def test_a_broken_state_file_is_simply_started_again(checks_on):
    news.state_path().parent.mkdir(parents=True, exist_ok=True)
    news.state_path().write_text("{not json", encoding="utf-8")
    assert news.load_state() == State()
    news.refresh(fake_fetch(_answers()))
    assert news.load_state().latest == {"magnacoda": "0.5.0"}


def test_no_start_check_without_a_terminal(checks_on):
    assert news.start_check_due() is False  # pytest's output isn't a terminal


def test_the_start_check_says_whether_there_is_an_update(checks_on):
    found = news.start_check(fake_fetch(_answers()))
    assert found.outcome == "update" and found.version == "0.5.0"
    assert news.load_state().latest == {"magnacoda": "0.5.0"}
    news.state_path().unlink()  # a day later
    old = {news.PYPI_URL.format(name="magnacoda"): _pypi(version="0.0.1"), news.NEWS_URL: FEED.encode()}
    assert news.start_check(fake_fetch(old)).outcome == "latest"


def test_a_start_check_that_cant_reach_anything_is_tried_again_at_the_next_start(checks_on):
    assert news.start_check(fake_fetch({})).outcome == "failed"
    assert news.load_state().checked == ""  # not counted as a check, so it is still due


def test_a_start_check_that_takes_too_long_saves_nothing_even_if_it_finishes_later(checks_on):
    release = threading.Event()
    answers = fake_fetch(_answers())

    def slow(url, max_bytes):
        release.wait(5)
        return answers(url, max_bytes)

    assert news.start_check(slow, wait=0.05).outcome == "timeout"
    release.set()
    time.sleep(0.3)  # the late answer arrives and is thrown away
    assert news.load_state().checked == "" and news.load_state().latest == {}


class _Tty:
    def isatty(self):
        return True


def test_the_switches_that_turn_checks_off(checks_on, monkeypatch):
    assert news.checks_enabled(_Tty(), _Tty(), {}) is True
    assert news.checks_enabled(_Tty(), _Tty(), {"MAGNACODA_NEWS": "off"}) is False
    assert news.checks_enabled(_Tty(), _Tty(), {"CI": "true"}) is False
    assert news.checks_enabled(SimpleNamespace(isatty=lambda: False), _Tty(), {}) is False
    news.preferences.ensure_file()
    path = news.preferences.preferences_path()
    path.write_text(path.read_text(encoding="utf-8").replace("check = on", "check = off"), encoding="utf-8")
    assert news.checks_enabled(_Tty(), _Tty(), {}) is False


# --- the banner line -----------------------------------------------------------------------------


def test_the_banner_line_says_what_is_new(checks_on, monkeypatch):
    news.refresh(fake_fetch(_answers()))
    assert news.notice_line() == (
        "News: magnacoda 0.5.0 is available (you have 0.4.0; type update) · 2 news items - type news"
    )
    news.mark_items_seen(item.id for item in news.load_state().feed)
    assert news.notice_line() == "News: magnacoda 0.5.0 is available (you have 0.4.0; type update)"


def test_release_notes_are_announced_once_after_an_upgrade_not_on_a_first_install(checks_on, monkeypatch):
    monkeypatch.setattr(news, "release_notes", lambda: {"0.4.0": "Four.", "0.5.0": "Five."})
    news.note_first_run()
    assert news.notice_line() == ""  # just installed: nothing to announce
    monkeypatch.setattr(news, "__version__", "0.5.0")  # upgraded
    assert news.notice_line() == "News: what's new in 0.5.0 - type news"
    news.mark_notes_seen("0.5.0")
    assert news.notice_line() == ""


def test_with_checks_off_only_the_notes_are_mentioned(checks_on, monkeypatch):
    news.refresh(fake_fetch(_answers()))
    monkeypatch.setenv("MAGNACODA_NEWS", "off")
    assert news.notice_line() == ""
    state = news.load_state()
    state.notes_seen = "0.3.0"
    news.save_state(state)
    monkeypatch.setattr(news, "release_notes", lambda: {"0.4.0": "Four."})
    assert news.notice_line() == "News: what's new in 0.4.0 - type news"


def test_add_on_updates_are_counted(checks_on, monkeypatch):
    addon = Package("public-addon", "1.0", frozenset({"example.org/addon"}))
    monkeypatch.setattr(news, "installed_packages", lambda: [MAGNACODA, addon])
    state = State(
        checked="x", latest={"magnacoda": "0.4.0", "public-addon": "1.1"}, feed=[FeedItem("i", "d", "t", "b")]
    )
    news.save_state(state)
    assert news.notice_line() == "News: 1 add-on update (type update) · 1 news item - type news"


def test_checks_name_only_the_version_without_a_development_builds_local_part(monkeypatch):
    monkeypatch.setattr(news, "__version__", "1.2.0")
    assert news.user_agent() == "magnacoda/1.2.0"
    monkeypatch.setattr(news, "__version__", "0.0.1.dev132+g305084c40.d20261013")
    assert news.user_agent() == "magnacoda/0.0.1.dev132"


def test_the_banner_shows_each_item_in_the_first_shell_of_a_day_on_up_to_three_days(checks_on):
    news.save_state(State(checked="x", feed=[FeedItem("a", "d", "t", "b")]))
    assert news.today_notice(today="2026-11-02") == {"news:a"}
    assert news.today_notice(today="2026-11-02") == set()  # later the same day
    assert news.today_notice(today="2026-11-09") == {"news:a"}  # days it was shown, however far apart
    assert news.today_notice(today="2026-11-10") == {"news:a"}
    assert news.today_notice(today="2026-11-11") == set()  # three days: `news` still has it
    state = news.load_state()
    state.feed.append(FeedItem("b", "d", "t", "b"))
    news.save_state(state)
    chosen = news.today_notice(today="2026-11-12")
    assert chosen == {"news:b"}  # a new item gets its own three days
    assert news.notice_line(only=chosen) == "News: 2 news items - type news"


def test_an_update_is_mentioned_every_day_until_it_is_installed(checks_on):
    news.save_state(State(checked="x", latest={"magnacoda": "0.5.0"}))
    for day in ("2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05", "2026-11-20"):
        assert news.today_notice(today=day) == {"update:magnacoda:0.5.0"}
        assert news.today_notice(today=day) == set()  # once a day
    assert news.notice_line() == "News: magnacoda 0.5.0 is available (you have 0.4.0; type update)"


NOTES = """## 0.6.0

Six.

## 0.5.0

Five.

## 0.4.1

Four one.

## 0.4.0

Four.
"""


def test_update_reads_the_notes_of_the_new_versions_from_the_new_tag():
    fetch = fake_fetch({news.NOTES_URL.format(version="0.5.0"): NOTES.encode()})
    assert news.notes_before_update("0.4.0", "0.5.0", fetch) == [("0.5.0", "Five."), ("0.4.1", "Four one.")]
    assert fetch.calls == [
        "https://raw.githubusercontent.com/EmagineEngine/magnacoda/v0.5.0/magnacoda/data/whats-new.md"
    ]
    assert news.notes_before_update("0.4.0", "0.6.0", fake_fetch({})) == []  # can't fetch: none


def test_update_shows_at_most_the_newest_few_releases_notes(monkeypatch):
    monkeypatch.setattr(news, "NOTES_BEFORE_UPDATE", 2)
    fetch = fake_fetch({news.NOTES_URL.format(version="0.6.0"): NOTES.encode()})
    assert [v for v, _ in news.notes_before_update("0.3.0", "0.6.0", fetch)] == ["0.6.0", "0.5.0"]


def test_leaving_asks_once_a_day():
    assert news.ask_on_leaving(today="2026-11-02")
    assert not news.ask_on_leaving(today="2026-11-02")
    assert news.ask_on_leaving(today="2026-11-03")
