from __future__ import annotations

from playwright.sync_api import Page

from magnacoda.findings.models import FeatureExample, OptionGroup, PageFeatures

_EXAMPLES_PER_FEATURE = 20  # the checklist's "Page elements" lists each one, with its own checks

# Shared page-side helpers: selectorFor(el) gives a short CSS selector, hintFor(el) a human-readable name.
PAGE_HELPERS = """
    // A short CSS selector that finds this element: its id when that is unique, otherwise a path of
    // tag, a couple of classes and :nth-of-type, up to four levels, stopping as soon as it is unique.
    const selectorFor = (el) => {
        const unique = (sel) => {
            try { return document.querySelectorAll(sel).length === 1; } catch (e) { return false; }
        };
        if (el.id && unique('#' + CSS.escape(el.id))) return '#' + CSS.escape(el.id);
        const parts = [];
        let node = el;
        for (let depth = 0; node && node.nodeType === 1 && depth < 4; depth++) {
            let part = node.localName;
            if (node.id && unique('#' + CSS.escape(node.id))) {
                parts.unshift('#' + CSS.escape(node.id));
                break;
            }
            const classes = Array.from(node.classList)
                .filter((c) => /^[A-Za-z_-][\\w-]*$/.test(c))
                .slice(0, 2);
            if (classes.length) part += '.' + classes.join('.');
            const parent = node.parentElement;
            if (parent) {
                const same = Array.from(parent.children).filter((c) => c.localName === node.localName);
                if (same.length > 1) part += ':nth-of-type(' + (same.indexOf(node) + 1) + ')';
            }
            parts.unshift(part);
            if (unique(parts.join(' > '))) break;
            node = parent;
        }
        return parts.join(' > ');
    };

    // Its HTML, shortened, as the page wrote it (Playwright's screenshots leave an empty style="" on
    // form fields, which means nothing).
    const htmlOf = (el) => el.outerHTML.replace(/ style=""/g, '').slice(0, 500);

    // What a person would recognize it by: its label (aria-label, or a form field's own <label>), alt
    // text, title, placeholder, source or first words.
    const hintFor = (el) => {
        const label = el.labels && el.labels.length ? el.labels[0].innerText : '';
        const text = el.getAttribute('aria-label') || label || el.getAttribute('alt')
            || el.getAttribute('title')
            || el.getAttribute('placeholder') || el.getAttribute('src')
            || (el.innerText || el.textContent || '');
        const clean = text.replace(/\\s+/g, ' ').trim();
        return clean.length > 50 ? clean.slice(0, 49) + '\u2026' : clean;
    };

"""

