"""Moving content (2.2.2) and audio description tracks (1.2.3, 1.2.5).

The motion watch starts after the page is read and is read before the interaction tests, so it only
sees what the page does on its own. Anything that moves with no pause/stop control nearby is reported.
"""

from __future__ import annotations

from playwright.sync_api import Page

from magnacoda.browser.features import PAGE_HELPERS
from magnacoda.findings.models import FeatureExample, InteractionResult, PageNote, PageProblem

MOTION_MS = 6000
_LIMIT = 10

_WATCH_SCRIPT = """
() => {
    if (window.__magnacodaMotion) return;
    const changes = new Map();
    const note = (el) => {
        if (!el || el.nodeType !== 1) return;
        const times = changes.get(el) || [];
        times.push(performance.now());
        changes.set(el, times);
    };
    const observer = new MutationObserver((records) => {
        for (const r of records) {
            // Playwright's screenshots leave an empty style on form fields: not movement.
            if (r.type === 'attributes' && r.attributeName === 'style' && r.oldValue === null
                && r.target.getAttribute('style') === '') continue;
            note(r.type === 'characterData' ? r.target.parentElement : r.target);
        }
    });
    observer.observe(document.body, {
        subtree: true, childList: true, characterData: true, attributes: true,
        attributeFilter: ['style', 'class', 'transform'], attributeOldValue: true,
    });
    window.__magnacodaMotion = { start: performance.now(), changes, observer };
}
"""

_ELAPSED_SCRIPT = "() => window.__magnacodaMotion ? performance.now() - window.__magnacodaMotion.start : -1"

_READ_SCRIPT = (
    """
(limit) => {
"""
    + PAGE_HELPERS
    + """
    const state = window.__magnacodaMotion;
    state.observer.disconnect();
    const visible = (el, w, h) => {
        const r = el.getBoundingClientRect();
        const cs = getComputedStyle(el);
        return r.width >= w && r.height >= h && cs.display !== 'none' && cs.visibility !== 'hidden'
            && cs.opacity !== '0';
    };
    const movers = [];
    for (const [el, times] of state.changes) {
        if (!el.isConnected || times.length < 2 || times[times.length - 1] - times[0] < 400) continue;
        if (el.closest('[data-magnacoda-stop], input, select, textarea')) continue;
        if (visible(el, 24, 16)) movers.push([el, 'changes by itself']);
    }
    for (const animation of document.getAnimations()) {
        const target = animation.effect && animation.effect.target;
        const timing = animation.effect && animation.effect.getComputedTiming();
        if (target && target.nodeType === 1 && timing && timing.iterations === Infinity
            && animation.playState === 'running' && visible(target, 48, 48)) {
            movers.push([target, 'keeps animating']);
        }
    }
    for (const video of document.querySelectorAll('video')) {
        if (!video.paused && (video.loop || video.duration > 5) && visible(video, 24, 16)) {
            movers.push([video, 'plays by itself']);
        }
    }
    // Outermost only, once each.
    const kept = [];
    for (const [el, how] of movers) {
        if (kept.some(([k]) => k === el || k.contains(el))) continue;
        for (let i = kept.length - 1; i >= 0; i--) if (el.contains(kept[i][0])) kept.splice(i, 1);
        kept.push([el, how]);
    }
    const pauseWords = /\\b(pause|stop|play|freeze|halt)\\b/i;
    const hasPause = (el) => {
        if (el.localName === 'video' && el.controls) return true;
        // Up to three levels up, but not into the page's main parts: a pause button elsewhere on the
        // page doesn't belong to this.
        const landmark = 'body, main, [role="main"], header, footer, nav, aside, article, section, form';
        let scope = el;
        for (let i = 0; i < 3 && scope.parentElement && !scope.parentElement.matches(landmark); i++) {
            scope = scope.parentElement;
        }
        for (const c of scope.querySelectorAll('button, [role="button"], a, input[type="button"]')) {
            const text = [c.getAttribute('aria-label'), c.innerText, c.title, c.value].join(' ');
            if (pauseWords.test(text) || c.hasAttribute('aria-pressed')) return true;
        }
        return false;
    };
    return kept.slice(0, limit).map(([el, how]) => ({
        selector: selectorFor(el), hint: hintFor(el), html: htmlOf(el), how, pause: hasPause(el),
    }));
}
"""
)

_TRACKS_SCRIPT = (
    """
(limit) => {
"""
    + PAGE_HELPERS
    + """
    return Array.from(document.querySelectorAll('video')).slice(0, limit).map((video) => ({
        selector: selectorFor(video), hint: hintFor(video),
        kinds: Array.from(video.querySelectorAll('track')).map((t) => (t.getAttribute('kind') || 'subtitles')
            .toLowerCase()),
    }));
}
"""
)


def start_motion_watch(page: Page) -> None:
    """Start noting what changes on the page by itself (read later by `read_motion`)."""
    try:
        page.evaluate(_WATCH_SCRIPT)
    except Exception:  # noqa: BLE001 - without a watch, nothing is reported
        pass


def read_motion(page: Page, result: InteractionResult) -> None:
    """Wait until the watch has seen the page for MOTION_MS, then note what moved by itself."""
    try:
        elapsed = page.evaluate(_ELAPSED_SCRIPT)
        if elapsed < 0:
            return
        if elapsed < MOTION_MS:
            page.wait_for_timeout(MOTION_MS - elapsed)
        movers = page.evaluate(_READ_SCRIPT, _LIMIT)
    except Exception:  # noqa: BLE001
        return
    result.tested["motion"] = len(movers)
    for mover in movers:
        element = FeatureExample(selector=mover["selector"], hint=mover["hint"])
        if mover["pause"]:
            result.notes.append(
                PageNote(
                    element=element,
                    num="2.2.2",
                    note=f" *It {mover['how']}, and has a pause, stop or play button near it*: check that "
                    "the button works with the keyboard and stops all of it.",
                )
            )
        else:
            result.problems.append(
                PageProblem(element=element, kind="moving-no-pause", detail=mover["how"], html=mover["html"])
            )


def note_media_tracks(page: Page, result: InteractionResult) -> None:
    """Note on each video's 1.2.3 and 1.2.5 Check items whether it has an audio description track."""
    try:
        videos = page.evaluate(_TRACKS_SCRIPT, _LIMIT)
    except Exception:  # noqa: BLE001
        return
    result.tested["videos"] = len(videos)
    for video in videos:
        element = FeatureExample(selector=video["selector"], hint=video["hint"])
        if "descriptions" in video["kinds"]:
            note = " *It has an audio description track*: check that it describes what's shown."
        else:
            note = (
                ' *It has no audio description track* (`<track kind="descriptions">`): unless its own '
                "sound already says everything that's shown, add one, or a text version."
            )
        for num in ("1.2.3", "1.2.5"):
            result.notes.append(PageNote(element=element, num=num, note=note))
