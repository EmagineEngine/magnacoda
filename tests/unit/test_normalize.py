import json
from pathlib import Path

from magnacoda.findings.normalize import axe_raw_to_findings

FIXTURE = Path(__file__).parent.parent / "fixtures" / "axe_raw" / "static_violations.json"


def _load_raw() -> dict:
    return json.loads(FIXTURE.read_text())


def test_normalize_produces_expected_rule_ids():
    findings = axe_raw_to_findings(_load_raw(), "http://example.test/page")
    rule_ids = {f.rule_id for f in findings}
    assert {"image-alt", "label", "html-has-lang", "color-contrast"} <= rule_ids


def test_normalize_sets_source_and_confidence():
    findings = axe_raw_to_findings(_load_raw(), "http://example.test/page")
    assert all(f.source == "axe-core" for f in findings)
    assert all(f.confidence == "certain" for f in findings)


def test_normalize_maps_wcag_criteria():
    findings = axe_raw_to_findings(_load_raw(), "http://example.test/page")
    image_alt = next(f for f in findings if f.rule_id == "image-alt")
    assert "1.1.1" in image_alt.wcag_criteria
    assert image_alt.wcag_level == "A"


def test_normalize_finding_id_is_stable():
    findings_a = axe_raw_to_findings(_load_raw(), "http://example.test/page")
    findings_b = axe_raw_to_findings(_load_raw(), "http://example.test/page")
    assert [f.finding_id for f in findings_a] == [f.finding_id for f in findings_b]


def test_normalize_finding_id_differs_by_url():
    findings_a = axe_raw_to_findings(_load_raw(), "http://example.test/page-a")
    findings_b = axe_raw_to_findings(_load_raw(), "http://example.test/page-b")
    assert {f.finding_id for f in findings_a}.isdisjoint({f.finding_id for f in findings_b})


def test_normalize_dom_order_index_is_sequential():
    findings = axe_raw_to_findings(_load_raw(), "http://example.test/page")
    indices = [f.dom_order_index for f in findings]
    assert indices == sorted(indices)
    assert indices == list(range(len(indices)))


def test_normalize_captures_contrast_detail():
    findings = axe_raw_to_findings(_load_raw(), "http://example.test/page")
    contrast = next(f for f in findings if f.rule_id == "color-contrast")
    assert contrast.detail is not None
    assert "2.32" in contrast.detail
    assert "#aaaaaa" in contrast.detail


def test_passed_rules_exclude_rules_that_also_have_violations():
    from magnacoda.findings.normalize import axe_rule_results

    raw = _load_raw()
    violation_ids = {v["id"] for v in raw["violations"]}
    passed = axe_rule_results(raw, "passes", exclude_ids=violation_ids)
    ids = {r.rule_id for r in passed}
    assert "document-title" in ids
    assert "color-contrast" not in ids  # some elements passed, but the rule has violations
    doc_title = next(r for r in passed if r.rule_id == "document-title")
    assert "2.4.2" in doc_title.wcag_criteria and doc_title.wcag_level == "A"


def test_rule_results_are_ordered_by_success_criterion():
    from magnacoda.findings.normalize import axe_rule_results

    passed = axe_rule_results(_load_raw(), "passes")
    firsts = [[int(p) for p in r.wcag_criteria[0].split(".")] for r in passed if r.wcag_criteria]
    assert firsts == sorted(firsts)


def test_needs_review_items_carry_selector_and_reason():
    from magnacoda.findings.normalize import axe_rule_results

    raw = {
        "incomplete": [
            {
                "id": "color-contrast",
                "help": "Elements must meet minimum color contrast ratio thresholds",
                "tags": ["wcag2aa", "wcag143"],
                "nodes": [
                    {
                        "target": ["#group_type"],
                        "html": "<select>",
                        "any": [
                            {"message": "background color could not be determined due to a background image"}
                        ],
                    }
                ],
            }
        ]
    }
    [result] = axe_rule_results(raw, "incomplete")
    assert result.details == [
        "#group_type - background color could not be determined due to a background image"
    ]


