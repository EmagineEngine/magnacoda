import re

import pytest
from click.testing import CliRunner
from rich.console import Console

from magnacoda import cli
from magnacoda.cli import main


@pytest.mark.parametrize(
    ("typed", "said"),
    [
        ("shell", "Already in the magnacoda shell"),
        ("scan not-a-url", "No website or computer named 'not-a-url' was found."),
        ("scan http://x --ai bogus", "not one of"),
        ('scan "unterminated', "unable to parse"),
        ("--help", "Only inside the shell:"),
    ],
)
def test_a_mistake_says_what_went_wrong_and_the_session_goes_on(typed, said):
    result = CliRunner().invoke(main, ["shell"], input=f"{typed}\nexit\n")
    assert result.exit_code == 0 and said in result.output


@pytest.mark.parametrize("typed", ["", "\n\n   \nexit\n"])  # Ctrl+D at once; blank lines first
def test_the_shell_ends_cleanly_without_exit_and_skips_blank_lines(typed):
    assert CliRunner().invoke(main, ["shell"], input=typed).exit_code == 0


def test_shell_shows_a_banner_and_exits_cleanly():
    result = CliRunner().invoke(main, ["shell"], input="exit\n")
    assert result.exit_code == 0
    assert "accessibility scanner" in result.output
    assert "magnacoda" in result.output


@pytest.mark.parametrize("exit_word", ["exit", "quit", "q"])
def test_shell_accepts_any_exit_word(exit_word):
    result = CliRunner().invoke(main, ["shell"], input=f"{exit_word}\n")
    assert result.exit_code == 0


def test_details_before_any_error_says_there_is_nothing_to_show():
    result = CliRunner().invoke(main, ["shell"], input="details\nexit\n")
    assert "nothing unexpected has gone wrong in this session" in result.output


def test_details_shows_the_last_unexpected_error_of_a_command(monkeypatch):
    from magnacoda import cli

    def broken() -> str:
        raise RuntimeError("boom")

    monkeypatch.setattr(cli, "about_text", broken)
    result = CliRunner().invoke(main, ["shell"], input="about\nDetails\nexit\n")
    out = " ".join(result.output.split())
    assert "Error: boom Type details to see more." in out and out.count("Traceback") == 1
    assert "from: about" in out and "RuntimeError: boom" in out and "magnacoda " in out


def test_a_scan_that_crashes_in_the_shell_points_to_details_without_cookie_values(monkeypatch, tmp_path):
    from magnacoda import cli

    monkeypatch.chdir(tmp_path)

    def broken(config, *, consent_given=False):
        raise RuntimeError("Target page, context or browser has been closed")

    monkeypatch.setattr(cli, "run_scan", broken)
    lines = "scan http://example.test --cookie session=secret123\ndetails\nexit\n"
    out = " ".join(CliRunner().invoke(main, ["shell"], input=lines).output.split())
    assert "This is likely a bug in magnacoda. Type details to see more." in out and "-v" not in out
    assert "Traceback" in out and "from: scan http://example.test --cookie" in out
    assert "secret123" not in out


@pytest.mark.integration
def test_shell_runs_a_real_scan_then_keeps_prompting(fixture_server):
    lines = f"scan {fixture_server}/clean_page.html --fail-on none\nexit\n"
    result = CliRunner().invoke(main, ["shell"], input=lines)
    assert result.exit_code == 0
    assert "Found no problems the automated checks can see" in result.output


@pytest.mark.parametrize(
    ("args", "installed", "shown"),
    [
        (["shell"], False, True),
        (["shell"], True, False),
        ([], True, False),  # magnacoda alone starts the shell
        (["shell", "--force-setup-notice"], True, True),
        (["--force-setup-notice"], True, True),
    ],
)
def test_the_chromium_notice_shows_when_it_is_missing_or_asked_for(monkeypatch, args, installed, shown):
    monkeypatch.setattr(cli, "_chromium_probably_installed", lambda: installed)
    result = CliRunner().invoke(main, args, input="exit\n")
    assert result.exit_code == 0 and "accessibility scanner" in result.output  # the shell, not a scan
    assert ("Chromium isn't installed yet" in result.output) is shown


