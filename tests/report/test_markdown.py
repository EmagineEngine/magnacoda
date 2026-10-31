from magnacoda.findings.models import (
    CriterionEntry,
    Finding,
    FindingExplanation,
    FindingFix,
    RuleResult,
    ScanMeta,
    ScanReport,
)
from magnacoda.report.markdown_export import to_markdown


def _entry(num: str, tier: str, status: str = "not_automated", **kw) -> CriterionEntry:
    return CriterionEntry(
        num=num,
        title=f"Title {num}",
        level="AA",
        principle="Operable",
        url=f"https://www.w3.org/WAI/WCAG22/Understanding/x-{num}.html",
        status=status,  # type: ignore[arg-type]
        tier=tier,  # type: ignore[arg-type]
        how_to_check=f"how {num}",
        **kw,
    )


def _report() -> ScanReport:
    meta = ScanMeta(
        tool_version="0",
        axe_core_version="4",
        wcag_version="2.2",
        wcag_level="AA",
        ai_tier="off",
        fixes_tier="off",
        color_scheme="dark",
        stability_settled=True,
        stability_elapsed_ms=0,
        stability_reason="quiescent",
    )
    finding = Finding(
        finding_id="f",
        rule_id="color-contrast",
        wcag_criteria=["1.4.3"],
        wcag_level="AA",
        severity="serious",
        description="d",
        selector="p",
        html_snippet="<p>",
        source="axe-core",
    )
    return ScanReport(
        url="http://example.test",
        meta=meta,
        findings=[finding],
        needs_review=[
            RuleResult(rule_id="color-contrast", description="d", details=["#group_type - background image"])
        ],
        checklist=[
            _entry("1.4.3", "automated", "failed", rules=["color-contrast"]),
            _entry("3.3.8", "relevant", reason="found 1 password field"),
            _entry("2.4.7", "every_page"),
            _entry("3.2.3", "depends", reason="site-level"),
            _entry("2.4.2", "automated", "passed", follow_up="confirm the title is descriptive"),
            _entry("1.1.1", "automated", "no_elements"),
            _entry("1.2.2", "likely_na", reason="no video detected"),
        ],
    )


def test_markdown_has_all_sections_in_order():
    md = to_markdown(_report())
    order = [
        "## Page elements",
        "## Check first: relevant to this page",
        "## Check on every page",
        "## Depends on your site or user flows",
        "## Passed automated checks",
        "## Probably not applicable",
    ]
    positions = [md.index(heading) for heading in order]
    assert positions == sorted(positions)


def test_markdown_links_and_checkboxes():
    md = to_markdown(_report())
    assert (
        "- [ ] **[3.3.8 Title 3.3.8](https://www.w3.org/WAI/WCAG22/Understanding/x-3.3.8.html)** (AA)" in md
    )
    assert "*Why here:* found 1 password field" in md  # no examples recorded: listed by criterion
    assert "### 1. `p`\n\n- [ ] **Fix** **[1.4.3 Title 1.4.3]" in md  # the failing element, with its fix
    assert "dark color scheme" in md


def test_something_axe_could_not_decide_is_listed_under_its_element():
    md = to_markdown(_report())
    lines = md[md.index("`#group_type`") :].split("\n")
    assert lines[2].startswith("- [ ] **Checked:**")  # one box for the element: a person looks at it
    assert lines[3].startswith("- **Review**") and lines[4] == "  - here: background image"


def test_passed_items_with_follow_up_stay_unticked():
    md = to_markdown(_report())
    assert (
        "- [ ] **[2.4.2 Title 2.4.2]" in md and "*Still worth a look:* confirm the title is descriptive" in md
    )
    assert "- [x] **[1.1.1 Title 1.1.1]" in md and "found nothing to check here" in md


def test_anchor_matches_github_style_slugs():
    from magnacoda.report.markdown_export import anchor

    assert anchor("Fix these: automated checks failed (1)") == "fix-these-automated-checks-failed-1"
    assert anchor("Depends on your site or user flows (7)") == "depends-on-your-site-or-user-flows-7"


def test_contents_links_every_present_section_and_only_those():
    import re

    md = to_markdown(_report())
    contents = md.split("## Contents")[1].split("\n## ")[0]
    links = re.findall(r"^- \[(.+?)\]\(#(.+?)\)$", contents, re.M)
    headings = re.findall(r"^## (.+)$", md, re.M)
    from magnacoda.report.markdown_export import anchor

    section_headings = [h for h in headings if h != "Contents"]
    assert [title for title, _ in links] == section_headings
    assert all(target == anchor(title) for title, target in links)
    assert md.index("## Contents") < md.index(f"## {section_headings[0]}")


