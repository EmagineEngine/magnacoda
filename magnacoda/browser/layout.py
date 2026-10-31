"""Layout checks that need the page laid out again, so axe-core can't do them.

- 1.4.10 Reflow: no sideways scrolling at 320 px (400% zoom on a 1280 px screen).
- 1.4.12 Text Spacing: WCAG's spacing mustn't cut text off or make it spill.
- 1.4.4 Resize Text: no text cut off at 200% zoom (sideways scrolling is fine here).

Only problems that weren't there before count, so a deliberate ellipsis isn't flagged.
"""

from __future__ import annotations

from typing import Any

from playwright.sync_api import Page

from magnacoda.browser.features import PAGE_HELPERS
from magnacoda.findings.models import FeatureExample, LayoutProblem, LayoutProblemKind, LayoutResult

REFLOW_WIDTH = 320
REFLOW_HEIGHT = 256
_SETTLE_MS = 300
_LIMIT = 10
_STYLE_ID = "magnacoda-text-spacing"

# Outermost elements past the right edge, skipping anything inside a scroll/clip container.
_REFLOW_SCRIPT = (
    """
(limit) => {
"""
    + PAGE_HELPERS
    + """
    const width = document.documentElement.clientWidth;
    const overflow = document.documentElement.scrollWidth - width;
    if (overflow <= 1) return { overflow: 0, culprits: [] };
    const contained = (el) => {
        for (let n = el.parentElement; n && n !== document.body; n = n.parentElement) {
            const x = getComputedStyle(n).overflowX;
            if (x !== 'visible') return true;
        }
        return false;
    };
    const culprits = [];
    for (const el of document.body.querySelectorAll('*')) {
        if (culprits.length >= limit) break;
        const r = el.getBoundingClientRect();
        if (r.right <= width + 1 || r.width < 1 || r.height < 1) continue;
        const cs = getComputedStyle(el);
        if (cs.visibility === 'hidden' || cs.display === 'none') continue;
        const parent = el.parentElement;
        if (parent && parent !== document.body && parent.getBoundingClientRect().right > width + 1) continue;
        if (contained(el)) continue;
        culprits.push({
            selector: selectorFor(el), hint: hintFor(el), html: htmlOf(el),
            by: Math.round(r.right - width), table: Boolean(el.closest('table, pre')),
        });
    }
    return { overflow: Math.round(overflow), culprits };
}
"""
)

# Every visible element with text whose content doesn't fit: {selector: [hint, html, clipped, height]}.
_FIT_SCRIPT = (
    """
() => {
"""
    + PAGE_HELPERS
    + """
    const found = {};
    for (const el of document.body.querySelectorAll('*')) {
        if (el.scrollHeight <= el.clientHeight + 1 && el.scrollWidth <= el.clientWidth + 1) continue;
        const r = el.getBoundingClientRect();
        if (r.width < 4 || r.height < 4) continue;
        const cs = getComputedStyle(el);
        if (cs.display === 'none' || cs.visibility === 'hidden' || cs.display === 'inline') continue;
        if (!(el.textContent || '').trim()) continue;
        if (['html', 'body', 'textarea', 'select'].includes(el.localName)) continue;
        const scrolling = ['auto', 'scroll'];
        const scrolls = scrolling.includes(cs.overflowY) || scrolling.includes(cs.overflowX);
        if (scrolls) continue;  // it can be scrolled: nothing is lost
        const clipped = cs.overflowX !== 'visible' || cs.overflowY !== 'visible';
        found[selectorFor(el)] = [hintFor(el), htmlOf(el), clipped, el.clientHeight];
    }
    return found;
}
"""
)

_SPACING_CSS = (
    "* { line-height: 1.5 !important; letter-spacing: 0.12em !important; word-spacing: 0.16em !important; }"
    " p { margin-bottom: 2em !important; }"
)
_ADD_STYLE = (
    "([id, css]) => { const s = document.createElement('style'); s.id = id; s.textContent = css;"
    " document.head.appendChild(s); }"
)
_REMOVE_STYLE = "(id) => { const s = document.getElementById(id); if (s) s.remove(); }"


def check_layout(page: Page) -> LayoutResult:
    """Lay the page out at 320 px, with WCAG's text spacing, and at 200% zoom, and report what breaks."""
    viewport = page.viewport_size
    if viewport is None:
        return LayoutResult()
    result = LayoutResult(tested=True)
    try:
        before = page.evaluate(_FIT_SCRIPT)
        _spacing(page, before, result)
        _resize(page, viewport, before, result)
        _reflow(page, result)
    finally:
        page.set_viewport_size(viewport)
        page.wait_for_timeout(_SETTLE_MS)
    return result


def _add(
    result: LayoutResult, selector: str, hint: str, html: str, kind: LayoutProblemKind, detail: str
) -> None:
    if any(p.element.selector == selector and p.kind == kind for p in result.problems):
        return
    result.problems.append(
        LayoutProblem(
            element=FeatureExample(selector=selector, hint=hint), kind=kind, detail=detail, html=html
        )
    )


def _newly_unfit(before: dict[str, Any], after: dict[str, Any]) -> list[tuple[str, list[Any]]]:
    """Elements that fit before the change but not after (up to _LIMIT)."""
    return [(selector, info) for selector, info in after.items() if selector not in before][:_LIMIT]


def _spacing(page: Page, before: dict[str, Any], result: LayoutResult) -> None:
    page.evaluate(_ADD_STYLE, [_STYLE_ID, _SPACING_CSS])
    try:
        page.wait_for_timeout(_SETTLE_MS)
        after = page.evaluate(_FIT_SCRIPT)
    finally:
        page.evaluate(_REMOVE_STYLE, _STYLE_ID)
    for selector, (hint, html, clipped, _height) in _newly_unfit(before, after):
        if clipped:
            _add(result, selector, hint, html, "spacing-clipped", "")
        else:
            _add(result, selector, hint, html, "spacing-spills", "")


def _resize(page: Page, viewport: Any, before: dict[str, Any], result: LayoutResult) -> None:
    """200% zoom: the layout gets half the width and everything is drawn twice as big."""
    page.set_viewport_size(
        {"width": max(viewport["width"] // 2, REFLOW_WIDTH), "height": viewport["height"] // 2}
    )
    page.wait_for_timeout(_SETTLE_MS)
    after = page.evaluate(_FIT_SCRIPT)
    for selector, (hint, html, clipped, _height) in _newly_unfit(before, after):
        if clipped:
            _add(result, selector, hint, html, "resize-clipped", "")


def _reflow(page: Page, result: LayoutResult) -> None:
    page.set_viewport_size({"width": REFLOW_WIDTH, "height": REFLOW_HEIGHT})
    page.wait_for_timeout(_SETTLE_MS)
    found = page.evaluate(_REFLOW_SCRIPT, _LIMIT)
    result.overflow = found["overflow"]
    for culprit in found["culprits"]:
        kind: LayoutProblemKind = "reflow-table" if culprit["table"] else "reflow"
        _add(result, culprit["selector"], culprit["hint"], culprit["html"], kind, f"{culprit['by']} px")
    if result.overflow and not found["culprits"]:
        _add(result, "", "", "", "reflow", f"{result.overflow} px")
