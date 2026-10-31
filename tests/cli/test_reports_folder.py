import shutil
import subprocess

import pytest
from click.testing import CliRunner

from magnacoda import cli
from magnacoda.cli import main
from magnacoda.findings.models import ScanMeta, ScanReport


def _fake_scan(config, *, consent_given=False):
    meta = ScanMeta(
        tool_version="0",
        axe_core_version="0",
        wcag_version="2.2",
        wcag_level="AA",
        ai_tier="off",
        fixes_tier="template",
        stability_settled=True,
        stability_elapsed_ms=0,
        stability_reason="quiescent",
    )
    return ScanReport(url=config.url, meta=meta, findings=[])


def _save(monkeypatch, tmp_path, *args):
    monkeypatch.setattr(cli, "run_scan", _fake_scan)
    monkeypatch.chdir(tmp_path)
    return CliRunner().invoke(main, ["scan", "http://example.test", *args])


def test_save_creates_a_reports_folder_that_ignores_itself(monkeypatch, tmp_path):
    result = _save(monkeypatch, tmp_path)
    assert result.exit_code == 0
    ignore = tmp_path / "magnacoda-scans" / ".gitignore"
    assert ignore.read_text().splitlines()[-1] == "*"
    scans = list((tmp_path / "magnacoda-scans").glob("*/results.json"))
    assert len(scans) == 1 and (scans[0].parent / "checklist.md").exists()  # one folder per scan


def test_a_custom_reports_dir_that_is_created_also_ignores_itself(monkeypatch, tmp_path):
    _save(monkeypatch, tmp_path, "--scans-dir", "out/my-reports")
    assert (tmp_path / "out" / "my-reports" / ".gitignore").exists()


def test_a_folder_that_already_existed_is_left_alone(monkeypatch, tmp_path):
    (tmp_path / "magnacoda-scans").mkdir()
    _save(monkeypatch, tmp_path)
    assert not (tmp_path / "magnacoda-scans" / ".gitignore").exists()


def test_reports_dir_dot_never_gets_a_star_rule(monkeypatch, tmp_path):
    _save(monkeypatch, tmp_path, "--scans-dir", ".")
    assert not (tmp_path / ".gitignore").exists()


def test_an_existing_gitignore_is_never_overwritten(monkeypatch, tmp_path):
    from magnacoda.report.paths import make_self_ignoring

    folder = tmp_path / "reports"
    folder.mkdir()
    (folder / ".gitignore").write_text("keep-me\n")
    assert make_self_ignoring(folder) is False
    assert (folder / ".gitignore").read_text() == "keep-me\n"


def test_explicit_output_paths_do_not_create_a_self_ignoring_folder(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "run_scan", _fake_scan)
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "somewhere" / "r.json"
    CliRunner().invoke(main, ["scan", "http://example.test", "-o", str(out)])
    assert out.exists() and not (out.parent / ".gitignore").exists()


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_git_really_ignores_what_was_saved(monkeypatch, tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "notes.txt").write_text("mine")
    _save(monkeypatch, tmp_path)
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    ).stdout
    assert "notes.txt" in status  # git works and sees the user's own file
    assert "magnacoda-scans" not in status  # but not the saved reports


def test_every_scan_takes_screenshots_of_the_images(monkeypatch, tmp_path):
    from magnacoda.findings.models import PageImage

    seen = []

    def scan_with_an_image(config, *, consent_given=False):
        seen.append(config)
        report = _fake_scan(config)
        report.images = [PageImage(selector="img", kind="img", alt="x", png=b"\x89PNG")]
        return report

    monkeypatch.setattr(cli, "run_scan", scan_with_an_image)
    monkeypatch.chdir(tmp_path)
    CliRunner().invoke(main, ["scan", "https://a.test", "--fail-on", "none"])
    assert [config.capture_images for config in seen] == [True]
    (checklist,) = (tmp_path / "magnacoda-scans").glob("*/checklist.md")
    assert (checklist.parent / "images" / "1.png").exists() and "](images/1.png)" in checklist.read_text()


def test_a_saved_scan_ends_with_a_summary_and_what_to_do_next_instead_of_a_file_list(monkeypatch, tmp_path):
    result = _save(monkeypatch, tmp_path, "--fail-on", "none")
    out = " ".join(result.output.split())
    assert (
        "Wrote " not in out
        and f"Saved in {tmp_path / 'magnacoda-scans'}/example.test_" in out
        and "results.json" not in out
    )
    assert out.endswith("Type magnacoda review to see them in your browser.")  # nothing to recheck
    assert "Found no problems the automated checks can see" in out  # a summary, not the findings


def test_how_long_the_scan_took_is_saved_and_said_with_the_estimate(monkeypatch, tmp_path, capsys):
    import json

    _save(monkeypatch, tmp_path, "--fail-on", "none")
    (results,) = (tmp_path / "magnacoda-scans").glob("*/results.json")
    meta = json.loads(results.read_text())["meta"]
    assert meta["scan_seconds"] >= 0 and meta["estimated_seconds"] is None  # no estimate outside a terminal
    report = _fake_scan(type("Config", (), {"url": "http://example.test"}))
    report.meta.scan_seconds, report.meta.estimated_seconds = 131.6, 120.0
    cli._say_what_was_saved(tmp_path, report)
    assert "The scan took 2 min 11 s; the estimate was about 2 min." in capsys.readouterr().err


