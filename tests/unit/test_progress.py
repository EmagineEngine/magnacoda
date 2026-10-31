"""What a scan is doing, for the spinner (progress.py, cli._scan_progress)."""

import io

from rich.console import Console

from magnacoda import cli, preferences, progress


def test_steps_reach_a_listener_only_while_it_listens():
    heard: list[str] = []
    progress.step("before")
    with progress.listening(heard.append):
        progress.step("loading the page")
        with progress.listening(lambda text: None):
            progress.step("ignored by the outer listener")
        progress.step("running the checks")
    progress.step("after")
    assert heard == ["loading the page", "running the checks"]


def _terminal(monkeypatch):
    out = io.StringIO()
    monkeypatch.setattr(
        cli,
        "Console",
        lambda **kw: Console(
            file=out, force_terminal=True, width=120, **{k: v for k, v in kw.items() if k != "stderr"}
        ),
    )
    return out


def test_with_the_spinner_off_each_pass_gets_one_plain_line(monkeypatch, capsys):
    _terminal(monkeypatch)
    preferences.ensure_file()
    path = preferences.preferences_path()
    path.write_text(path.read_text().replace("spinner = on", "spinner = off"))
    with cli._scan_progress("https://a.test") as next_pass:
        next_pass(1, 2, "light")
        progress.step("loading the page")  # not shown: no animation for screen readers
        next_pass(2, 2, "dark")
    err = capsys.readouterr().err
    assert "Scanning https://a.test (light: 1 of 2)..." in err and "(dark: 2 of 2)" in err
    assert "loading the page" not in err


def test_the_spinner_shows_the_pass_and_the_step(monkeypatch):
    out = _terminal(monkeypatch)
    with cli._scan_progress("https://a.test") as next_pass:
        next_pass(1, 4, "mobile.dark")
        progress.step("running the accessibility checks")
    two_lines = "Scanning https://a.test\n  running the accessibility checks (mobile, dark: 1 of 4)"
    assert two_lines in out.getvalue()


def test_not_on_a_terminal_nothing_is_shown(capsys):
    with cli._scan_progress("https://a.test") as next_pass:  # tests' stderr isn't a terminal
        next_pass(1, 1, None)
        progress.step("loading the page")
    assert capsys.readouterr().err == ""
