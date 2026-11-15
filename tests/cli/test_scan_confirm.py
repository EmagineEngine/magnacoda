"""A scan typed with only an address, or none, with a person there: the defaults are said and the
options asked for before anything runs (cli.scan_cmd, [scan] confirm in preferences.ini)."""

import dataclasses

from click.testing import CliRunner

from magnacoda import cli, history, plugins, preferences
from magnacoda.browser import redirects
from magnacoda.cli import main
from tests.cli.test_screen import _fake_run

DEFAULTS = "The defaults: WCAG 2.2 AA, a desktop screen, light and dark mode, no AI"


def _scan(monkeypatch, tmp_path, *args, answer="defaults", person=True):
    seen: list = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "run_scan", _fake_run(seen))
    monkeypatch.setattr(cli, "_is_interactive", lambda: person)
    monkeypatch.setattr(redirects, "check_address", lambda url, **kw: None)
    result = CliRunner().invoke(main, ["scan", "example.com", *args], input=f"{answer}\n")
    return " ".join(result.output.split()), seen


def test_the_address_alone_says_the_defaults_and_asks_for_options(monkeypatch, tmp_path):
    text, seen = _scan(monkeypatch, tmp_path)
    assert DEFAULTS in text and "options (such as --option), defaults, help. Enter cancels." in text
    assert seen and seen[0].level == "AA"
    text, seen = _scan(monkeypatch, tmp_path, answer="--level AAA --screen mobile")
    assert seen[0].level == "AAA" and seen[0].screen == "mobile"
    assert "--screen mobile" in history.read()[0].command


def test_enter_cancels_and_nothing_is_scanned(monkeypatch, tmp_path):
    text, seen = _scan(monkeypatch, tmp_path, answer="")
    assert "Cancelled" in text and seen == [] and "Checking the page" not in text
    assert not list(tmp_path.glob("magnacoda-scans/*/results.json"))


def test_quick_is_named_only_when_the_preferences_turn_it_on(monkeypatch, tmp_path):
    load = preferences.load  # tests/cli/conftest.py turns quick on for every test here
    for quick, ending in (
        (True, ", quick (set in preferences.ini). You can type"),
        (False, ". You can type"),
    ):
        monkeypatch.setattr(preferences, "load", lambda quick=quick: dataclasses.replace(load(), quick=quick))
        text, _ = _scan(monkeypatch, tmp_path)
        assert DEFAULTS + ending in text


def test_nothing_is_asked_with_options_with_y_without_a_person_or_with_confirm_off(monkeypatch, tmp_path):
    for args, person in ((["--screen", "both"], True), (["-v"], True), (["-y"], True), ([], False)):
        text, seen = _scan(monkeypatch, tmp_path, *args, person=person)
        assert "Options »" not in text and len(seen) >= 1, (args, person)
    path = preferences.preferences_path()
    path.write_text(path.read_text().replace("confirm = on", "confirm = off"))
    assert preferences.load().confirm is False
    text, seen = _scan(monkeypatch, tmp_path)
    assert "Options »" not in text and seen
    _, text, seen = _prompt(monkeypatch, tmp_path, "example.com\n")  # nor after `scan` and the address
    assert "Options »" not in text and seen


def test_how_to_cancel_comes_before_the_question_and_q_cancels(monkeypatch, tmp_path):
    text, seen = _scan(monkeypatch, tmp_path, answer="q")
    assert text.index("Ctrl+C or q cancels at any time.") < text.index(DEFAULTS)
    assert "Cancelled" in text and seen == []


# A page scanned before: the question says so, and fav or recent lists that page's saved scans.


def _history(*lines: str) -> None:
    history.ensure_file()
    path = history.history_path()
    entries = "".join(f"- 2026-10-1{n} 09:00 `{line}`\n" for n, line in zip((7, 6, 5), lines, strict=False))
    path.write_text(history.HEADER + entries, encoding="utf-8")


def test_a_page_scanned_before_is_noted_and_recent_lists_only_its_scans(monkeypatch, tmp_path):
    _history(
        "scan https://other.test --level AAA --ai off",
        "scan https://example.com/ --level AAA --ai off --screen mobile",
        "scan https://example.com --level AA --ai off --color-scheme dark",
    )
    text, seen = _scan(monkeypatch, tmp_path, answer="recent\n2\n")  # 2, then Enter: no changes
    assert "example.com is in your recent scans (2). You can type: options, defaults, recent, help." in text
    listed = text.split("Options » recent", 1)[1]
    assert "Recent scans of example.com 1. --level AAA --screen mobile (Oct 16, 09:00) 2." in listed
    assert "other.test" not in text and "Change anything? [y/N]" in listed
    assert seen[0].color_scheme == "dark" and seen[0].level == "AA"
    assert "--color-scheme dark" in history.read()[0].command


