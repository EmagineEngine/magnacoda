"""AI engines behind one interface: the Anthropic SDK ("api") or `claude -p` ("claude-code").

Both offer `messages.parse(...)` returning `.parsed_output`, which is all explain.py and semantic.py use.
This is the only module that imports `anthropic`.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from pydantic import BaseModel, ValidationError

from magnacoda.config import AIConfig
from magnacoda.exceptions import AIAuthenticationError, AIConfigError

CLAUDE_CODE_TIMEOUT_S = 600
# Claude Code answers "not logged in" and similar failures with messages like these.
_AUTH_HINTS = ("/login", "not logged in", "invalid api key", "authentication", "unauthorized", "oauth")


def build_client(config: AIConfig) -> Any:
    """The client for the engine this config resolves to."""
    if config.resolve_engine() == "claude-code":
        return ClaudeCodeClient()
    api_key = config.resolve_api_key()
    if not api_key and config.claude_plan_undecided():
        raise AIConfigError(
            f"--ai={config.tier} needs to know which account to use: your Claude plan (through Claude "
            "Code) or an Anthropic API key. Run `magnacoda setup` to choose, or add --ai-engine "
            "claude-code (your Claude plan) or --ai-engine api to this scan."
        )
    if not api_key:
        raise AIConfigError(
            f"--ai={config.tier} needs either an Anthropic API key (in ${config.api_key_env}, or saved "
            "with `magnacoda setup`) or Claude Code installed and logged in (`--ai-engine claude-code`, "
            "which uses your Claude subscription)."
        )
    try:
        import anthropic  # imported here, not at the top, so magnacoda starts quickly without AI
    except ImportError as exc:  # it comes with magnacoda, so only a damaged install lacks it
        raise AIConfigError(
            "The Anthropic library that magnacoda needs for --ai-engine api is missing; reinstall "
            "magnacoda (or use --ai-engine claude-code)."
        ) from exc
    return anthropic.Anthropic(api_key=api_key)


def is_authentication_error(exc: BaseException) -> bool:
    """Whether `exc` is the SDK's AuthenticationError (here so callers needn't import anthropic)."""
    try:
        import anthropic
    except ImportError:
        return False
    return isinstance(exc, anthropic.AuthenticationError)


class ClaudeCodeClient:
    """Runs each request through `claude -p` on the user's Claude Code login.

    Prompt on stdin and system prompt in a file (no command-line limits), UTF-8 everywhere. Runs from an
    empty temp folder with no tools, no session and hooks off, so it can't touch the user's files.
    """

    def __init__(self) -> None:
        self.messages = SimpleNamespace(parse=self._parse)

    def _parse(
        self,
        *,
        model: str,
        max_tokens: int,  # accepted for interface compatibility; Claude Code sets its own limit
        system: str,
        messages: list[dict[str, Any]],
        output_format: type[BaseModel],
    ) -> SimpleNamespace:
        executable = shutil.which("claude")
        if executable is None:
            raise AIConfigError(
                "Claude Code (`claude`) is not installed or not on the PATH. Install it from "
                "https://claude.com/claude-code and log in once, or use an API key (--ai-engine api)."
            )
        prompt = "\n\n".join(str(m["content"]) for m in messages if m.get("role") == "user")
        schema = json.dumps(output_format.model_json_schema())
        # An npm-installed claude.cmd/.bat on Windows goes through cmd.exe, which treats quotes
        # specially: keep the schema off its command line and validate the text answer instead.
        via_shell_script = Path(executable).suffix.lower() in (".cmd", ".bat")

        with tempfile.TemporaryDirectory(prefix="magnacoda-ai-") as folder:
            system_file = Path(folder) / "system.txt"
            settings_file = Path(folder) / "settings.json"
            system_text = system
            if via_shell_script:
                system_text += (
                    "\n\nAnswer with only a JSON object that matches this JSON Schema, with no other "
                    f"text:\n{schema}"
                )
            system_file.write_text(system_text, encoding="utf-8")
            settings_file.write_text(json.dumps({"disableAllHooks": True}), encoding="utf-8")
            command = [
                executable,
                "-p",
                "--output-format", "json",
                "--system-prompt-file", str(system_file),
                "--settings", str(settings_file),
                "--tools", "",
                "--no-session-persistence",
                "--model", model,
            ]  # fmt: skip
            if not via_shell_script:
                command += ["--json-schema", schema]
            try:
                done = subprocess.run(
                    command,
                    input=prompt,
                    cwd=folder,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=CLAUDE_CODE_TIMEOUT_S,
                )
            except subprocess.TimeoutExpired as exc:
                raise AIConfigError(
                    f"Claude Code did not answer within {CLAUDE_CODE_TIMEOUT_S // 60} minutes."
                ) from exc
            except OSError as exc:
                raise AIConfigError(f"Could not start Claude Code: {exc}") from exc

        try:
            result = json.loads(done.stdout)
        except ValueError:
            detail = (done.stderr or done.stdout).strip()
            _raise_for_message(detail, done.returncode)
            raise AIConfigError(  # _raise_for_message only raises for auth problems
                f"Claude Code did not return a usable answer (exit {done.returncode}): {detail[:300]}"
            ) from None
        if result.get("is_error"):
            _raise_for_message(str(result.get("result", "")), done.returncode)
            raise AIConfigError(f"Claude Code reported an error: {str(result.get('result', ''))[:300]}")

        try:
            if result.get("structured_output") is not None:
                parsed = output_format.model_validate(result["structured_output"])
            else:
                parsed = output_format.model_validate_json(_json_part(str(result.get("result", ""))))
        except (ValidationError, ValueError) as exc:
            raise AIConfigError(f"Claude Code's answer did not match the expected format: {exc}") from exc
        return SimpleNamespace(parsed_output=parsed)


def _raise_for_message(message: str, returncode: int) -> None:
    if any(hint in message.lower() for hint in _AUTH_HINTS):
        raise AIAuthenticationError(
            "Claude Code is not logged in (or its login has expired). Run `claude` once and use "
            f"/login, then scan again. (Claude Code said: {message.strip()[:200]})"
        )


def _json_part(text: str) -> str:
    """The JSON object inside a text answer (tolerates a code fence or a sentence around it)."""
    start, end = text.find("{"), text.rfind("}")
    return text[start : end + 1] if start != -1 and end > start else text
