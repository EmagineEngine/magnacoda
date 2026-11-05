"""Tips under the shell's banner (tips.py, data/tips.md, and cli._show_tip)."""

import pytest
from click.testing import CliRunner

from magnacoda import cli, preferences, tips
from magnacoda.cli import main


def test_tips_are_the_list_items_with_comments_and_emphasis_dropped():
    text = "# Tips\n<!-- - not a tip -->\n- First **tip** with `code`.\n\nIgnored line.\n- Second *one*.\n"
    assert tips.load(text) == ["First tip with `code`.", "Second one."]


def test_the_real_tips_start_with_menu_then_the_wizard_and_end_with_how_to_turn_them_off():
    found = tips.load()
    assert "`menu`" in found[0] and "`wizard`" in found[1] and "tips = off" in found[-1]


def test_each_tip_shown_moves_on_to_the_next_and_then_starts_over(monkeypatch):
    monkeypatch.setattr(tips, "load", lambda: ["one", "two"])
    assert [tips.next_tip() for _ in range(5)] == ["one", "two", "one", "two", "one"]


def test_a_damaged_state_file_starts_over_and_no_tips_gives_none(monkeypatch):
    tips.state_path().parent.mkdir(parents=True, exist_ok=True)
    tips.state_path().write_text("[1, 2]")
    monkeypatch.setattr(tips, "load", lambda: ["one", "two"])
    assert tips.next_tip() == "one"
    monkeypatch.setattr(tips, "load", lambda: [])
    assert tips.next_tip() is None


@pytest.fixture
def at_a_terminal(monkeypatch):
    monkeypatch.setattr(cli, "_interactive", lambda console: True)
    monkeypatch.setattr(tips, "load", lambda: ["Try the wizard."])
    monkeypatch.setattr(cli, "_chromium_probably_installed", lambda: True)  # its notice would hide the tip


def test_one_tip_a_session_under_the_first_menu_and_not_at_the_start(at_a_terminal):
    output = CliRunner().invoke(main, ["shell"], input="menu\nmenu\nexit\n").output
    assert output.count("Tip: Try the wizard.") == 1 and "Tip:" not in output.split("Commands:")[0]
    assert output.index("Commands:") < output.index("Tip:") < output.rindex("Commands:")
    lines = "menu\nexit\n"
    setup_notice = CliRunner().invoke(main, ["shell", "--force-setup-notice"], input=lines).output
    assert "Tip:" not in setup_notice  # one notice at a time


def test_a_tips_lines_stop_by_column_60_even_in_a_wide_terminal(monkeypatch):
    monkeypatch.setattr(cli, "_interactive", lambda console: True)
    monkeypatch.setattr(tips, "load", lambda: ["word " * 40])
    monkeypatch.setenv("COLUMNS", "120")
    output = CliRunner().invoke(main, ["shell"], input="menu\nexit\n").output
    lines = [line for line in output.splitlines() if line.startswith("    ") and "word" in line]
    assert len(lines) > 2 and all(len(line.rstrip()) <= 60 for line in lines)
    assert max(len(line.rstrip()) for line in lines) > 50  # and it does use the room


def test_code_in_a_tip_is_bold_without_its_backticks():
    shown = tips.markup("Set `tips = off` under [display].")
    assert shown == "Set [bold]tips = off[/bold] under \\[display]."


def test_tips_can_be_turned_off_in_the_preferences(at_a_terminal):
    preferences.ensure_file()
    path = preferences.preferences_path()
    path.write_text(path.read_text().replace("tips = on", "tips = off"))
    assert not preferences.load().tips
    assert "Tip:" not in CliRunner().invoke(main, ["shell"], input="exit\n").output


def test_no_tip_when_commands_are_piped_in():
    assert "Tip:" not in CliRunner().invoke(main, ["shell"], input="exit\n").output
