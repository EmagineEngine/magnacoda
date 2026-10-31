import json
from pathlib import Path

from magnacoda.findings.checklist import build_checklist, load_criteria, load_guidance
from magnacoda.findings.models import PageFeatures

FIXTURE = Path(__file__).parent.parent / "fixtures" / "axe_raw" / "static_violations.json"


def _raw() -> dict:
    return json.loads(FIXTURE.read_text())


def _by_num(entries):
    return {e.num: e for e in entries}


def test_every_a_and_aa_criterion_has_guidance():
    guidance = load_guidance()
    missing = [c["num"] for c in load_criteria() if c["level"] in ("A", "AA") and c["num"] not in guidance]
    assert missing == []


def test_all_links_point_to_w3c_understanding_pages():
    assert all(c["url"].startswith("https://www.w3.org/WAI/WCAG22/Understanding/") for c in load_criteria())


def test_scope_follows_wcag_version_and_level():
    v22 = _by_num(build_checklist(_raw(), PageFeatures(), "2.2", "AA"))
    assert "4.1.1" not in v22  # obsolete in 2.2
    assert "2.4.11" in v22
    v21 = _by_num(build_checklist(_raw(), PageFeatures(), "2.1", "AA"))
    assert "4.1.1" in v21 and "2.4.11" not in v21  # 2.4.11 is new in 2.2
    level_a = _by_num(build_checklist(_raw(), PageFeatures(), "2.2", "A"))
    assert "1.4.3" not in level_a and "1.1.1" in level_a
    level_aaa = _by_num(build_checklist(_raw(), PageFeatures(), "2.2", "AAA"))
    assert "1.4.6" in level_aaa


def test_axe_outcomes_map_to_statuses():
    checklist = _by_num(build_checklist(_raw(), PageFeatures(), "2.2", "AA"))
    assert checklist["1.1.1"].status == "failed" and "image-alt" in checklist["1.1.1"].rules
    assert checklist["3.1.1"].status == "failed"
    assert checklist["2.4.2"].status == "passed"
    assert all(
        e.tier in ("automated", "not_applicable") for e in checklist.values() if e.status != "not_automated"
    )


def test_worst_outcome_wins_when_a_rule_both_passes_and_fails():
    raw = {
        "violations": [{"id": "r1", "tags": ["wcag143"], "nodes": []}],
        "passes": [{"id": "r2", "tags": ["wcag143"], "nodes": []}],
        "incomplete": [],
        "inapplicable": [],
    }
    assert _by_num(build_checklist(raw, PageFeatures(), "2.2", "AA"))["1.4.3"].status == "failed"


def test_feature_absent_marks_criterion_likely_not_applicable():
    entry = _by_num(build_checklist(_raw(), PageFeatures(), "2.2", "AA"))["3.3.8"]
    assert entry.status == "not_automated" and entry.tier == "likely_na"
    assert "no password field" in (entry.reason or "")


def test_feature_present_marks_criterion_relevant_with_reason():
    entry = _by_num(build_checklist(_raw(), PageFeatures(password_inputs=1), "2.2", "AA"))["3.3.8"]
    assert entry.tier == "relevant" and entry.reason == "found 1 password field"


def test_plural_reason_and_multiple_triggers():
    entry = _by_num(build_checklist(_raw(), PageFeatures(video=2, iframes=1), "2.2", "AA"))["3.3.8"]
    assert entry.tier == "likely_na"
    entry = _by_num(build_checklist(_raw(), PageFeatures(video=2, iframes=1, forms=1), "2.2", "AA"))["3.3.4"]
    assert entry.tier == "relevant" and entry.reason == "found 1 form"
    entry = _by_num(build_checklist(_raw(), PageFeatures(video=2, iframes=1), "2.2", "AA"))["1.2.2"]
    assert entry.tier == "relevant"
    assert "2 video elements" in (entry.reason or "") and "1 iframe" in (entry.reason or "")


def test_site_level_and_every_page_tiers():
    checklist = _by_num(build_checklist(_raw(), PageFeatures(), "2.2", "AA"))
    assert checklist["3.2.3"].tier == "depends"
    assert checklist["2.4.7"].tier == "every_page"


def test_follow_up_only_shown_for_automated_criteria():
    checklist = _by_num(build_checklist(_raw(), PageFeatures(), "2.2", "AA"))
    assert checklist["2.4.2"].follow_up  # passed by axe, but a human should confirm the title is descriptive
    assert checklist["2.4.7"].follow_up is None


def test_axe_no_elements_result_does_not_hide_a_manual_trigger():
    # axe's video-caption rule is "inapplicable" without a <video>, but an iframe embed is invisible to it.
    with_embed = _by_num(build_checklist(_raw(), PageFeatures(iframes=1), "2.2", "AA"))["1.2.2"]
    assert with_embed.status == "no_elements" and with_embed.tier == "relevant"
    without = _by_num(build_checklist(_raw(), PageFeatures(), "2.2", "AA"))["1.2.2"]
    assert without.status == "no_elements" and without.tier == "not_applicable"  # no media at all


