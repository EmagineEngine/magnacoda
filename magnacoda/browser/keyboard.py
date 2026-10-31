"""Tab through the page (axe-core never moves focus) for 2.4.7, 2.4.11, 2.1.2, 3.2.1, 2.4.1 and 2.4.3.

Focus visibility compares screenshots with and without focus; a text caret counts, as the
Understanding doc allows. A modal dialog may keep the focus without being a trap. Runs with requests
blocked, up to TAB_LIMIT elements.
"""

from __future__ import annotations

from typing import Any, Literal

from playwright.sync_api import FloatRect, Page

from magnacoda.browser.blocking import Watch, blocked
from magnacoda.browser.features import PAGE_HELPERS
from magnacoda.findings.models import FeatureExample, KeyboardProblem, KeyboardResult

TAB_LIMIT = 100
_IFRAME_PRESSES = 30  # Tab presses allowed inside one embedded frame before it counts as stuck
_TAB_SETTLE_MS = 40
_REFOCUS_SETTLE_MS = 25  # a focus handler's page load or new window shows up within a few milliseconds
_JUMP_PX = 150  # how far back up the page the focus must jump to be listed
_JUMP_LIMIT = 10
_STOP_MARK = "data-magnacoda-stop"

# Put the keyboard's starting point at the top of the page, with nothing focused, and log each focus.
START_SCRIPT = """
() => {
    if (!window.__magnacodaFocusLog) {
        window.__magnacodaFocusLog = [];
        // 'focus' (captured), not 'focusin': it comes in the order the elements got the focus
        document.addEventListener('focus', (e) => window.__magnacodaFocusLog.push(e.target), true);
    }
    window.scrollTo(0, 0);
    const body = document.body;
    const had = body.getAttribute('tabindex');
    body.setAttribute('tabindex', '-1');
    body.focus({ preventScroll: true });
    if (had === null) body.removeAttribute('tabindex'); else body.setAttribute('tabindex', had);
    window.__magnacodaFocusLog.length = 0;
}
"""

# The element that has the focus now: who it is, where, whether something fixed covers it, and whether a
# script moved the focus on from where Tab put it.
_STOP_SCRIPT = (
    """
(mark) => {
"""
    + PAGE_HELPERS
    + """
    const log = window.__magnacodaFocusLog || [];
    const seenFocus = log.slice();
    log.length = 0;
    const el = document.activeElement;
    if (!el || el === document.body || el === document.documentElement) return null;
    const describe = (node) => ({ selector: selectorFor(node), hint: hintFor(node) });
    const fixed = (node) => {
        for (let n = node; n && n.nodeType === 1; n = n.parentElement) {
            const position = getComputedStyle(n).position;
            if (position === 'fixed' || position === 'sticky') return n;
        }
        return null;
    };
    let index = el.getAttribute(mark);
    const isNew = index === null;
    const html = htmlOf(el);
    if (isNew) {
        index = String(window.__magnacodaStops || 0);
        window.__magnacodaStops = Number(index) + 1;
        el.setAttribute(mark, index);
    }
    const r = el.getBoundingClientRect();
    const width = innerWidth, height = innerHeight;
    const points = [[0.5, 0.5], [0.1, 0.1], [0.9, 0.1], [0.1, 0.9], [0.9, 0.9]]
        .map(([fx, fy]) => [r.left + r.width * fx, r.top + r.height * fy])
        .filter(([x, y]) => x >= 0 && y >= 0 && x < width && y < height);
    let cover = null;
    const ownFixed = fixed(el);
    const covered = points.length > 0 && r.width >= 1 && r.height >= 1 && points.every(([x, y]) => {
        const hit = document.elementFromPoint(x, y);
        if (!hit || el.contains(hit) || hit.contains(el)) return false;
        const box = fixed(hit);
        if (!box || box === ownFixed || box.contains(el)) return false;
        cover = cover || box;
        return true;
    });
    const first = seenFocus.find((node) => node !== document.body) || el;
    const moved = first !== el && !first.contains(el);
    return {
        index: Number(index), isNew, html, ...describe(el),
        rect: { x: r.left, y: r.top, width: r.width, height: r.height },
        top: r.top + scrollY, inFixed: Boolean(ownFixed),
        obscured: covered, cover: cover ? describe(cover) : null,
        moved, from: moved ? { ...describe(first), html: htmlOf(first) } : null,
        textEntry: el.isContentEditable || el.localName === 'textarea' || (el.localName === 'input'
            && !['checkbox', 'radio', 'button', 'submit', 'reset', 'image', 'range', 'color', 'file']
                .includes(el.type)),
        frame: el.localName === 'iframe' || el.localName === 'object' || el.localName === 'embed',
        inModal: Boolean(el.closest('[aria-modal="true"], dialog[open]')),
        href: el.localName === 'a' ? el.getAttribute('href') : null,
        text: (el.innerText || el.getAttribute('aria-label') || '').trim().slice(0, 80),
    };
}
"""
)

