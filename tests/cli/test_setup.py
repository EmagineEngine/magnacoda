from types import SimpleNamespace

import click
import pytest
from click.testing import CliRunner

from magnacoda import cli, preferences
from magnacoda.cli import main


def _fake_run(calls, returncode=0):
    def run(*args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=returncode)

    return run


def test_setup_reports_already_installed_and_never_calls_the_installer(monkeypatch):
    monkeypatch.setattr(cli, "_chromium_already_installed", lambda: True)
    calls = []
    monkeypatch.setattr(
        cli.subprocess, "run", lambda *a, **kw: calls.append(a) or SimpleNamespace(returncode=0)
    )

    result = CliRunner().invoke(main, ["setup"])

    assert result.exit_code == 0
    assert "Chromium is already installed." in result.output
    assert result.output.count("installed") == 1
    assert calls == []


def test_setup_prompts_before_installing_and_installs_on_yes(monkeypatch):
    monkeypatch.setattr(cli, "_chromium_already_installed", lambda: False)
    monkeypatch.setattr(cli, "_is_interactive", lambda: True)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake")  # skip the (separately tested) key prompt
    calls = []
    monkeypatch.setattr(
        cli.subprocess, "run", lambda *a, **kw: calls.append(a) or SimpleNamespace(returncode=0)
    )

    result = CliRunner().invoke(main, ["setup"], input="y\n\nn\n")  # install, no shortcut, no wizard

    assert result.exit_code == 0
    assert "100 MB" in result.output
    assert "Download and install it now?" in result.output
    assert "Chromium is installed." in result.output
    assert len(calls) == 1


def test_setup_cancelled_on_no_does_not_install(monkeypatch):
    monkeypatch.setattr(cli, "_chromium_already_installed", lambda: False)
    monkeypatch.setattr(cli, "_is_interactive", lambda: True)
    calls = []
    monkeypatch.setattr(
        cli.subprocess, "run", lambda *a, **kw: calls.append(a) or SimpleNamespace(returncode=0)
    )

    result = CliRunner().invoke(main, ["setup"], input="n\n")

    assert result.exit_code == 1
    assert "Cancelled" in result.output
    assert calls == []


def test_setup_non_interactive_without_yes_refuses(monkeypatch):
    monkeypatch.setattr(cli, "_chromium_already_installed", lambda: False)
    monkeypatch.setattr(cli, "_is_interactive", lambda: False)
    calls = []
    monkeypatch.setattr(
        cli.subprocess, "run", lambda *a, **kw: calls.append(a) or SimpleNamespace(returncode=0)
    )

    result = CliRunner().invoke(main, ["setup"])

    assert result.exit_code != 0
    assert "--yes" in result.output
    assert calls == []


def test_setup_yes_flag_skips_the_prompt(monkeypatch):
    monkeypatch.setattr(cli, "_chromium_already_installed", lambda: False)
    monkeypatch.setattr(cli, "_is_interactive", lambda: False)
    calls = []
    monkeypatch.setattr(
        cli.subprocess, "run", lambda *a, **kw: calls.append(a) or SimpleNamespace(returncode=0)
    )

    result = CliRunner().invoke(main, ["setup", "--yes"])

    assert result.exit_code == 0
    assert "Download and install it now?" not in result.output
    assert "Chromium is installed." in result.output
    assert len(calls) == 1


def test_setup_reports_installer_failure(monkeypatch):
    monkeypatch.setattr(cli, "_chromium_already_installed", lambda: False)
    monkeypatch.setattr(cli.subprocess, "run", _fake_run([], returncode=3))

    result = CliRunner().invoke(main, ["setup", "--yes"])

    assert result.exit_code == 3
    assert "Installation failed" in result.output
    assert "Chromium is installed." not in result.output


def test_chromium_probably_installed_true_when_a_chromium_dir_exists(tmp_path, monkeypatch):
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))
    (tmp_path / "chromium-1243").mkdir()

    assert cli._chromium_probably_installed() is True


def test_chromium_probably_installed_false_on_an_empty_or_missing_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path / "does-not-exist"))
    assert cli._chromium_probably_installed() is False

    (tmp_path / "firefox-9999").mkdir()
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))
    assert cli._chromium_probably_installed() is False


