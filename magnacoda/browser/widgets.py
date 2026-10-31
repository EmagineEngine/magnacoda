"""Click the page's controls (axe-core never clicks).

- 4.1.2: aria-expanded must change when the control opens or closes something. Disclosure buttons
  without it are listed too (tabs, carousel arrows and dialogs excepted).
- 2.1.1: click handlers on elements Tab can't reach, and custom controls that ignore Enter/Space.
  Handlers come from the DevTools protocol, so Firefox only sees onclick attributes.

Runs last with requests blocked; each control is clicked again to put it back.
"""

from __future__ import annotations

from typing import Any

from playwright.sync_api import CDPSession, Page

from magnacoda.browser.blocking import blocked
from magnacoda.browser.features import PAGE_HELPERS
from magnacoda.browser.hover import VISIBILITY_HELPERS
from magnacoda.findings.models import FeatureExample, InteractionResult, PageProblem

TOGGLE_LIMIT = 10
CLICK_LIMIT = 40
_SETTLE_MS = 250
_MARK = "data-magnacoda-widget"
_CLICK_MARK = "data-magnacoda-clickable"
_POINTER_EVENTS = {"click", "mousedown", "mouseup", "pointerdown", "pointerup", "touchstart", "touchend"}

_FIND_TOGGLES_SCRIPT = (
    """
([limit, mark]) => {
"""
    + PAGE_HELPERS
    + VISIBILITY_HELPERS
    + """
    const notToggles = new RegExp('\\b(next|prev|previous|slide|close|dismiss|submit|send|search|'
        + 'log ?in|sign ?in)\\b|[‹›←→]', 'i');
    const found = [];
    const candidates = document.querySelectorAll(
        '[aria-expanded], button, [role="button"]');
    for (const el of candidates) {
        if (found.length >= limit) break;
        if (!shown(el) || el.disabled) continue;
        if (el.closest('[role="tablist"], [role="dialog"], [aria-modal="true"]')) continue;
        const expanded = el.getAttribute('aria-expanded');
        if (expanded === null) {
            // A plain button: only one that doesn't send a form or name an action it obviously isn't.
            if (el.localName === 'button' && el.form && el.type !== 'button') continue;
            if (el.hasAttribute('aria-haspopup') || el.hasAttribute('aria-pressed')) continue;
            const text = [el.getAttribute('aria-label'), el.innerText, el.title].join(' ');
            if (notToggles.test(text)) continue;
        }
        el.setAttribute(mark, String(found.length));
        const controls = (el.getAttribute('aria-controls') || '').split(/\\s+/).filter(Boolean)[0];
        found.push({ selector: selectorFor(el), hint: hintFor(el), html: htmlOf(el), expanded, controls });
    }
    return found;
}
"""
)

_STATE_SCRIPT = (
    """
([index, mark, controls]) => {
"""
    + VISIBILITY_HELPERS
    + """
    const el = document.querySelector(`[${mark}="${index}"]`);
    const target = controls ? document.getElementById(controls) : null;
    return {
        expanded: el ? el.getAttribute('aria-expanded') : null,
        target: target ? shown(target) : null,
    };
}
"""
)

_SNAPSHOT_SCRIPT = "() => {" + VISIBILITY_HELPERS + " snapshot(); }"

_APPEARED_SCRIPT = (
    """
() => {
"""
    + PAGE_HELPERS
    + VISIBILITY_HELPERS
    + """
    const content = fresh(40, 16)
        .filter((el) => !el.closest('[role="dialog"], [role="alertdialog"], [aria-modal="true"], dialog'));
    return content.length ? hintFor(content[0]) || 'more content' : null;
}
"""
)

