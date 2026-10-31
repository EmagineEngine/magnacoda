from magnacoda.findings.fix_templates import template_fix
from magnacoda.findings.models import Finding


def _finding(rule_id: str, html_snippet: str = "<div>") -> Finding:
    return Finding(
        finding_id="id",
        rule_id=rule_id,
        wcag_level="AA",
        severity="serious",
        description="Some axe description",
        help_url="https://dequeuniversity.com/rules/axe/x",
        selector="sel",
        html_snippet=html_snippet,
        source="axe-core",
    )


def test_known_rule_gets_specific_template():
    fix = template_fix(_finding("image-alt", "<img src='x.jpg'>"))
    assert "alt=" in fix.corrected_snippet
    assert fix.generated_by == "template"


def test_html_lang_template():
    fix = template_fix(_finding("html-has-lang"))
    assert fix.corrected_snippet == '<html lang="en">'


def test_unknown_rule_gets_generic_fallback():
    fix = template_fix(_finding("some-unmapped-rule"))
    assert "Some axe description" in fix.summary
    assert "dequeuniversity.com" in fix.summary
    assert fix.generated_by == "template"


def test_a_fallback_fix_links_the_axe_rule_and_the_w3c_page_for_each_criterion():
    finding = _finding("some-unmapped-rule")  # a rule with no template of its own
    finding.wcag_criteria = ["1.4.1"]
    fix = template_fix(finding)
    assert fix.summary == (
        "Some axe description. See axe-core rule: https://dequeuniversity.com/rules/axe/x; "
        "WCAG 1.4.1: https://www.w3.org/WAI/WCAG22/Understanding/use-of-color.html"
    )


def test_a_fallback_fix_says_what_axe_found_here():
    finding = _finding("some-unmapped-rule")
    finding.detail = "Element has no title attribute"
    assert template_fix(finding).summary.startswith(
        "Some axe description. Found: Element has no title attribute. See axe-core rule:"
    )


def test_a_list_fix_names_the_children_that_are_not_allowed():
    finding = _finding("list", "<ul><li>May 24</li><span>•</span><li>Editor</li></ul>")
    finding.detail = "List element has direct children that are not allowed: span"
    summary = template_fix(finding).summary
    assert summary.startswith(
        "Take `<span>` out from directly inside the `<ul>` or `<ol>`: move it into an `<li>`"
    )
    assert "only directly contain `<li>`, `<script>` and `<template>`" in summary


def test_a_list_fix_names_several_children_and_roles():
    finding = _finding("list")
    finding.detail = "List element has direct children that are not allowed: span, div, [role=button]"
    assert template_fix(finding).summary.startswith(
        "Take `<span>`, `<div>`, `[role=button]` out from directly inside the `<ul>` or `<ol>`: move them"
    )


def test_a_definition_list_fix_names_the_children_that_are_not_allowed():
    finding = _finding("definition-list")
    finding.detail = "dl element has direct children that are not allowed: p"
    assert template_fix(finding).summary.startswith("Take `<p>` out from directly inside the `<dl>`")


def test_a_list_fix_without_axe_message_still_says_what_to_do():
    assert "anything that isn't allowed" in template_fix(_finding("list")).summary


def test_every_finding_gets_some_fix():
    rule_ids = [
        "image-alt",
        "label",
        "color-contrast",
        "html-has-lang",
        "link-name",
        "heading-order",
        "totally-unknown",
    ]
    for rule_id in rule_ids:
        fix = template_fix(_finding(rule_id))
        assert fix.summary
