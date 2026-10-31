"""A repeat scan of the same page keeps what a person checked (saved_reports.previous_ticks, ticks.py,
markdown_export.carry_ticks, cli.scan_cmd)."""

import json
from datetime import datetime

from click.testing import CliRunner

from magnacoda import cli, ticks
from magnacoda.cli import main
from magnacoda.findings.models import FeatureExample
from tests.report.test_markdown import _report

URL = "http://example.test"


class _Clock:
    """Each saved scan a minute later, so each gets its own folder."""

    minute = 0

    @classmethod
    def now(cls, tz=None):
        cls.minute += 1
        return datetime(2026, 10, 11, 9, cls.minute)


def _scan(monkeypatch, *extra):
    monkeypatch.setattr(cli, "run_scan", lambda config, consent_given=False: _report())
    monkeypatch.setattr(cli, "datetime", _Clock)
    return CliRunner().invoke(main, ["scan", URL, "--fail-on", "none", *extra])


def _checklists(tmp_path):
    return sorted((tmp_path / "magnacoda-scans").glob("*/checklist.md"))


def test_what_a_person_checked_carries_over_but_failures_found_again_start_unticked(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _scan(monkeypatch)
    (first,) = _checklists(tmp_path)
    items = ticks.read_ticks(first)
    fix = next(i for i in items if "-fix-" in i)
    ticks.set_tick(first, "c-3.3.8", True)  # a manual check a person verified
    ticks.set_tick(first, fix, True)  # someone ticked a failure as fixed
    result = _scan(monkeypatch)
    second = _checklists(tmp_path)[-1]
    now = ticks.read_ticks(second)
    assert now["c-3.3.8"] is True and now[fix] is False  # the failure was found again
    text = second.read_text()
    assert "(checked in the scan of 2026-10-11)" in text
    assert "c-3.3.8" in json.loads(second.with_name("results.json").read_text())["ticked"]
    assert "Kept 1 tick from your scan of 2026-10-11 09:01." in " ".join(result.output.split())


def test_a_different_level_or_page_starts_fresh(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _scan(monkeypatch)
    (first,) = _checklists(tmp_path)
    ticks.set_tick(first, "c-3.3.8", True)
    result = _scan(monkeypatch, "--level", "AAA")  # the fake report says AA: not the same scan
    assert "Kept " not in result.output
    assert ticks.read_ticks(_checklists(tmp_path)[-1])["c-3.3.8"] is False


def test_only_human_checks_may_carry_over():
    assert ticks.carries_over("c-2.4.7") and ticks.carries_over("e-0123456789-done-a1b2c3")
    assert ticks.carries_over("e-0123456789-check-1.3.5")  # from scans saved before element boxes
    assert not ticks.carries_over("e-0123456789-fix-color-contrast")
    assert not ticks.carries_over("e-0123456789-review-video-caption")
    assert not ticks.carries_over("e-0123456789-hidden-x") and not ticks.carries_over("u-1")


def test_an_elements_checked_box_carries_over_unless_its_checks_changed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _scan(monkeypatch)
    (first,) = _checklists(tmp_path)
    (done,) = [i for i in ticks.read_ticks(first) if "-done-" in i]  # the element axe couldn't decide
    ticks.set_tick(first, done, True)
    _scan(monkeypatch)
    assert ticks.read_ticks(_checklists(tmp_path)[-1])[done] is True  # same checks: still checked

    def with_another_check(config, consent_given=False):
        from tests.report.test_markdown import _entry

        report = _report()
        report.checklist.append(_entry("1.3.5", "relevant"))
        report.checklist[-1].examples = [FeatureExample(selector="#group_type")]
        return report

    monkeypatch.setattr(cli, "run_scan", with_another_check)
    CliRunner().invoke(main, ["scan", URL, "--fail-on", "none"])
    latest = ticks.read_ticks(_checklists(tmp_path)[-1])
    assert done not in latest and not any(v for k, v in latest.items() if "-done-" in k)  # asked again
