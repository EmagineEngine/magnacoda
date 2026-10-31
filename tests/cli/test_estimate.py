"""The wizard's time estimate (estimate.py and cli._offer_faster): what it says, and the settings it
offers to make a scan faster. The page check itself is faked; tests/integration runs it for real."""

import dataclasses

import click
from click.testing import CliRunner

from magnacoda import cli, estimate, preferences
from magnacoda.cli import main
from tests.cli.test_wizard import _answers

PROBE = estimate.PageProbe(
    startup=2.0, settle=0.6, elements=2000, images=4, forms=1, fields=3, focusable=60, hover=4, toggles=5,
    speed=1.0,
)  # fmt: skip


def test_the_estimate_adds_up_the_parts_for_each_scan():
    thorough = estimate.estimate(PROBE, estimate.Choices(scans=4, ai="explain"))
    assert thorough.total == thorough.per_scan * 4 and thorough.parts["AI"] == 30.0
    quick = estimate.estimate(PROBE, estimate.Choices(scans=4, quick=True, ai="explain"))
    assert "moving content, hovering, clicking and single keys" not in quick.parts
    assert quick.total < thorough.total
    assert estimate.duration(42) == "about 40 seconds" and estimate.duration(100) == "about 1 min 40 s"
    assert estimate.duration(2) == "about 5 seconds" and estimate.duration(120) == "about 2 min"


def _wizard(monkeypatch, picks: str, **answers):
    """The wizard, then "Run this scan now?" yes; the scan then checks the page (faked) and asks."""
    from magnacoda.browser import redirects
    from tests.cli.test_screen import _fake_run

    seen, scanned = [], []
    monkeypatch.setattr(estimate, "probe_page", lambda config: seen.append(config) or PROBE)
    load = preferences.load
    monkeypatch.setattr(preferences, "load", lambda: dataclasses.replace(load(), quick=False, estimate=True))
    monkeypatch.setattr(cli, "_is_interactive", lambda: True)
    monkeypatch.setattr(cli, "run_scan", _fake_run(scanned))
    monkeypatch.setattr(redirects, "check_address", lambda url, **kw: None)
    text = _answers(**{"confirm": "y", **answers}) + picks + "\n"
    result = CliRunner().invoke(main, ["wizard"], input=text)
    return " ".join(result.output.split()), seen, scanned


def test_the_wizard_says_how_long_and_offers_faster_settings(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    out, seen, _ = _wizard(monkeypatch, "", url="example.com", screen="both", ai="explain")
    assert seen[0].url == "https://example.com" and seen[0].screen == "desktop"  # as the first scan sees it
    assert out.index("Run this scan now?") < out.index("Estimated time: about")  # the scan says it
    assert "(desktop and mobile, about" in out
    assert "1. Quick scan" in out and "2. Desktop only" in out and "4. No AI" in out
    assert "3. Light mode only, not dark mode too" in out


def test_picking_settings_runs_the_scan_with_them_and_history_keeps_them(monkeypatch, tmp_path):
    from magnacoda import history

    monkeypatch.chdir(tmp_path)
    out, seen, scanned = _wizard(monkeypatch, "1 2\n", url="example.com", screen="both")
    assert "--quick" in out.split("Equivalent command:")[-1]
    assert len(seen) == 1  # the page is checked once, not again for the faster scan
    assert scanned and all(config.quick for config in scanned) and len(scanned) == 1  # desktop only
    assert "--quick" in history.read()[0].command


def test_a_page_that_cannot_be_checked_does_not_stop_the_scan(monkeypatch, tmp_path):
    from magnacoda.browser import redirects
    from magnacoda.exceptions import NavigationError
    from tests.cli.test_screen import _fake_run

    def fail(config):
        raise NavigationError("Could not load https://example.com: connection refused")

    monkeypatch.chdir(tmp_path)
    scanned: list = []
    monkeypatch.setattr(estimate, "probe_page", fail)
    load = preferences.load
    monkeypatch.setattr(preferences, "load", lambda: dataclasses.replace(load(), estimate=True))
    monkeypatch.setattr(cli, "_is_interactive", lambda: True)
    monkeypatch.setattr(cli, "run_scan", _fake_run(scanned))
    monkeypatch.setattr(redirects, "check_address", lambda url, **kw: None)
    answers = _answers(url="example.com", confirm="y")
    out = " ".join(CliRunner().invoke(main, ["wizard"], input=answers).output.split())
    assert "Couldn't check the page first" in out and "connection refused" in out
    assert scanned  # the scan went ahead


def test_several_numbers_may_be_separated_by_spaces_or_commas():
    @click.command()
    def ask() -> None:
        click.echo(f"PICKED={estimate._pick_numbers('Which', 3)}")

    for typed in ("1 3", "1,3", "1, 3", " 3 , 1 "):
        assert "PICKED=[0, 2]" in CliRunner().invoke(ask, input=f"{typed}\n").output, typed


def _typed_scan(monkeypatch, typed: str):
    """`scan example.com` with a person there: Enter at "Scan with these settings?", then `typed`."""
    from magnacoda.browser import redirects
    from tests.cli.test_screen import _fake_run

    seen: list = []
    monkeypatch.setattr(estimate, "probe_page", lambda config: PROBE)
    load = preferences.load
    monkeypatch.setattr(preferences, "load", lambda: dataclasses.replace(load(), quick=False, estimate=True))
    monkeypatch.setattr(cli, "_is_interactive", lambda: True)
    monkeypatch.setattr(cli, "run_scan", _fake_run(seen))
    monkeypatch.setattr(redirects, "check_address", lambda url, **kw: None)
    result = CliRunner().invoke(main, ["scan", "example.com"], input=f"\n{typed}\n")
    return " ".join(result.output.split()), seen


def test_a_typed_scan_says_how_long_and_offers_faster_settings_too(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    out, seen = _typed_scan(monkeypatch, "")  # Enter: run as-is
    assert "Scan with these settings? [Y/n]" in out and "Estimated time: about" in out
    assert "[run as-is]" in out and seen and seen[0].quick is False
    out, seen = _typed_scan(monkeypatch, "1\n")  # the quick scan, then run it as it now is
    assert "--quick" in out.split("Equivalent command:")[-1] and seen[0].quick is True