def test_form_fields_that_change_the_context_become_serious_3_2_2_findings_with_a_fix():
    from magnacoda.findings.fix_templates import template_fix
    from magnacoda.findings.models import FeatureExample, OnInputProblem, OnInputResult
    from magnacoda.findings.normalize import on_input_findings

    problem = OnInputProblem(
        element=FeatureExample(selector="#lang", hint="Language"),
        effect="started loading another page",
        html='<select id="lang">',
    )
    (finding,) = on_input_findings(OnInputResult(tested=3, problems=[problem]), "http://x.test/", start=7)
    assert finding.rule_id == "magnacoda/on-input" and finding.wcag_criteria == ["3.2.2"]
    assert finding.severity == "serious" and finding.source == "magnacoda" and finding.dom_order_index == 7
    assert finding.description.startswith("Changing this field's value started loading another page")
    assert "button" in template_fix(finding).summary
    assert on_input_findings(None, "http://x.test/", start=0) == []


def test_sending_forms_empty_finds_missing_untied_and_unannounced_error_text():
    from magnacoda.findings.fix_templates import template_fix
    from magnacoda.findings.models import EmptySubmitCheck, EmptySubmitResult, FeatureExample, FormFieldError
    from magnacoda.findings.normalize import empty_submit_findings

    def field(selector, invalid=True, message=None):
        return FormFieldError(element=FeatureExample(selector=selector), invalid=invalid, message=message)

    result = EmptySubmitResult(
        tested=4,
        forms=[
            EmptySubmitCheck(form=FeatureExample(selector="#a"), outcome="page", fields=[field("#a1")]),
            EmptySubmitCheck(
                form=FeatureExample(selector="#b"),
                outcome="page",
                messages=["Fix the errors below."],
                fields=[field("#b1"), field("#b2", message="Enter a date.")],
            ),
            EmptySubmitCheck(
                form=FeatureExample(selector="#c"),
                outcome="page",
                announced=True,
                fields=[field("#c1", message="Required.")],
            ),
            EmptySubmitCheck(form=FeatureExample(selector="#d"), outcome="sent", required=3),
        ],
    )
    found = {(f.rule_id, f.selector): f for f in empty_submit_findings(result, "http://x.test/", start=0)}
    assert set(found) == {
        ("magnacoda/error-without-text", "#a1"),
        ("magnacoda/error-not-tied", "#b1"),
        ("magnacoda/error-not-announced", "#b"),
    }
    assert found[("magnacoda/error-without-text", "#a1")].severity == "serious"
    assert found[("magnacoda/error-not-tied", "#b1")].wcag_criteria == ["3.3.1"]
    unannounced = found[("magnacoda/error-not-announced", "#b")]
    assert unannounced.wcag_criteria == ["4.1.3"] and '"Fix the errors below."' in unannounced.description
    assert all(template_fix(f).summary for f in found.values())
    assert empty_submit_findings(None, "http://x.test/", start=0) == []


def test_keyboard_problems_become_findings_with_fixes():
    from magnacoda.findings.fix_templates import template_fix
    from magnacoda.findings.models import FeatureExample, KeyboardProblem, KeyboardResult
    from magnacoda.findings.normalize import keyboard_findings

    kinds = ["focus-not-visible", "focus-obscured", "on-focus", "keyboard-trap", "skip-link"]
    result = KeyboardResult(
        stops=5,
        problems=[
            KeyboardProblem(element=FeatureExample(selector=f"#e{i}"), kind=kind, detail="covered by #x")
            for i, kind in enumerate(kinds)
        ],
    )
    found = keyboard_findings(result, "http://x.test/", start=3)
    assert [f.wcag_criteria[0] for f in found] == ["2.4.7", "2.4.11", "3.2.1", "2.1.2", "2.4.1"]
    assert found[3].severity == "critical" and found[1].description.endswith("covered by #x")
    assert all(f.source == "magnacoda" and template_fix(f).summary for f in found)
    assert keyboard_findings(None, "http://x.test/", start=0) == []


def test_layout_problems_become_findings_with_fixes():
    from magnacoda.findings.fix_templates import template_fix
    from magnacoda.findings.models import FeatureExample, LayoutProblem, LayoutResult
    from magnacoda.findings.normalize import layout_findings

    kinds = ["reflow", "reflow-table", "spacing-clipped", "spacing-spills", "resize-clipped"]
    problems = [
        LayoutProblem(element=FeatureExample(selector=f"#e{i}"), kind=kind, detail="40 px")
        for i, kind in enumerate(kinds)
    ]
    problems.append(LayoutProblem(element=FeatureExample(selector=""), kind="reflow", detail="12 px"))
    found = layout_findings(LayoutResult(tested=True, problems=problems), "http://x.test/", start=0)
    assert [f.wcag_criteria[0] for f in found] == ["1.4.10", "1.4.10", "1.4.12", "1.4.12", "1.4.4", "1.4.10"]
    assert "sticks out 40 px past the edge" in found[0].description
    assert "the page is 12 px wider than the window" in found[-1].description and found[-1].selector == ""
    assert all(template_fix(f).summary for f in found)