_BLUR_SCRIPT = (
    f"(index) => {{ const el = document.querySelector('[{_STOP_MARK}=\"' + index + '\"]');"
    " if (el) el.blur(); }"
)
_REFOCUS_SCRIPT = (
    f"(index) => {{ const el = document.querySelector('[{_STOP_MARK}=\"' + index + '\"]');"
    " if (el) el.focus({ preventScroll: true }); (window.__magnacodaFocusLog || []).length = 0; }"
)

# After Enter on a skip link and one more Tab: did the focus land inside or after the link's target?
_SKIPPED_SCRIPT = """
(href) => {
    const id = decodeURIComponent(href.slice(1));
    const target = document.getElementById(id) || document.getElementsByName(id)[0];
    const now = document.activeElement;
    if (!target) return 'missing';
    if (!now || now === document.body) return 'broken';
    const after = target.compareDocumentPosition(now) & Node.DOCUMENT_POSITION_FOLLOWING;
    return target === now || target.contains(now) || after ? 'works' : 'broken';
}
"""

_SKIP_WORDS = ("skip", "jump", "main content", "go to content", "to content")


def press_tab_through(page: Page, limit: int = TAB_LIMIT) -> KeyboardResult:
    """Press Tab through the page (up to `limit` elements) and report what a keyboard user would meet."""
    result = KeyboardResult()
    with blocked(page, (_STOP_MARK,)) as watch:
        page.evaluate(START_SCRIPT)
        stops: list[dict[str, Any]] = []
        flagged: set[tuple[str, str]] = set()
        frame_presses = 0
        pending: dict[str, Any] | None = None
        for _ in range(limit * 2 + _IFRAME_PRESSES):
            if len(stops) >= limit:
                break
            if pending is not None:
                info, pending = pending, None
            else:
                watch.clear()
                page.keyboard.press("Tab")
                page.wait_for_timeout(_TAB_SETTLE_MS)
                info = page.evaluate(_STOP_SCRIPT, _STOP_MARK)
                _on_focus(result, flagged, watch, info, page)
            if info is None:  # past the last element: the focus left the page
                result.complete = True
                break
            if not info["isNew"]:
                if info["frame"] and stops and info["index"] == stops[-1]["index"]:
                    frame_presses += 1  # still moving around inside an embedded frame
                    if frame_presses < _IFRAME_PRESSES:
                        continue
                    _add(result, flagged, info, "keyboard-trap", "Tab never leaves this embedded content")
                    break
                if info["index"] == 0:  # back at the first element: all the way round
                    result.complete = True
                    break
                cycle = [s for s in stops if s["index"] >= info["index"]]
                if all(s["inModal"] for s in cycle):
                    break  # an open modal dialog keeps the focus, as it should
                escaped = _escape(page, watch, {s["index"] for s in cycle})
                if escaped is False:
                    stuck = ", ".join(_name(s) for s in cycle[:4])
                    _add(result, flagged, cycle[0], "keyboard-trap", f"Tab keeps going round: {stuck}")
                    break
                if escaped is True:
                    break  # only Shift+Tab gets out: not a trap, but Tab can't go on from here
                pending = escaped  # Escape got out: carry on from there
                continue
            frame_presses = 0
            if stops and not info["inFixed"] and not stops[-1]["inFixed"]:
                if info["top"] < stops[-1]["top"] - _JUMP_PX and len(result.jumps) < _JUMP_LIMIT:
                    result.jumps.append((_example(stops[-1]), _example(info)))
            stops.append(info)
            if info["obscured"]:
                cover = info["cover"] or {}
                detail = f"covered by {cover.get('selector', 'something fixed')}"
                if cover.get("hint"):
                    detail += f' ("{cover["hint"]}")'
                _add(result, flagged, info, "focus-obscured", detail)
            elif not info["frame"]:
                shows = _focus_shows(page, info)
                # Giving the focus back may run the element's focus handler again: let that settle.
                page.wait_for_timeout(_REFOCUS_SETTLE_MS)
                watch.clear()
                if shows is False and not info["textEntry"]:
                    _add(result, flagged, info, "focus-not-visible", "")
        result.stops = len(stops)
        if stops and stops[0]["href"] and _looks_like_skip_link(stops[0]):
            result.skip_link = _try_skip_link(page, stops[0])
            if result.skip_link == "broken":
                _add(result, flagged, stops[0], "skip-link", "")
    return result


