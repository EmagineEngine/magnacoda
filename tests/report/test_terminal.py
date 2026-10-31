from io import StringIO

from rich.console import Console

from magnacoda.findings.models import Finding, ScanMeta, ScanReport
from magnacoda.report import terminal


def _finding(i: int, selector: str = "label > .req") -> Finding:
    return Finding(
        finding_id=f"f{i}",
        rule_id="color-contrast",
        wcag_criteria=["1.4.3"],
        wcag_level="AA",
        severity="serious",
        description="Elements must meet minimum color contrast ratio thresholds",
        detail=f"Element has insufficient color contrast of 2.{i} (foreground color: #aaa)",
        selector=selector,
        html_snippet="<span>",
        source="axe-core",
        instance_count=7,
        dom_order_index=i,
    )


def _report(findings: list[Finding]) -> ScanReport:
    meta = ScanMeta(
        tool_version="0",
        axe_core_version="0",
        wcag_version="2.2",
        wcag_level="AA",
        ai_tier="off",
        fixes_tier="off",
        stability_settled=True,
        stability_elapsed_ms=0,
        stability_reason="quiescent",
    )
    return ScanReport(url="http://example.test", meta=meta, findings=findings)


def _render(report: ScanReport, monkeypatch) -> str:
    buffer = StringIO()
    monkeypatch.setattr(terminal, "Console", lambda **kw: Console(file=buffer, width=140, **kw))
    terminal.render_report(report, no_color=True)
    return buffer.getvalue()


def test_same_rule_findings_are_grouped_into_one_row(monkeypatch):
    out = _render(_report([_finding(i) for i in range(4)]), monkeypatch)
    assert out.count("color-contrast") == 1
    assert "2.0" in out and "2.3" in out


def test_rule_name_is_not_truncated(monkeypatch):
    out = _render(_report([_finding(0)]), monkeypatch)
    assert "color-contrast" in out and "…" not in out


def test_instances_are_capped_with_overflow_note(monkeypatch):
    out = _render(_report([_finding(i) for i in range(8)]), monkeypatch)
    assert "+3 more" in out


def test_selector_with_brackets_is_not_treated_as_markup(monkeypatch):
    out = _render(_report([_finding(0, selector="a[href]")]), monkeypatch)
    assert "a[href]" in out


def test_heading_is_rendered_above_the_report(monkeypatch):
    buffer = StringIO()
    monkeypatch.setattr(terminal, "Console", lambda **kw: Console(file=buffer, width=140, **kw))
    terminal.render_report(_report([_finding(0)]), no_color=True, heading="Dark theme")
    out = buffer.getvalue()
    assert "Dark theme" in out
    assert out.index("Dark theme") < out.index("magnacoda")


def test_no_heading_by_default(monkeypatch):
    assert "theme" not in _render(_report([_finding(0)]), monkeypatch).lower()


def _report_with_coverage(findings: list[Finding]) -> ScanReport:
    from magnacoda.findings.models import RuleResult

    base = _report(findings)
    base.passed = [
        RuleResult(
            rule_id="document-title",
            description="Documents must have a title",
            wcag_criteria=["2.4.2"],
            wcag_level="A",
            instance_count=1,
        )
    ]
    base.needs_review = [
        RuleResult(
            rule_id="color-contrast",
            description="Contrast over an image",
            wcag_criteria=["1.4.3"],
            wcag_level="AA",
            instance_count=2,
        )
    ]
    base.inapplicable_count = 51
    return base


def test_passed_and_needs_review_sections_are_shown(monkeypatch):
    out = _render(_report_with_coverage([_finding(0)]), monkeypatch)
    assert "Passed checks (1)" in out and "document-title" in out
    assert "Needs manual review (1)" in out
    assert "51 other rules did not apply" in out
    assert "not a full audit" in out


def test_coverage_is_shown_even_when_there_are_no_violations(monkeypatch):
    out = _render(_report_with_coverage([]), monkeypatch)
    assert "No violations found" in out and "Passed checks (1)" in out


