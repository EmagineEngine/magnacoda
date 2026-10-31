"""The one-time offer to turn off typing, the spinner and paging when a screen reader is running."""

import sys

import click
import pytest
from click.testing import CliRunner

from magnacoda import preferences, questions, screenreader
from magnacoda.cli import main


@pytest.fixture
def at_a_terminal(monkeypatch):
    screenreader.state_path().unlink()
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(screenreader, "running", lambda: True)


def _answer(monkeypatch, answer):
    asked = []

    def ask(text, **kwargs):
        asked.append(text)
        if answer is None:
            raise click.Abort
        return answer

    monkeypatch.setattr(questions, "ask_yes_no", ask)
    return asked


def test_yes_turns_off_typing_the_spinner_and_paging_and_keeps_the_rest(at_a_terminal, monkeypatch):
    preferences.set_value("history", "max", "7")
    asked = _answer(monkeypatch, True)
    screenreader.offer()
    current = preferences.load()
    assert asked and not (current.typing or current.spinner or current.paging)
    assert current.history_max == 7 and current.tips


def test_it_asks_only_once_whatever_the_answer(at_a_terminal, monkeypatch):
    for answer in (False, None):  # no, then Ctrl+C or q
        screenreader.state_path().unlink(missing_ok=True)
        asked = _answer(monkeypatch, answer)
        screenreader.offer()
        screenreader.offer()
        assert len(asked) == 1 and preferences.load().typing


def test_no_offer_without_a_screen_reader_or_with_everything_already_off(at_a_terminal, monkeypatch):
    asked = _answer(monkeypatch, True)
    monkeypatch.setattr(screenreader, "running", lambda: False)
    screenreader.offer()
    monkeypatch.setattr(screenreader, "running", lambda: True)
    for section, key in (("display", "typing"), ("display", "spinner"), ("pager", "paging")):
        preferences.set_value(section, key, "off")
    screenreader.offer()
    assert asked == []


def test_only_settings_still_on_are_changed(at_a_terminal, monkeypatch):
    preferences.set_value("display", "typing", "no")
    _answer(monkeypatch, True)
    screenreader.offer()
    assert "typing = no" in preferences.preferences_path().read_text(encoding="utf-8")


def test_over_ssh_any_screen_reader_is_on_the_other_computer(monkeypatch):
    monkeypatch.setenv("SSH_CONNECTION", "10.0.0.2 50000 10.0.0.1 22")
    assert screenreader.running() is False


def test_the_command_turns_the_three_off_and_on_says_which_are_on_and_ends_the_offer():
    run = CliRunner().invoke
    assert "type screenreader on" in run(main, ["screenreader"]).output
    assert "type screenreader off" in run(main, ["screenreader", "ON"]).output
    current = preferences.load()
    assert not (current.typing or current.spinner or current.paging) and screenreader._asked()
    preferences.set_value("display", "spinner", "on")
    assert "Still on: the spinner." in run(main, ["screenreader"]).output
    run(main, ["screenreader", "off"])
    assert screenreader.settings_on() == ["typing", "spinner", "paging"]
