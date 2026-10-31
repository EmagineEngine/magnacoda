from click.testing import CliRunner

from magnacoda import cli, credentials, userdir
from magnacoda.cli import main
from magnacoda.exceptions import AIAuthenticationError


def _use_tmp_config(monkeypatch, tmp_path):
    monkeypatch.setattr(userdir.sys, "platform", "linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


def test_setup_forget_key_with_nothing_stored(monkeypatch, tmp_path):
    _use_tmp_config(monkeypatch, tmp_path)

    result = CliRunner().invoke(main, ["setup", "--forget-key"])

    assert result.exit_code == 0
    assert "No saved Anthropic API key to remove." in result.output


def test_setup_forget_key_removes_a_stored_key_and_skips_chromium_check(monkeypatch, tmp_path):
    _use_tmp_config(monkeypatch, tmp_path)
    credentials.save_key("ANTHROPIC_API_KEY", "sk-ant-abc")
    monkeypatch.setattr(cli, "_chromium_already_installed", lambda: (_ for _ in ()).throw(AssertionError))

    result = CliRunner().invoke(main, ["setup", "--forget-key"])

    assert result.exit_code == 0
    assert "Removed the saved Anthropic API key." in result.output
    assert credentials.load_stored_key("ANTHROPIC_API_KEY") is None


def test_setup_reports_a_stored_key_and_mentions_forget_key(monkeypatch, tmp_path):
    _use_tmp_config(monkeypatch, tmp_path)
    credentials.save_key("ANTHROPIC_API_KEY", "sk-ant-abc")
    monkeypatch.setattr(cli, "_chromium_already_installed", lambda: True)

    result = CliRunner().invoke(main, ["setup"])

    assert result.exit_code == 0
    assert "Ready, with your Anthropic API key (saved in" in result.output
    assert "--forget-key" in result.output


def test_setup_prompts_and_saves_a_key_when_interactive_and_confirmed(monkeypatch, tmp_path):
    _use_tmp_config(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_chromium_already_installed", lambda: True)
    monkeypatch.setattr(cli, "_is_interactive", lambda: True)

    result = CliRunner().invoke(main, ["setup"], input="\ny\nsk-ant-typed-in\n")

    assert result.exit_code == 0
    assert "Paste your Anthropic API key" in result.output
    assert "Saved to" in result.output
    assert credentials.load_stored_key("ANTHROPIC_API_KEY") == "sk-ant-typed-in"


def test_setup_prompt_declined_falls_back_to_manual_instructions(monkeypatch, tmp_path):
    _use_tmp_config(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_chromium_already_installed", lambda: True)
    monkeypatch.setattr(cli, "_is_interactive", lambda: True)

    result = CliRunner().invoke(main, ["setup"], input="\nn\n")

    assert result.exit_code == 0
    assert "Paste your Anthropic API key" not in result.output
    assert "export ANTHROPIC_API_KEY=" in result.output
    assert credentials.load_stored_key("ANTHROPIC_API_KEY") is None


def test_setup_prompt_with_empty_input_saves_nothing(monkeypatch, tmp_path):
    _use_tmp_config(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_chromium_already_installed", lambda: True)
    monkeypatch.setattr(cli, "_is_interactive", lambda: True)

    result = CliRunner().invoke(main, ["setup"], input="\ny\n\n")

    assert result.exit_code == 0
    assert "No key entered - nothing saved." in result.output
    assert credentials.load_stored_key("ANTHROPIC_API_KEY") is None


def test_setup_non_interactive_never_prompts_for_a_key(monkeypatch, tmp_path):
    _use_tmp_config(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_chromium_already_installed", lambda: True)
    monkeypatch.setattr(cli, "_is_interactive", lambda: False)

    result = CliRunner().invoke(main, ["setup"])

    assert result.exit_code == 0
    assert "Paste your Anthropic API key" not in result.output
    assert "export ANTHROPIC_API_KEY=" in result.output


def test_scan_auth_error_interactive_confirmed_saves_key_and_suggests_rerun(monkeypatch, tmp_path):
    _use_tmp_config(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_is_interactive", lambda: True)

    def fake_run_scan(config, *, consent_given=False):
        raise AIAuthenticationError("The Anthropic API rejected the configured key.")

    monkeypatch.setattr(cli, "run_scan", fake_run_scan)

    result = CliRunner().invoke(
        main,
        ["scan", "http://example.test", "--ai", "explain", "--yes"],
        input="y\nsk-ant-replacement\n",
    )

    assert result.exit_code == 2
    assert "rejected the configured key" in result.output
    assert "Saved. Re-run your scan to try again." in result.output
    assert credentials.load_stored_key("ANTHROPIC_API_KEY") == "sk-ant-replacement"


def test_scan_auth_error_interactive_declined_shows_manual_instructions(monkeypatch, tmp_path):
    _use_tmp_config(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_is_interactive", lambda: True)

    def fake_run_scan(config, *, consent_given=False):
        raise AIAuthenticationError("The Anthropic API rejected the configured key.")

    monkeypatch.setattr(cli, "run_scan", fake_run_scan)

    result = CliRunner().invoke(
        main, ["scan", "http://example.test", "--ai", "explain", "--yes"], input="n\n"
    )

    assert result.exit_code == 2
    assert "magnacoda setup" in result.output
    assert "export ANTHROPIC_API_KEY=" in result.output
    assert credentials.load_stored_key("ANTHROPIC_API_KEY") is None


def test_scan_auth_error_non_interactive_shows_manual_instructions_without_hanging(monkeypatch, tmp_path):
    _use_tmp_config(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_is_interactive", lambda: False)

    def fake_run_scan(config, *, consent_given=False):
        raise AIAuthenticationError("The Anthropic API rejected the configured key.")

    monkeypatch.setattr(cli, "run_scan", fake_run_scan)

    result = CliRunner().invoke(main, ["scan", "http://example.test", "--ai", "explain", "--yes"])

    assert result.exit_code == 2
    assert "magnacoda setup" in result.output
    assert "export ANTHROPIC_API_KEY=" in result.output


def test_setup_message_wraps_at_word_boundaries_on_a_narrow_terminal(monkeypatch, tmp_path):
    from magnacoda import wrapping

    _use_tmp_config(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_chromium_already_installed", lambda: True)
    monkeypatch.setattr(cli, "_is_interactive", lambda: False)
    monkeypatch.setattr(cli, "wrap_for_stream", lambda text, stream: wrapping.wrap_text(text, 40))

    result = CliRunner().invoke(main, ["setup"])

    lines = [ln for ln in result.output.splitlines() if not ln.lstrip().startswith("export ")]
    assert max(len(ln) for ln in lines) <= 40
    assert "platform.claude.com/settings/keys" in result.output