def test_show_passed_false_hides_sections(monkeypatch):
    buffer = StringIO()
    monkeypatch.setattr(terminal, "Console", lambda **kw: Console(file=buffer, width=140, **kw))
    terminal.render_report(_report_with_coverage([_finding(0)]), no_color=True, show_passed=False)
    assert "Passed checks" not in buffer.getvalue()


def _report_with_checklist() -> ScanReport:
    from magnacoda.findings.models import CriterionEntry

    def entry(num: str, tier: str, reason: str | None = None) -> CriterionEntry:
        return CriterionEntry(
            num=num,
            title=f"Title {num}",
            level="AA",
            principle="Operable",
            url=f"https://www.w3.org/WAI/WCAG22/Understanding/x-{num}.html",
            status="not_automated",
            tier=tier,  # type: ignore[arg-type]
            how_to_check=f"how {num}",
            reason=reason,
        )

    base = _report([])
    base.checklist = [
        entry("3.3.8", "relevant", "found 1 password field"),
        entry("2.4.7", "every_page"),
        entry("3.2.3", "depends", "site-level"),
        entry("1.2.2", "likely_na", "no video"),
    ]
    return base


def test_relevant_checks_are_listed_and_others_summarised(monkeypatch):
    out = _render(_report_with_checklist(), monkeypatch)
    assert "relevant to this page (1)" in out
    assert "3.3.8" in out and "found 1 password field" in out and "how 3.3.8" in out
    assert "1 to check on every page" in out and "1 that depend" in out and "1 probably not applicable" in out
    assert "The scan's checklist has the full list" in " ".join(out.split())
    assert "how 2.4.7" not in out  # only the relevant tier is expanded in the terminal


def _explained_finding(i: int, fix_group: str | None, selector: str) -> Finding:
    from magnacoda.findings.models import FindingExplanation, FindingFix

    f = Finding(
        finding_id=f"e{i}",
        rule_id="color-contrast",
        wcag_criteria=["1.4.3"],
        wcag_level="AA",
        severity="serious",
        description="d",
        selector=selector,
        html_snippet="<span>",
        source="axe-core",
        dom_order_index=i,
    )
    f.explanation = FindingExplanation(
        why_it_matters="why", how_to_fix="how", generated_by="claude-explain", model="m", fix_group=fix_group
    )
    f.fix = FindingFix(corrected_snippet="color: #000;", summary="darken it", generated_by="claude-explain")
    return f


def test_grouped_ai_explanations_render_as_one_panel(monkeypatch):
    findings = [
        _explained_finding(0, "shared", "label[for=a] > .req"),
        _explained_finding(1, "shared", "label[for=b] > .req"),
        _explained_finding(2, None, "a"),
    ]
    out = _render(_report(findings), monkeypatch)
    assert out.count("Why it matters") == 2  # one panel for the group, one for the lone finding
    assert "Same fix applies to 2 elements" in out
    assert "label[for=a] > .req" in out and "label[for=b] > .req" in out
    assert "1. color-contrast (2 elements)" in out
    assert "2. color-contrast (a)" in out


def test_why_here_names_the_first_two_elements():
    from magnacoda.findings.models import CriterionEntry, FeatureExample
    from magnacoda.report.terminal import _why_here

    entry = CriterionEntry(
        num="2.4.11",
        title="t",
        level="AA",
        principle="p",
        url="u",
        status="not_automated",
        tier="relevant",
        reason="found 3 fixed/sticky elements",
        examples=[FeatureExample(selector=f"div#s{i}", hint="Cookies" if i == 0 else "") for i in range(3)],
    )
    assert _why_here(entry) == 'found 3 fixed/sticky elements\ne.g. div#s0 ("Cookies")\ne.g. div#s1'


def test_the_terminal_says_how_many_elements_are_hidden_but_reachable():
    from io import StringIO

    from rich.console import Console

    from magnacoda.findings.models import PageFeatures
    from magnacoda.report.terminal import _render_checklist
    from tests.report.test_markdown import _report

    report = _report()
    report.page_features = PageFeatures(hidden_reachable=2)
    out = StringIO()
    _render_checklist(Console(file=out, width=200, color_system=None), report)
    assert "Hidden but reachable: 2 elements" in out.getvalue()