def test_inside_the_shell_the_next_step_says_type_review(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "run_scan", _fake_scan)
    monkeypatch.chdir(tmp_path)
    out = " ".join(
        CliRunner()
        .invoke(main, ["shell"], input="scan http://example.test --fail-on none\nexit\n")
        .output.split()
    )
    assert "Type review to see them in your browser." in out and "Type magnacoda review" not in out


def test_a_saved_scan_shows_a_summary_of_its_findings_unless_asked_for_them_all(monkeypatch, tmp_path):
    from magnacoda.findings.models import Finding

    def scan_with_problems(config, *, consent_given=False):
        report = _fake_scan(config)
        report.findings = [
            Finding(
                finding_id=str(i),
                rule_id="image-alt",
                severity=severity,
                description="Images must have alternative text",
                selector=selector,
                html_snippet="<img>",
                source="axe-core",
            )
            for i, (severity, selector) in enumerate(
                [("critical", "img.a"), ("serious", "img.a"), ("serious", "p")]
            )
        ]
        return report

    monkeypatch.setattr(cli, "run_scan", scan_with_problems)
    monkeypatch.chdir(tmp_path)
    out = " ".join(
        CliRunner().invoke(main, ["scan", "http://example.test", "--fail-on", "none"]).output.split()
    )
    assert "Found 3 problems on 2 elements (1 critical, 2 serious), and " in out and " items to check." in out
    assert "image-alt" not in out  # the findings are on the review page
    assert "magnacoda review" in out and "magnacoda recheck" in out  # what to do next
    full = (
        CliRunner()
        .invoke(main, ["scan", "http://example.test", "--show-findings", "--fail-on", "none"])
        .output
    )
    assert "image-alt" in full  # the findings table, with its rule


def test_quick_comes_from_the_option_or_else_the_preference(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(cli, "run_scan", lambda config, **kw: seen.append(config.quick) or _fake_scan(config))
    monkeypatch.chdir(tmp_path)
    for args in ([], ["--thorough"], ["--quick"]):
        CliRunner().invoke(main, ["scan", "http://example.test", "--fail-on", "none", *args])
    assert seen == [True, False, True]  # these tests' preference is quick (tests/cli/conftest.py)


def test_an_exit_code_of_1_says_why(monkeypatch, tmp_path):
    from magnacoda.findings.models import Finding

    def scan_with(severities):
        def fake(config, *, consent_given=False):
            report = _fake_scan(config)
            report.findings = [
                Finding(
                    finding_id=str(i), rule_id="r", severity=s, description="d", selector=f"#e{i}",
                    html_snippet="", source="axe-core",
                )
                for i, s in enumerate(severities)
            ]  # fmt: skip
            return report

        return fake

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "run_scan", scan_with(["critical", "serious", "minor"]))
    failing = CliRunner().invoke(main, ["scan", "http://example.test"])
    assert failing.exit_code == 1
    assert "Exit code 1: 2 problems at or above serious (--fail-on serious)." in " ".join(
        failing.output.split()
    )
    passing = CliRunner().invoke(main, ["scan", "http://example.test", "--fail-on", "none"])
    assert passing.exit_code == 0 and "Exit code 1" not in passing.output
    monkeypatch.setattr(cli, "run_scan", scan_with(["minor"]))
    below = CliRunner().invoke(main, ["scan", "http://example.test"])
    assert below.exit_code == 0 and "Exit code 1" not in below.output


def test_an_exit_code_of_2_says_the_scan_did_not_finish(monkeypatch, tmp_path):
    from magnacoda.exceptions import NavigationError

    monkeypatch.chdir(tmp_path)

    def unreachable(config, *, consent_given=False):
        raise NavigationError("Could not load http://example.test: connection refused")

    monkeypatch.setattr(cli, "run_scan", unreachable)
    known = CliRunner().invoke(main, ["scan", "http://example.test"])
    out = " ".join(known.output.split())
    assert known.exit_code == 2 and "Error: Could not load http://example.test: connection refused" in out
    assert "Exit code 2: the scan didn't finish, so nothing was checked or saved." in out

    def broken(config, *, consent_given=False):
        raise RuntimeError("Target page, context or browser has been closed\nmore detail")

    monkeypatch.setattr(cli, "run_scan", broken)
    crash = CliRunner().invoke(main, ["scan", "http://example.test"])
    out = " ".join(crash.output.split())
    assert crash.exit_code == 2 and "Traceback" not in crash.output
    assert (
        "magnacoda stopped unexpectedly (RuntimeError: Target page, context or browser has been closed)"
        in out
    )
    assert "run the scan again with -v to see the details" in out and "Exit code 2:" in out
    detailed = CliRunner().invoke(main, ["scan", "http://example.test", "-v"])
    assert (
        detailed.exit_code == 2
        and "Traceback" in detailed.output
        and "The details are above." in detailed.output
    )


def test_o_dash_prints_the_json_instead_of_the_report_and_a_saved_scan_still_gets_its_file(
    monkeypatch, tmp_path
):
    out = _save(monkeypatch, tmp_path, "-o", "-", "--fail-on", "none").output
    assert '"findings"' in out and "Passed checks" not in out  # the JSON, not the readable report
    assert list((tmp_path / "magnacoda-scans").glob("*/results.json"))  # the review page still has it
    assert not (tmp_path / "-").exists()