def test_contents_omits_empty_sections():
    report = _report()
    report.checklist = [e for e in report.checklist if e.tier != "depends"]
    md = to_markdown(report)
    assert "Depends on your site" not in md


def _finding_with_fix(**overrides) -> Finding:
    base = dict(
        finding_id="f",
        rule_id="color-contrast",
        wcag_criteria=["1.4.3"],
        wcag_level="AA",
        severity="serious",
        description="d",
        selector="p",
        html_snippet="<p>",
        source="axe-core",
    )
    base.update(overrides)
    return Finding(**base)


def _report_with_fixes(findings: list[Finding]) -> ScanReport:
    report = _report()
    report.findings = findings
    report.checklist = [_entry("1.4.3", "automated", "failed", rules=["color-contrast"])]
    return report


def test_each_failing_element_has_its_own_fix_and_says_when_the_fix_is_shared():
    findings = [
        _finding_with_fix(
            finding_id=f"f{i}",
            selector=f"#field-{i}",
            html_snippet=f"<label id='field-{i}'>",
            fix=FindingFix(
                corrected_snippet=f"/* #field-{i} */\ncolor: #c0545c;",
                summary="Change the text color from #c25b62 to #c0545c (4.50:1 on #ffffff; needs 4.5:1).",
                generated_by="template",
            ),
        )
        for i in range(3)
    ]
    md = to_markdown(_report_with_fixes(findings))
    # One block: the three elements, each with its own HTML and example, then the fix once, one box.
    assert "Fix these 3 elements, all in the same way" in md and md.count("- [ ] **Fix**") == 1
    assert md.count("  - fix: Change the text color") == 1
    assert md.count("*(the same fix applies to 3 elements)*") == 1
    assert "  - e.g. `/* #field-0 */ color: #c0545c;`" in md and "  - now: `<label id='field-0'>`" in md
    assert "- `#field-0`" in md and "- `#field-2`" in md  # Fix only: no element boxes


def test_different_fixes_for_the_same_rule_are_not_called_the_same():
    findings = [
        _finding_with_fix(
            finding_id="f1",
            selector="#a",
            fix=FindingFix(corrected_snippet="a", summary="fix A", generated_by="template"),
        ),
        _finding_with_fix(
            finding_id="f2",
            selector="#b",
            fix=FindingFix(corrected_snippet="b", summary="fix B", generated_by="template"),
        ),
    ]
    md = to_markdown(_report_with_fixes(findings))
    assert "fix A" in md and "fix B" in md and "the same fix applies" not in md


def test_ai_fix_is_labelled_and_snippet_that_echoes_html_is_omitted():
    findings = [
        _finding_with_fix(
            html_snippet="<p>same</p>",
            fix=FindingFix(
                corrected_snippet="<p>same</p>", summary="an AI fix", generated_by="claude-explain"
            ),
        )
    ]
    md = to_markdown(_report_with_fixes(findings))
    assert "AI-suggested fix: an AI fix" in md
    assert "e.g." not in md.split("AI-suggested fix")[1].split("\n")[0]


def test_criterion_with_no_fixed_findings_has_no_fix_lines():
    md = to_markdown(_report_with_fixes([]))
    assert "- fix:" not in md and "AI-suggested fix" not in md


def _ai_finding(i: int, fix_group: str | None, snippet: str) -> Finding:
    return Finding(
        finding_id=f"ai{i}",
        rule_id="color-contrast",
        wcag_criteria=["1.4.3"],
        wcag_level="AA",
        severity="serious",
        description="d",
        selector=f"#el{i}",
        html_snippet="<span>",
        source="axe-core",
        explanation=FindingExplanation(
            why_it_matters="w", how_to_fix="h", generated_by="claude-explain", model="m", fix_group=fix_group
        ),
        fix=FindingFix(corrected_snippet=snippet, summary=f"AI text #{i}", generated_by="claude-explain"),
    )


