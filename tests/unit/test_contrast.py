from magnacoda.findings.contrast import (
    _parse_hex,
    contrast_ratio,
    parse_expected_ratio,
    suggest_passing_color,
)
from magnacoda.findings.fix_templates import template_fix
from magnacoda.findings.models import Finding


def _ratio(fg: str, bg: str) -> float:
    fg_rgb, bg_rgb = _parse_hex(fg), _parse_hex(bg)
    assert fg_rgb and bg_rgb
    return contrast_ratio(fg_rgb, bg_rgb)


def test_known_contrast_ratios():
    assert round(_ratio("#000000", "#ffffff"), 2) == 21.0
    assert round(_ratio("#767676", "#ffffff"), 2) == 4.54


def test_suggestion_meets_target_and_is_close_for_grey():
    suggestion = suggest_passing_color("#aaaaaa", "#ffffff", 4.5)
    assert suggestion is not None
    assert _ratio(suggestion, "#ffffff") >= 4.5
    assert abs(int(suggestion[1:3], 16) - 0x76) <= 2


def test_suggestion_preserves_hue_for_the_real_world_case():
    suggestion = suggest_passing_color("#c25b62", "#ffffff", 4.5)
    assert suggestion is not None
    assert _ratio(suggestion, "#ffffff") >= 4.5
    r, g, b = _parse_hex(suggestion)  # type: ignore[misc]
    assert r > g and r > b


def test_suggestion_lightens_on_dark_backgrounds():
    suggestion = suggest_passing_color("#555555", "#000000", 4.5)
    assert suggestion is not None
    assert _ratio(suggestion, "#000000") >= 4.5
    assert int(suggestion[1:3], 16) > 0x55


def test_already_passing_color_is_returned_unchanged_in_ratio_terms():
    suggestion = suggest_passing_color("#000000", "#ffffff", 4.5)
    assert suggestion is not None and _ratio(suggestion, "#ffffff") >= 4.5


def test_unparseable_color_returns_none():
    assert suggest_passing_color("rgba(0,0,0,0.5)", "#ffffff", 4.5) is None


def test_parse_expected_ratio():
    assert parse_expected_ratio("4.5:1") == 4.5
    assert parse_expected_ratio("3:1") == 3.0
    assert parse_expected_ratio("nonsense") is None


def _contrast_finding(**data) -> Finding:
    return Finding(
        finding_id="x",
        rule_id="color-contrast",
        wcag_level="AA",
        severity="serious",
        description="d",
        selector="label > .req",
        html_snippet="<span class='req'>*</span>",
        source="axe-core",
        check_data={"fgColor": "#c25b62", "bgColor": "#ffffff", "expectedContrastRatio": "4.5:1", **data},
    )


def test_template_fix_names_a_specific_passing_color():
    fix = template_fix(_contrast_finding())
    assert "#c25b62" in fix.summary and "needs 4.5:1" in fix.summary
    assert fix.corrected_snippet.startswith("/* label > .req */\ncolor: #")


def test_template_fix_honours_large_text_threshold():
    fix = template_fix(_contrast_finding(expectedContrastRatio="3:1"))
    assert "needs 3:1" in fix.summary


def test_template_fix_falls_back_without_color_data():
    finding = _contrast_finding()
    finding.check_data = None
    assert "contrast ratio" in template_fix(finding).summary
