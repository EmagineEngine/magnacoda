"""Dark mode: whether the page changes at all, and which checks to rerun if it does.

The full scan runs in light mode. The dark pass only reruns what colors can affect (contrast, images,
focus visibility), and is skipped when the page looks the same in both.
"""

from __future__ import annotations

import hashlib

from playwright.sync_api import Page

# Images too: a dark-mode logo is often a different image with its own alt text.
AXE_RULES = (
    "color-contrast",
    "link-in-text-block",
    "image-alt",
    "svg-img-alt",
    "role-img-alt",
    "input-image-alt",
    "object-alt",
    "area-alt",
)
AXE_RULES_AAA = ("color-contrast-enhanced",)
AXE_RULES_BEST_PRACTICE = ("image-redundant-alt",)
# A focus indicator can vanish against a dark background.
OWN_RULES = ("magnacoda/focus-not-visible",)

# Colors (and images) of the first ~400 visible elements, in page order.
_FINGERPRINT = """() => {
  const out = [];
  const root = getComputedStyle(document.documentElement);
  out.push(root.backgroundColor + '|' + root.color + '|' + root.colorScheme);
  for (const el of document.querySelectorAll('body, body *')) {
    if (out.length > 400) break;
    if (!el.getClientRects().length) continue;
    const s = getComputedStyle(el);
    if (s.visibility === 'hidden') continue;
    out.push([el.tagName, s.color, s.backgroundColor, s.borderTopColor, s.fill,
              s.backgroundImage.slice(0, 200), el.currentSrc || ''].join('|'));
  }
  return out.join('\\n');
}"""


def axe_rules(level: str, include_best_practice: bool) -> list[str]:
    rules = list(AXE_RULES)
    if level == "AAA":
        rules += AXE_RULES_AAA
    if include_best_practice:
        rules += AXE_RULES_BEST_PRACTICE
    return rules


def fingerprint(page: Page) -> str | None:
    """Hash of the page's current colors, or None if the page can't be read."""
    try:
        text = page.evaluate(_FINGERPRINT)
    except Exception:  # noqa: BLE001 - unknown, so run the dark pass
        return None
    return hashlib.sha1(str(text).encode("utf-8")).hexdigest()


def covered(level: str, include_best_practice: bool) -> set[str]:
    """Rules the dark pass runs (axe-core's and magnacoda's)."""
    return set(axe_rules(level, include_best_practice)) | set(OWN_RULES)
