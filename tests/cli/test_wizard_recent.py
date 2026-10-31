import stat
import sys

import pytest
from click.testing import CliRunner

from magnacoda import cli, history, preferences
from magnacoda.cli import main
from tests.cli.test_screen import _fake_run

BLANKS = ["", "", ""]  # level, AI, screens: keep every default


def _wizard(monkeypatch, *answers: str):
    seen: list = []
    monkeypatch.setattr(cli, "run_scan", _fake_run(seen))
    result = CliRunner().invoke(main, ["wizard"], input="\n".join(answers) + "\n")
    return result, seen


def _prefs(text: str) -> None:
    preferences.preferences_path().parent.mkdir(parents=True, exist_ok=True)
    preferences.preferences_path().write_text(text)


def _defaults_then(*rest: str) -> list[str]:
    return [*BLANKS, *rest]  # every default


def test_the_files_are_created_when_the_wizard_starts(monkeypatch):
    _wizard(monkeypatch, "https://a.test", *_defaults_then("n"))
    assert history.history_path().exists()
    assert preferences.preferences_path().exists()


def test_no_picker_appears_when_there_is_nothing_saved(monkeypatch):
    result, _ = _wizard(monkeypatch, "https://a.test", *_defaults_then("n"))
    assert "Start from a saved scan" not in result.output
    assert "favorite" not in result.output.lower()


def test_loading_a_recent_scan_keeps_its_values_and_lets_the_url_change(monkeypatch):
    history.record("scan https://old.test --level AAA --color-scheme dark --fail-on minor")
    result, seen = _wizard(monkeypatch, "recent", "1", "https://new.test", "", "y")
    assert "Recent scans" in result.output
    assert "magnacoda scan https://new.test --level AAA" in result.output
    assert "--color-scheme dark" in result.output and "--fail-on minor" in result.output
    assert "Change anything? [y/N]" in result.output
    assert "WCAG level" not in result.output  # none of the questions were asked
    assert result.output.count("Equivalent command:") == 1  # shown once, not again after "no"
    assert [c.url for c in seen] == ["https://new.test"]
    assert seen[0].color_scheme == "dark"


def test_saying_yes_to_more_changes_asks_every_question_defaulting_to_the_saved_scan(monkeypatch):
    history.record("scan https://old.test --level AAA --color-scheme dark --fail-on minor")
    result, seen = _wizard(monkeypatch, "recent", "1", "https://new.test", "y", "A", *BLANKS[1:], "y")
    assert "WCAG level (A, AA, AAA) [AAA]" in result.output
    assert "Screens to test (both, desktop, mobile) [desktop]" in result.output  # as the saved scan did
    assert "Color scheme" not in result.output  # not asked; the saved scan's dark is kept
    assert "Fail on" not in result.output and seen[0].fail_on == "minor"  # not asked, but kept
    assert [(c.url, c.color_scheme) for c in seen] == [("https://new.test", "dark")]
    assert seen[0].level == "A"


def test_options_the_wizard_does_not_ask_about_are_kept_and_used(monkeypatch):
    history.record("scan https://a.test --browser firefox")
    result, seen = _wizard(monkeypatch, "recent", "1", "", "", "y")
    assert "--browser firefox" in result.output
    assert seen and seen[0].browser_name == "firefox"


def test_redacted_history_values_are_dropped_with_a_note(monkeypatch):
    history.record("scan https://a.test --cookie 'sid=<redacted>'")
    result, _ = _wizard(monkeypatch, "recent", "1", "", "", "n", "n")
    assert "Left out --cookie" in result.output
    assert "--cookie" not in result.output.split("Equivalent command:")[1]


def test_a_number_outside_the_list_is_asked_again(monkeypatch):
    history.record("scan https://home.test")
    result, _ = _wizard(monkeypatch, "recent", "7", "1", "", "", "n", "n")
    assert "type one of the numbers above" in result.output.lower()


def test_a_wizard_scan_is_recorded_in_history(monkeypatch):
    _wizard(monkeypatch, "https://a.test", *_defaults_then("y"))
    assert [e.command for e in history.read()] == ["scan https://a.test --level AA --ai off --screen both"]


def test_a_declined_wizard_scan_is_not_recorded(monkeypatch):
    _wizard(monkeypatch, "https://a.test", *_defaults_then("n"))
    assert history.read() == []


def test_a_direct_scan_is_recorded_with_secrets_redacted(monkeypatch):
    monkeypatch.setattr(cli, "run_scan", _fake_run([]))
    result = CliRunner().invoke(
        main, ["scan", "https://a.test", "--cookie", "sid=topsecret", "--extra-http-header", "X-Key=abc123"]
    )
    assert result.exit_code == 0
    text = history.history_path().read_text()
    assert "topsecret" not in text and "abc123" not in text
    assert "sid=<redacted>" in text and "X-Key=<redacted>" in text