def _example(info: dict[str, Any]) -> FeatureExample:
    return FeatureExample(selector=info["selector"], hint=info["hint"])


def _name(info: dict[str, Any]) -> str:
    return info["selector"] + (f' ("{info["hint"]}")' if info["hint"] else "")


def _add(
    result: KeyboardResult, flagged: set[tuple[str, str]], info: dict[str, Any], kind: str, detail: str
) -> None:
    if (info["selector"], kind) in flagged:
        return
    flagged.add((info["selector"], kind))
    result.problems.append(
        KeyboardProblem(element=_example(info), kind=kind, detail=detail, html=info.get("html", ""))  # type: ignore[arg-type]
    )


def _on_focus(
    result: KeyboardResult,
    flagged: set[tuple[str, str]],
    watch: Watch,
    info: dict[str, Any] | None,
    page: Page,
) -> None:
    """3.2.1: what getting the focus alone made the page do."""
    effects = list(watch.events)
    if watch.windows_opened():
        effects.append("opened a new window")
    target = info
    if info is not None and info["moved"]:
        effects.append("moved the focus somewhere else")
        target = {**info["from"], "html": info["from"]["html"]}
    if effects and target is not None:
        _add(result, flagged, target, "on-focus", " and ".join(dict.fromkeys(effects)))


def _escape(page: Page, watch: Watch, cycle: set[int]) -> dict[str, Any] | bool:
    """Try to escape a Tab loop: Escape+Tab (returns where focus went), else Shift+Tab (True), else False."""
    page.keyboard.press("Escape")
    page.keyboard.press("Tab")
    page.wait_for_timeout(_TAB_SETTLE_MS)
    info = page.evaluate(_STOP_SCRIPT, _STOP_MARK)
    if info is None or info["isNew"] or info["index"] not in cycle:
        return info if info is not None and info["isNew"] else True
    for _ in range(len(cycle) + 1):
        page.keyboard.press("Shift+Tab")
        page.wait_for_timeout(_TAB_SETTLE_MS)
        info = page.evaluate(_STOP_SCRIPT, _STOP_MARK)
        if info is None or info["index"] not in cycle:
            return True
    watch.clear()
    return False


