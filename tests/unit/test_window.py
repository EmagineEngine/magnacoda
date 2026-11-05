import subprocess
import sys

import pytest
from click.testing import CliRunner

from magnacoda import cli, window
from magnacoda.cli import main


def test_the_window_waits_for_enter_and_shows_no_countdown(monkeypatch, capsys):
    monkeypatch.setattr(sys, "platform", "linux")
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


def test_on_a_mac_terminal_is_asked_to_close_this_window_once_the_shell_ends(monkeypatch):
    started = []
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr("builtins.input", lambda text: "")
    monkeypatch.setattr(sys, "stdin", type("Stdin", (), {"fileno": lambda self: 0})())
    monkeypatch.setattr(window.os, "ttyname", lambda fd: "/dev/ttys004")
    monkeypatch.setattr(window.os, "getppid", lambda: 4321)
    monkeypatch.setattr(subprocess, "Popen", lambda args, **kw: started.append((args, kw)))
    window.before_closing()
    ((args, kw),) = started
    assert args[0] == "osascript" and args[-2:] == ["/dev/ttys004", "4321"]
    assert kw["start_new_session"] is True  # it outlives magnacoda and the shell


def test_without_a_terminal_nothing_is_started(monkeypatch):
    def no_tty(fd):
        raise OSError

    monkeypatch.setattr(window.os, "ttyname", no_tty)
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: pytest.fail("started"))
    window.close_mac_window()
