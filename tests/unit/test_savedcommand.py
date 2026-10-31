import shlex

from magnacoda import savedcommand
from magnacoda.savedcommand import SavedScan


def _takes_value(flag: str) -> bool:
    return flag in {"--browser", "--cookie", "--timeout"}


def test_every_wizard_field_round_trips():
    scan = SavedScan(
        url="https://example.com/",
        level="AAA",
        ai="semantic",
        color_scheme="dark",
        screen="mobile",
        fail_on="critical",
    )
    parsed = savedcommand.parse(savedcommand.to_command(scan))
    assert parsed is not None
    for field in (
        "url",
        "level",
        "ai",
        "color_scheme",
        "screen",
        "fail_on",
    ):
        assert getattr(parsed, field) == getattr(scan, field)


def test_stored_commands_start_with_scan_and_leave_out_system_choices():
    command = savedcommand.to_command(SavedScan(url="https://example.com/"))
    assert command.startswith("scan https://example.com/ ")
    assert "--color-scheme" not in command and "--screen" not in command and "--save" not in command


def test_urls_with_ampersands_are_quoted_so_they_paste_safely():
    command = savedcommand.to_command(SavedScan(url="https://example.com/?a=1&b=2"))
    assert shlex.split(command)[1] == "https://example.com/?a=1&b=2"
    assert "'https://example.com/?a=1&b=2'" in command


def test_a_leading_program_name_or_scan_is_accepted_in_any_case():
    for prefix in ("magnacoda", "MagnaCoda", "scan", "Scan", "magnacoda scan"):
        parsed = savedcommand.parse(f"{prefix} https://example.com --level A")
        assert parsed is not None and parsed.url == "https://example.com" and parsed.level == "A"


def test_options_the_wizard_has_no_question_for_are_kept_with_their_values():
    parsed = savedcommand.parse(
        "scan https://example.com --browser firefox --timeout=30 --verbose", takes_value=_takes_value
    )
    assert parsed is not None
    assert parsed.extras == ["--browser", "firefox", "--timeout=30", "--verbose"]
    assert savedcommand.to_tokens(parsed)[-4:] == parsed.extras


def test_invalid_values_are_ignored_with_a_note():
    parsed = savedcommand.parse("scan https://example.com --level ZZ --fail-on")
    assert parsed is not None
    assert parsed.level == "AA"
    assert len(parsed.notes) == 2


def test_unreadable_or_url_less_commands_give_none():
    assert savedcommand.parse("") is None
    assert savedcommand.parse("scan") is None
    assert savedcommand.parse("scan --level AA") is None
    assert savedcommand.parse("scan 'unbalanced") is None


def test_redact_hides_cookie_and_header_values_but_keeps_names():
    tokens = [
        "scan",
        "https://x.test",
        "--cookie",
        "sid=abc123",
        "--extra-http-header=Authorization=Bearer t",
    ]
    out = savedcommand.redact(tokens)
    assert out == [
        "scan",
        "https://x.test",
        "--cookie",
        "sid=<redacted>",
        "--extra-http-header=Authorization=<redacted>",
    ]
    assert "abc123" not in " ".join(out) and "Bearer" not in " ".join(out)


def test_to_command_never_contains_secret_extras():
    scan = SavedScan(url="https://x.test", extras=["--cookie", "sid=secret"])
    assert "secret" not in savedcommand.to_command(scan)


def test_redacted_values_are_dropped_when_read_back_with_a_note():
    parsed = savedcommand.parse("scan https://x.test --cookie sid=<redacted> --level A")
    assert parsed is not None
    assert parsed.extras == [] and parsed.level == "A"
    assert any("--cookie" in note for note in parsed.notes)


def test_a_real_cookie_typed_into_a_hand_edited_command_is_kept_as_an_extra():
    parsed = savedcommand.parse("scan https://x.test --cookie sid=abc")
    assert parsed is not None and parsed.extras == ["--cookie", "sid=abc"]


def test_canonical_treats_differently_typed_commands_as_the_same():
    a = savedcommand.canonical("magnacoda https://x.test --level AA")
    b = savedcommand.canonical("scan https://x.test --ai off --level AA")
    assert a == b


def test_display_command_shows_the_program_name_and_scan():
    text = savedcommand.display_command(SavedScan(url="https://x.test"))
    assert text.startswith("magnacoda scan https://x.test --level AA")


def test_options_magnacoda_no_longer_has_are_stripped_from_saved_commands_with_their_values():
    old = (
        "scan https://a.test --save --format json --checklist out.md --force --hide-passed --no-color "
        "--api-key-env MY_KEY --fixes=ai --quiet-period-ms 100 --nav-timeout-ms 60000 "
        "--level A --browser firefox"
    )
    scan = savedcommand.parse(old)
    assert scan is not None and scan.url == "https://a.test" and scan.level == "A"
    assert scan.extras == ["--browser", "firefox"] and scan.notes == []  # quietly: they're simply gone
    assert savedcommand.to_command(scan) == "scan https://a.test --level A --ai off --browser firefox"