def test_ai_fixes_with_a_shared_fix_group_are_called_the_same_despite_different_wording():
    findings = [
        _ai_finding(0, "shared", "color: #595959;"),
        _ai_finding(1, "shared", "color: #595959;"),
        _ai_finding(2, "shared", "color: #595959;"),
        _ai_finding(3, "shared", "color: #595959;"),
        _ai_finding(4, "shared", "color: #595959;"),
        _ai_finding(5, None, "color: #0056B3;"),
    ]
    md = to_markdown(_report_with_fixes(findings))
    # The AI tagged five as one fix: one block, worded as the first; the sixth is its own.
    assert md.count("AI-suggested fix:") == 2 and "Fix these 5 elements, all in the same way" in md
    assert md.count("*(the same fix applies to 5 elements)*") == 1 and "AI text #1" not in md
    assert "AI-suggested fix: AI text #0" in md and "AI-suggested fix: AI text #5" in md
    assert "  - e.g. `color: #0056B3;`" in md


def test_template_and_ai_fixes_are_counted_independently():
    findings = [
        _finding_with_fix(
            finding_id="t1",
            selector="#t",
            fix=FindingFix(corrected_snippet="a", summary="template text", generated_by="template"),
        ),
        _ai_finding(0, "g", "x"),
        _ai_finding(1, "g", "x"),
    ]
    md = to_markdown(_report_with_fixes(findings))
    assert "  - fix: template text\n  - e.g. `a`\n" in md
    assert md.count("(the same fix applies to 2 elements)") == 1


def test_the_introduction_states_the_limits_and_how_to_cover_more():
    md = to_markdown(_report())
    intro = md[: md.index("## Contents")]
    assert "All 7 criteria in scope" in intro
    assert "**To cover more:** scan again with `--ai semantic`" in intro
    assert "work through the page elements and the checks below" in intro


def test_after_a_semantic_scan_it_doesnt_suggest_one_and_without_check_first_it_says_so():
    report = _report()
    report.meta.ai_tier = "semantic"
    report.checklist = [e for e in report.checklist if e.tier != "relevant"]
    intro = to_markdown(report).split("## Contents")[0]
    assert "--ai semantic" not in intro and "work through the page elements" in intro


def test_elements_with_the_same_failure_are_listed_together_each_by_name():
    report = _report()
    report.findings = [
        report.findings[0].model_copy(update={"finding_id": str(i), "selector": f"p.note:nth-of-type({i})"})
        for i in range(1, 13)
    ]
    md = to_markdown(report)
    assert all(f"- `p.note:nth-of-type({i})`" in md for i in range(1, 13))
    assert "Fix these 12 elements, all in the same way" in md and md.count("- [ ] **Fix**") == 1


def test_a_relevant_check_becomes_an_item_under_each_of_its_elements_with_page_text_escaped():
    from magnacoda.findings.models import FeatureExample

    report = _report()
    report.checklist[1].examples = [FeatureExample(selector="input#pw", hint="*Password*")]
    md = to_markdown(report)
    # third: after the failing element and the one axe-core couldn't decide
    block = md[md.index('### 3. `input#pw` ("\\*Password\\*")\n\n- [ ] **Checked:**') :]
    assert block.split("\n")[3].startswith("- **Check** **[3.3.8 Title 3.3.8]")
    assert "*Why here:* found 1 password field" not in md  # its one element has the item now


def test_what_sending_a_form_empty_showed_is_noted_on_its_fields_and_form():
    from magnacoda.findings.models import (
        EmptySubmitCheck,
        EmptySubmitResult,
        FeatureExample,
        FormFieldError,
    )

    report = _report()
    report.checklist += [
        _entry("3.3.1", "relevant"),
        _entry("3.3.3", "relevant"),
        _entry("4.1.3", "relevant"),
    ]
    report.checklist[-2].examples = [FeatureExample(selector="#name", hint="Name")]
    report.empty_submit = EmptySubmitResult(
        tested=3,
        forms=[
            EmptySubmitCheck(
                form=FeatureExample(selector="#signup"),
                outcome="page",
                announced=True,
                fields=[
                    FormFieldError(
                        element=FeatureExample(selector="#name", hint="Name"),
                        invalid=True,
                        message="Enter your *name*.",
                    )
                ],
            ),
            EmptySubmitCheck(
                form=FeatureExample(selector="#quiet"), outcome="page", messages=["Fill in your phone."]
            ),
            EmptySubmitCheck(form=FeatureExample(selector="#order"), outcome="sent", required=2),
        ],
    )
    text = to_markdown(report)
    name = text.split("`#name`")[1].split("###")[0]
    # The message goes on the field's own 3.3.3 item (no second one), with page text escaped.
    assert name.count("**Check** **[3.3.3") == 1 and '*Sent empty, it said:* "Enter your \\*name\\*."' in name
    assert "marked invalid, with its message tied to it" in name
    assert "reached screen readers" in text.split("`#signup`")[1].split("###")[0]
    quiet = text.split("`#quiet`")[1].split("###")[0]
    assert '*Sent empty, the form showed:* "Fill in your phone."' in quiet
    assert "no field was marked invalid or tied to it" in quiet
    assert "although 2 fields are marked required" in text.split("`#order`")[1].split("###")[0]


