"""Where a style is set, in words (report/css_lines.py), and the small rules behind it
(browser/css_sources.py)."""

from magnacoda.browser.css_sources import _is_own_class, _tidy_source
from magnacoda.findings.fix_templates import template_fix
from magnacoda.findings.models import CssSource, Finding
from magnacoda.report.css_lines import where_set


def test_declarations_of_one_rule_are_shown_together():
    rule = {"kind": "stylesheet", "selector": ".entry a", "file": "/site.css", "line": 1}
    sources = [
        CssSource(property="text-decoration-line", declaration="text-decoration: none", **rule),
        CssSource(property="color", declaration="color: #2a5a9a", **rule),
        CssSource(property="box-shadow", kind="not-set"),
    ]
    assert where_set(sources) == [
        (".entry a { text-decoration: none; color: #2a5a9a }", "in /site.css, line 1")
    ]


def test_each_kind_of_place_is_worded():
    assert where_set([CssSource(property="color", declaration="color: red", kind="style-attribute")]) == [
        ('style="color: red"', "in the element's own style attribute")
    ]
    assert where_set(
        [CssSource(property="color", declaration="color: #aaa", selector=".c", kind="script")]
    ) == [(".c { color: #aaa }", "added by a script (no file to point to)")]
    focused = CssSource(
        property="outline-style", declaration="outline: none", selector="a:focus", kind="stylesheet",
        file="/a.css", line=2, original_file="src/a.scss", original_line=8, state=":focus",
    )  # fmt: skip
    assert where_set([focused])[0][1] == (
        "in /a.css, line 2 (from src/a.scss, line 8, by its source map), with the keyboard focus on it"
    )


def test_a_utility_class_is_recognized_even_with_a_state():
    assert _is_own_class(".no-underline", ["no-underline", "text-blue"])
    assert _is_own_class(".hover\\:no-underline:hover", ["hover:no-underline"])
    assert not _is_own_class(".entry a", ["entry"]) and not _is_own_class(".a.b", ["a", "b"])


def test_source_names_are_tidied():
    assert _tidy_source("webpack:///./src/_links.scss") == "src/_links.scss"
    assert _tidy_source("src/a.scss") == "src/a.scss"


def test_links_shown_only_by_color_get_a_real_fix():
    finding = Finding(
        finding_id="1", rule_id="link-in-text-block", severity="serious", description="d",
        selector="p > a", html_snippet="<a>", source="axe-core",
    )  # fmt: skip
    fix = template_fix(finding)
    assert fix.summary.startswith("Underline links that sit in text")
    assert fix.corrected_snippet == "/* p > a */\ntext-decoration: underline;"


def test_one_rule_over_several_lines_is_shown_once():
    rule = {"kind": "stylesheet", "selector": "a, a:visited", "file": "/theme/default.css"}
    sources = [
        CssSource(property="text-decoration-line", declaration="text-decoration: none", line=290, **rule),
        CssSource(property="color", declaration="color: var(--brand-color-1, black)", line=292, **rule),
    ]
    assert where_set(sources) == [
        (
            "a, a:visited { text-decoration: none; color: var(--brand-color-1, black) }",
            "in /theme/default.css, lines 290 and 292",
        )
    ]