@pytest.mark.parametrize(("answer", "runs_setup"), [("\n", True), ("n\n", False)])
def test_at_a_terminal_the_first_shell_offers_to_run_setup(monkeypatch, answer, runs_setup):
    import click

    monkeypatch.setattr(cli, "_chromium_probably_installed", lambda: False)
    monkeypatch.setattr(cli, "_is_interactive", lambda: True)
    ran = []
    monkeypatch.setitem(main.commands, "setup", click.Command("setup", callback=lambda: ran.append(True)))

    result = CliRunner().invoke(main, ["shell"], input=answer + "exit\n")

    assert "Set it up now? [Y/n]" in result.output and result.exit_code == 0
    assert ran == ([True] if runs_setup else [])


@pytest.mark.parametrize(
    ("installed", "args"), [(True, ["shell"]), (False, ["shell", "--force-setup-notice"])]
)
def test_the_shell_offers_setup_only_when_chromium_is_missing(monkeypatch, installed, args):
    monkeypatch.setattr(cli, "_chromium_probably_installed", lambda: installed)
    monkeypatch.setattr(cli, "_is_interactive", lambda: True)
    assert "Set it up now?" not in CliRunner().invoke(main, args, input="exit\n").output


def test_the_chromium_notice_comes_under_the_commands_and_again_after_clear(monkeypatch):
    monkeypatch.setattr(cli, "_chromium_probably_installed", lambda: False)
    output = CliRunner().invoke(main, ["shell"], input="clear\nexit\n").output
    assert output.count("Chromium isn't installed yet") == 2
    assert output.index("Commands:") < output.index("Chromium isn't installed yet")


def test_clear_and_cls_show_the_banner_again_in_any_capitalization():
    for word in ("clear", "cls", "CLS", "Clear"):
        result = CliRunner().invoke(main, ["shell"], input=f"{word}\nexit\n")
        assert result.output.count("accessibility scanner - type a command") == 2, word


FEED = "\x1b[H"  # a page feed ends by moving to the top of the fed (empty) screen
ERASE = ("\x1b[2J", "\x1b[3J")  # clearing the screen or the scrollback: never in the teletype style


def test_the_shell_feeds_a_page_when_it_launches_and_erases_nothing(monkeypatch):
    _terminal_shell(monkeypatch)
    output = CliRunner().invoke(main, ["shell"], input="exit\n").output
    assert output.count(FEED) == 1 and output.index(FEED) < output.index("accessibility scanner")
    assert output.startswith("\n" * 10)  # blank lines scroll what was on screen up into the scrollback
    assert not any(code in output for code in ERASE)


def test_launch_clear_is_skipped_when_output_is_not_a_terminal():
    result = CliRunner().invoke(main, ["shell"], input="exit\n")
    assert "\x1b[" not in result.output


def _terminal_shell(monkeypatch):
    from rich.console import Console

    monkeypatch.setattr(Console, "is_terminal", property(lambda self: True))


def test_output_continues_below_without_a_new_banner_per_command(monkeypatch):
    _terminal_shell(monkeypatch)
    output = CliRunner().invoke(main, ["shell"], input="--version\n--version\nexit\n").output
    assert output.count(FEED) == 1  # the launch only: commands print below, like a printer
    assert output.count("accessibility scanner - type a command") == 1
    assert output.index("accessibility scanner") < output.index("magnacoda, version")
    assert output.count("magnacoda, version") == 2


def test_clear_feeds_a_page_and_shows_the_banner_on_top_without_erasing(monkeypatch):
    _terminal_shell(monkeypatch)
    output = CliRunner().invoke(main, ["shell"], input="--version\nclear\nexit\n").output
    assert output.count(FEED) == 2 and output.count("accessibility scanner - type a command") == 2
    second = output.index(FEED, output.index(FEED) + 1)
    assert output.index("magnacoda, version") < second < output.rindex("accessibility scanner")
    assert not any(code in output for code in ERASE)  # earlier output stays in the scrollback