def test_the_tab_pass_notes_the_focus_order_and_what_it_could_not_reach():
    from magnacoda.findings.models import FeatureExample, KeyboardResult

    report = _report()
    report.checklist += [_entry("2.4.3", "every_page"), _entry("2.4.7", "every_page")]
    report.keyboard = KeyboardResult(
        stops=100,
        complete=False,
        jumps=[(FeatureExample(selector="#footer-link"), FeatureExample(selector="#menu", hint="Menu"))],
    )
    text = to_markdown(report)
    order = next(line for line in text.splitlines() if "[2.4.3 " in line)
    assert 'the focus jumped back up the page from* `#footer-link` to `#menu` ("Menu")' in order
    visible = next(line for line in text.splitlines() if "[2.4.7 " in line)
    assert "the first 100 elements without this problem, then had to stop" in visible


def test_criteria_that_do_not_apply_come_ticked_in_their_own_section():
    report = _report()
    report.checklist.append(_entry("1.2.5", "not_applicable", reason="no audio"))
    text = to_markdown(report)
    section = text.split("## Not applicable to this page")[1].split("## ")[0]
    assert "- [x] **[1.2.5 " in section and "untick if the page shows audio or video" in section


def test_field_checks_note_what_was_found_on_each_fields_check_items():
    from magnacoda.findings.models import FeatureExample, FieldPurpose, FieldsResult

    report = _report()
    report.checklist += [_entry("1.3.5", "relevant"), _entry("3.3.8", "relevant")]
    pw = FeatureExample(selector="#pw", hint="Password")
    report.fields = FieldsResult(
        purposes=[
            FieldPurpose(element=FeatureExample(selector="#email"), autocomplete="email", guess="email"),
            FieldPurpose(element=FeatureExample(selector="#colour"), autocomplete=None, guess=None),
            FieldPurpose(element=pw, autocomplete="current-password", guess="current-password"),
        ]
    )
    text = to_markdown(report)
    assert 'It has autocomplete="email", as its label suggests.' in text.split("`#email`")[1].split("###")[0]
    assert "doesn't look like the visitor's own details" in text.split("`#colour`")[1].split("###")[0]
    assert "Pasting into it works" in text.split("`#pw`")[1].split("###")[0]


def test_interaction_notes_go_on_elements_and_criterion_lines():
    from magnacoda.findings.models import FeatureExample, InteractionResult, PageNote

    report = _report()
    report.checklist += [_entry("2.1.4", "depends", reason="site"), _entry("2.2.2", "relevant", reason="x")]
    report.interaction = InteractionResult(
        notes=[
            PageNote(element=FeatureExample(selector=""), num="2.1.4", note=" *Single keys did nothing.*"),
            PageNote(element=FeatureExample(selector="#news"), num="2.2.2", note=" *It has a pause button.*"),
        ]
    )
    text = to_markdown(report)
    assert "*Single keys did nothing.*" in next(line for line in text.splitlines() if "[2.1.4 " in line)
    assert "*It has a pause button.*" in text.split("`#news`")[1].split("###")[0]


def test_a_fix_shows_what_is_between_backticks_as_code_and_escapes_the_rest():
    from magnacoda.report.markdown_export import _with_code

    assert _with_code("Move the `<span>` into an `<li>`, **now**.") == (
        "Move the `<span>` into an `<li>`, \\*\\*now\\*\\*."
    )
    assert _with_code("An odd ` backtick <b>") == "An odd \\` backtick \\<b\\>"


def test_two_elements_fixed_the_same_way_are_both():
    findings = [
        _finding_with_fix(
            finding_id=f"f{i}",
            selector=f"#field-{i}",
            html_snippet=f"<label id='field-{i}'>",
            fix=FindingFix(corrected_snippet="", summary="Underline the link.", generated_by="template"),
        )
        for i in range(2)
    ]
    assert "Fix these 2 elements, both in the same way" in to_markdown(_report_with_fixes(findings))


def test_the_checklist_ends_with_a_footer_under_a_rule():
    assert to_markdown(_report()).endswith(
        "\n\n---\n\nAccessibility scan by *magnacoda*: <https://magnacoda.dev/>\n"
    )