def test_field_purposes_are_guessed_from_labels_types_and_names():
    from magnacoda.browser.fields import guess_purpose

    assert guess_purpose("Email address *", "", "", "text") == ("email", "email address")
    assert guess_purpose("", "billing_postcode", "", "text")[0] == "postal-code"
    assert guess_purpose("", "", "lastName", "text")[0] == "family-name"
    assert guess_purpose("Name on card", "", "", "text")[0] == "cc-name"
    assert guess_purpose("Your name", "", "", "text")[0] == "name"
    assert guess_purpose("Choose a new password", "", "", "password")[0] == "new-password"
    assert guess_purpose("Product name", "", "", "text") is None  # not the visitor's own
    assert guess_purpose("Favourite colour", "q", "", "text") is None


def test_field_problems_become_findings_with_fixes_that_show_the_corrected_field():
    from magnacoda.findings.fix_templates import template_fix
    from magnacoda.findings.models import FeatureExample, FieldProblem, FieldsResult
    from magnacoda.findings.normalize import fields_findings

    def problem(kind, html, **kw):
        return FieldProblem(element=FeatureExample(selector="#f"), kind=kind, html=html, **kw)

    result = FieldsResult(
        problems=[
            problem("paste-blocked", '<input type="password" onpaste="return false">'),
            problem("password-autocomplete-off", '<input type="password" autocomplete="off">'),
            problem(
                "missing-autocomplete",
                '<input id="t" autocomplete="off">',
                detail="tel",
                purpose="phone number",
                off=True,
            ),
        ]
    )
    paste, off, missing = fields_findings(result, "http://x.test/", start=0)
    assert paste.wcag_criteria == ["3.3.8"] and paste.severity == "serious"
    assert template_fix(paste).corrected_snippet == '<input type="password">'
    assert template_fix(off).corrected_snippet == '<input type="password" autocomplete="current-password">'
    assert missing.wcag_criteria == ["1.3.5"] and 'has autocomplete="off"' in missing.description
    assert template_fix(missing).corrected_snippet == '<input id="t" autocomplete="tel">'


def test_interaction_problems_become_findings_with_fixes():
    from magnacoda.findings.fix_templates import template_fix
    from magnacoda.findings.models import FeatureExample, InteractionResult, PageProblem
    from magnacoda.findings.normalize import _INTERACTION_RULES, interaction_findings

    result = InteractionResult(
        problems=[
            PageProblem(element=FeatureExample(selector=f"#e{i}"), kind=kind, detail='"x"')
            for i, kind in enumerate(_INTERACTION_RULES)
        ]
    )
    found = interaction_findings(result, "http://x.test/", start=0)
    assert len(found) == len(_INTERACTION_RULES)
    assert {f.wcag_criteria[0] for f in found} == {"1.4.13", "4.1.2", "2.1.1", "2.2.2", "2.1.4", "2.2.1"}
    assert all(
        f.source == "magnacoda" and "{" not in f.description and template_fix(f).summary for f in found
    )


def test_an_option_group_without_a_name_becomes_a_1_3_1_finding_with_a_fieldset_fix():
    from magnacoda.findings.fix_templates import template_fix
    from magnacoda.findings.models import FeatureExample, OptionGroup
    from magnacoda.findings.normalize import option_group_findings

    options = [FeatureExample(selector="#s"), FeatureExample(selector="#l")]
    groups = [
        OptionGroup(element=FeatureExample(selector="div.sizes"), options=options, named=False),
        OptionGroup(element=FeatureExample(selector="fieldset"), options=options, named=True),
    ]
    (finding,) = option_group_findings(groups, "http://x.test/", start=0)
    assert finding.selector == "div.sizes" and finding.wcag_criteria == ["1.3.1"]
    assert finding.description.startswith("These 2 options answer one question")
    assert "<legend>" in template_fix(finding).corrected_snippet
