"""magnacoda.pager stands on its own: options from defaults, a settings file and launch, the contents
rule, and nothing imported from the rest of magnacoda (it is to become its own package)."""

import ast
import sys
from pathlib import Path

import pytest

import magnacoda.pager as pager_package
from magnacoda.pager import markdown, options
from magnacoda.pager.options import PagerOptions, read_settings, resolve

PACKAGE = Path(pager_package.__file__).parent


def test_the_package_imports_only_itself_the_standard_library_and_rich():
    allowed = set(sys.stdlib_module_names) | {"rich", "magnacoda.pager"}
    for file in PACKAGE.glob("*.py"):
        for node in ast.walk(ast.parse(file.read_text(encoding="utf-8"))):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names = [node.module]
            for name in names:
                top = name.split(".")[0]
                assert top in allowed or name.startswith("magnacoda.pager"), f"{file.name} imports {name}"


# --- options ---------------------------------------------------------------------------------------


def test_launch_options_win_over_the_settings_file_which_wins_over_the_defaults(tmp_path):
    settings = tmp_path / "app.ini"
    settings.write_text(
        "[other]\nnumber_links = off\n\n[pager]\nnumber_links = off\nstart = section-list\npaging = no\n"
    )
    found = resolve(settings, title_bar="app - Help", paging=True, document_title=None)
    colors_file = tmp_path / "pager-colors.ini"
    assert found == PagerOptions(
        title_bar="app - Help",
        start="section_list",
        number_links=False,
        paging=True,
        settings_path=settings,
        colors_file=colors_file,
    )
    missing = tmp_path / "missing.ini"
    assert resolve(missing) == PagerOptions(settings_path=missing, colors_file=colors_file)


def test_bad_values_and_unknown_or_program_only_keys_in_the_file_are_ignored(tmp_path):
    settings = tmp_path / "pager.ini"
    settings.write_text(
        "[pager]\nstart = sideways\nhide_contents = maybe\ntitle_bar = Hacked\nnumber_links = 0\n"
    )
    assert read_settings(settings) == {"number_links": False}
    with pytest.raises(TypeError, match="unknown pager options: colour"):
        resolve(settings, colour="red")


def test_on_its_own_the_pager_reads_its_own_settings_file(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("APPDATA", raising=False)
    path = options.default_settings_path()
    path.parent.mkdir(parents=True)
    path.write_text("[pager]\nhide_contents = off\n")
    assert resolve().hide_contents is False


# --- the document's title --------------------------------------------------------------------------


def test_the_first_line_as_a_title_is_taken_out_and_shown_only_when_asked():
    document = markdown.parse("# Notes\n\nIntro.\n\n## Part\n\nText.\n")
    assert document.title == "Notes" and document.sections[0] == ("Introduction", "Intro.")
    assert markdown.with_title(document.title, document.sections)[0][1].startswith("**Notes**")
    later = markdown.parse("Intro.\n\n# Not a title\n")
    assert later.title is None and "# Not a title" in later.sections[0][1]


# --- tables of contents ----------------------------------------------------------------------------

HEADINGS = "\n\n## One\n\nA.\n\n## Two\n\nB.\n\n## Three\n\nC.\n"


def _first(text: str, **chosen) -> str:
    return markdown.parse(text + HEADINGS, PagerOptions(number_links=False, **chosen)).sections[0][1]


@pytest.mark.parametrize(
    "contents",
    [
        "**Contents**\n\n- [One](#one)\n- [Two](#two)",  # the README's own style
        "- [One](#one)\n- [Two](#two)\n- [Three](#three)",  # no label, three items
        "1. [One](#one)\n2. [Two](#two)\n3. [Three](#three)",  # numbered
        "On this page:\n\n- [One](#one)\n- [Two](#two)",  # a short label ending in a colon
        "- **[One](#one)**\n  - [Two](#two)\n\n  - [Three](#three)",  # bold, nested, a blank line between
        "[[_TOC_]]",  # GitLab's marker
        "[TOC]",
    ],
)
def test_a_table_of_contents_is_left_out_whatever_it_is_called(contents):
    assert _first(f"Intro.\n\n{contents}\n\nAfter.") == "Intro.\n\nAfter."


def test_a_contents_section_goes_even_with_a_single_entry():
    found = markdown.parse("Intro.\n\n## Contents\n\n- [Two](#two)\n" + HEADINGS)
    assert [name for name, _ in found.sections] == ["Introduction", "One", "Two", "Three"]


@pytest.mark.parametrize(
    "kept",
    [
        "- [One](#one)\n- [Two](#two)",  # two in-page links with no label: maybe just a short list
        "For details, see:\n\n- [One](#one)",  # one link under a sentence
        "- [Site](https://example.com)\n- [Docs](https://example.org)\n- [Blog](https://example.net)",
        "- [One](#one)\n- [Gone](#nowhere)\n- [Also gone](#missing)",  # links to headings that don't exist
        "```\n- [One](#one)\n- [Two](#two)\n- [Three](#three)\n```",  # an example in a code block
    ],
)
def test_other_lists_stay(kept):
    assert kept in _first(f"Intro.\n\n{kept}\n\nAfter.")


def test_a_heading_with_more_under_it_than_the_list_stays_and_nothing_moves():
    text = "Intro.\n\n### Sections\n\n- [One](#one)\n- [Two](#two)\n\nA closing note."
    assert _first(text) == "Intro.\n\n### Sections\n\nA closing note."


def test_hide_contents_off_keeps_it():
    text = "Intro.\n\n**Contents**\n\n- [One](#one)\n- [Two](#two)\n\nAfter."
    assert "**Contents**" in _first(text, hide_contents=False)


def test_paging_off_prints_everything_even_in_a_terminal(monkeypatch):
    import io

    from magnacoda.pager import screen

    monkeypatch.setattr(pager_package, "pager_available", lambda off_switch=None: True)
    monkeypatch.setattr(screen, "page_sections", lambda *a, **k: pytest.fail("should not page"))
    out = io.StringIO()
    result = pager_package.show([("a", "first"), ("b", "second")], PagerOptions(paging=False), out=out)
    assert result is None and out.getvalue() == "first\n\nsecond\n"
    out = io.StringIO()
    pager_package.show([("a", "body")], PagerOptions(paging=False), title="Title", out=out)
    assert out.getvalue() == "**Title**\n\nbody\n"  # default_wrap leaves Markdown alone; the title is first


@pytest.mark.parametrize(
    "first,listed",
    [("## Abbreviation\n\nFSL-1.1-MIT", True), ("A paragraph long enough to read on its own. " * 4, False)],
)
def test_a_document_whose_opening_section_is_a_line_or_two_starts_on_its_section_list(
    monkeypatch, first, listed
):
    asked = {}
    monkeypatch.setattr(pager_package, "pager_available", lambda off_switch=None: True)
    monkeypatch.setattr(pager_package, "page_sections", lambda sections, **kwargs: asked.update(kwargs))
    pager_package.show([("one", first), ("two", "more")], PagerOptions(), title="License")
    assert asked["open_list"] is listed
