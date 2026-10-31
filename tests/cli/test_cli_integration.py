import json

import pytest
from click.testing import CliRunner

from magnacoda.cli import main

pytestmark = pytest.mark.integration


def test_fail_on_gates_exit_code(fixture_server):
    result = CliRunner().invoke(
        main, ["scan", f"{fixture_server}/static_violations.html", "--fail-on", "critical"]
    )
    assert result.exit_code == 1


def test_json_output_written_to_file(fixture_server, tmp_path):
    out = tmp_path / "report.json"
    result = CliRunner().invoke(
        main,
        ["scan", f"{fixture_server}/static_violations.html", "-o", str(out), "--fail-on", "none"],
    )
    assert result.exit_code == 0
    assert out.exists()
    assert '"schema_version"' in out.read_text()


def test_both_schemes_exit_code_is_worst_of_both(fixture_server):
    url = f"{fixture_server}/dark_mode.html"
    light_only = CliRunner().invoke(main, ["scan", url, "--color-scheme", "light"])
    both = CliRunner().invoke(main, ["scan", url, "--color-scheme", "both"])
    assert light_only.exit_code == 0
    assert both.exit_code == 1


def _scan_folder(tmp_path):
    (folder,) = [p for p in tmp_path.iterdir() if p.is_dir()]
    return folder


def test_the_saved_checklist_covers_the_page(fixture_server, tmp_path):
    args = ["scan", f"{fixture_server}/features.html", "--scans-dir", str(tmp_path), "--fail-on", "none"]
    assert CliRunner().invoke(main, args).exit_code == 0
    text = (_scan_folder(tmp_path) / "checklist.md").read_text()
    assert "## Check first: relevant to this page" in text
    assert "3.3.8 Accessible Authentication (Minimum)" in text


def test_output_writes_a_copy_of_the_results_replacing_a_file_and_creating_folders(fixture_server, tmp_path):
    out = tmp_path / "reports" / "nested" / "results.json"
    for _ in range(2):  # the second time, the file is there already: it's replaced, without asking
        args = ["scan", f"{fixture_server}/clean_page.html", "--scans-dir", str(tmp_path / "scans")]
        result = CliRunner().invoke(main, [*args, "-o", str(out), "--fail-on", "none"])
        assert result.exit_code == 0 and "already exist" not in result.output
    newest = sorted(p for p in (tmp_path / "scans").iterdir() if p.is_dir())[-1]
    assert out.read_text() == (newest / "results.json").read_text()


def test_every_scan_is_saved_in_the_default_scans_folder(fixture_server, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    args = ["scan", f"{fixture_server}/clean_page.html", "--fail-on", "none"]
    result = CliRunner().invoke(main, args)
    assert result.exit_code == 0
    folder = tmp_path / "magnacoda-scans"
    assert (folder / ".gitignore").exists()  # the folder ignores itself in git
    scans = [p for p in folder.iterdir() if p.name != ".gitignore"]
    assert len(scans) == 1 and scans[0].is_dir()  # one folder per scan, named after the site and time
    assert scans[0].name.startswith("127.0.0.1_") and "clean_page.html_" in scans[0].name
    assert sorted(p.name for p in scans[0].iterdir() if p.is_file()) == ["checklist.md", "results.json"]


def test_dark_mode_is_checked_too_and_its_own_problems_are_marked(fixture_server):
    url = f"{fixture_server}/dark_mode.html"
    result = CliRunner().invoke(main, ["scan", url, "--fail-on", "none", "--show-findings"])
    assert result.exit_code == 0
    text = " ".join(result.output.split())
    assert "Tested on desktop, in light and dark mode." in text
    squeezed = "".join(c for c in result.output if c not in "│ \n")  # table cells wrap
    assert "(onlyindarkmode)" in squeezed and "color-contrast" in text


def test_one_json_file_says_where_each_problem_was_found(fixture_server, tmp_path):
    out = tmp_path / "report.json"
    url = f"{fixture_server}/dark_mode.html"
    result = CliRunner().invoke(main, ["scan", url, "-o", str(out), "--fail-on", "none"])
    assert result.exit_code == 0
    assert [p.name for p in tmp_path.iterdir()] == ["report.json"]
    report = json.loads(out.read_text())
    assert report["meta"]["variants"] == ["desktop.light", "desktop.dark"]
    assert report["meta"]["dark_theme"] is True
    contrast = [f for f in report["findings"] if f["rule_id"] == "color-contrast"]
    assert contrast and all(f["seen_in"] == ["desktop.dark"] for f in contrast)
    status = {e["num"]: e["status"] for e in report["checklist"]}
    assert status["1.4.3"] == "failed"


def test_a_page_without_a_dark_theme_gets_no_dark_pass(fixture_server, tmp_path):
    out = tmp_path / "report.json"
    url = f"{fixture_server}/static_violations.html"
    result = CliRunner().invoke(main, ["scan", url, "-o", str(out), "--fail-on", "none"])
    assert result.exit_code == 0
    report = json.loads(out.read_text())
    assert report["meta"]["variants"] == ["desktop.light"] and report["meta"]["dark_theme"] is False
    assert all(not f["seen_in"] for f in report["findings"])
    assert "looks the same in dark mode" in " ".join(result.output.split())


def test_one_theme_only_scans_just_that(fixture_server, tmp_path):
    out = tmp_path / "report.json"
    url = f"{fixture_server}/dark_mode.html"
    args = ["scan", url, "--color-scheme", "dark", "-o", str(out), "--fail-on", "none"]
    assert CliRunner().invoke(main, args).exit_code == 0
    report = json.loads(out.read_text())
    assert report["meta"]["variants"] == ["desktop.dark"] and report["meta"]["dark_theme"] is None
    assert "color-contrast" in {f["rule_id"] for f in report["findings"]}


def test_a_saved_scan_is_one_checklist_and_one_results_file(fixture_server, tmp_path):
    url = f"{fixture_server}/dark_mode.html"
    args = ["scan", url, "--scans-dir", str(tmp_path), "--fail-on", "none"]
    assert CliRunner().invoke(main, args).exit_code == 0
    (scan,) = [p for p in tmp_path.iterdir() if p.is_dir()]
    assert sorted(p.name for p in scan.iterdir() if p.is_file()) == ["checklist.md", "results.json"]
    checklist = (scan / "checklist.md").read_text()
    assert "in light and dark mode" in checklist and "only in dark mode" in checklist
