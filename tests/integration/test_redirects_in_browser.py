"""Redirects in a real browser (browser/redirects.py): where the page landed, another site, and a page
that moves on by itself after a delay (WCAG 2.2.1)."""

import re

import pytest
from click.testing import CliRunner

from magnacoda.cli import main
from magnacoda.config import ScanConfig
from magnacoda.orchestrator import run_scan

pytestmark = pytest.mark.integration


def test_the_report_is_of_where_the_page_landed(fixture_server):
    report = run_scan(ScanConfig(url=f"{fixture_server}/redirects/at_once.html", quick=True))
    assert report.url == f"{fixture_server}/redirects/target.html"
    assert report.meta.requested_url == f"{fixture_server}/redirects/at_once.html"
    assert not [f for f in report.findings if f.rule_id == "magnacoda/timed-redirect"]  # at once is fine


def test_a_page_that_moves_on_while_still_changing_is_followed_not_a_crash(fixture_server):
    report = run_scan(ScanConfig(url=f"{fixture_server}/redirects/while_settling.html", quick=True))
    assert report.url == f"{fixture_server}/redirects/target.html"


def test_a_page_that_moves_on_after_a_delay_fails_2_2_1_and_the_scan_stays_on_it(fixture_server):
    url = f"{fixture_server}/redirects/timed.html"
    report = run_scan(ScanConfig(url=url))  # thorough: watching for motion gives the timer time to fire
    (finding,) = [f for f in report.findings if f.rule_id == "magnacoda/timed-redirect"]
    assert finding.wcag_criteria == ["2.2.1"] and finding.severity == "serious"
    assert re.search(r"goes on to \S+/redirects/target\.html after [23] seconds", finding.description)
    assert report.url == url  # held: the scan is of the page people saw
    assert next(e for e in report.checklist if e.num == "2.2.1").status == "failed"


def test_a_redirect_to_another_site_is_said_in_the_summary_and_the_checklist(fixture_server, tmp_path):
    url = f"{fixture_server}/redirects/other_site.html"
    result = CliRunner().invoke(
        main, ["scan", url, "--quick", "--scans-dir", str(tmp_path), "--fail-on", "none"]
    )
    assert result.exit_code == 0
    text = " ".join(result.output.split())
    assert f"{url} redirected to http://localhost:" in text and "this scan is of localhost." in text
    (folder,) = [p for p in tmp_path.iterdir() if p.is_dir()]
    assert folder.name.startswith("localhost_")  # named after the site scanned
    title = (folder / "checklist.md").read_text().splitlines()[0]
    assert (
        title.startswith("# Accessibility checklist: http://localhost:") and f"(reached from {url})" in title
    )