def test_a_relevant_check_carries_its_examples_without_repeats():
    from magnacoda.findings.models import FeatureExample

    examples = {
        "video": [FeatureExample(selector="video", hint="intro")],
        "iframes": [
            FeatureExample(selector="video"),
            *[FeatureExample(selector=f"iframe#f{i}") for i in range(9)],
        ],
    }
    features = PageFeatures(video=1, iframes=10, examples=examples)
    entries = _by_num(build_checklist(_raw(), features, "2.2", "AA"))
    media = entries["1.2.3"]
    assert media.tier == "relevant"
    assert [e.selector for e in media.examples] == ["video", *[f"iframe#f{i}" for i in range(9)]]  # no repeat
    assert entries["2.4.7"].examples == []  # not a feature-triggered check


def test_trying_the_form_fields_settles_3_2_2():
    from magnacoda.findings.models import FeatureExample, OnInputProblem, OnInputResult

    features = PageFeatures(inputs=2, forms=1)
    untried = _by_num(build_checklist(_raw(), features, "2.2", "AA"))["3.2.2"]
    assert untried.tier == "relevant"  # older reports, or no visible field: a person checks
    none_tried = _by_num(build_checklist(_raw(), features, "2.2", "AA", OnInputResult(tested=0)))["3.2.2"]
    assert none_tried.tier == "relevant"
    calm = _by_num(build_checklist(_raw(), features, "2.2", "AA", OnInputResult(tested=2)))["3.2.2"]
    assert (calm.status, calm.tier, calm.rules) == ("passed", "automated", ["magnacoda/on-input"])
    assert "beforehand" in calm.follow_up
    problem = OnInputProblem(element=FeatureExample(selector="#go"), effect="submitted the form")
    jumpy = build_checklist(_raw(), features, "2.2", "AA", OnInputResult(tested=2, problems=[problem]))
    assert _by_num(jumpy)["3.2.2"].status == "failed"


def test_pressing_tab_through_the_page_settles_the_keyboard_criteria():
    from magnacoda.findings.models import FeatureExample, KeyboardProblem, KeyboardResult

    def entries(keyboard):
        return _by_num(build_checklist(_raw(), PageFeatures(), "2.2", "AA", keyboard=keyboard))

    clean = entries(KeyboardResult(stops=12, complete=True, skip_link="works"))
    for num in ("2.4.7", "2.4.11", "2.1.2", "3.2.1"):
        assert (clean[num].status, clean[num].tier) == ("passed", "automated")
        assert "all 12 elements" in clean[num].follow_up
    assert clean["2.4.1"].follow_up is None  # nothing left to confirm: the skip link works
    assert clean["2.4.3"].tier == "every_page"  # the order still needs a person
    stopped = entries(KeyboardResult(stops=100, complete=False))
    assert stopped["2.4.7"].tier == "every_page"
    unseen = KeyboardProblem(element=FeatureExample(selector="a.x"), kind="focus-not-visible")
    failed = entries(KeyboardResult(stops=100, complete=False, problems=[unseen], skip_link="broken"))
    assert failed["2.4.7"].status == "failed" and failed["2.4.1"].status == "failed"
    assert "magnacoda/focus-not-visible" in failed["2.4.7"].rules


def test_audio_and_video_criteria_do_not_apply_to_a_page_without_any():
    from magnacoda.findings.checklist import NO_MEDIA

    none = _by_num(build_checklist(_raw(), PageFeatures(), "2.2", "AAA"))
    for num in ("1.2.1", "1.2.2", "1.2.3", "1.2.4", "1.2.5", "1.2.6", "1.2.9", "1.4.2", "1.4.7"):
        assert (none[num].tier, none[num].reason) == ("not_applicable", NO_MEDIA), num
    assert none["1.1.1"].tier != "not_applicable"
    for features in (PageFeatures(video=1), PageFeatures(iframes=1), PageFeatures(embeds=1)):
        assert _by_num(build_checklist(_raw(), features, "2.2", "AA"))["1.2.2"].tier == "relevant"


def test_the_layout_tests_settle_reflow_text_spacing_and_resize():
    from magnacoda.findings.models import FeatureExample, LayoutProblem, LayoutResult

    def entries(layout):
        return _by_num(build_checklist(_raw(), PageFeatures(), "2.2", "AA", layout=layout))

    fine = entries(LayoutResult(tested=True))
    assert all(fine[num].status == "passed" for num in ("1.4.10", "1.4.12", "1.4.4"))
    clipped = LayoutProblem(element=FeatureExample(selector="#x"), kind="spacing-clipped")
    broken = entries(LayoutResult(tested=True, problems=[clipped]))
    assert broken["1.4.12"].status == "failed" and broken["1.4.10"].status == "passed"
    assert entries(LayoutResult())["1.4.10"].tier == "every_page"  # not tried: left to a person