@pytest.mark.parametrize(
    ("typed", "first_words"),
    [
        ("about", "Author:"),
        ("wizard\nq", "Page to scan"),
        ("review", "No saved scans"),
        ("Scan", "Missing argument 'URL'."),  # no person here: the error, on its fresh page
        ("update", "development install"),
        ("setup", "Chromium"),
    ],
)
def test_each_section_starts_on_a_fresh_page_under_the_banner_and_its_heading(
    monkeypatch, tmp_path, typed, first_words
):
    monkeypatch.chdir(tmp_path)
    _terminal_shell(monkeypatch)
    output = CliRunner().invoke(main, ["shell"], input=f"--version\n{typed}\nexit\n").output
    assert output.count(FEED) == 2 and output.count("accessibility scanner - type a command") == 2
    second = output.index(FEED, output.index(FEED) + 1)
    assert output.index("magnacoda, version") < second  # earlier text stays above, in the scrollback
    heading = typed.split()[0].capitalize()
    assert second < output.rindex("accessibility scanner") < output.index(first_words)  # banner, then it
    above = re.sub(r"\x1b\[[0-9;]*m", "", output[second : output.index(first_words)])  # without styles
    assert f"\n\n{heading}\n\n" in above  # a blank line each side
    assert not any(code in output for code in ERASE)


def test_a_section_underlines_its_command_in_the_banner_and_clear_or_the_launch_does_not():
    env = {"FORCE_COLOR": "1", "TERM": "xterm"}
    output = CliRunner().invoke(main, ["shell"], input="wizard\nq\nclear\nexit\n", env=env).output
    launch, wizard, cleared = output.split("accessibility scanner - type a command")[1:]
    assert "\x1b[1;4m" not in launch and "\x1b[1;4m" not in cleared
    assert "\x1b[1;4mwizard\x1b[0m" in wizard and "\x1b[1mWizard\x1b[0m" in wizard  # underlined; the heading
    assert "\x1b[1mWizard" not in cleared


def test_piped_sessions_never_clear_or_reprint_the_banner():
    result = CliRunner().invoke(main, ["shell"], input="about\nabout\nexit\n")
    assert "\x1b[" not in result.output
    assert result.output.count("accessibility scanner - type a command") == 1


def test_banner_words_use_the_normal_color_and_only_the_dots_are_dim():
    env = {"FORCE_COLOR": "1", "TERM": "xterm"}
    output = CliRunner().invoke(main, ["shell"], input="exit\n", env=env).output
    assert "or exit to leave." in output  # normal color: dim gray can be too faint to read
    assert "\x1b[1mCommands:\x1b[0m scan \x1b[2m·\x1b[0m wizard" in output  # bold label, dim dots only
    assert "\x1b[2mwizard" not in output


def test_notices_are_indented_set_apart_and_use_bold_not_a_color():
    env = {"FORCE_COLOR": "1", "TERM": "xterm", "COLUMNS": "80"}
    output = CliRunner().invoke(main, ["shell", "--force-setup-notice"], input="exit\n", env=env).output
    lines = output.splitlines()
    first = next(i for i, line in enumerate(lines) if "Chromium isn't installed yet" in line)
    assert lines[first - 1] == "" and lines[first].startswith(
        "    \x1b[1mChromium isn't installed yet\x1b[0m"
    )
    notice = lines[first : lines.index("", first)]
    assert len(notice) > 1 and all(line.startswith("    ") and line == line.rstrip() for line in notice)
    assert "\x1b[33m" not in output  # no yellow (or any fixed color) for notices


def test_an_old_windows_console_feeds_a_page_with_cls_and_gets_no_control_codes(monkeypatch):
    import io

    from magnacoda import teletype

    ran = []
    monkeypatch.setattr(teletype.os, "system", lambda command: ran.append(command) or 0)
    out = io.StringIO()
    teletype.page_feed(Console(file=out, force_terminal=True, legacy_windows=True))
    assert ran == ["cls"] and "\x1b" not in out.getvalue()  # no ←[ codes left on screen


def test_a_modern_console_feeds_one_screen_of_blank_lines_then_goes_to_the_top(monkeypatch):
    import io

    from magnacoda import teletype

    monkeypatch.setattr(teletype.os, "system", lambda command: pytest.fail("must not run cls"))
    out = io.StringIO()
    teletype.page_feed(Console(file=out, force_terminal=True, legacy_windows=False, height=30))
    assert out.getvalue() == "\n" * 30 + "\x1b[H"


