from click.testing import CliRunner

from magnacoda import cli, window
from magnacoda.cli import main


def test_the_window_waits_for_enter_and_shows_no_countdown(monkeypatch, capsys):
    asked = []
    monkeypatch.setattr("builtins.input", lambda text: asked.append(text) or "")
    window.before_closing()
    assert asked == [window.ENTER_PROMPT] and capsys.readouterr().out == ""


def test_from_a_shortcut_the_shell_pauses_after_the_farewell_and_only_then(monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "_interactive", lambda console: True)
    monkeypatch.setattr(window, "before_closing", lambda: calls.append("waited"))
    CliRunner().invoke(main, ["shell"], input="exit\n")
    assert calls == []
    CliRunner().invoke(main, ["shell", "--from-shortcut"], input="exit\n")
    assert calls == ["waited"]
