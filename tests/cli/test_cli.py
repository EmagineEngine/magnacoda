import io
import os

import click
import pytest
from click.testing import CliRunner

from magnacoda import cli
from magnacoda.cli import main


def test_help_lists_commands():
    result = CliRunner().invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "scan" in result.output
    assert "setup" in result.output


def test_version():
    result = CliRunner().invoke(main, ["--version"])
    assert result.exit_code == 0


def test_an_unknown_option_gets_one_clean_line():
    for removed in ("--fixes", "--checklist", "--save", "--no-color"):
        result = CliRunner().invoke(main, ["scan", "http://example.test", removed])
        assert result.exit_code == 2
        assert result.output.strip() == (
            f"Error: scan has no option {removed}. "
            "To see its options, type magnacoda help (the scan section)."
        )


class _Terminal(io.StringIO):
    def isatty(self):
        return True


@pytest.mark.parametrize("args", [["1"], ["help", "no-such-section"]])
def test_a_long_error_wraps_between_words_at_the_terminal(args, monkeypatch):
    from magnacoda import wrapping

    monkeypatch.setattr(wrapping.shutil, "get_terminal_size", lambda fallback: os.terminal_size((40, 24)))
    with pytest.raises(click.ClickException) as raised:
        main.main(args, standalone_mode=False)
    terminal = _Terminal()
    raised.value.show(terminal)
    lines = terminal.getvalue().splitlines()
    assert len(lines) > 1 and all(len(line) < 40 for line in lines)
    assert " ".join(lines) == f"Error: {raised.value.format_message()}"


@pytest.mark.parametrize("option", [["--viewport", "notanumber"], ["--cookie", "not-a-kv-pair"]])
def test_a_badly_written_option_value_is_refused(option):
    assert CliRunner().invoke(main, ["scan", "http://example.test", *option]).exit_code != 0


def test_light_and_dark_ask_for_ai_consent_once_and_scan_fully_once(monkeypatch):
    from magnacoda import cli
    from magnacoda.findings.models import ScanMeta, ScanReport

    consent_calls: list[int] = []
    scanned: list[str | None] = []

    def fake_confirm(ai, passes=1):
        consent_calls.append(passes)

    def fake_run_scan(config, *, consent_given=False):
        assert consent_given
        scanned.append(config.color_scheme)
        meta = ScanMeta(
            tool_version="0",
            axe_core_version="0",
            wcag_version="2.2",
            wcag_level="AA",
            ai_tier="explain",
            fixes_tier="template",
            color_scheme=config.color_scheme,
            stability_settled=True,
            stability_elapsed_ms=0,
            stability_reason="quiescent",
        )
        return ScanReport(url=config.url, meta=meta, findings=[])

    monkeypatch.setattr(cli, "confirm_ai_usage", fake_confirm)
    monkeypatch.setattr(cli, "run_scan", fake_run_scan)

    for scheme in ([], ["--color-scheme", "both"]):  # both is the default
        result = CliRunner().invoke(main, ["scan", "http://example.test", *scheme, "--ai", "explain"])
        assert result.exit_code == 0
    assert consent_calls == [1, 1]
    assert scanned == ["light", "light"]  # dark mode is a short pass after it, without AI


def test_an_option_first_says_options_come_after_a_command():
    for args in (["--level", "Z", "http://example.test"], ["--ai", "bogus"]):
        result = CliRunner().invoke(main, args)
        assert result.exit_code == 2 and "Usage:" not in result.output
        assert "magnacoda scan ADDRESS" in " ".join(result.output.split())  # shows where options go


def test_a_first_word_that_isnt_a_command_says_what_to_type_instead(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "LICENSE.md").write_text("terms")
    (tmp_path / "NOTICE").write_text("credits")
    cases = {
        "example.com": "example.com isn't a command. To scan it, type magnacoda scan example.com.",
        "localhost:3000": "To scan it, type magnacoda scan localhost:3000.",
        "NOTICE.md": "To scan it, type magnacoda scan NOTICE.md. There's a file named NOTICE here: "
        "to read it, type magnacoda view NOTICE.",
        "LICENSE.md": "To read the file, type magnacoda view LICENSE.md; to scan a website by that name, "
        "type magnacoda scan LICENSE.md.",
        "reveiw": "reveiw isn't a magnacoda command. Did you mean review? To see the commands, type "
        "magnacoda help; to scan a site by that name, type magnacoda scan reveiw.",
    }
    for word, message in cases.items():
        result = CliRunner().invoke(main, [word])
        assert result.exit_code == 2 and message in " ".join(result.output.split()), word
    inside = " ".join(CliRunner().invoke(main, ["shell"], input="example.com\nexit\n").output.split())
    assert "To scan it, type scan example.com." in inside


def test_output_without_a_filename_is_an_error():
    result = CliRunner().invoke(main, ["scan", "http://example.test", "-o"])
    assert result.exit_code == 2 and "requires an argument" in result.output


