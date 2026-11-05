import pytest
from click.testing import CliRunner

from magnacoda import documents, help_sections
from magnacoda.cli import main
from magnacoda.pager import Entry, Opening

SECTIONS = [
    "overview",
    "wizard",
    "url-rules",
    "usage",
    "commands",
    "options",
    "scan",
    "advanced",
    "examples",
    "add-ons",
    "uninstall",
    "more info",
    "about the name",
]
MARKERS = {
    "overview": "The help viewer shows its keys",
    "wizard": "The guided wizard",
    "url-rules": "URL rules",
    "usage": "Usage (outside the shell)",
    "commands": "Commands (inside the shell",
    "options": "Show the version number",
    "scan": "--wait-for-selector",
    "advanced": "Advanced scan options",
    "examples": "Example scans",
    "add-ons": "Make it do more: write an add-on",
    "uninstall": "Uninstalling",
    "more info": "Where to find more",
    "about the name": "About the name",
}


def _run(*args, columns=None, **kwargs):
    env = {"COLUMNS": str(columns)} if columns else None
    return CliRunner(env=env).invoke(main, list(args), **kwargs)


def test_help_and_dashdash_help_both_show_every_section_without_a_terminal():
    plain, flag = _run("help"), _run("--help")
    assert plain.exit_code == 0 and flag.exit_code == 0
    assert plain.output == flag.output
    for marker in MARKERS.values():
        assert marker in plain.output
    assert "Anthropic API key" in " ".join(plain.output.split())


def test_a_section_name_after_help_shows_that_section_only_when_printing():
    result = _run("help", "scan")
    assert result.exit_code == 0 and MARKERS["scan"] in result.output
    assert MARKERS["overview"] not in result.output and MARKERS["examples"] not in result.output


@pytest.mark.parametrize(
    ("words", "section"),
    [
        (["SCAN"], "scan"),
        (["url", "rules"], "url-rules"),
        (["about"], "about the name"),
        (["name"], "about the name"),
        (["more"], "more info"),
    ],
)
def test_section_names_ignore_capitals_and_punctuation_and_may_be_shortened(words, section):
    output = _run("help", *words).output
    assert MARKERS[section] in output and MARKERS["overview"] not in output


def test_an_unknown_or_unclear_name_says_what_there_is():
    unknown = _run("help", "colours")
    assert (
        unknown.exit_code == 1
        and "Help has no section named 'colours'. Its sections: overview, wizard" in unknown.output
    )
    unclear = _run("help", "a")
    assert (
        unclear.exit_code == 1
        and "'a' fits more than one section: advanced, add-ons, about the name." in unclear.output
    )


def test_shell_commands_ignore_capitalization():
    for word in ("HELP", "Help"):
        output = CliRunner().invoke(main, ["shell"], input=f"{word}\nexit\n").output
        assert "Invalid URL" not in output, word
    assert (
        "Already in the magnacoda shell." in CliRunner().invoke(main, ["shell"], input="SHELL\nexit\n").output
    )
    for word in ("EXIT", "Quit", "Q"):
        output = CliRunner().invoke(main, ["shell"], input=f"{word}\nhelp\n").output
        assert MARKERS["overview"] not in output, f"{word} did not end the session"


def test_menu_and_clear_are_documented():
    output = _run("help").output
    assert "\n  menu\n" in output and "clear, cls" in output


def test_help_fits_a_narrow_terminal_except_for_unwrapped_terms():
    for line in _run("help", columns=50).output.splitlines():
        assert len(line) <= 50 or (line.startswith("  ") and not line.startswith("   ")), line


def test_wrapping_never_breaks_a_word_at_its_hyphen():
    for width in range(40, 90, 3):
        output = _run("help", columns=width).output
        assert "expert-\n" not in output and "--force-\n" not in output, width


def test_the_old_overview_command_and_option_are_gone():
    assert _run("--overview").exit_code == 2
    assert "overview isn't a magnacoda command" in _run("overview").output  # just an unknown word


# --- the help file itself -------------------------------------------------------------------


def test_the_help_file_is_packaged_and_starts_with_overview():
    names, bodies = help_sections.load_help()
    assert names == SECTIONS


def test_help_file_mentions_every_scan_flag_in_its_section():
    """Drift guard: the help file is hand-written, so adding a scan flag without documenting it fails here.
    Hidden options are the advanced ones, in their own section."""
    scan = main.commands["scan"]
    bodies = help_sections.load_help()[1]
    missing = [
        opt
        for p in scan.params
        for opt in getattr(p, "opts", [])
        if opt.startswith("-") and opt not in bodies["advanced" if getattr(p, "hidden", False) else "scan"]
    ]
    assert missing == []


def test_help_file_mentions_every_command_and_shell_word():
    body = help_sections.load_help()[1]["commands"]
    for command in main.commands:
        assert command in body, command
    for word in ("menu", "clear", "cls", "details", "exit", "quit", "q"):
        assert word in body, word


def test_editing_the_file_adds_a_section_without_code_changes(monkeypatch):
    text = "## overview\nHi.\n## custom\nMy section.\n"
    monkeypatch.setattr(help_sections, "help_file_text", lambda: text)
    assert "My section." in _run("help").output


def test_a_help_file_without_overview_first_is_reported_cleanly(monkeypatch):
    monkeypatch.setattr(help_sections, "help_file_text", lambda: "## usage\nx\n")
    result = _run("help")
    assert result.exit_code == 1 and "first section must be" in result.output


def test_help_without_a_terminal_prints_every_section_straight_through():
    output = _run("help").output
    assert "\x1b[" not in output  # no pager codes when not on a real terminal
    positions = [output.index(MARKERS[name]) for name in SECTIONS]
    assert positions == sorted(positions)


def test_help_is_described_as_one_screen_at_a_time():
    text = " ".join(_run("help").output.split())
    assert "one screen at a time" in text


@pytest.mark.parametrize(
    "title,section,problem",
    [
        ("Manual", "starting", ""),
        ("Help", "scan", ""),
        ("License", "", ""),
        ("Manual", "nothing like it", "No section named 'nothing like it' in Manual."),
    ],
)
def test_the_open_list_opens_documents_and_their_sections_and_says_why_not(title, section, problem):
    entry = next(entry for entry in documents.entries() if entry.title == title)
    assert help_sections._opening_problem(Opening(entry, section)) == problem


def test_a_file_that_cant_be_shown_says_why(tmp_path):
    empty = tmp_path / "empty.md"
    empty.write_text("")
    assert "is empty" in help_sections._opening_problem(Opening(Entry("empty.md", empty)))


def test_manual_is_another_name_for_docs():
    manual, docs = _run("manual", "starting"), _run("docs", "starting")
    assert manual.exit_code == 0 and manual.output == docs.output and "Starting" in manual.output