def test_chromium_probably_installed_is_fast(monkeypatch):
    import time

    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
    t0 = time.monotonic()
    cli._chromium_probably_installed()
    assert time.monotonic() - t0 < 0.2  # real check; must never start Playwright's driver process


def test_chromium_probably_installed_honours_xdg_cache_home_on_linux(tmp_path, monkeypatch):
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
    monkeypatch.setattr(cli.sys, "platform", "linux")
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    (tmp_path / "ms-playwright" / "chromium-1243").mkdir(parents=True)

    assert cli._chromium_probably_installed() is True


def test_setup_reports_missing_api_key(monkeypatch):
    monkeypatch.setattr(cli, "_chromium_already_installed", lambda: True)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    result = CliRunner().invoke(main, ["setup"])

    assert result.exit_code == 0
    assert "Not set up yet" in result.output and "install Claude Code" in result.output
    assert "platform.claude.com/settings/keys" in result.output
    assert "export ANTHROPIC_API_KEY=" in result.output
    assert "only lasts for this terminal" in result.output
    assert "~/.bashrc" in result.output


def test_setup_reports_present_api_key(monkeypatch):
    monkeypatch.setattr(cli, "_chromium_already_installed", lambda: True)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake")

    result = CliRunner().invoke(main, ["setup"])

    assert result.exit_code == 0
    assert "Ready, with your Anthropic API key (from $ANTHROPIC_API_KEY)" in result.output
    assert "Not set up yet" not in result.output


def test_setup_checks_api_key_after_a_fresh_install_too(monkeypatch):
    monkeypatch.setattr(cli, "_chromium_already_installed", lambda: False)
    monkeypatch.setattr(cli.subprocess, "run", _fake_run([]))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    result = CliRunner().invoke(main, ["setup", "--yes"])

    assert result.exit_code == 0
    assert "Chromium is installed." in result.output
    assert "AI tiers (optional" in result.output


def test_setup_skips_api_key_check_when_cancelled(monkeypatch):
    monkeypatch.setattr(cli, "_chromium_already_installed", lambda: False)
    monkeypatch.setattr(cli, "_is_interactive", lambda: True)
    calls = []
    monkeypatch.setattr(cli.subprocess, "run", _fake_run(calls))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    result = CliRunner().invoke(main, ["setup"], input="n\n")

    assert result.exit_code == 1
    assert "AI tiers" not in result.output
    assert calls == []


def _claude_installed(monkeypatch):
    monkeypatch.setattr(
        cli.shutil, "which", lambda name, *a, **k: "/usr/bin/claude" if name == "claude" else None
    )


def test_with_claude_code_setup_asks_whether_to_use_the_claude_plan_and_saves_the_answer(monkeypatch):
    monkeypatch.setattr(cli, "_chromium_already_installed", lambda: True)
    monkeypatch.setattr(cli, "_is_interactive", lambda: True)
    _claude_installed(monkeypatch)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    output = CliRunner().invoke(main, ["setup"], input="\n\n").output  # no shortcut; Enter: yes

    assert "Use your Claude plan for the AI tiers? [Y/n]" in output
    assert "Ready, with your Claude plan" in output and "You don't need an API key" in output
    assert "Save an API key" not in output
    assert preferences.load().ai_engine == "claude-code"
    assert "engine = claude-plan" in preferences.preferences_path().read_text()


def test_answering_no_uses_an_api_key_and_the_next_setup_defaults_to_that(monkeypatch):
    monkeypatch.setattr(cli, "_chromium_already_installed", lambda: True)
    monkeypatch.setattr(cli, "_is_interactive", lambda: True)
    _claude_installed(monkeypatch)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    output = CliRunner().invoke(main, ["setup"], input="\nn\nn\n").output  # no shortcut, no plan, no key
    assert "No Anthropic API key is saved yet" in output and "Save an API key now? [y/N]" in output
    assert preferences.load().ai_engine == "api"
    assert (
        "Use your Claude plan for the AI tiers? [y/N]"
        in CliRunner().invoke(main, ["setup"], input="\n\nn\n").output
    )