def test_unwritable_output_path_fails_cleanly_before_scanning(tmp_path):
    blocker = tmp_path / "a-file"
    blocker.write_text("x")
    result = CliRunner().invoke(main, ["scan", "http://example.test", "-o", str(blocker / "out.json")])
    assert result.exit_code == 2
    assert "Cannot write to" in result.output and "Traceback" not in result.output


def test_output_path_that_is_a_directory_is_rejected(tmp_path):
    result = CliRunner().invoke(main, ["scan", "http://example.test", "-o", str(tmp_path)])
    assert result.exit_code == 2 and "is a directory" in result.output


def test_commands_have_no_dashdash_help_of_their_own():
    for command in ("scan", "setup", "about"):
        args = [command, "--help"]
        result = CliRunner().invoke(main, args)
        assert result.exit_code == 2, args
        assert "`magnacoda help`" in result.output  # points to the one help
    inside = CliRunner().invoke(main, ["shell"], input="scan --help\nexit\n").output
    assert "For help, type `help`." in inside


def test_top_level_flag_is_exempt_from_the_default_group_reroute():
    # a flag registered on the group itself must not be shoved into `scan` as if it were the URL
    result = CliRunner().invoke(main, ["--force-setup-notice"], input="exit\n")
    assert "No such option" not in result.output
    assert "Missing argument" not in result.output


# What was typed as the address, and the http fallback (addresses.py, scan_cmd)


def _scans(monkeypatch, fail_https=False):
    from magnacoda.exceptions import NavigationError
    from tests.cli.test_screen import _fake_run

    seen: list = []
    record = _fake_run(seen)

    def run(config, *, consent_given=False):
        if fail_https and config.url.startswith("https://"):
            seen.append(config)
            raise NavigationError("Could not load it: connection refused", could_not_connect=True)
        return record(config, consent_given=consent_given)

    monkeypatch.setattr(cli, "run_scan", run)
    return seen


def test_a_typed_web_address_gets_https_and_says_so(monkeypatch):
    from magnacoda import history

    seen = _scans(monkeypatch)
    result = CliRunner().invoke(main, ["scan", "example.com", "--fail-on", "none"])
    assert result.exit_code == 0 and seen[0].url == "https://example.com"
    assert "Scanning https://example.com" in result.output
    assert "https://example.com" in history.read()[0].command  # the full address is remembered


def test_https_that_was_added_falls_back_to_http_once(monkeypatch):
    seen = _scans(monkeypatch, fail_https=True)
    result = CliRunner().invoke(main, ["scan", "example.com", "--fail-on", "none", "--screen", "both"])
    assert result.exit_code == 0
    assert "https://example.com didn't answer over https; trying http://example.com" in result.output
    assert [c.url for c in seen] == ["https://example.com", "http://example.com", "http://example.com"]


@pytest.mark.parametrize(
    "extra",
    [["--cookie", "sid=1"], ["--extra-http-header", "Authorization=Bearer x"]],
)
def test_no_fallback_with_cookies_or_headers_which_would_go_unencrypted(monkeypatch, extra):
    seen = _scans(monkeypatch, fail_https=True)
    result = CliRunner().invoke(main, ["scan", "example.com", "--fail-on", "none", *extra])
    assert result.exit_code == 2 and "trying http" not in result.output and len(seen) == 1


def test_no_fallback_when_https_was_typed(monkeypatch):
    seen = _scans(monkeypatch, fail_https=True)
    result = CliRunner().invoke(main, ["scan", "https://example.com", "--fail-on", "none"])
    assert result.exit_code == 2 and len(seen) == 1 and "Scanning" not in result.output


def test_a_one_word_name_in_the_hosts_file_is_scanned_over_http(monkeypatch):
    from magnacoda import addresses

    monkeypatch.setattr(addresses, "resolves", lambda host, timeout=0: host == "mysite")
    seen = _scans(monkeypatch)
    assert CliRunner().invoke(main, ["scan", "mysite", "--fail-on", "none"]).exit_code == 0
    assert seen[0].url == "http://mysite"
    result = CliRunner().invoke(main, ["scan", "mysitee"])
    assert result.exit_code == 2 and "type its full address, such as http://mysitee" in result.output


def test_a_bare_number_typed_in_the_shell_explains_itself_instead_of_scanning(monkeypatch):
    seen = _scans(monkeypatch)
    output = CliRunner().invoke(main, ["shell"], input="1\nexit\n").output
    assert "1 isn't a command. To run a favorite" in output and seen == []
    typed = CliRunner().invoke(main, ["shell"], input="scan 1\nexit\n").output
    assert "'1' isn't a web address. To run a favorite" in typed and seen == []


def test_playwrights_internal_asyncio_reports_are_switched_off():
    import logging

    from magnacoda.browser import launcher  # noqa: F401 - importing it switches them off

    assert logging.getLogger("asyncio").level == logging.CRITICAL