# One pass over the live DOM. Counts drive which manual WCAG checks are relevant to this page, and a few
# examples of each feature (a CSS selector, and a short visible hint) say where to look.
_DETECT_SCRIPT = (
    """
(limit) => {
    const counts = {};
    const examples = {};
"""
    + PAGE_HELPERS
    + """
    const add = (name, elements) => {
        const list = Array.from(elements);
        counts[name] = (counts[name] || 0) + list.length;
        const kept = examples[name] || (examples[name] = []);
        for (const el of list) {
            if (kept.length >= limit) break;
            kept.push({ selector: selectorFor(el), hint: hintFor(el) });
        }
    };
    const all = (selector) => document.querySelectorAll(selector);

    const fixed = [];
    const animated = Array.from(
        all('marquee, blink, [class*="carousel" i], [class*="swiper" i], [class*="slick" i]')
    );
    for (const el of Array.from(document.querySelectorAll('body *')).slice(0, 3000)) {
        const cs = getComputedStyle(el);
        if (cs.display === 'none' || cs.visibility === 'hidden') continue;
        if (cs.position === 'fixed' || cs.position === 'sticky') fixed.push(el);
        if (cs.animationName !== 'none'
            && cs.animationIterationCount.split(',').some((v) => v.trim() === 'infinite')) animated.push(el);
    }

    add('video', all('video'));
    add('audio', all('audio'));
    add('autoplay_media', all('video[autoplay], audio[autoplay]'));
    add('iframes', all('iframe'));
    add('embeds', all('object, embed'));
    add('canvas', all('canvas'));
    add('images', all('img, picture, [role="img"]'));
    add('svg', all('svg'));
    add('forms', all('form'));
    add('inputs', all('input:not([type="hidden"]):not([type="submit"]):not([type="button"]), '
                      + 'select, textarea'));
    add('password_inputs', all('input[type="password"], input[autocomplete~="current-password"], '
                               + 'input[autocomplete~="new-password"]'));
    add('captcha', all('[class*="captcha" i], [id*="captcha" i], iframe[src*="recaptcha" i], '
                       + 'iframe[src*="hcaptcha" i]'));
    add('live_regions', all('[aria-live]:not([aria-live="off"]), [role="status"], [role="alert"], '
                            + '[role="log"]'));
    add('custom_widgets', all('[role="dialog"], [role="alertdialog"], [role="tablist"], [role="menu"], '
                              + '[role="menubar"], [role="slider"], [role="combobox"], [role="listbox"], '
                              + '[role="tree"], [role="grid"], [role="treegrid"], [role="switch"]'));
    add('popups', all('[aria-haspopup]:not([aria-haspopup="false"]), [role="tooltip"], [popover], '
                      + '[data-tooltip], [data-bs-toggle="tooltip"], [data-toggle="tooltip"], '
                      + 'body [title]:not(iframe):not(img):not(svg)'));
    add('draggable', all('[draggable="true"], [class*="sortable" i], [class*="draggable" i]'));
    add('animated', animated);
    add('meta_refresh', all('meta[http-equiv="refresh" i]'));
    add('fixed_elements', fixed);
    add('labelled_controls', all('button[aria-label], a[aria-label], input[aria-label], '
                                 + '[role="button"][aria-label]'));

    // Reachable with Tab and by screen readers, yet invisible: moved off-screen, clipped or shrunk to
    // almost nothing, or fully transparent (itself or an ancestor). An element that shows up when it
    // gets focus (a "Skip to content" link) is fine, so each candidate is focused once and measured
    // again; focus is cleared afterwards.
    const looksInvisible = (el) => {
        const r = el.getBoundingClientRect();
        if (r.width < 2 || r.height < 2) return true;
        if (r.right + window.scrollX < 0 || r.bottom + window.scrollY < 0) return true;
        for (let node = el; node && node !== document.body; node = node.parentElement) {
            const cs = getComputedStyle(node);
            if (parseFloat(cs.opacity) === 0) return true;
            if (cs.clip === 'rect(0px, 0px, 0px, 0px)' || /inset\\(50%\\)/.test(cs.clipPath)) return true;
        }
        return false;
    };
    const hiddenReachable = [];
    const focusable = 'a[href], button, input:not([type="hidden"]), select, textarea, '
        + '[tabindex]:not([tabindex="-1"]), [contenteditable="true"]';
    for (const el of Array.from(document.querySelectorAll(focusable)).slice(0, 500)) {
        const cs = getComputedStyle(el);
        if (cs.display === 'none' || cs.visibility === 'hidden' || el.disabled || el.tabIndex < 0) continue;
        // Inside a display: none parent (such as [hidden]) the element isn't rendered, so Tab skips it.
        if (el.checkVisibility ? !el.checkVisibility() : el.getClientRects().length === 0) continue;
        if (el.closest('[aria-hidden="true"], [inert]')) continue;
        if (!looksInvisible(el)) continue;
        el.focus({ preventScroll: true });
        const stillInvisible = looksInvisible(el);
        el.blur();
        if (stillInvisible) hiddenReachable.push(el);
    }
    if (document.activeElement && document.activeElement !== document.body) document.activeElement.blur();
    add('hidden_reachable', hiddenReachable);
    return { ...counts, examples };
}
"""
)