def test_with_the_claude_plan_chosen_a_key_is_said_to_be_unused(monkeypatch):
    monkeypatch.setattr(cli, "_chromium_already_installed", lambda: True)
    _claude_installed(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake")
    preferences.set_ai_engine("claude-code")

    output = CliRunner().invoke(main, ["setup"]).output  # not interactive: nothing asked

    assert "Ready, with your Claude plan" in output and "API key isn't used" in output


def test_without_a_terminal_setup_reports_an_undecided_choice_without_asking(monkeypatch):
    monkeypatch.setattr(cli, "_chromium_already_installed", lambda: True)
    _claude_installed(monkeypatch)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    output = CliRunner().invoke(main, ["setup"]).output

    assert "you haven't chosen whether the AI tiers may use your Claude plan" in output
    assert "[Y/n]" not in output and preferences.load().ai_engine == "ask"


def test_on_windows_setup_shows_setx_instead_of_export(monkeypatch):
    monkeypatch.setattr(cli, "_chromium_already_installed", lambda: True)
    monkeypatch.setattr(cli.sys, "platform", "win32")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    output = CliRunner().invoke(main, ["setup"]).output

    assert "setx ANTHROPIC_API_KEY sk-ant-..." in output and "export" not in output


def test_the_first_ai_scan_asks_about_the_claude_plan_once_and_uses_the_answer(monkeypatch):
    from tests.cli.test_screen import _fake_run

    seen = []
    monkeypatch.setattr(cli, "run_scan", _fake_run(seen))
    monkeypatch.setattr(cli, "_is_interactive", lambda: True)
    _claude_installed(monkeypatch)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    scan = ["scan", "https://a.test", "--ai", "explain", "--yes", "--fail-on", "none"]

    first = CliRunner().invoke(main, scan, input="\n").output
    assert "Use your Claude plan for the AI tiers? [Y/n]" in first
    assert seen[-1].ai.resolve_engine() == "claude-code"
    second = CliRunner().invoke(main, scan).output
    assert "Use your Claude plan" not in second and seen[-1].ai.resolve_engine() == "claude-code"


def test_setup_says_q_cancels_when_a_person_is_there_and_q_does(monkeypatch):
    monkeypatch.setattr(cli, "_chromium_already_installed", lambda: False)
    calls = []
    monkeypatch.setattr(
        cli.subprocess, "run", lambda *a, **kw: calls.append(a) or SimpleNamespace(returncode=0)
    )
    monkeypatch.setattr(cli, "_is_interactive", lambda: True)
    result = CliRunner().invoke(main, ["setup"], input="q\n")
    assert result.output.startswith("Ctrl+C or q cancels at any time.")
    assert "Cancelled." in result.output and calls == []  # nothing downloaded
    monkeypatch.setattr(cli, "_is_interactive", lambda: False)
    assert "q cancels" not in CliRunner().invoke(main, ["setup", "-y"]).output  # scripts and CI


def _wizard_stand_in(started):
    @click.command()
    @click.option("--force-setup-notice", is_flag=True)
    def wizard(force_setup_notice):
        started.append(force_setup_notice)

    return wizard


@pytest.mark.parametrize(("answer", "starts"), [("\n", True), ("n\n", False)])
def test_the_first_setup_offers_the_wizard_for_the_first_scan(monkeypatch, answer, starts):
    monkeypatch.setattr(cli, "_chromium_already_installed", lambda: False)
    monkeypatch.setattr(cli, "_is_interactive", lambda: True)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake")
    monkeypatch.setattr(cli.subprocess, "run", _fake_run([]))
    started = []
    monkeypatch.setattr(cli, "wizard", _wizard_stand_in(started))

    result = CliRunner().invoke(main, ["setup"], input="y\n\n" + answer)

    assert result.exit_code == 0
    assert "Scan your first page with the wizard now? [Y/n]" in result.output
    assert started == ([False] if starts else [])


@pytest.mark.parametrize(("installed", "args"), [(True, ["setup"]), (False, ["setup", "--yes"])])
def test_setup_offers_the_wizard_only_after_the_first_download_at_a_terminal(monkeypatch, installed, args):
    monkeypatch.setattr(cli, "_chromium_already_installed", lambda: installed)
    monkeypatch.setattr(cli, "_is_interactive", lambda: True)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake")
    monkeypatch.setattr(cli.subprocess, "run", _fake_run([]))

    result = CliRunner().invoke(main, args, input="\n")

    assert result.exit_code == 0 and "wizard now?" not in result.output
