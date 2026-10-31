"""Single-key shortcuts (2.1.4): press common shortcut keys with nothing focused and see what happens.

Effects that count: focus moves (often "/" to search), the page scrolls, a dialog opens, or a page or
window starts to load. Runs with requests blocked.
"""

from __future__ import annotations

from playwright.sync_api import Page

from magnacoda.browser.blocking import blocked
from magnacoda.browser.features import PAGE_HELPERS
from magnacoda.browser.hover import VISIBILITY_HELPERS
from magnacoda.browser.keyboard import START_SCRIPT
from magnacoda.findings.models import FeatureExample, InteractionResult, PageNote, PageProblem

KEYS = ["/", "?", "s", "j", "k", "n", "g", "h"]
_REPORT_LIMIT = 3
_SETTLE_MS = 120

_STATE_SCRIPT = (
    """
() => {
"""
    + VISIBILITY_HELPERS
    + """
    const dialogs = Array.from(document.querySelectorAll(
        '[role="dialog"], [role="alertdialog"], [aria-modal="true"], dialog')).filter(shown).length;
    const el = document.activeElement;
    return { focused: Boolean(el && el !== document.body && el !== document.documentElement),
             scroll: Math.round(scrollY), dialogs };
}
"""
)

_FOCUSED_SCRIPT = (
    """
() => {
"""
    + PAGE_HELPERS
    + """
    const el = document.activeElement;
    return { selector: selectorFor(el), hint: hintFor(el), html: htmlOf(el) };
}
"""
)


def try_shortcuts(page: Page, result: InteractionResult) -> None:
    """Press single keys with nothing focused, and note the ones that did something."""
    found = 0
    with blocked(page) as watch:
        for key in KEYS:
            if found >= _REPORT_LIMIT:
                break
            try:
                page.evaluate(START_SCRIPT)
                before = page.evaluate(_STATE_SCRIPT)
                watch.clear()
                page.keyboard.press(key)
                page.wait_for_timeout(_SETTLE_MS)
                after = page.evaluate(_STATE_SCRIPT)
                effects = list(watch.events)
                if watch.windows_opened():
                    effects.append("opened a new window")
                element = FeatureExample(selector="")
                html = ""
                if after["focused"] and not before["focused"]:
                    focused = page.evaluate(_FOCUSED_SCRIPT)
                    element = FeatureExample(selector=focused["selector"], hint=focused["hint"])
                    html = focused["html"]
                    effects.append("moved the focus here")
                if after["scroll"] != before["scroll"]:
                    effects.append("scrolled the page")
                if after["dialogs"] > before["dialogs"]:
                    effects.append("opened a dialog")
            except Exception:  # noqa: BLE001 - skip that key
                continue
            finally:
                _put_back(page)
            if effects:
                found += 1
                detail = (
                    f'Pressing "{key}" alone, with no field focused, {" and ".join(dict.fromkeys(effects))}'
                )
                result.problems.append(
                    PageProblem(element=element, kind="single-key-shortcut", detail=detail, html=html)
                )
    result.tested["shortcut keys"] = len(KEYS)
    if not found:
        keys = ", ".join(f"`{key}`" for key in KEYS)
        result.notes.append(
            PageNote(
                element=FeatureExample(selector=""),
                num="2.1.4",
                note=f" *Pressing single keys ({keys}) with nothing focused did nothing*; check any "
                "shortcuts the page lists.",
            )
        )


def _put_back(page: Page) -> None:
    try:
        page.keyboard.press("Escape")
        page.evaluate(START_SCRIPT)
    except Exception:  # noqa: BLE001
        pass
