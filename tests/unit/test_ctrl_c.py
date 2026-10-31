"""Ctrl+C: the browser guard (launcher._ctrl_c_ends_the_browser), the CLI's "Cancelled." and start.py."""

import builtins
import os
import signal

import pytest
from click.testing import CliRunner

from magnacoda import cli, start
from magnacoda.browser import launcher
from magnacoda.cli import main


def _press_ctrl_c() -> None:
    os.kill(os.getpid(), signal.SIGINT)


def test_ctrl_c_with_the_browser_open_ends_as_an_interrupt_when_the_browser_goes():
    before = signal.getsignal(signal.SIGINT)
    with pytest.raises(KeyboardInterrupt), launcher._ctrl_c_ends_the_browser():
        _press_ctrl_c()  # noted, not raised mid-call
        raise RuntimeError("Target page, context or browser has been closed")
    assert signal.getsignal(signal.SIGINT) is before


def test_ctrl_c_with_the_browser_open_still_stops_if_nothing_fails():
    with pytest.raises(KeyboardInterrupt), launcher._ctrl_c_ends_the_browser():
        _press_ctrl_c()


def test_a_second_ctrl_c_interrupts_at_once():
    reached = []
    with pytest.raises(KeyboardInterrupt), launcher._ctrl_c_ends_the_browser():
        _press_ctrl_c()
        _press_ctrl_c()
        reached.append(True)
    assert not reached


def test_without_ctrl_c_errors_pass_through_unchanged():
    with pytest.raises(RuntimeError, match="real problem"), launcher._ctrl_c_ends_the_browser():
        raise RuntimeError("real problem")


def _interrupted(config, *, consent_given=False):
    raise KeyboardInterrupt


def test_ctrl_c_during_a_scan_says_cancelled_with_exit_code_130(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "run_scan", _interrupted)
    result = CliRunner().invoke(main, ["scan", "http://example.test"])
    assert result.exit_code == 130 and "Cancelled." in result.output
    assert "Aborted!" not in result.output and not list(tmp_path.glob("magnacoda-scans/*/results.json"))


def test_ctrl_c_during_a_scan_in_the_shell_returns_to_the_prompt(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "run_scan", _interrupted)
    result = CliRunner().invoke(main, ["shell"], input="scan http://example.test\nabout\nexit\n")
    assert result.exit_code == 0 and "Cancelled." in result.output and "Copyright" in result.output


def test_ctrl_c_while_magnacoda_is_still_loading_ends_quietly(monkeypatch, capsys):
    real_import = builtins.__import__

    def loading(name, *args, **kwargs):
        if name == "magnacoda" and args[2] and "cli" in args[2]:
            raise KeyboardInterrupt
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", loading)
    with pytest.raises(SystemExit) as stopped:
        start.main()
    assert stopped.value.code == 130 and capsys.readouterr().err == "\nCancelled.\n"
