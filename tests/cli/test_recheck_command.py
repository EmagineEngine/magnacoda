"""The recheck command: picking a saved scan and saying what the recheck found (recheck.py itself is
tested with a real browser in tests/integration/test_recheck.py)."""

from datetime import datetime

from click.testing import CliRunner

from magnacoda import cli, recheck
from magnacoda.cli import main
from magnacoda.pager import browser
from tests.unit.test_review import _scan_folder


def test_recheck_picks_a_scan_and_says_what_it_found(tmp_path, monkeypatch):
    _scan_folder(tmp_path, ("light", "dark"))
    monkeypatch.chdir(tmp_path)
    seen = []

    def fake(variants, on_variant=None, login=None):
        seen.extend(v.label for v in variants)
        return recheck.RecheckResult(
            datetime(2026, 10, 12),
            [recheck.VariantResult("light", fixed=2, failing=1), recheck.VariantResult("dark", fixed=3)],
        )

    monkeypatch.setattr(recheck, "recheck_scan", fake)
    monkeypatch.setattr(browser, "browser_available", lambda: False)
    out = " ".join(CliRunner().invoke(main, ["recheck"], input="1\n").output.split())
    assert seen == ["light", "dark"]
    assert "Rechecked example.test: 5 of 6 problems fixed; 1 still fails." in out
    assert "scan the page again before release" in out and "Type magnacoda review to see it." in out


def test_a_scan_from_an_older_magnacoda_cannot_be_rechecked(tmp_path, monkeypatch):
    old = tmp_path / "magnacoda-scans"
    old.mkdir()
    (old / "site_20261001-090000.md").write_text("# Old\n\n- [ ] **[1.1.1 X](https://x)** (A) - a\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "_review_in_browser", lambda scan: False)
    out = CliRunner().invoke(main, ["recheck"], input="1\n").output
    assert "can't be rechecked: scan the page again" in out
