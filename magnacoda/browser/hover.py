"""Content on hover (1.4.13): hover likely triggers and check that what appears is persistent,
hoverable and dismissible with Escape.

Native `title` tooltips are skipped. Runs with requests blocked.
"""

from __future__ import annotations

from playwright.sync_api import Page

from magnacoda.browser.blocking import blocked
from magnacoda.browser.features import PAGE_HELPERS
from magnacoda.findings.models import FeatureExample, InteractionResult, PageNote, PageProblem

HOVER_LIMIT = 12
_SHOWING_LIMIT = 5  # triggers that showed something, tried in full (each takes about 3 seconds)
_SHOW_MS = 400
_STAY_MS = 1000
_MARK = "data-magnacoda-hover"
_SHOWN = "data-magnacoda-shown"

# Shared: which elements are visible now, and which became visible since the last snapshot.
VISIBILITY_HELPERS = """
    const shown = (el) => {
        const r = el.getBoundingClientRect();
        if (r.width < 1 || r.height < 1) return false;
        const cs = getComputedStyle(el);
        return cs.display !== 'none' && cs.visibility !== 'hidden' && Number(cs.opacity) > 0.05;
    };
    const snapshot = () => {
        const seen = new WeakSet();
        for (const el of document.body.querySelectorAll('*')) if (shown(el)) seen.add(el);
        window.__magnacodaSeen = seen;
    };
    // The outermost elements that became visible since the snapshot, with some size and some text.
    const fresh = (minWidth, minHeight) => {
        const seen = window.__magnacodaSeen || new WeakSet();
        const found = [];
        for (const el of document.body.querySelectorAll('*')) {
            if (seen.has(el) || !shown(el)) continue;
            if (found.some((f) => f.contains(el))) continue;
            const r = el.getBoundingClientRect();
            if (r.width < minWidth || r.height < minHeight || !(el.innerText || '').trim()) continue;
            found.push(el);
        }
        return found;
    };
"""

_FIND_SCRIPT = (
    """
([limit, mark]) => {
"""
    + PAGE_HELPERS
    + VISIBILITY_HELPERS
    + """
    const selector = '[aria-haspopup]:not([aria-haspopup="false"]), [aria-describedby], [data-tooltip], '
        + '[data-bs-toggle="tooltip"], [data-toggle="tooltip"], [popovertarget], '
        + 'nav li:has(> ul) > a, nav li:has(> ul) > button, [role="menubar"] [aria-haspopup]';
    const found = [];
    for (const el of document.querySelectorAll(selector)) {
        if (found.length >= limit) break;
        if (!shown(el) || el.matches('input, select, textarea') || el.hasAttribute(mark)) continue;
        el.setAttribute(mark, String(found.length));
        found.push({ selector: selectorFor(el), hint: hintFor(el), html: htmlOf(el) });
    }
    return found;
}
"""
)

_SNAPSHOT_SCRIPT = "() => {" + VISIBILITY_HELPERS + " snapshot(); }"

# What hovering showed: the first new content (marked, to find again), or null.
_FRESH_SCRIPT = (
    """
([index, mark, shownMark]) => {
"""
    + PAGE_HELPERS
    + VISIBILITY_HELPERS
    + """
    const trigger = document.querySelector(`[${mark}="${index}"]`);
    document.querySelectorAll(`[${shownMark}]`).forEach((el) => el.removeAttribute(shownMark));
    const content = fresh(8, 8).find((el) => !el.contains(trigger));
    if (!content) return null;
    content.setAttribute(shownMark, '');
    const r = content.getBoundingClientRect();
    const t = trigger.getBoundingClientRect();
    // The way a person moves onto it: straight to its nearest edge, in line with the trigger, then in.
    const edgeX = Math.min(Math.max(t.left + t.width / 2, r.left + 2), r.right - 2);
    const edgeY = r.top >= t.bottom - 1 ? r.top + 2
        : r.bottom <= t.top + 1 ? r.bottom - 2 : r.top + r.height / 2;
    return { hint: hintFor(content), x: r.left + r.width / 2, y: r.top + r.height / 2, edgeX, edgeY };
}
"""
)

_STILL_SHOWN = (
    "(shownMark) => {"
    + VISIBILITY_HELPERS
    + " const el = document.querySelector(`[${shownMark}]`); return Boolean(el && shown(el)); }"
)


def try_hover_content(page: Page, result: InteractionResult, limit: int = HOVER_LIMIT) -> None:
    """Hover likely triggers, and try what they show for 1.4.13."""
    try:
        triggers = page.evaluate(_FIND_SCRIPT, [limit, _MARK])
    except Exception:  # noqa: BLE001
        return
    result.tested["hover"] = len(triggers)
    showing = 0
    with blocked(page, (_MARK, _SHOWN)):
        for index, trigger in enumerate(triggers):
            if showing >= _SHOWING_LIMIT:
                break
            locator = page.locator(f'[{_MARK}="{index}"]')
            try:
                content = _hover(page, locator, index)
                if content is None:
                    continue
                showing += 1
                problems = _try_content(page, locator, index, content)
            except Exception:  # noqa: BLE001 - a trigger that can't be hovered is just skipped
                continue
            finally:
                _leave(page)
            element = FeatureExample(selector=trigger["selector"], hint=trigger["hint"])
            what = f'"{content["hint"]}"' if content["hint"] else "more content"
            for kind in problems:
                result.problems.append(
                    PageProblem(element=element, kind=kind, detail=what, html=trigger["html"])
                )
            if not problems:
                result.notes.append(
                    PageNote(
                        element=element,
                        num="1.4.13",
                        note=" *Hovering shows more content; it stays, the pointer can move onto it, and "
                        "Escape closes it*: check the same when it gets the keyboard focus.",
                    )
                )


def _leave(page: Page) -> None:
    page.keyboard.press("Escape")
    page.mouse.move(1, 1)
    page.wait_for_timeout(150)


def _hover(page: Page, locator, index: int):  # type: ignore[no-untyped-def]
    """Hover the trigger; what it showed, or None."""
    _leave(page)
    page.evaluate(_SNAPSHOT_SCRIPT)
    locator.hover(timeout=2000)
    page.wait_for_timeout(_SHOW_MS)
    return page.evaluate(_FRESH_SCRIPT, [index, _MARK, _SHOWN])


def _try_content(page: Page, locator, index: int, content) -> list[str]:  # type: ignore[no-untyped-def]
    """Persistent, hoverable, dismissible: the kinds of problem found."""
    problems = []
    page.wait_for_timeout(_STAY_MS)
    if not page.evaluate(_STILL_SHOWN, _SHOWN):
        return ["hover-vanishes"]
    page.mouse.move(content["edgeX"], content["edgeY"], steps=6)
    page.mouse.move(content["x"], content["y"], steps=4)
    page.wait_for_timeout(300)
    if not page.evaluate(_STILL_SHOWN, _SHOWN):
        problems.append("hover-not-hoverable")
    again = _hover(page, locator, index)
    if again is not None:
        page.keyboard.press("Escape")
        page.wait_for_timeout(250)
        if page.evaluate(_STILL_SHOWN, _SHOWN):
            problems.append("hover-not-dismissible")
    return problems
