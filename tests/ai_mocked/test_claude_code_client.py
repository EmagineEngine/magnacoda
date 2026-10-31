"""The Claude Code engine (ai/client.py), with `claude` faked: no subscription or network used."""

import json
import subprocess
from types import SimpleNamespace

import pytest

from magnacoda import preferences
from magnacoda.ai import client as ai_client
from magnacoda.ai.client import ClaudeCodeClient, build_client
from magnacoda.ai.prompts import ExplanationBatch
from magnacoda.config import AIConfig
from magnacoda.consent import confirm_ai_usage
from magnacoda.exceptions import AIAuthenticationError, AIConfigError

ANSWER = {"explanations": [{"finding_id": "f1", "why_it_matters": "w", "how_to_fix": "h"}]}


@pytest.fixture
def fake_claude(monkeypatch):
    """Install a fake `claude` at the given path; record every call. Returns the list of calls."""
    calls: list[dict] = []

    def install(path="/usr/local/bin/claude", stdout=None, returncode=0, raises=None, stderr=""):
        monkeypatch.setattr(ai_client.shutil, "which", lambda name: path)

        def run(command, **kwargs):
            folder = kwargs["cwd"]
            calls.append(
                {
                    "command": command,
                    "kwargs": kwargs,
                    "system": open(f"{folder}/system.txt", encoding="utf-8").read(),
                    "settings": json.loads(open(f"{folder}/settings.json", encoding="utf-8").read()),
                }
            )
            if raises:
                raise raises
            out = (
                stdout if stdout is not None else json.dumps({"is_error": False, "structured_output": ANSWER})
            )
            return SimpleNamespace(stdout=out, stderr=stderr, returncode=returncode)

        monkeypatch.setattr(ai_client.subprocess, "run", run)
        return calls

    return install


def _ask():
    return ClaudeCodeClient().messages.parse(
        model="claude-sonnet-5",
        max_tokens=4096,
        system="You explain findings.",
        messages=[{"role": "user", "content": "Explain these: ünïcode ✓"}],
        output_format=ExplanationBatch,
    )


def test_the_answer_is_parsed_into_the_pydantic_model(fake_claude):
    fake_claude()
    parsed = _ask().parsed_output
    assert isinstance(parsed, ExplanationBatch)
    assert parsed.explanations[0].finding_id == "f1"


def test_the_command_uses_stdin_files_no_tools_and_utf8(fake_claude):
    calls = fake_claude()
    _ask()
    call = calls[0]
    command, kwargs = call["command"], call["kwargs"]
    assert command[0] == "/usr/local/bin/claude" and "-p" in command
    assert command[command.index("--output-format") + 1] == "json"
    assert command[command.index("--tools") + 1] == ""
    assert command[command.index("--model") + 1] == "claude-sonnet-5"
    assert "--no-session-persistence" in command
    assert json.loads(command[command.index("--json-schema") + 1])["title"] == "ExplanationBatch"
    assert kwargs["input"] == "Explain these: ünïcode ✓"  # the prompt goes on standard input
    assert kwargs["encoding"] == "utf-8"
    assert "Explain these" not in " ".join(command)  # never on the command line
    assert call["system"] == "You explain findings."
    assert call["settings"] == {"disableAllHooks": True}
    assert kwargs["cwd"] != ""  # an empty temporary folder, not the user's current one


def test_a_windows_cmd_shim_gets_the_schema_in_the_system_prompt_and_a_text_answer(fake_claude):
    text = "Here it is:\n```json\n" + json.dumps(ANSWER) + "\n```"
    calls = fake_claude(
        path=r"C:\Users\me\AppData\Roaming\npm\claude.CMD",
        stdout=json.dumps({"is_error": False, "result": text}),
    )
    parsed = _ask().parsed_output
    assert parsed.explanations[0].how_to_fix == "h"
    assert "--json-schema" not in calls[0]["command"]
    assert "JSON Schema" in calls[0]["system"] and "ExplanationBatch" in calls[0]["system"]


def test_claude_code_not_installed_is_a_clear_error(monkeypatch):
    monkeypatch.setattr(ai_client.shutil, "which", lambda name: None)
    with pytest.raises(AIConfigError, match="not installed"):
        _ask()


def test_not_logged_in_becomes_an_authentication_error(fake_claude):
    fake_claude(
        stdout=json.dumps({"is_error": True, "result": "Invalid API key · Please run /login"}), returncode=1
    )
    with pytest.raises(AIAuthenticationError, match="/login"):
        _ask()


