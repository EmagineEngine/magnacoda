"""One report for several screens and themes (findings/merge.py)."""

from magnacoda.findings import merge
from magnacoda.findings.models import (
    CriterionEntry,
    FeatureExample,
    Finding,
    KeyboardProblem,
    KeyboardResult,
    PageImage,
    RuleResult,
    ScanMeta,
    ScanReport,
)

DARK_RULES = {"color-contrast", "image-alt", "magnacoda/focus-not-visible"}


def _finding(rule: str, selector: str, severity: str = "serious", criteria=("1.4.3",)) -> Finding:
    return Finding(
        finding_id=f"{rule}:{selector}",
        rule_id=rule,
        wcag_criteria=list(criteria),
        severity=severity,  # type: ignore[arg-type]
        description=rule,
        selector=selector,
        html_snippet="<p>",
        source="axe-core",
    )


def _criterion(num: str, status: str) -> CriterionEntry:
    return CriterionEntry(
        num=num, title=num, level="AA", principle="p", url="u", status=status, tier="automated"
    )  # type: ignore[arg-type]


def _report(findings, screen="desktop", theme="light", **extra) -> ScanReport:
    meta = ScanMeta(
        tool_version="0",
        axe_core_version="0",
        wcag_version="2.2",
        wcag_level="AA",
        ai_tier="off",
        fixes_tier="template",
        color_scheme=theme,  # type: ignore[arg-type]
        screen=screen,  # type: ignore[arg-type]
        device="Pixel 8 Pro" if screen == "mobile" else None,
        stability_settled=True,
        stability_elapsed_ms=0,
        stability_reason="quiescent",
    )
    return ScanReport(url="https://example.test", meta=meta, findings=list(findings), **extra)


def _seen(report: ScanReport) -> dict[tuple[str, str], list[str]]:
    return {(f.rule_id, f.selector): f.seen_in for f in report.findings}


def test_a_problem_found_everywhere_is_listed_once_without_a_place():
    desktop = _report([_finding("label", "input")])
    mobile = _report([_finding("label", "input")], screen="mobile")
    merged = merge.merge([merge.Pass("desktop.light", desktop), merge.Pass("mobile.light", mobile)])
    assert _seen(merged) == {("label", "input"): []}
    assert merged.meta.variants == ["desktop.light", "mobile.light"]
    assert merged.meta.screen is None and merged.meta.device == "Pixel 8 Pro"


def test_problems_on_one_screen_say_which():
    desktop = _report([_finding("label", "input"), _finding("region", "aside")])
    mobile = _report([_finding("label", "input"), _finding("target-size", "nav a")], screen="mobile")
    merged = merge.merge([merge.Pass("desktop.light", desktop), merge.Pass("mobile.light", mobile)])
    assert _seen(merged) == {
        ("label", "input"): [],
        ("region", "aside"): ["desktop.light"],
        ("target-size", "nav a"): ["mobile.light"],
    }
    variants = merged.meta.variants
    assert merge.where_text(["mobile.light"], variants) == "only on mobile"


def test_dark_mode_counts_what_it_did_not_test_as_unchanged():
    light = _report([_finding("label", "input"), _finding("color-contrast", "p.light-only")])
    dark = _report([_finding("color-contrast", "p.dark-only")], theme="dark")
    merged = merge.merge(
        [merge.Pass("desktop.light", light), merge.Pass("desktop.dark", dark, covered=DARK_RULES)],
        dark_theme=True,
    )
    assert _seen(merged) == {
        ("label", "input"): [],  # dark mode can't change it: seen there too
        ("color-contrast", "p.light-only"): ["desktop.light"],
        ("color-contrast", "p.dark-only"): ["desktop.dark"],
    }
    assert merge.where_text(["desktop.dark"], merged.meta.variants) == "only in dark mode"
    assert merged.meta.dark_theme is True and merged.meta.color_scheme is None


def test_a_criterion_failed_only_in_dark_mode_is_failed():
    light = _report([], checklist=[_criterion("1.4.3", "passed"), _criterion("1.1.1", "passed")])
    light.passed = [RuleResult(rule_id="color-contrast", description="contrast")]
    dark = _report([_finding("color-contrast", "p")], theme="dark")
    merged = merge.merge(
        [merge.Pass("desktop.light", light), merge.Pass("desktop.dark", dark, covered=DARK_RULES)]
    )
    status = {e.num: (e.status, e.rules) for e in merged.checklist}
    assert status["1.4.3"] == ("failed", ["color-contrast"])
    assert status["1.1.1"] == ("passed", [])
    assert merged.passed == []  # it failed somewhere, so it didn't pass


def test_criteria_take_the_worse_status_of_two_screens():
    desktop = _report([], checklist=[_criterion("2.4.7", "passed")])
    mobile = _report([], screen="mobile", checklist=[_criterion("2.4.7", "failed")])
    merged = merge.merge([merge.Pass("desktop.light", desktop), merge.Pass("mobile.light", mobile)])
    assert merged.checklist[0].status == "failed"


def test_two_of_the_same_in_one_pass_stay_two():
    desktop = _report([_finding("image-alt", "img"), _finding("image-alt", "img", severity="critical")])
    merged = merge.merge([merge.Pass("desktop.light", desktop)])
    assert len(merged.findings) == 2


def test_what_magnacoda_tested_on_the_phone_is_added():
    problem = KeyboardProblem(element=FeatureExample(selector="button.menu"), kind="focus-not-visible")
    desktop = _report([], keyboard=KeyboardResult(stops=10, complete=True))
    mobile = _report(
        [], screen="mobile", keyboard=KeyboardResult(stops=12, complete=True, problems=[problem])
    )
    merged = merge.merge([merge.Pass("desktop.light", desktop), merge.Pass("mobile.light", mobile)])
    assert merged.keyboard is not None
    assert merged.keyboard.stops == 12 and [p.element.selector for p in merged.keyboard.problems] == [
        "button.menu"
    ]


def test_an_image_only_dark_mode_shows_says_so():
    light = _report([], images=[PageImage(selector="img.logo-light", kind="img")])
    dark = _report(
        [],
        theme="dark",
        images=[
            PageImage(selector="img.logo-light", kind="img"),
            PageImage(selector="img.logo-dark", kind="img"),
        ],
    )
    merged = merge.merge(
        [merge.Pass("desktop.light", light), merge.Pass("desktop.dark", dark, covered=DARK_RULES)]
    )
    assert {i.selector: i.seen_in for i in merged.images} == {
        "img.logo-light": [],
        "img.logo-dark": ["desktop.dark"],
    }


def test_where_and_what_was_tested_in_words():
    variants = ["desktop.light", "desktop.dark", "mobile.light", "mobile.dark"]
    assert merge.where_text([], variants) == ""
    assert merge.where_text(["mobile.light", "mobile.dark"], variants) == "only on mobile"
    assert merge.where_text(["mobile.dark"], variants) == "only on mobile in dark mode"
    assert merge.where_text(["desktop.dark", "mobile.dark"], variants) == "only in dark mode"
    assert merge.tested_text(variants, "Pixel 8 Pro", True) == (
        "Tested on desktop and mobile (Pixel 8 Pro), in light and dark mode."
    )
    assert merge.tested_text(["desktop.light"], None, False) == (
        "Tested on desktop, in light mode (the page looks the same in dark mode)."
    )
    assert merge.tested_text([], None, None) == ""  # saved before scans were merged
