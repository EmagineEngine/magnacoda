"""The goodbye when someone leaves the shell (farewell.py and the end of cli.shell)."""

from datetime import date, timedelta

import pytest
from click.testing import CliRunner

from magnacoda import cli, farewell
from magnacoda.cli import main

THANKS = farewell.goodbyes()[0].replace("{name}", "magnacoda")  # the first goodbye, as written
FEEDBACK = "Feedback or suggestions: https://magnacoda.dev/feedback"


def _asks(day: date) -> bool:
    return len(farewell.lines(day)) == 2


def test_a_new_user_is_first_asked_after_seven_goodbyes_and_seven_days():
    start = date(2026, 10, 1)
    assert [_asks(start + timedelta(days=n)) for n in range(6)] == [False] * 6  # 6 goodbyes, 5 days
    assert not _asks(start + timedelta(days=6))  # 7 goodbyes, but only 6 days
    assert _asks(start + timedelta(days=7))  # 8 goodbyes and 7 days


def test_a_daily_user_is_asked_about_once_a_week():
    start = date(2026, 10, 1)
    asked = [n for n in range(40) if _asks(start + timedelta(days=n))]
    assert asked == [7, 14, 21, 28, 35]


def test_a_weekly_user_is_asked_once_every_seven_goodbyes():
    start = date(2026, 10, 1)
    asked = [n for n in range(30) if _asks(start + timedelta(weeks=n))]
    assert asked == [6, 13, 20, 27]  # the 7th goodbye, then every 7th


def test_many_goodbyes_in_one_day_still_wait_seven_days():
    day = date(2026, 10, 1)
    assert not any(_asks(day) for _ in range(20))
    assert _asks(day + timedelta(days=7))


@pytest.mark.parametrize(
    "damaged", ["not json", '{"feedback_week": "2026-W41"}', '{"since": "x", "goodbyes": 3}']
)
def test_damaged_or_old_state_starts_counting_afresh_without_asking(damaged):
    farewell.state_path().parent.mkdir(parents=True, exist_ok=True)
    farewell.state_path().write_text(damaged)
    assert farewell.lines(date(2026, 10, 5)) == [
        farewell.goodbyes()[0].replace("{name}", "[italic]magnacoda[/italic]")
    ]


@pytest.fixture
def at_a_terminal(monkeypatch):
    monkeypatch.setattr(cli, "_interactive", lambda console: True)


def _shell(input_text):
    return CliRunner().invoke(main, ["shell"], input=input_text).output


@pytest.mark.parametrize("leaving", ["exit\n", "QUIT\n", "q\n", ""])  # "" is Ctrl+D (end of input)
def test_leaving_the_shell_says_thanks_but_does_not_ask_a_new_user_for_feedback(at_a_terminal, leaving):
    output = _shell(leaving)
    assert THANKS in output and "Feedback" not in output


def test_the_feedback_line_shows_in_the_shell_when_it_is_time(at_a_terminal, monkeypatch):
    farewell.state_path().parent.mkdir(parents=True, exist_ok=True)
    farewell.state_path().write_text('{"since": "2026-01-01", "goodbyes": 6}')
    assert FEEDBACK in _shell("exit\n")


def test_ctrl_c_at_the_prompt_says_thanks_too(at_a_terminal, monkeypatch):
    def interrupted(self, prompt=""):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli.Console, "input", interrupted)
    assert THANKS in CliRunner().invoke(main, ["shell"]).output


def test_no_goodbye_when_commands_are_piped_in():
    assert "checking accessibility" not in _shell("exit\n")  # CliRunner's input is not a terminal


def test_no_goodbye_when_update_ends_the_session(at_a_terminal, monkeypatch):
    def update_that_ends_the_session(*args, obj=None, **kwargs):
        obj["leave"] = True  # what `update` does (see cli._leave_the_session)

    monkeypatch.setattr(cli.main, "main", update_that_ends_the_session)
    assert "checking accessibility" not in CliRunner().invoke(cli.shell, [], input="update\n").output


def test_the_goodbyes_come_in_turn_and_start_over():
    said = [farewell.lines(date(2026, 10, 12))[0] for _ in range(6)]
    written = [line.replace("{name}", "[italic]magnacoda[/italic]") for line in farewell.goodbyes()]
    assert said[:2] == written[:2]
    assert len(set(said[:5])) == 5 and said[5] == said[0]
    assert all("{name}" not in line for line in said)


def test_only_goodbye_lines_with_text_count_whatever_blank_lines_there_are(monkeypatch, tmp_path):
    from importlib import resources

    text = "# Goodbyes\n\n- First.\n\n\n-   \n-\n   \n- Second.\n<!-- - Not this. -->\n"
    monkeypatch.setattr(resources, "files", lambda package: tmp_path)
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "goodbyes.md").write_text(text)
    assert farewell.goodbyes() == ["First.", "Second."]
    said = [farewell.lines(date(2026, 10, 12))[0] for _ in range(3)]
    assert said == ["First.", "Second.", "First."]