def test_the_windows_console_setup_does_nothing_elsewhere():
    from magnacoda import winconsole

    assert winconsole.enable_virtual_terminal() is True  # not Windows: nothing to switch on


@pytest.mark.parametrize("typed", ["magnacoda", "Magnacode", "MAGNACONDA"])
def test_typing_the_program_name_inside_the_shell_names_the_real_paths(typed):
    output = CliRunner().invoke(main, ["shell"], input=f"{typed}\nexit\n").output
    assert "Obvious paths: help, scan URL, wizard." in output
    assert "Error" not in output and "Did you mean" not in output


@pytest.mark.parametrize(
    ("typed", "said"),
    [
        ("xyzzy", "Nothing happens."),
        ("LOOK", "maze of twisty"),
        ("i", "carrying one magnacoda shell"),
        ("n", "can't go"),
        ("West", "can't go"),
    ],
)
def test_adventure_words_get_an_answer_and_the_real_paths(typed, said):
    output = CliRunner().invoke(main, ["shell"], input=f"{typed}\nexit\n").output
    assert said in output and "Obvious paths: help, scan URL, wizard." in output
    assert "Error" not in output


def test_the_lines_come_in_turn_then_nothing_happens_for_good():
    from magnacoda.cli import _ALREADY_HERE

    output = CliRunner().invoke(main, ["shell"], input="magnacoda\n" * 7 + "exit\n").output
    said = [line.split("» ")[-1] for line in output.splitlines() if line.startswith("magnacoda » ")][:7]
    expected = [line.format(name="magnacoda") for line in _ALREADY_HERE]
    assert said == [*expected, "Nothing happens.", "Nothing happens."]


def test_a_command_typed_with_the_program_name_in_front_runs_as_it_would_outside(monkeypatch):
    from magnacoda import cli
    from tests.cli.test_screen import _fake_run

    seen: list = []
    monkeypatch.setattr(cli, "run_scan", _fake_run(seen))
    output = (
        CliRunner()
        .invoke(main, ["shell"], input="magnacoda scan https://a.test -y\nmagnacode shell\nexit\n")
        .output
    )
    assert [config.url for config in seen] == ["https://a.test"]
    assert "Already in the magnacoda shell." in output


def test_a_scan_the_wizard_or_saved_settings_start_gets_no_second_page(monkeypatch, tmp_path):
    from magnacoda import cli, history
    from magnacoda.browser import redirects
    from tests.cli.test_screen import _fake_run

    monkeypatch.chdir(tmp_path)
    _terminal_shell(monkeypatch)
    monkeypatch.setattr(cli, "run_scan", _fake_run([]))
    monkeypatch.setattr(cli, "_is_interactive", lambda: True)
    monkeypatch.setattr(redirects, "check_address", lambda url, **kw: None)
    history.ensure_file()
    history.history_path().write_text(
        history.HEADER + "- 2026-10-17 09:00 `scan https://example.com --level AAA --ai off`\n"
    )
    # scan example.com: the saved settings, Enter (the last scan), Enter (no changes): one page, not two
    output = CliRunner().invoke(main, ["shell"], input="scan example.com\n\n\nexit\n").output
    assert "scanned before" in output and output.count(FEED) == 2


def test_q_and_ctrl_c_at_the_prompt_ask_before_leaving(monkeypatch):
    monkeypatch.setattr(cli, "_is_interactive", lambda: True)
    typed = iter(["q", KeyboardInterrupt, "q"])

    def fake_input(self, prompt=""):
        line = next(typed)
        if line is KeyboardInterrupt:
            raise KeyboardInterrupt
        return line

    monkeypatch.setattr(cli.Console, "input", fake_input)
    # q: n stays; Ctrl+C: q stays; q: y leaves
    result = CliRunner().invoke(main, ["shell"], input="n\nq\ny\n")
    assert result.output.count("Leave magnacoda? [y/N]") == 3 and result.exit_code == 0


def test_exit_and_quit_leave_at_once(monkeypatch):
    monkeypatch.setattr(cli, "_is_interactive", lambda: True)
    for word in ("exit", "quit"):
        result = CliRunner().invoke(main, ["shell"], input=f"{word}\n")
        assert "Leave magnacoda?" not in result.output and result.exit_code == 0