# Outermost elements with a pointer cursor that Tab can't reach (nothing focusable in or around them).
_FIND_CLICKABLE_SCRIPT = (
    """
([limit, mark]) => {
"""
    + PAGE_HELPERS
    + VISIBILITY_HELPERS
    + """
    const focusable = 'a[href], button, input, select, textarea, summary, label, option, iframe, '
        + '[tabindex], [contenteditable=""], [contenteditable="true"], audio[controls], video[controls]';
    const found = [];
    for (const el of document.body.querySelectorAll('*')) {
        if (found.length >= limit) break;
        if (getComputedStyle(el).cursor !== 'pointer' || !shown(el)) continue;
        const parent = el.parentElement;
        if (parent && parent !== document.body && getComputedStyle(parent).cursor === 'pointer') continue;
        if (el.closest(focusable) || el.querySelector(focusable)) continue;
        el.setAttribute(mark, String(found.length));
        found.push({
            selector: selectorFor(el), hint: hintFor(el), html: htmlOf(el),
            onclick: el.hasAttribute('onclick') || el.hasAttribute('onmousedown'),
            focusable: false,
        });
    }
    // Custom controls Tab reaches: a role, or tabindex, on something that isn't a native control.
    for (const el of document.querySelectorAll('[tabindex]:not([tabindex^="-"])')) {
        if (found.length >= limit) break;
        if (el.matches(focusable.replace(', [tabindex]', '')) || !shown(el)) continue;
        if (el.isContentEditable || el.closest('[role="dialog"], [aria-modal="true"]')) continue;
        el.setAttribute(mark, String(found.length));
        found.push({
            selector: selectorFor(el), hint: hintFor(el), html: htmlOf(el),
            onclick: el.hasAttribute('onclick') || el.hasAttribute('onmousedown'),
            focusable: true, role: el.getAttribute('role') || '',
        });
    }
    return found;
}
"""
)

# Press a key on a custom control and see whether anything happened (a click, or a change on the page).
_KEY_WATCH_SCRIPT = """
([index, mark]) => {
    const el = document.querySelector(`[${mark}="${index}"]`);
    const state = { changes: 0, clicked: false };
    // Only what concerns the control counts (a ticker elsewhere on the page doesn't): changes inside it,
    // or a state attribute changing anywhere (something opening, pressed, checked or selected).
    const states = ['aria-expanded', 'aria-pressed', 'aria-checked', 'aria-selected', 'hidden', 'open'];
    const observer = new MutationObserver((records) => {
        state.changes += records.filter((r) => {
            return el.contains(r.target) || (r.type === 'attributes' && states.includes(r.attributeName));
        }).length;
    });
    observer.observe(document.body,
        { subtree: true, childList: true, attributes: true, characterData: true });

    const onClick = (e) => { if (el.contains(e.target)) state.clicked = true; };
    document.addEventListener('click', onClick, true);
    window.__magnacodaKeyWatch = { state, observer, onClick };
    el.focus({ preventScroll: true });
    state.focus = document.activeElement;  // moving the focus away (into a menu or dialog) also counts
}
"""
_KEY_RESULT_SCRIPT = """
() => {
    const watch = window.__magnacodaKeyWatch;
    watch.observer.disconnect();
    document.removeEventListener('click', watch.onClick, true);
    const moved = document.activeElement !== watch.state.focus && document.activeElement !== document.body;
    return watch.state.clicked || watch.state.changes > 0 || moved;
}
"""


def try_widgets(page: Page, result: InteractionResult) -> None:
    """Click the toggles (4.1.2), and look for controls only the mouse can use (2.1.1)."""
    with blocked(page, (_MARK, _CLICK_MARK)):
        _toggles(page, result)
        _mouse_only(page, result)


