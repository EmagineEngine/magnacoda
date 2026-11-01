"""`view FILE`, `readme FILE` and `help readme` (viewer.py)."""

import pytest
from click.testing import CliRunner

from magnacoda import viewer
from magnacoda.cli import main
from magnacoda.pager import files, markdown


def _run(*args):
    return CliRunner().invoke(main, list(args))  # no terminal: the pager prints everything


def test_a_markdown_file_is_laid_out_with_its_sections(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "notes.md").write_text(
        "# Notes\n\nIntro with `code`.\n\n## Part two\n\n| a | b |\n|---|---|\n| 1 | 2 |\n"
    )
    shown = viewer.load("notes.md")
    title, sections = shown.name, shown.sections
    assert title == "notes.md" and [name for name, _ in sections] == ["Introduction", "Part two"]
    output = _run("view", "notes.md").output
    assert "Intro with `code`." in output and "Part two" in output and "# Notes" not in output


def test_section_numbers_in_links_skip_a_contents_section_only_when_there_is_one(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    body = "Intro: see [Part two](#part-two).\n\n## Part one\n\nOne.\n\n## Part two\n\nTwo.\n"
    (tmp_path / "plain.md").write_text(body)
    (tmp_path / "listed.md").write_text(
        body.replace("\n\n## Part one", "\n\n## Contents\n\n- [Part two](#part-two)\n\n## Part one")
    )
    for name in ("plain.md", "listed.md"):
        sections = viewer.load(name).sections
        assert [n for n, _ in sections] == ["Introduction", "Part one", "Part two"]
        assert "see Part two (section 3)." in " ".join(markdown.render(sections[0][1], 80))


MARKDOWN_WITHOUT_SAYING_SO = "# License\n\n## Terms\n\nUse it well.\n\n## Notice\n\nCopyright.\n"


@pytest.mark.parametrize("name", ["LICENSE", "notes.txt"])
def test_markdown_without_a_markdown_extension_is_laid_out_as_markdown(tmp_path, monkeypatch, name):
    monkeypatch.chdir(tmp_path)
    (tmp_path / name).write_text(MARKDOWN_WITHOUT_SAYING_SO)
    shown = viewer.load(name)
    title, sections, wrap = shown.name, shown.sections, shown.format.render
    assert title == name and [n for n, _ in sections] == ["Terms", "Notice"]
    assert shown.title == "License"  # shown at the top of the first page (pager.show, document_title)
    first = markdown.with_title(shown.title, sections)[0][1]
    assert wrap(first, 60)[:3] == ["License", "", "Terms"]
    assert "License" in _run("view", name).output.splitlines()[0]


def test_a_file_without_a_title_starts_with_its_text(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "notes.md").write_text("Intro first.\n\n# Not the first line\n\n## Part\n\nText.\n")
    shown = viewer.load("notes.md")
    sections, wrap = shown.sections, shown.format.render
    assert wrap(sections[0][1], 60)[0] == "Intro first."


@pytest.mark.parametrize(
    "name, text",
    [
        ("Makefile", "# Build\nall:\n\tmake it\n\n# Clean up\nclean:\n\trm -f out\n"),
        ("deploy", "#!/bin/sh\n\n# Settings\n\nA=1\n\n## Steps\n\necho go\n"),  # a script
        ("settings.cfg", MARKDOWN_WITHOUT_SAYING_SO),  # another extension: never guessed
        ("short", "# Just a title\n\nAnd a line.\n"),  # one heading isn't enough to tell
    ],
)
def test_other_text_with_hash_lines_stays_plain_text(tmp_path, monkeypatch, name, text):
    monkeypatch.chdir(tmp_path)
    (tmp_path / name).write_text(text)
    assert len(viewer.load(name).sections) == 1


def test_a_text_file_is_one_section_and_control_codes_are_removed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "log.txt").write_text("line one\n\x1b[2Jcleared?\n")
    shown = viewer.load("log.txt")
    title, sections = shown.name, shown.sections
    assert title == "log.txt" and len(sections) == 1
    output = _run("view", "log.txt").output
    assert "line one" in output and "\x1b" not in output


def test_readme_with_a_file_shows_that_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "mine.txt").write_text("my own text\n")
    assert "my own text" in _run("readme", "mine.txt").output


@pytest.mark.parametrize(
    ("make", "message"),
    [
        (lambda p: None, "There is no file x.md"),
        (lambda p: (p / "x.md").mkdir(), "is a folder"),
        (lambda p: (p / "x.md").write_bytes(b"\x89PNG\x00\x00data"), "doesn't look like a text file"),
        (lambda p: (p / "x.md").write_text("  \n"), "is empty"),
    ],
)
def test_files_that_cant_be_shown_get_a_short_reason(tmp_path, monkeypatch, make, message):
    monkeypatch.chdir(tmp_path)
    make(tmp_path)
    result = _run("view", "x.md")
    assert result.exit_code == 1 and message in result.output


def test_a_file_over_the_size_limit_is_refused(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(files, "MAX_BYTES", 10)
    (tmp_path / "big.txt").write_text("x" * 50)
    assert "too large to view" in _run("view", "big.txt").output


@pytest.mark.parametrize("word", ["readme", "README", "readme.md"])
def test_help_readme_opens_the_readme(word):
    output = _run("help", word).output
    assert "Quick start" in output and "URL rules" in output


def test_view_and_readme_can_start_at_a_named_section(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "notes.md").write_text("# Notes\n\nIntro.\n\n## Part one\n\nOne.\n\n## Part two\n\nTwo.\n")
    output = _run("view", "notes.md", "part", "two").output
    assert "Two." in output and "One." not in output and "Intro." not in output
    assert "Two." in _run("readme", "notes.md", "Part Two").output  # a file first: that file's section
    readme = _run("readme", "quick", "start").output
    assert "pipx" in readme and "Related tools" not in readme and "Guided wizard" not in readme
    unknown = _run("view", "notes.md", "part", "three")
    assert unknown.exit_code == 1 and "notes.md has no section named 'part three'" in unknown.output
    assert "fits more than one section: Part one, Part two" in _run("view", "notes.md", "part").output


def test_a_document_magnacoda_comes_with_opens_from_any_folder(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert "Writing an add-on" in _run("view", "contributing.md").output
    (tmp_path / "CONTRIBUTING.md").write_text("# Mine\n\nMy own notes.\n")
    assert "My own notes." in _run("view", "CONTRIBUTING.md").output  # a file here comes first
