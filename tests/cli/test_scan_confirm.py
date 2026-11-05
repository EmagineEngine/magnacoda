"""Before a scan typed with only an address, with a person there: say the default settings and ask
(cli.scan_cmd, [scan] confirm in preferences.ini)."""

import dataclasses

from click.testing import CliRunner

from magnacoda import cli, history, plugins, preferences
from magnacoda.browser import redirects
from magnacoda.cli import main
from tests.cli.test_screen import _fake_run

QUESTION = "The default settings: WCAG 2.2 AA, a desktop screen, light and dark mode, no AI"


def _scan(monkeypatch, tmp_path, *args, answer="", person=True, shell=False):
    seen: list = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "run_scan", _fake_run(seen))
    monkeypatch.setattr(cli, "_is_interactive", lambda: person)
    monkeypatch.setattr(redirects, "check_address", lambda url, **kw: None)
    if shell:
        command = " ".join(["scan", "example.com", *args])
        result = CliRunner().invoke(main, ["shell"], input=f"{command}\n{answer}\nexit\n")
    else:
        result = CliRunner().invoke(main, ["scan", "example.com", *args], input=f"{answer}\n")
    return " ".join(result.output.split()), seen


def test_the_address_alone_says_the_defaults_and_enter_scans(monkeypatch, tmp_path):
    text, seen = _scan(monkeypatch, tmp_path)
    assert (
        QUESTION in text and "Scan with these settings? [Y/n]" in text and seen
    )  # light, then the dark pass


def test_no_scans_nothing_and_points_to_the_wizard_and_the_options(monkeypatch, tmp_path):
    text, seen = _scan(monkeypatch, tmp_path, answer="n")
    assert seen == [] and not list(tmp_path.glob("magnacoda-scans/*/results.json"))
    assert "Nothing was scanned." in text and "type magnacoda wizard" in text and "magnacoda help" in text
    inside, _ = _scan(monkeypatch, tmp_path, answer="n", shell=True)
    assert "type wizard; to see the options, type help (the scan section)." in inside


def test_quick_is_named_only_when_the_preferences_turn_it_on(monkeypatch, tmp_path):
    load = preferences.load  # tests/cli/conftest.py turns quick on for every test here
    for quick, ending in (
        (True, "no AI, quick (set in preferences.ini). Scan with these settings?"),
        (False, "no AI. Scan with these settings?"),
    ):
        monkeypatch.setattr(preferences, "load", lambda quick=quick: dataclasses.replace(load(), quick=quick))
        text, _ = _scan(monkeypatch, tmp_path)
        assert QUESTION + ending.removeprefix("no AI") in text


def test_nothing_is_asked_with_options_with_y_without_a_person_or_with_confirm_off(monkeypatch, tmp_path):
    for args, person in ((["--screen", "both"], True), (["-v"], True), (["-y"], True), ([], False)):
        text, seen = _scan(monkeypatch, tmp_path, *args, person=person)
        assert "Scan with these settings?" not in text and len(seen) >= 1, (args, person)
    path = preferences.preferences_path()
    path.write_text(path.read_text().replace("confirm = on", "confirm = off"))
    assert preferences.load().confirm is False
    text, seen = _scan(monkeypatch, tmp_path)
    assert "Scan with these settings?" not in text and seen


# A page scanned before: its saved settings are offered first (favorites from the add-on, if there,
# then the latest from history), the defaults last.


def _history(*lines: str) -> None:
    history.ensure_file()
    path = history.history_path()
    entries = "".join(f"- 2026-10-1{n} 09:00 `{line}`\n" for n, line in zip((7, 6, 5), lines, strict=False))
    path.write_text(history.HEADER + entries, encoding="utf-8")


def test_the_latest_scan_of_the_page_is_offered_and_enter_takes_it(monkeypatch, tmp_path):
    _history(
        "scan https://other.test --level AAA --ai off",
        "scan https://example.com/ --level AAA --ai off --screen mobile",
        "scan https://example.com --level AA --ai off --color-scheme dark",  # older: not offered
    )
    text, seen = _scan(monkeypatch, tmp_path, answer="\n")  # Enter, Enter: no changes
    assert (
        "example.com was scanned before. Scan it with: 1. as on Oct 16, 09:00: --level AAA --screen mobile"
        in text
    )
    assert "2. the default settings: WCAG 2.2 AA" in text and "--color-scheme" not in text
    assert "other.test" not in text
    assert "Scan with these settings?" not in text
    assert seen[0].level == "AAA" and seen[0].screen == "mobile"
    assert history.read()[0].command.startswith("scan https://example.com/ --level AAA")


