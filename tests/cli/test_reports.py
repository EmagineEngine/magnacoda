"""The `reports` command (saved_reports.py) and hiding a document's own table of contents."""

from datetime import datetime

from click.testing import CliRunner

from magnacoda import saved_reports
from magnacoda.about import about_text
from magnacoda.cli import main
from magnacoda.pager import markdown
from magnacoda.pager import screen as pager

CHECKLIST = """# Accessibility checklist: https://example.com/

Scanned with magnacoda.

## Contents

- [Fix these (1)](#fix-these-1)

## Fix these (1)

- [ ] **1.4.3 Contrast** - e.g. `<span class="req">`
"""


def _save(folder, name, text=CHECKLIST):
    folder.mkdir(exist_ok=True)
    (folder / name).write_text(text)


def test_saved_checklists_are_listed_newest_first_with_their_variant(tmp_path):
    folder = tmp_path / "magnacoda-scans"
    _save(folder, "example.com_20261001-090000.md")
    _save(folder, "example.com_docs_20261003-101500.dark.md")
    _save(folder, "example.com_docs_20261003-101500.mobile.light.md")
    _save(folder, "example.com_20261001-090000.json", "{}")
    _save(folder, "my-own-checklist.md")
    found = saved_reports.find(folder)
    assert [r.line() for r in found] == [
        "example.com_docs  2026-10-03 10:15  (mobile, light)  - 0 of 1 checked",
        "example.com_docs  2026-10-03 10:15  (dark)  - 0 of 1 checked",
        "example.com  2026-10-01 09:00  - 0 of 1 checked",
    ]
    assert found[-1].when == datetime(2026, 10, 1, 9, 0)


def test_only_the_newest_are_listed(tmp_path):
    folder = tmp_path / "r"
    for day in range(1, 26):
        _save(folder, f"site_202610{day:02d}-120000.md")
    found = saved_reports.find(folder)
    assert len(found) == saved_reports.LIMIT and found[0].when.day == 25


def test_with_no_reports_it_says_how_to_make_one(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    output = CliRunner().invoke(main, ["review"]).output
    assert (
        f"No saved scans in {tmp_path / 'magnacoda-scans'}." in output
        and "Every scan is saved there" in output
    )


def test_picking_a_report_shows_its_checklist_without_its_own_contents(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _save(tmp_path / "magnacoda-scans", "example.com_20261001-090000.md")
    output = CliRunner().invoke(main, ["review"], input="1\n\n").output
    assert "1. example.com  2026-10-01 09:00  - 0 of 1 checked" in output
    assert "Fix these (1)" in output and "Contents" not in output
    assert '`<span class="req">`' in output  # code is shown exactly as written


def test_enter_goes_back_without_showing_anything(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _save(tmp_path / "magnacoda-scans", "example.com_20261001-090000.md")
    assert "Fix these" not in CliRunner().invoke(main, ["review"], input="\n").output


def test_another_folder_can_be_given(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _save(tmp_path / "elsewhere", "site_20261001-090000.md")
    assert (
        f"Saved scans in {tmp_path / 'elsewhere'},"
        in CliRunner().invoke(main, ["review", "elsewhere"], input="\n").output
    )


def test_the_pager_leaves_out_hidden_sections_but_never_everything():
    sections = [("Intro", "a"), ("Contents", "b"), ("Body", "c")]
    assert pager.visible_sections(sections, ["contents "]) == [("Intro", "a"), ("Body", "c")]
    assert pager.visible_sections([("Contents", "b")], ["Contents"]) == [("Contents", "b")]


def test_code_in_backticks_is_shown_exactly_as_written():
    lines = markdown.render("Use `<b>*args*</b>` and `a_b_c`.", 80)
    assert lines == ["Use `<b>*args*</b>` and `a_b_c`."]


def test_about_points_to_news_now_that_it_is_off_the_banner():
    assert "type news for updates" in about_text()


def test_the_list_and_the_report_show_how_far_along_each_checklist_is(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _save(tmp_path / "magnacoda-scans", "example.com_20261001-090000.md", CHECKLIST.replace("[ ]", "[x]"))
    output = CliRunner().invoke(main, ["review"], input="1\n\n").output
    assert "1. example.com  2026-10-01 09:00  - 1 of 1 checked" in output
    assert "Progress: 1 of 1 checked" in output and "[✓] 1.4.3 Contrast" in output


def test_the_report_says_which_file_to_open_in_a_markdown_editor(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))  # so the path is shown starting with ~
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    _save(tmp_path / "magnacoda-scans", "example.com_20261001-090000.md")
    output = CliRunner().invoke(main, ["review"], input="1\n\n").output
    assert "Tick items off by opening this file in a Markdown editor:" in " ".join(output.split())
    assert "`~/magnacoda-scans/example.com_20261001-090000.md`" in output.replace("\\", "/")


def test_scans_saved_in_their_own_folders_are_listed_with_their_variants(tmp_path):
    folder = tmp_path / "magnacoda-scans"
    scan = folder / "example.com_20261010-091500"
    scan.mkdir(parents=True)
    (scan / "checklist.light.md").write_text(CHECKLIST)
    (scan / "checklist.dark.md").write_text(CHECKLIST)
    (scan / "results.light.json").write_text("{}")
    _save(folder, "example.com_20261001-090000.md")  # an older, loose one
    (folder / "not-a-scan").mkdir()
    lines = [r.line() for r in saved_reports.find(folder)]
    assert lines[:2] == [
        "example.com  2026-10-10 09:15  (light)  - 0 of 1 checked",
        "example.com  2026-10-10 09:15  (dark)  - 0 of 1 checked",
    ]
    assert lines[2].startswith("example.com  2026-10-01 09:00") and len(lines) == 3
