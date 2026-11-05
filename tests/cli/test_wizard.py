import pytest
from click.testing import CliRunner

from magnacoda.cli import main


def _answers(**overrides) -> str:
    defaults = {
        "url": "https://example.com/",
        "level": "",
        "ai": "",
        "color_scheme": "",
        "screen": "",
        "confirm": "n",
    }
    defaults.update(overrides)
    order = [
        "url",
        "level",
        "ai",
        "screen",
        "confirm",
    ]
    return "\n".join(defaults[k] for k in order) + "\n"


def test_wizard_shows_the_equivalent_command_and_can_be_declined():
    result = CliRunner().invoke(main, ["wizard"], input=_answers())
    assert result.exit_code == 0
    assert "Equivalent command:" in result.output
    command = result.output.split("Equivalent command:\n")[1].splitlines()[0].strip()
    # The defaults left out, except testing both screens: the wizard's default, not the command line's.
    assert command == "magnacoda scan https://example.com/ --level AA --ai off --screen both"
    assert "Cancelled - nothing was scanned." in result.output


def test_wizard_omits_color_scheme_when_left_at_default_and_never_asks_about_saving():
    result = CliRunner().invoke(main, ["wizard"], input=_answers())
    line = next(line for line in result.output.splitlines() if line.strip().startswith("magnacoda "))
    assert "--color-scheme" not in line and "--save" not in line
    assert "Save this scan?" not in result.output  # every scan is saved


def test_wizard_includes_the_screen_when_chosen():
    result = CliRunner().invoke(main, ["wizard"], input=_answers(screen="mobile"))
    command_line = result.output.split("Equivalent command:\n")[1].splitlines()[0]
    assert "--screen mobile" in command_line
    assert "Color scheme" not in result.output  # dark mode is checked without asking


def test_wizard_asks_nothing_about_fixes_or_failing():
    # Those are for scripts and CI, which use the flags; the wizard keeps the defaults.
    output = CliRunner().invoke(main, ["wizard"], input=_answers(ai="explain")).output
    assert "Fix suggestions" not in output and "Output format" not in output and "Fail on" not in output


@pytest.mark.parametrize("typed", ["\n", "   \n"])
def test_with_no_address_yet_enter_cancels_the_wizard_and_its_prompt_says_so(typed, monkeypatch):
    from magnacoda import cli

    monkeypatch.setattr(cli, "_is_interactive", lambda: True)
    result = CliRunner().invoke(main, ["wizard"], input=typed)
    assert "Ctrl+C or q cancels at any time." in result.output
    assert "or localhost:3000), or press Enter to cancel:" in result.output
    assert "Cancelled." in result.output and "WCAG level" not in result.output


@pytest.mark.integration
def test_wizard_runs_a_real_scan_when_confirmed(fixture_server):
    result = CliRunner().invoke(
        main,
        ["wizard"],
        input=_answers(url=f"{fixture_server}/static_violations.html", confirm="y"),
    )
    assert result.exit_code == 1  # it found a serious problem: the scan's default --fail-on serious
    assert "Found " in result.output and "magnacoda-scans/" in result.output


@pytest.mark.integration
def test_wizard_reachable_from_inside_the_shell(fixture_server):
    lines = "wizard\n" + _answers(url=f"{fixture_server}/clean_page.html", confirm="y") + "exit\n"
    result = CliRunner().invoke(main, [], input=lines)
    assert result.exit_code == 0
    assert "Welcome to magnacoda" in result.output  # bare invocation launches the shell
    assert "Equivalent command:" in result.output
    assert "Found no problems the automated checks can see" in result.output


@pytest.mark.parametrize(
    ("args", "installed", "shown"),
    [(["wizard"], False, True), (["wizard"], True, False), (["wizard", "--force-setup-notice"], True, True)],
)
def test_the_wizard_shows_the_chromium_notice_like_the_shell(monkeypatch, args, installed, shown):
    from magnacoda import cli

    monkeypatch.setattr(cli, "_chromium_probably_installed", lambda: installed)
    result = CliRunner().invoke(main, args, input=_answers())
    assert ("Chromium isn't installed yet" in result.output) is shown


@pytest.mark.parametrize(("answer", "downloads"), [("\n", True), ("n\n", False)])
def test_at_a_terminal_the_wizard_offers_to_download_chromium_first(monkeypatch, answer, downloads):
    from types import SimpleNamespace

    from magnacoda import cli

    monkeypatch.setattr(cli, "_chromium_probably_installed", lambda: False)
    monkeypatch.setattr(cli, "_is_interactive", lambda: True)
    calls = []
    monkeypatch.setattr(
        cli.subprocess, "run", lambda *a, **kw: calls.append(a) or SimpleNamespace(returncode=0)
    )

    result = CliRunner().invoke(main, ["wizard"], input=answer + _answers())

    assert "Download it now? [Y/n]" in result.output and len(calls) == int(downloads)
    assert ("Chromium isn't installed yet" in result.output) is not downloads
    assert "Equivalent command:" in result.output  # the wizard carries on either way