def test_the_saved_scans_are_not_listed_until_asked_for(monkeypatch, tmp_path):
    _history("scan https://example.com --level AAA --ai off")
    text, seen = _scan(monkeypatch, tmp_path)
    assert "recent scans (1)" in text and "--level AAA" not in text and seen[0].level == "AA"
    text, seen = _scan(monkeypatch, tmp_path, answer="recent\n")  # Enter at the list cancels
    assert "press Enter to cancel" in text and "Cancelled" in text and seen == []


def test_a_scan_with_the_default_settings_is_not_a_saved_scan(monkeypatch, tmp_path):
    _history("scan https://example.com --level AA --ai off")
    text, seen = _scan(monkeypatch, tmp_path, answer="recent\ndefaults")
    assert "is in your" not in text and "Options start with dashes" in text and seen


def test_an_add_ons_saved_scans_are_their_own_group_and_the_same_settings_are_listed_once(
    monkeypatch, tmp_path
):
    favorite = "scan https://example.com --level AA --ai off --screen both"
    entries = [("client home", favorite), ("elsewhere", "scan https://b.test")]
    monkeypatch.setattr(
        plugins, "start_groups", lambda: [plugins.StartGroup("Favorites", entries, word="fav")]
    )
    _history(favorite, "scan https://example.com --level AAA --ai off")
    text, seen = _scan(monkeypatch, tmp_path, answer="fav\n1\n")
    # history's copy of the favorite isn't counted again
    assert "example.com is in your favorites (1) and recent scans (1)." in text
    assert "options, defaults, fav, recent, help" in text
    assert "Favorites of example.com 1. client home: --screen both Type a number" in text
    assert "elsewhere" not in text and [config.screen for config in seen][:2] == ["desktop", "mobile"]


def test_changing_a_saved_scan_asks_the_wizards_questions_with_its_settings_first(monkeypatch, tmp_path):
    _history("scan https://example.com --level AAA --ai off --screen mobile")
    load = preferences.load
    monkeypatch.setattr(preferences, "load", lambda: dataclasses.replace(load(), estimate=False))
    # recent, 1, change: yes, level A, AI, screens and other options as they were, run: yes
    text, seen = _scan(monkeypatch, tmp_path, answer="recent\n1\ny\nA\n\n\n\ny")
    assert "Change anything? [y/N]" in text and "WCAG level" in text and "Run this scan now?" in text
    assert seen[0].level == "A" and seen[0].screen == "mobile"


# scan alone: the address is asked for, with help for the scan section; scripts get the error.


def test_scan_alone_asks_for_the_address_then_the_options(monkeypatch, tmp_path):
    seen: list = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "run_scan", _fake_run(seen))
    monkeypatch.setattr(cli, "_is_interactive", lambda: True)
    monkeypatch.setattr(redirects, "check_address", lambda url, **kw: None)
    monkeypatch.setenv("MAGNACODA_PAGER", "off")
    result = CliRunner().invoke(main, ["scan"], input="help\nexample.com\ndefaults\n")
    text = " ".join(result.output.split())
    prompt = "Page to scan »"
    assert prompt in text and "--screen" in text.split(prompt + " help", 1)[1]  # the scan section
    assert "You can type: an address, wizard, help. Enter cancels." in text
    assert "The defaults: WCAG 2.2 AA" in text and "defaults, help. Enter cancels. Options »" in text
    assert seen[0].url == "https://example.com"
    assert text.count("cancels at any time") == 1
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


def _prompt(monkeypatch, tmp_path, typed, *args):
    seen: list = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "run_scan", _fake_run(seen))
    monkeypatch.setattr(cli, "_is_interactive", lambda: True)
    monkeypatch.setattr(redirects, "check_address", lambda url, **kw: None)
    monkeypatch.setenv("MAGNACODA_PAGER", "off")
    result = CliRunner().invoke(main, ["scan", *args], input=typed)
    return result, " ".join(result.output.split()), seen


def test_options_typed_after_the_address_are_used(monkeypatch, tmp_path):
    _, _, seen = _prompt(monkeypatch, tmp_path, "example.com --screen mobile\n")
    assert seen[0].url == "https://example.com" and seen[0].screen == "mobile"
    assert "--screen mobile" in history.read()[0].command


def test_options_given_with_a_bare_scan_are_kept(monkeypatch, tmp_path):
    _, _, seen = _prompt(monkeypatch, tmp_path, "example.com --level A\n", "--screen", "mobile")
    assert seen[0].screen == "mobile" and seen[0].level == "A"


def test_a_wrong_option_is_explained_and_asked_again(monkeypatch, tmp_path):
    result, text, seen = _prompt(monkeypatch, tmp_path, "example.com --scren mobile\nexample.com\ndefaults\n")
    assert "no option --scren" in text and seen[0].url == "https://example.com"
    result, text, seen = _prompt(monkeypatch, tmp_path, "example.com --option\n\n")
    assert "stands for any of the scan options" in text and seen == [] and result.exit_code == 130
    _, text, _ = _prompt(monkeypatch, tmp_path, "--screen mobile\nexample.com\ndefaults\n")
    assert "Start with the page to scan" in text


