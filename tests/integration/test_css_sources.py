"""Where the CSS behind a problem is set (browser/css_sources.py), on a page whose styles come from a
stylesheet with a source map, a <style> element, a style attribute and a utility class."""

import pytest

from magnacoda.browser import css_sources
from magnacoda.config import ScanConfig
from magnacoda.orchestrator import run_scan
from magnacoda.report.markdown_export import to_markdown

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def report(fixture_server):
    return run_scan(ScanConfig(url=f"{fixture_server}/css_sources/page.html", quick=True))


def _sources(report, rule, selector_part):
    finding = next(f for f in report.findings if f.rule_id == rule and selector_part in f.selector)
    return {s.property: s for s in finding.css}


def test_a_stylesheet_rule_is_found_with_its_file_line_and_original_source(report):
    found = _sources(report, "link-in-text-block", "#one")
    underline = found["text-decoration-line"]
    assert (underline.kind, underline.selector, underline.declaration) == (
        "stylesheet",
        ".entry a",
        "text-decoration: none",
    )
    assert (underline.file, underline.line) == ("/css_sources/site.css", 1)
    assert (underline.original_file, underline.original_line) == ("/src/_links.scss", 5)
    assert found["color"].declaration == "color: #2a5a9a" and not underline.utility_class


def test_a_utility_class_and_a_style_attribute_are_named_as_such(report):
    utility = _sources(report, "link-in-text-block", "no-underline")["text-decoration-line"]
    assert utility.selector == ".no-underline" and utility.utility_class
    inline = _sources(report, "link-in-text-block", "#three")["text-decoration-line"]
    assert inline.kind == "style-attribute" and inline.declaration == "text-decoration: none"


def test_a_style_element_gives_its_line_in_the_page(report):
    color = _sources(report, "color-contrast", "note")["color"]
    assert (color.kind, color.selector, color.file, color.line) == (
        "style-element",
        "p.note",
        "/css_sources/page.html",
        8,
    )


def test_a_removed_focus_outline_is_found_with_the_focus_forced_on(report):
    outline = _sources(report, "magnacoda/focus-not-visible", "")["outline-style"]
    assert (outline.selector, outline.declaration, outline.state) == ("a:focus", "outline: none", ":focus")
    assert outline.original_line == 8


def test_the_checklist_says_where_each_style_is_set(report):
    text = to_markdown(report)
    assert (
        "set by `.entry a { text-decoration: none; color: #2a5a9a }` in /css\\_sources/site.css, line 1"
        in text
    )
    assert "(from /src/\\_links.scss, line 5, by its source map)" in text
    assert "utility class (as in Tailwind)" in text


def test_text_clipped_by_a_fixed_height_points_at_the_height_and_the_overflow(report):
    found = _sources(report, "magnacoda/text-spacing-clipped", "card-title")
    assert (
        found["overflow"].declaration == "overflow: hidden" and found["height"].declaration == "height: 1.2em"
    )
    assert (found["height"].line, found["height"].original_line) == (5, 17)


def test_firefox_has_no_devtools_protocol_so_nothing_is_added(fixture_server):
    class NoProtocol:
        class context:  # noqa: N801
            @staticmethod
            def new_cdp_session(page):
                raise RuntimeError("not Chromium")

    from magnacoda.findings.models import Finding

    finding = Finding(
        finding_id="1", rule_id="color-contrast", severity="serious", description="d", selector="p",
        html_snippet="<p>", source="axe-core",
    )  # fmt: skip
    css_sources.attach_sources(NoProtocol(), [finding])  # type: ignore[arg-type]
    assert finding.css == []
