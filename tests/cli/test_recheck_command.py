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
    monkeypatch.setattr(cli, "_is_interactive", lambda: True)
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
    monkeypatch.setattr(cli, "_is_interactive", lambda: True)
    out = CliRunner().invoke(main, ["recheck"], input="1\n").output
    assert "can't be rechecked: scan the page again" in out


def _fake_recheck(monkeypatch):
    rechecked = []

    def fake(variants, on_variant=None, login=None):
        rechecked.append(True)
        return recheck.RecheckResult(datetime(2026, 10, 12), [recheck.VariantResult("", fixed=1)])

    monkeypatch.setattr(recheck, "recheck_scan", fake)
    return rechecked


def test_with_no_person_there_the_scan_is_named_and_rechecked_only_up_to_the_limit(tmp_path, monkeypatch):
    folder = _scan_folder(tmp_path)
    monkeypatch.chdir(tmp_path)
    rechecked = _fake_recheck(monkeypatch)
    runs = [CliRunner().invoke(main, ["recheck", str(folder)]) for _ in range(4)]
    assert [run.exit_code for run in runs] == [0, 0, 0, 2] and len(rechecked) == 3
    assert "rechecked 3 times with no person at the keyboard" in " ".join(runs[3].output.split())


def test_with_no_person_there_and_no_scan_named_it_says_to_name_one(tmp_path, monkeypatch):
    _scan_folder(tmp_path)
    monkeypatch.chdir(tmp_path)
    rechecked = _fake_recheck(monkeypatch)
    result = CliRunner().invoke(main, ["recheck"])
    assert result.exit_code == 2 and "Name the scan to recheck" in result.output and rechecked == []


def test_a_persons_own_rechecks_are_not_limited(tmp_path, monkeypatch):
    folder = _scan_folder(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "_is_interactive", lambda: True)
    monkeypatch.setattr(browser, "browser_available", lambda: False)
    rechecked = _fake_recheck(monkeypatch)
    for _ in range(4):
        assert CliRunner().invoke(main, ["recheck", str(folder)]).exit_code == 0
    assert len(rechecked) == 4