def test_how_to_cancel_comes_before_the_first_question_and_q_cancels(monkeypatch, tmp_path):
    hint = "Ctrl+C or q cancels at any time."
    text, _ = _scan(monkeypatch, tmp_path, answer="n")
    assert text.index(hint) < text.index(QUESTION)
    _history("scan https://example.com --level AAA --ai off")
    text, seen = _scan(monkeypatch, tmp_path, answer="q")
    assert text.index(hint) < text.index("was scanned before") and "Cancelled" in text and seen == []


def test_choosing_the_defaults_scans_with_them(monkeypatch, tmp_path):
    _history("scan https://example.com --level AAA --ai off")
    text, seen = _scan(monkeypatch, tmp_path, answer="2")
    assert "1. as on" in text and seen[0].level == "AA"


def test_a_scan_with_the_default_settings_is_not_offered_again(monkeypatch, tmp_path):
    _history("scan https://example.com --level AA --ai off")
    text, _ = _scan(monkeypatch, tmp_path)
    assert "scanned before" not in text and "Scan with these settings?" in text


def test_an_add_ons_saved_scans_come_first_and_the_same_settings_are_listed_once(monkeypatch, tmp_path):
    favorite = "scan https://example.com --level AA --ai off --screen both"
    groups = [
        plugins.StartGroup("Favorites", [("client home", favorite), ("elsewhere", "scan https://b.test")])
    ]
    monkeypatch.setattr(plugins, "start_groups", lambda: groups)
    _history(favorite, "scan https://example.com --level AAA --ai off")
    text, seen = _scan(monkeypatch, tmp_path, answer="\n")
    # history's is the same as the favorite, so it isn't listed again
    assert "1. client home (Favorites): --screen both 2. the default settings" in text
    assert "elsewhere" not in text and [config.screen for config in seen][:2] == ["desktop", "mobile"]


def test_changing_a_saved_scan_asks_the_wizards_questions_with_its_settings_first(monkeypatch, tmp_path):
    _history("scan https://example.com --level AAA --ai off --screen mobile")
    load = preferences.load
    monkeypatch.setattr(preferences, "load", lambda: dataclasses.replace(load(), estimate=False))
    # 1, change: yes, level A, AI and screens as they were, run: yes
    text, seen = _scan(monkeypatch, tmp_path, answer="1\ny\nA\n\n\ny")
    assert "Change anything? [y/N]" in text and "WCAG level" in text and "Run this scan now?" in text
    assert seen[0].level == "A" and seen[0].screen == "mobile"


# scan alone: the address is asked for, with help for the scan section; scripts get the error.


def test_scan_alone_asks_for_the_address_and_goes_on_as_with_it(monkeypatch, tmp_path):
    seen: list = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "run_scan", _fake_run(seen))
    monkeypatch.setattr(cli, "_is_interactive", lambda: True)
    monkeypatch.setattr(redirects, "check_address", lambda url, **kw: None)
    monkeypatch.setenv("MAGNACODA_PAGER", "off")
    result = CliRunner().invoke(main, ["scan"], input="help\nexample.com\n\n")
    text = " ".join(result.output.split())
    prompt = "Page to scan (such as example.com), help for more, or press Enter to cancel:"
    assert prompt in text and "--screen" in text.split(prompt + " help", 1)[1]  # the scan section
    assert "Scan with these settings?" in text and seen[0].url == "https://example.com"
    assert history.read()[0].command.startswith("scan https://example.com")


def test_scan_alone_without_a_person_is_an_error():
    result = CliRunner().invoke(main, ["scan"])
    assert result.exit_code != 0 and "Missing argument 'URL'." in result.output


def test_enter_at_the_address_question_cancels(monkeypatch, tmp_path):
    seen: list = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "run_scan", _fake_run(seen))
    monkeypatch.setattr(cli, "_is_interactive", lambda: True)
    result = CliRunner().invoke(main, ["scan"], input="\n")
    assert result.exit_code == 130 and seen == []  # cancelled, as Ctrl+C
