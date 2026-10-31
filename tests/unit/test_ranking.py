from magnacoda.findings.models import Finding


def _finding(**overrides) -> Finding:
    base = dict(
        finding_id="id",
        rule_id="rule",
        wcag_level="AA",
        severity="moderate",
        description="d",
        selector="sel",
        html_snippet="<div>",
        source="axe-core",
        instance_count=1,
        dom_order_index=0,
    )
    base.update(overrides)
    return Finding(**base)


def test_sort_by_severity_first():
    critical = _finding(finding_id="c", severity="critical")
    minor = _finding(finding_id="m", severity="minor")
    ranked = sorted([minor, critical], key=Finding.sort_key)
    assert ranked == [critical, minor]


def test_sort_by_wcag_level_when_severity_ties():
    level_a = _finding(finding_id="a", severity="serious", wcag_level="A")
    level_aa = _finding(finding_id="aa", severity="serious", wcag_level="AA")
    ranked = sorted([level_aa, level_a], key=Finding.sort_key)
    assert ranked == [level_a, level_aa]


def test_sort_by_instance_count_when_severity_and_level_tie():
    broad = _finding(finding_id="broad", severity="serious", wcag_level="AA", instance_count=10)
    narrow = _finding(finding_id="narrow", severity="serious", wcag_level="AA", instance_count=1)
    ranked = sorted([narrow, broad], key=Finding.sort_key)
    assert ranked == [broad, narrow]


def test_sort_by_dom_order_as_final_tiebreak():
    first = _finding(
        finding_id="first", severity="serious", wcag_level="AA", instance_count=1, dom_order_index=0
    )
    second = _finding(
        finding_id="second",
        severity="serious",
        wcag_level="AA",
        instance_count=1,
        dom_order_index=5,
    )
    ranked = sorted([second, first], key=Finding.sort_key)
    assert ranked == [first, second]


def test_missing_wcag_level_sorts_last_within_severity():
    with_level = _finding(finding_id="with", severity="serious", wcag_level="A")
    without_level = _finding(finding_id="without", severity="serious", wcag_level=None)
    ranked = sorted([without_level, with_level], key=Finding.sort_key)
    assert ranked == [with_level, without_level]


def test_group_by_fix_collapses_shared_fix_group():
    from magnacoda.findings.models import FindingExplanation, group_by_fix

    def explained(finding_id: str, group: str | None) -> Finding:
        f = _finding(finding_id=finding_id)
        f.explanation = FindingExplanation(
            why_it_matters="w", how_to_fix="h", generated_by="claude-explain", model="m", fix_group=group
        )
        return f

    a = explained("a", "shared")
    b = explained("b", "shared")
    c = explained("c", None)
    groups = group_by_fix([a, b, c])
    assert groups == [[a, b], [c]]


def test_group_by_fix_preserves_first_occurrence_order():
    from magnacoda.findings.models import FindingExplanation, group_by_fix

    def explained(finding_id: str, group: str | None) -> Finding:
        f = _finding(finding_id=finding_id)
        f.explanation = FindingExplanation(
            why_it_matters="w", how_to_fix="h", generated_by="claude-explain", model="m", fix_group=group
        )
        return f

    a, b, c = explained("a", "g1"), explained("b", None), explained("c", "g1")
    groups = group_by_fix([a, b, c])
    assert groups == [[a, c], [b]]


def test_group_by_fix_findings_with_no_explanation_are_ungrouped():
    from magnacoda.findings.models import group_by_fix

    a, b = _finding(finding_id="a"), _finding(finding_id="b")
    assert group_by_fix([a, b]) == [[a], [b]]