def _toggles(page: Page, result: InteractionResult) -> None:
    try:
        toggles = page.evaluate(_FIND_TOGGLES_SCRIPT, [TOGGLE_LIMIT, _MARK])
    except Exception:  # noqa: BLE001
        return
    result.tested["toggles"] = len(toggles)
    for index, toggle in enumerate(toggles):
        locator = page.locator(f'[{_MARK}="{index}"]')
        args = [index, _MARK, toggle["controls"]]
        try:
            # Hover first, so a tooltip the pointer brings up isn't taken for what the click opened.
            locator.hover(timeout=2000)
            page.wait_for_timeout(_SETTLE_MS)
            before = page.evaluate(_STATE_SCRIPT, args)
            page.evaluate(_SNAPSHOT_SCRIPT)
            locator.click(timeout=2000)
            page.wait_for_timeout(_SETTLE_MS)
            after = page.evaluate(_STATE_SCRIPT, args)
            appeared = page.evaluate(_APPEARED_SCRIPT)
        except Exception:  # noqa: BLE001 - a control that can't be clicked is just skipped
            continue
        element = FeatureExample(selector=toggle["selector"], hint=toggle["hint"])
        opened = appeared is not None or (
            before["target"] is not None and before["target"] != after["target"]
        )
        if toggle["expanded"] is not None:
            if opened and after["expanded"] == before["expanded"]:
                result.problems.append(
                    PageProblem(
                        element=element,
                        kind="expanded-stale",
                        detail=str(before["expanded"]),
                        html=toggle["html"],
                    )
                )
        elif appeared is not None:
            result.problems.append(
                PageProblem(
                    element=element, kind="toggle-no-expanded", detail=f'"{appeared}"', html=toggle["html"]
                )
            )
        _put_back(page, locator, changed=opened or after["expanded"] != before["expanded"])


def _put_back(page: Page, locator, changed: bool) -> None:  # type: ignore[no-untyped-def]
    try:
        if changed:
            locator.click(timeout=2000)
            page.wait_for_timeout(_SETTLE_MS)
        page.keyboard.press("Escape")
    except Exception:  # noqa: BLE001
        pass


def _listeners(cdp: CDPSession | None, index: int) -> set[str]:
    """The pointer events this element itself listens to (Chromium only)."""
    if cdp is None:
        return set()
    try:
        found = cdp.send(
            "Runtime.evaluate", {"expression": f"document.querySelector('[{_CLICK_MARK}=\"{index}\"]')"}
        )
        object_id = found["result"].get("objectId")
        if not object_id:
            return set()
        listeners = cdp.send("DOMDebugger.getEventListeners", {"objectId": object_id})["listeners"]
    except Exception:  # noqa: BLE001
        return set()
    return {listener["type"] for listener in listeners} & _POINTER_EVENTS


def _mouse_only(page: Page, result: InteractionResult) -> None:
    try:
        candidates: list[dict[str, Any]] = page.evaluate(_FIND_CLICKABLE_SCRIPT, [CLICK_LIMIT, _CLICK_MARK])
    except Exception:  # noqa: BLE001
        return
    try:
        cdp: CDPSession | None = page.context.new_cdp_session(page)
    except Exception:  # noqa: BLE001 - not Chromium: only onclick attributes are seen
        cdp = None
    result.tested["clickable"] = len(candidates)
    try:
        for index, candidate in enumerate(candidates):
            reacts = candidate["onclick"] or bool(_listeners(cdp, index))
            if not reacts:
                continue
            element = FeatureExample(selector=candidate["selector"], hint=candidate["hint"])
            if not candidate["focusable"]:
                result.problems.append(
                    PageProblem(element=element, kind="click-only", html=candidate["html"])
                )
            elif not _keys_work(page, index):
                result.problems.append(
                    PageProblem(element=element, kind="keys-dont-work", html=candidate["html"])
                )
    finally:
        if cdp is not None:
            try:
                cdp.detach()
            except Exception:  # noqa: BLE001
                pass


def _keys_work(page: Page, index: int) -> bool:
    """Whether Enter or Space on the focused control makes anything happen."""
    for key in ("Enter", " "):
        try:
            page.evaluate(_KEY_WATCH_SCRIPT, [index, _CLICK_MARK])
            page.keyboard.press(key)
            page.wait_for_timeout(_SETTLE_MS)
            if page.evaluate(_KEY_RESULT_SCRIPT):
                page.keyboard.press("Escape")
                return True
        except Exception:  # noqa: BLE001 - can't tell: don't blame it
            return True
    return False