def test_other_reported_errors_are_config_errors(fake_claude):
    fake_claude(stdout=json.dumps({"is_error": True, "result": "Overloaded, try later"}))
    with pytest.raises(AIConfigError, match="Overloaded"):
        _ask()


def test_unreadable_output_is_a_config_error(fake_claude):
    fake_claude(stdout="not json at all", returncode=2, stderr="something broke")
    with pytest.raises(AIConfigError, match="something broke"):
        _ask()


def test_a_timeout_is_a_config_error(fake_claude):
    fake_claude(raises=subprocess.TimeoutExpired(cmd="claude", timeout=600))
    with pytest.raises(AIConfigError, match="did not answer"):
        _ask()


def test_an_answer_in_the_wrong_shape_is_a_config_error(fake_claude):
    fake_claude(stdout=json.dumps({"is_error": False, "structured_output": {"unexpected": 1}}))
    with pytest.raises(AIConfigError, match="expected format"):
        _ask()


# Choosing the engine


def _config(monkeypatch, *, key: str | None, claude: bool, engine="auto") -> AIConfig:
    if key:
        monkeypatch.setenv("ANTHROPIC_API_KEY", key)
    else:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    import magnacoda.config as config_module

    monkeypatch.setattr(config_module.shutil, "which", lambda name: "/usr/bin/claude" if claude else None)
    return AIConfig(tier="explain", engine=engine)


def test_auto_prefers_an_api_key(monkeypatch):
    assert _config(monkeypatch, key="sk-ant-x", claude=True).resolve_engine() == "api"


def test_auto_never_uses_the_claude_plan_until_the_user_has_chosen_it(monkeypatch):
    config = _config(monkeypatch, key=None, claude=True)
    assert config.claude_plan_undecided() and config.resolve_engine() == "api"
    with pytest.raises(AIConfigError, match="needs to know which account to use"):
        build_client(config)
    preferences.set_ai_engine("claude-code")
    assert not config.claude_plan_undecided() and config.resolve_engine() == "claude-code"


def test_auto_follows_the_saved_choice_even_with_a_key(monkeypatch):
    config = _config(monkeypatch, key="sk-ant-x", claude=True)
    preferences.set_ai_engine("claude-code")
    assert config.resolve_engine() == "claude-code"
    preferences.set_ai_engine("api")
    assert config.resolve_engine() == "api"


def test_auto_with_neither_falls_back_to_the_api_whose_error_explains_both(monkeypatch):
    config = _config(monkeypatch, key=None, claude=False)
    assert config.resolve_engine() == "api"
    with pytest.raises(AIConfigError, match="Claude Code"):
        build_client(config)


def test_an_explicit_engine_wins(monkeypatch):
    assert (
        _config(monkeypatch, key="sk-ant-x", claude=True, engine="claude-code").resolve_engine()
        == "claude-code"
    )
    assert _config(monkeypatch, key=None, claude=True, engine="api").resolve_engine() == "api"


def test_build_client_returns_the_claude_code_client(monkeypatch):
    preferences.set_ai_engine("claude-code")
    assert isinstance(build_client(_config(monkeypatch, key=None, claude=True)), ClaudeCodeClient)


# What the consent banner says


def test_consent_names_the_claude_plan_for_the_claude_code_engine(monkeypatch, capsys):
    config = _config(monkeypatch, key=None, claude=True, engine="claude-code")
    config.assume_yes = True
    confirm_ai_usage(config)
    text = capsys.readouterr().err
    assert "Claude Code login" in text and "Claude plan's terms and data settings" in text
    assert "API key" not in text


def test_consent_names_the_api_key_for_the_api_engine(monkeypatch, capsys):
    config = _config(monkeypatch, key="sk-ant-x", claude=True)
    config.assume_yes = True
    confirm_ai_usage(config)
    text = capsys.readouterr().err
    assert "Anthropic's API" in text and "$ANTHROPIC_API_KEY" in text


def test_scan_passes_ai_engine_through(monkeypatch):
    from click.testing import CliRunner

    from magnacoda import cli
    from tests.cli.test_screen import _fake_run

    seen: list = []
    monkeypatch.setattr(cli, "run_scan", _fake_run(seen))
    monkeypatch.setattr(cli, "confirm_ai_usage", lambda ai, passes=1: None)
    result = CliRunner().invoke(
        cli.main,
        ["scan", "https://a.test", "--ai", "explain", "--ai-engine", "claude-code", "--fail-on", "none"],
    )
    assert result.exit_code == 0, result.output
    assert seen[0].ai.engine == "claude-code"
