"""Screenshots of the page's images, shown next to their alt text in the checklist (1.1.1, 1.4.5).

Never sent to the AI tiers.
"""

from __future__ import annotations

from playwright.sync_api import Page

from magnacoda.browser.features import PAGE_HELPERS
from magnacoda.findings.models import PageImage

IMAGE_LIMIT = 30
_SHOT_TIMEOUT_MS = 3000
_MARK = "data-magnacoda-shot"

# Marks the first `limit` visible images so Playwright can find each one again for its screenshot.
_FIND_SCRIPT = (
    """
([limit, mark]) => {
"""
    + PAGE_HELPERS
    + """
    const selector = 'img, svg, canvas, [role="img"], input[type="image"]';
    const found = [];
    let total = 0;
    for (const el of document.querySelectorAll(selector)) {
        if (el.parentElement && el.parentElement.closest(selector)) continue;
        const box = el.getBoundingClientRect();
        const cs = getComputedStyle(el);
        if (box.width < 2 || box.height < 2 || cs.display === 'none' || cs.visibility === 'hidden') continue;
        total++;
        if (found.length >= limit) continue;
        const tag = el.localName;
        const kind = tag === 'input' ? 'input-image'
            : (tag === 'img' || tag === 'svg' || tag === 'canvas') ? tag : 'role-img';
        const labelledby = (el.getAttribute('aria-labelledby') || '').split(/\\s+/)
            .map((id) => document.getElementById(id)).filter(Boolean)
            .map((node) => node.innerText).join(' ').trim();
        const named = el.getAttribute('aria-label') || labelledby || el.getAttribute('title')
            || (tag === 'svg' && el.querySelector('title') ? el.querySelector('title').textContent : '');
        el.setAttribute(mark, String(found.length));
        found.push({
            selector: selectorFor(el),
            kind,
            alt: el.hasAttribute('alt') ? el.getAttribute('alt') : null,
            label: named ? named.replace(/\\s+/g, ' ').trim() : null,
            src: el.currentSrc || el.getAttribute('src') || null,
            width: Math.round(box.width),
            height: Math.round(box.height),
        });
    }
    return { found, total };
}
"""
)


def capture_images(page: Page, limit: int = IMAGE_LIMIT) -> tuple[list[PageImage], int]:
    """The first `limit` visible images (with screenshots where possible), and the total count."""
    result = page.evaluate(_FIND_SCRIPT, [limit, _MARK])
    images = []
    for index, info in enumerate(result["found"]):
        image = PageImage(**info)
        try:
            element = page.query_selector(f'[{_MARK}="{index}"]')
            if element is not None:
                image.png = element.screenshot(timeout=_SHOT_TIMEOUT_MS, animations="disabled")
        except Exception:  # noqa: BLE001 - an image that won't photograph is still listed
            image.png = None
        images.append(image)
    page.evaluate(
        f"() => document.querySelectorAll('[{_MARK}]').forEach((el) => el.removeAttribute('{_MARK}'))"
    )
    return images, int(result["total"])
