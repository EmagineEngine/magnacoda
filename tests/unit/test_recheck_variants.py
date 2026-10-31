"""A recheck of a scan of several screens and themes tests each problem where it was found
(recheck._test_again); the page loads themselves are faked here (tests/integration/test_recheck.py
runs them for real)."""

from magnacoda import recheck
from magnacoda.recheck import Login
from tests.unit.test_merge import _finding, _report


def _calls(monkeypatch, report, old):
    calls = []

    def fake_test_in(report, findings, login, screen, scheme):
        calls.append((screen, scheme, sorted(f.selector for f in findings)))
        failing = {("color-contrast", "p.dark")} if scheme == "dark" else set()
        return failing, {f.finding_id: True for f in findings}

    monkeypatch.setattr(recheck, "_test_in", fake_test_in)
    return recheck._test_again(report, old, Login()), calls


def test_each_problem_is_tested_where_it_was_found(monkeypatch):
    everywhere = _finding("label", "input", criteria=("1.3.1",))
    on_mobile = _finding("target-size", "nav a", criteria=("2.5.8",))
    on_mobile.seen_in = ["mobile.light", "mobile.dark"]
    dark_only = _finding("color-contrast", "p.dark")
    dark_only.seen_in = ["desktop.dark", "mobile.dark"]
    report = _report([everywhere, on_mobile, dark_only])
    report.meta.variants = ["desktop.light", "desktop.dark", "mobile.light", "mobile.dark"]
    (still, _), calls = _calls(monkeypatch, report, [everywhere, on_mobile, dark_only])
    # A missing label doesn't change in dark mode: tested in light only, on both screens.
    assert calls == [
        ("desktop", "light", ["input"]),
        ("desktop", "dark", ["p.dark"]),
        ("mobile", "light", ["input", "nav a"]),
        ("mobile", "dark", ["p.dark"]),
    ]
    assert still == {("color-contrast", "p.dark")}


def test_a_scan_saved_before_merging_is_tested_as_it_was_scanned(monkeypatch):
    report = _report([_finding("color-contrast", "p")], screen="mobile", theme="dark")
    _, calls = _calls(monkeypatch, report, report.findings)
    assert calls == [("mobile", "dark", ["p"])]


def test_a_scan_of_dark_mode_only_is_tested_in_dark_mode(monkeypatch):
    report = _report([_finding("label", "input")], theme="dark")
    report.meta.variants = ["desktop.dark"]
    _, calls = _calls(monkeypatch, report, report.findings)
    assert calls == [("desktop", "dark", ["input"])]
