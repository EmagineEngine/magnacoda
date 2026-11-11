import io
import sys
import threading
from pathlib import Path

import pytest

from magnacoda import errors, preferences


@pytest.fixture(autouse=True)
def folder(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("MAGNACODA_DEBUG", raising=False)
    monkeypatch.setattr(errors, "in_shell", False)
    return tmp_path


def _boom(text: str = "boom") -> RuntimeError:
    try:
        raise RuntimeError(text)
    except RuntimeError as exc:
        return exc


def test_an_unexpected_error_is_one_short_message_and_the_details_are_saved():
    out = io.StringIO()
    errors.report(_boom(), "scan http://example.test", out)
    shown = out.getvalue()
    assert "Something went wrong. Please report it at magnacoda.dev/contact" in shown
    assert "Type magnacoda errors to see the details." in shown and "Traceback" not in shown
    saved = errors.read()
    assert len(saved) == 1 and saved[0].command == "scan http://example.test"
    assert "RuntimeError: boom" in saved[0].details and "magnacoda " in saved[0].system


def test_in_the_shell_the_message_says_to_type_errors(monkeypatch):
    monkeypatch.setattr(errors, "in_shell", True)
    out = io.StringIO()
    errors.report(_boom(), "", out)
    assert "Type errors to see the details." in out.getvalue()


@pytest.mark.parametrize("how", ["setting", "variable"])
def test_showing_errors_prints_the_traceback_as_well(how, monkeypatch):
    if how == "setting":
        preferences.set_value("display", "show_errors", "on")
    else:
        monkeypatch.setenv("MAGNACODA_DEBUG", "1")
    out = io.StringIO()
    errors.report(_boom(), "", out)
    assert "Traceback" in out.getvalue() and "RuntimeError: boom" in out.getvalue()
    assert "Something went wrong." in out.getvalue() and len(errors.read()) == 1


def test_the_log_keeps_the_newest_few_and_shows_the_latest():
    for number in range(errors.KEEP + 3):
        errors.record(_boom(f"error {number}"), f"command {number}")
    saved = errors.read()
    assert len(saved) == errors.KEEP and f"error {errors.KEEP + 2}" in saved[0].details
    text = errors.text()
    assert f"error {errors.KEEP + 2}" in text and f"{errors.KEEP - 1} older errors are saved" in text


def test_nothing_saved_says_so_and_the_home_folder_is_left_out(monkeypatch):
    assert "No errors are saved" in errors.text()
    monkeypatch.setattr(Path, "home", lambda: Path(__file__).parent)
    errors.record(_boom(), "")
    assert str(Path(__file__).parent) not in errors.log_path().read_text()


def test_an_error_in_a_thread_is_reported_not_printed(monkeypatch):
    out = io.StringIO()
    monkeypatch.setattr(sys, "stderr", out)
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    monkeypatch.setattr(threading, "excepthook", threading.excepthook)
    errors.install()

    def fails() -> None:
        raise ValueError("in a thread")

    worker = threading.Thread(target=fails)
    worker.start()
    worker.join()
    assert "Something went wrong." in out.getvalue() and "Traceback" not in out.getvalue()
    assert "ValueError: in a thread" in errors.read()[0].details