# The styles that draw a focus indicator, on the element and its ::before and ::after, with and without
# the focus (the element is given the focus back afterwards): true if any of them differ.
_STYLE_CHANGES_SCRIPT = (
    f"""
(index) => {{
    const el = document.querySelector('[{_STOP_MARK}="' + index + '"]');
    if (!el) return false;"""
    + """
    // Only what is drawn counts: an outline's offset or color doesn't show while it is switched off
    // (the browser's own focus style sets an offset even where the page turns the outline off).
    const drawn = (cs) => {
        const parts = ['box-shadow', 'background-color', 'background-image', 'color', 'opacity',
            'transform', 'filter', 'text-decoration-line'].map((p) => cs.getPropertyValue(p));
        if (cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) > 0) {
            parts.push(cs.outlineStyle, cs.outlineWidth, cs.outlineColor, cs.outlineOffset);
        }
        for (const side of ['top', 'right', 'bottom', 'left']) {
            const width = cs.getPropertyValue(`border-${side}-width`);
            if (cs.getPropertyValue(`border-${side}-style`) !== 'none' && parseFloat(width) > 0) {
                parts.push(width, cs.getPropertyValue(`border-${side}-color`));
            }
        }
        if (cs.textDecorationLine !== 'none') parts.push(cs.textDecorationThickness, cs.textDecorationColor);
        return parts.join('|') + '|' + cs.content;
    };
    const look = () => [null, '::before', '::after'].map((pseudo) => drawn(getComputedStyle(el, pseudo)))
        .join('#');
    const focused = look();
    el.blur();
    const unfocused = look();
    el.focus({ preventScroll: true });
    (window.__magnacodaFocusLog || []).length = 0;
    return focused !== unfocused;
}
"""
)


def _focus_shows(page: Page, info: dict[str, Any]) -> bool | None:
    """Whether anything on screen changes when the element loses the focus (None: can't be pictured)."""
    viewport = page.viewport_size or {"width": 1280, "height": 800}
    rect = info["rect"]
    left, top = max(rect["x"] - 6, 0), max(rect["y"] - 6, 0)
    right = min(rect["x"] + rect["width"] + 6, viewport["width"])
    bottom = min(rect["y"] + rect["height"] + 6, viewport["height"])
    if right - left < 2 or bottom - top < 2:
        return None
    clip: FloatRect = {"x": left, "y": top, "width": right - left, "height": bottom - top}
    try:
        # Cheap style check first; screenshots (~0.3 s on a big page) only when it's inconclusive,
        # e.g. an indicator drawn by a parent's :focus-within.
        if page.evaluate(_STYLE_CHANGES_SCRIPT, info["index"]):
            return True
        focused = page.screenshot(clip=clip, animations="disabled")  # the text cursor is hidden
        page.evaluate(_BLUR_SCRIPT, info["index"])
        unfocused = page.screenshot(clip=clip, animations="disabled")
        page.evaluate(_REFOCUS_SCRIPT, info["index"])
    except Exception:  # noqa: BLE001 - an element that can't be pictured is just not judged
        return None
    return focused != unfocused


def _looks_like_skip_link(info: dict[str, Any]) -> bool:
    href = info["href"] or ""
    text = info["text"].lower()
    return href.startswith("#") and len(href) > 1 and any(word in text for word in _SKIP_WORDS)


def _try_skip_link(page: Page, first: dict[str, Any]) -> Literal["works", "broken", "none"]:
    """Activate the skip link from the top of the page, press Tab once more, and see where the focus is."""
    try:
        page.evaluate(START_SCRIPT)
        page.keyboard.press("Tab")
        page.keyboard.press("Enter")
        page.wait_for_timeout(150)
        page.keyboard.press("Tab")
        page.wait_for_timeout(_TAB_SETTLE_MS)
        outcome = page.evaluate(_SKIPPED_SCRIPT, first["href"])
    except Exception:  # noqa: BLE001
        return "none"
    return "works" if outcome == "works" else "broken"