def detect_page_features(page: Page) -> PageFeatures:
    """Count page features that determine which manual checks apply. Must run while the page is open."""
    return PageFeatures(**page.evaluate(_DETECT_SCRIPT, _EXAMPLES_PER_FEATURE))


# For each selector axe-core reported, the same element's name as magnacoda writes it (selectorFor) and its
# hint, so a failure and the manual checks or screenshot for one element can be listed together.
_NAME_SCRIPT = (
    """
(selectors) => {
"""
    + PAGE_HELPERS
    + """
    const named = {};
    for (const sel of selectors) {
        let el = null;
        try { el = document.querySelector(sel); } catch (e) { el = null; }
        if (el) named[sel] = { selector: selectorFor(el), hint: hintFor(el) };
    }
    return named;
}
"""
)


def name_axe_elements(page: Page, raw: dict) -> dict[str, FeatureExample]:
    """Map axe-core's selectors for failing/incomplete elements to readable hints.

    Selectors that no longer match, or point into frames, are left out.
    """
    selectors: set[str] = set()
    for key in ("violations", "incomplete"):
        for rule in raw.get(key, []):
            for node in rule.get("nodes", []):
                target = node.get("target", [])
                if target and all(isinstance(part, str) for part in target):
                    selectors.add(" ".join(target))
    if not selectors:
        return {}
    named = page.evaluate(_NAME_SCRIPT, sorted(selectors))
    return {sel: FeatureExample(**name) for sel, name in named.items()}


# Groups of 2+ radios/checkboxes sharing a name: their container, its name, and the options.
_GROUPS_SCRIPT = (
    """
() => {
"""
    + PAGE_HELPERS
    + """
    const groups = new Map();
    for (const el of document.querySelectorAll('input[type="radio"][name], input[type="checkbox"][name]')) {
        const key = [el.type, el.form ? Array.from(document.forms).indexOf(el.form) : -1, el.name].join('|');
        if (!groups.has(key)) groups.set(key, []);
        groups.get(key).push(el);
    }
    const textOf = (ids) => (ids || '').split(/\\s+/).map((id) => document.getElementById(id))
        .filter(Boolean).map((t) => t.innerText.trim()).join(' ');
    const found = [];
    for (const members of groups.values()) {
        if (members.length < 2) continue;
        const holder = members[0].closest('fieldset, [role="radiogroup"], [role="group"]');
        let box = holder && members.every((m) => holder.contains(m)) ? holder : members[0].parentElement;
        while (box && !members.every((m) => box.contains(m))) box = box.parentElement;
        if (!box || box === document.body) continue;
        const legend = box.localName === 'fieldset' && box.querySelector(':scope > legend');
        const name = (legend && legend.innerText.trim()) || box.getAttribute('aria-label')
            || textOf(box.getAttribute('aria-labelledby'));
        const options = members.map((m) => ({ selector: selectorFor(m), hint: hintFor(m) }));
        const hint = (name || options.map((o) => o.hint).join(', ')).replace(/\\s+/g, ' ').trim();
        const short = hint.length > 50 ? hint.slice(0, 49) + '\u2026' : hint;
        const grouping = box.matches('fieldset, [role="radiogroup"], [role="group"]');
        found.push({
            element: { selector: selectorFor(box), hint: short }, options,
            named: Boolean(grouping && name), html: htmlOf(box).split('>')[0] + '>',
        });
    }
    return found;
}
"""
)


def find_option_groups(page: Page) -> list[OptionGroup]:
    """Radio buttons and checkboxes that share a name: one question, listed once in the checklist."""
    try:
        return [OptionGroup.model_validate(group) for group in page.evaluate(_GROUPS_SCRIPT)]
    except Exception:  # noqa: BLE001 - without groups, each option is listed on its own, as before
        return []