def test_a_group_word_opens_its_list_and_a_number_repeats_that_scan(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    history.record("scan https://a.example --screen mobile")
    history.record("scan https://b.example")
    _, text, seen = _prompt(monkeypatch, tmp_path, "recent\n2\n\n")
    assert "an address, recent, wizard, help" in text and "1. b.example" in text and "2. a.example" in text
    assert "Change anything?" in text
    assert seen[0].url == "https://a.example" and seen[0].screen == "mobile"
    _, text, seen = _prompt(monkeypatch, tmp_path, "recent\n9\n\n")
    assert "numbers above (1 to 2)" in text and seen == []


def test_favorites_are_offered_as_their_own_group(monkeypatch, tmp_path):
    group = plugins.StartGroup(
        "Favorites", [("client home", "scan https://fav.example --screen both")], word="fav"
    )
    monkeypatch.setattr(plugins, "start_groups", lambda: [group])
    _, text, seen = _prompt(monkeypatch, tmp_path, "fav\n1\n\n")
    assert "an address, fav, wizard, help" in text and "1. client home" in text
    assert seen[0].url == "https://fav.example"


def test_a_long_group_is_offered_for_viewing_not_printed(monkeypatch, tmp_path):
    entries = [(f"site {n}", f"scan https://s{n}.example") for n in range(1, 16)]
    monkeypatch.setattr(
        plugins, "start_groups", lambda: [plugins.StartGroup("Favorites", entries, word="fav")]
    )
    viewed: list = []
    monkeypatch.setattr(cli, "show_pages", lambda ctx, sections, *a, **kw: viewed.append(sections))
    _, text, seen = _prompt(monkeypatch, tmp_path, "fav\nview\n3\n\n")
    assert "has 15 entries" in text and "site 7" not in text and "Type view" in text
    assert viewed and "15. site 15" in viewed[0][0][1]
    assert seen[0].url == "https://s3.example"


def test_wizard_typed_at_the_prompt_opens_the_wizard(monkeypatch, tmp_path):
    opened: list = []
    monkeypatch.setattr(cli.wizard, "callback", lambda **kw: opened.append(kw))
    result, _, seen = _prompt(monkeypatch, tmp_path, "wizard\n")
    assert opened and seen == [] and result.exit_code == 0


def test_nothing_runs_until_the_options_question_is_answered(monkeypatch, tmp_path):
    result, text, seen = _prompt(monkeypatch, tmp_path, "example.com\n\n")
    assert "Options »" in text and seen == [] and result.exit_code == 130
    assert "Checking the page" not in text and not history.read()


def test_options_typed_at_the_second_question_run_the_scan(monkeypatch, tmp_path):
    _, text, seen = _prompt(monkeypatch, tmp_path, "example.com\n--screen mobile --level A\n")
    assert (
        seen[0].screen == "mobile" and seen[0].level == "A" and "--screen mobile" in history.read()[0].command
    )
    _, text, seen = _prompt(monkeypatch, tmp_path, "example.com\nmobile\n--scren x\n--option\ndefaults\n")
    assert "Options start with dashes" in text and "no option --scren" in text and "stands for any" in text
    assert seen[0].url == "https://example.com" and seen[0].screen is None


def test_a_script_with_piped_input_is_never_asked_anything(monkeypatch, tmp_path):
    questions = ("You can type", "Options »", "Page to scan", "Change anything?")
    for args in ([], ["--screen", "mobile"], ["--level", "AAA", "--fail-on", "minor"]):
        text, seen = _scan(monkeypatch, tmp_path, *args, answer="--level A", person=False)
        assert seen and not any(question in text for question in questions), args
    seen = []
    monkeypatch.setattr(cli, "run_scan", _fake_run(seen))
    monkeypatch.setattr(cli, "_is_interactive", lambda: False)
    result = CliRunner().invoke(main, ["scan"], input="example.com\n--screen mobile\n")
    assert result.exit_code != 0 and "Missing argument 'URL'" in result.output and seen == []


def test_the_scan_questions_fit_an_80_column_window_and_the_prompts_are_short(monkeypatch, tmp_path):
    load = preferences.load  # tests/cli/conftest.py turns quick on, which adds a note to the defaults
    monkeypatch.setattr(preferences, "load", lambda: dataclasses.replace(load(), quick=False))
    entries = [("client home", "scan https://example.com --screen both")]
    monkeypatch.setattr(
        plugins, "start_groups", lambda: [plugins.StartGroup("Favorites", entries, word="fav")]
    )
    history.record("scan https://example.com --level AAA")
    result, _, _ = _prompt(monkeypatch, tmp_path, "example.com\n\n")
    lines = result.output.splitlines()
    assert "example.com is in your favorites (1) and recent scans (1)." in lines
    assert max(len(line) for line in lines) < 80
    assert "Page to scan » example.com" in lines and any(line.startswith("Options »") for line in lines)
