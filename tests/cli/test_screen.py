import json

from click.testing import CliRunner

from magnacoda import cli
from magnacoda.cli import main
from magnacoda.findings.models import ScanMeta, ScanReport


def _meta(config):
    return ScanMeta(
        tool_version="0",
        axe_core_version="0",
        wcag_version="2.2",
        wcag_level="AA",
        ai_tier="off",
        fixes_tier="template",
        color_scheme=config.color_scheme,
        screen=config.screen,
        device="Pixel 8 Pro" if config.screen == "mobile" else None,
        stability_settled=True,
        stability_elapsed_ms=0,
        stability_reason="quiescent",
    )


def _fake_run(seen: list):
    def fake_run_scan(config, *, consent_given=False):
        seen.append(config)
        return ScanReport(url=config.url, meta=_meta(config), findings=[])

    return fake_run_scan


def _fake_dark(dark_seen: list, findings=()):
    """A dark-mode pass that finds the page has a dark theme, with these findings."""

    def fake_dark_pass(config, light_colors):
        dark_seen.append(config)
        return ScanReport(url=config.url, meta=_meta(config), findings=list(findings))

    return fake_dark_pass


def _invoke(monkeypatch, *args, input=None):
    seen: list = []
    monkeypatch.setattr(cli, "run_scan", _fake_run(seen))
    result = CliRunner().invoke(main, ["scan", "http://example.test", *args], input=input)
    return result, seen


def test_screen_both_runs_desktop_then_mobile_into_one_report(monkeypatch):
    result, seen = _invoke(monkeypatch, "--screen", "both")
    assert result.exit_code == 0
    assert [c.screen for c in seen] == ["desktop", "mobile"]
    assert "Tested on desktop and mobile (Pixel 8 Pro)" in " ".join(result.output.split())


def test_a_single_screen_is_passed_through_and_unset_stays_unset(monkeypatch):
    assert [c.screen for c in _invoke(monkeypatch, "--screen", "mobile")[1]] == ["mobile"]
    assert [c.screen for c in _invoke(monkeypatch)[1]] == [None]


def test_viewport_and_device_are_unset_unless_given(monkeypatch):
    config = _invoke(monkeypatch)[1][0]
    assert config.viewport_width is None and config.viewport_height is None and config.device is None
    config = _invoke(monkeypatch, "--viewport", "390x844", "--device", "Pixel 5")[1][0]
    assert (config.viewport_width, config.viewport_height, config.device) == (390, 844, "Pixel 5")


def test_screen_both_refuses_to_combine_with_device_or_viewport(monkeypatch):
    for extra in (["--device", "Pixel 5"], ["--viewport", "390x844"]):
        result, seen = _invoke(monkeypatch, "--screen", "both", *extra)
        assert result.exit_code == 2 and "can't be combined" in result.output
        assert seen == []


def test_screen_mobile_may_be_combined_with_device_or_viewport(monkeypatch):
    result, seen = _invoke(monkeypatch, "--screen", "mobile", "--viewport", "500x900")
    assert result.exit_code == 0 and seen[0].viewport_width == 500


def test_screen_both_prints_one_json_with_both_screens(monkeypatch):
    result, _ = _invoke(monkeypatch, "--screen", "both", "-o", "-")
    assert result.exit_code == 0
    data = json.loads(result.stdout)  # the summary goes to stderr
    assert data["meta"]["variants"] == ["desktop.light", "mobile.light"]
    assert data["meta"]["dark_theme"] is False and data["meta"]["device"] == "Pixel 8 Pro"


def test_both_screens_and_themes_make_one_file(monkeypatch, tmp_path):
    dark_seen: list = []
    monkeypatch.setattr(cli, "run_dark_pass", _fake_dark(dark_seen))
    out = tmp_path / "report.json"
    result, seen = _invoke(monkeypatch, "--screen", "both", "-o", str(out))
    assert result.exit_code == 0
    assert [(c.screen, c.color_scheme) for c in seen] == [("desktop", "light"), ("mobile", "light")]
    assert [c.screen for c in dark_seen] == ["desktop", "mobile"]
    assert [p.name for p in tmp_path.iterdir()] == ["report.json"]
    variants = json.loads(out.read_text())["meta"]["variants"]
    assert variants == ["desktop.light", "desktop.dark", "mobile.light", "mobile.dark"]


def test_one_theme_asked_for_has_no_dark_pass(monkeypatch):
    dark_seen: list = []
    monkeypatch.setattr(cli, "run_dark_pass", _fake_dark(dark_seen))
    for scheme in ("light", "dark"):
        _, seen = _invoke(monkeypatch, "--color-scheme", scheme, "-o", "-")
        assert seen[-1].color_scheme == scheme
    assert dark_seen == []


def test_consent_counts_each_screen_not_the_dark_pass(monkeypatch):
    counts: list[int] = []
    monkeypatch.setattr(cli, "confirm_ai_usage", lambda ai, passes=1: counts.append(passes))
    _invoke(monkeypatch, "--ai", "explain", "--screen", "both")
    assert counts == [2]


def test_the_wizard_tests_both_screens_unless_told_otherwise(monkeypatch):
    seen: list = []
    monkeypatch.setattr(cli, "run_scan", _fake_run(seen))
    answers = "https://example.test\n\n\n\ny\n"  # level, AI, screens (Enter: both), run
    result = CliRunner().invoke(main, ["wizard"], input=answers)
    assert "Screens to test" in result.output and "Pixel 8 Pro" in result.output
    assert "Color scheme" not in result.output
    assert "--screen both" in result.output
    assert [c.screen for c in seen] == ["desktop", "mobile"]


def test_wizard_offers_the_screen_choice_and_shows_it_in_the_command(monkeypatch):
    seen: list = []
    monkeypatch.setattr(cli, "run_scan", _fake_run(seen))
    answers = "https://example.test\n\n\nmobile\ny\n"  # level, AI, screens, run
    result = CliRunner().invoke(main, ["wizard"], input=answers)
    assert "--screen mobile" in result.output
    assert seen and seen[0].screen == "mobile" and seen[0].viewport_width is None
    seen.clear()
    answers = "new\nhttps://example.test\n\n\ndesktop\ny\n"  # new: not a recent scan
    result = CliRunner().invoke(main, ["wizard"], input=answers)
    assert "--screen" not in result.output.split("Equivalent command:")[1]  # desktop is the default
    assert [c.screen for c in seen] == [None]