def test_a_scan_is_recorded_with_its_command_word(monkeypatch):
    monkeypatch.setattr(cli, "run_scan", _fake_run([]))
    CliRunner().invoke(main, ["scan", "https://a.test", "--level", "A"])
    assert history.read()[0].command == "scan https://a.test --level A"


def test_a_scan_that_fails_validation_is_not_recorded(monkeypatch):
    monkeypatch.setattr(cli, "run_scan", _fake_run([]))
    result = CliRunner().invoke(main, ["scan", "https://a.test", "--level", "ZZ"])
    assert result.exit_code != 0
    assert history.read() == []


def test_history_off_records_nothing(monkeypatch):
    _prefs("[history]\nmax = 0\n")
    monkeypatch.setattr(cli, "run_scan", _fake_run([]))
    CliRunner().invoke(main, ["scan", "https://a.test"])
    assert not history.history_path().exists()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
def test_wizard_created_files_are_owner_only(monkeypatch):
    _wizard(monkeypatch, "https://a.test", *_defaults_then("y"))
    assert stat.S_IMODE(history.history_path().stat().st_mode) == 0o600


def test_ctrl_c_inside_the_shell_says_cancelled_instead_of_error(monkeypatch):
    lines = iter(["wizard"])

    def fake_input(self, prompt=""):
        try:
            return next(lines)
        except StopIteration:
            raise EOFError from None

    monkeypatch.setattr(cli.Console, "input", fake_input)
    monkeypatch.setattr(cli.click, "prompt", lambda *a, **k: (_ for _ in ()).throw(cli.click.Abort()))
    result = CliRunner().invoke(main, [])
    assert "Cancelled." in result.output
    assert "Error" not in result.output


def test_clear_at_a_question_inside_the_shell_starts_a_fresh_page(monkeypatch):
    def run(typed: str) -> str:
        lines = iter(["wizard"])

        def fake_input(self, prompt=""):
            try:
                return next(lines)
            except StopIteration:
                raise EOFError from None

        monkeypatch.setattr(cli.Console, "input", fake_input)
        monkeypatch.setattr(cli.click, "prompt", lambda *a, **k: k["value_proc"](typed))
        return CliRunner().invoke(main, []).output

    banner = "type a command, or exit to leave"
    cancelled, cleared = run("q"), run("clear")
    assert "Cancelled." in cancelled and "Cancelled." not in cleared and "Error" not in cleared
    assert cleared.count(banner) == cancelled.count(banner) + 1


# The first question: a new scan, or from a list


def _flat(result) -> str:
    return " ".join(result.output.split())


def test_the_first_question_offers_only_what_there_is_and_enter_cancels(monkeypatch):
    from datetime import datetime

    history.record("scan https://home.test --level A", now=datetime(2020, 3, 4, 5, 6))
    result, seen = _wizard(monkeypatch, "new", "https://new.test", *_defaults_then("y"))
    text = _flat(result)
    assert "Type new, recent, or press Enter to cancel" in text  # no favorites offered
    assert "Recent scans" not in text and {c.url for c in seen} == {"https://new.test"}
    for quit_with in ("", "q"):  # q cancels too, as at any question
        result, seen = _wizard(monkeypatch, quit_with, "https://new.test")
        assert "Cancelled." in result.output and seen == [] and "Page to scan" not in result.output


@pytest.mark.parametrize("word", ["recent", "Recent", "r", "recent scans", " RECENT "])
def test_the_recent_list_opens_with_any_of_its_words_one_line_per_scan(monkeypatch, word):
    from datetime import datetime

    history.record("scan http://old.test --level A", now=datetime(2020, 3, 4, 5, 6))
    history.record("scan https://home.test/blog --level A", now=datetime.now().replace(hour=9, minute=5))
    result, _ = _wizard(monkeypatch, word, "", "n")
    listed = result.output.split("Recent scans", 1)[1].split("Type a number", 1)[0]
    lines = [line for line in listed.splitlines() if line.strip()]
    assert lines[0].startswith("  1. home.test/blog   ") and lines[0].endswith(", 09:05")  # lined up
    assert lines[1] == "  2. http://old.test  Mar 4 2020, 05:06"  # http:// shows; another year shows


def test_enter_at_a_list_goes_back_and_an_unknown_word_asks_again(monkeypatch):
    history.record("scan https://home.test --level A")
    result, seen = _wizard(monkeypatch, "recnet", "recent", "", "new", "https://b.test", *_defaults_then("y"))
    text = _flat(result)
    assert "Error: type new, recent, or press Enter to cancel." in text
    assert text.count("Start a new scan, or from one of your") == 2  # at first, and after going back
    assert text.count("Type new, recent, or press Enter to cancel") == 3  # a typo asks just this line again
    assert {c.url for c in seen} == {"https://b.test"}
