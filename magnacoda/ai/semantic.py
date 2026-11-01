from __future__ import annotations

import hashlib
import json
from typing import Any

from playwright.sync_api import Page

from magnacoda.ai.prompts import SEMANTIC_SYSTEM_PROMPT, SemanticReview
from magnacoda.browser.features import PAGE_HELPERS
from magnacoda.findings.models import Finding

# Bounded, targeted extract only — never full-page HTML or a screenshot. Link addresses stay here too:
# only which links go to the same place.
_EXTRACT_SCRIPT = (
    """
() => {
"""
    + PAGE_HELPERS
    + """
    const shown = (el) => {
        const box = el.getBoundingClientRect();
        return box.width > 0 && box.height > 0 && getComputedStyle(el).visibility !== 'hidden';
    };
    // What a screen reader reads: aria-label, aria-labelledby, or the text with images' alt text in place,
    // leaving out what is hidden.
    const nameOf = (el) => {
        const label = (el.getAttribute('aria-label') || '').trim();
        if (label) return label;
        const by = (el.getAttribute('aria-labelledby') || '').split(/\\s+/)
            .map((id) => document.getElementById(id)).filter(Boolean);
        if (by.length) return by.map((n) => n.textContent).join(' ');
        const read = (node) => {
            if (node.nodeType === 3) return node.data;
            if (node.nodeType !== 1 || node.getAttribute('aria-hidden') === 'true') return '';
            if (getComputedStyle(node).display === 'none') return '';
            if (node.localName === 'img') return ' ' + (node.getAttribute('alt') || '') + ' ';
            if (node.getAttribute('aria-label')) return ' ' + node.getAttribute('aria-label') + ' ';
            return Array.from(node.childNodes).map(read).join('');
        };
        return read(el);
    };
    const clean = (text, length) => text.replace(/\\s+/g, ' ').trim().slice(0, length);
    const images = Array.from(document.querySelectorAll('img')).slice(0, 200).map((img) => ({
        selector: selectorFor(img),
        alt: img.getAttribute('alt'),
        src: (img.getAttribute('src') || '').slice(0, 120),
        shown: shown(img),
    }));
    const headings = Array.from(document.querySelectorAll('h1,h2,h3,h4,h5,h6')).slice(0, 200).map((h) => ({
        level: h.tagName,
        selector: selectorFor(h),
        name: clean(nameOf(h), 200),
    }));
    const places = new Map();
    const links = Array.from(document.querySelectorAll('a[href]')).slice(0, 200).map((a) => {
        const place = a.href.split('#')[0];
        if (!places.has(place)) places.set(place, places.size + 1);
        return {
            selector: selectorFor(a),
            name: clean(nameOf(a), 200),
            goes_to: places.get(place),
            context: clean(a.parentElement ? a.parentElement.textContent : '', 300),
        };
    });
    return { images, headings, links };
}
"""
)


def extract_semantic_context(page: Page) -> dict:
    """Pull a bounded DOM extract for semantic review. Must run while the page is still open."""
    return page.evaluate(_EXTRACT_SCRIPT)


def run_semantic_review(
    *,
    page_url: str,
    existing_rule_ids: list[str],
    dom_extract: dict,
    client: Any,
    model: str,
) -> list[Finding]:
    """Ask Claude to review axe-blind categories (alt text quality, reading order, link text,
    heading structure) against a bounded DOM extract, and return them as Finding objects."""
    user_content = (
        f"Page URL: {page_url}\n"
        f"axe-core rules already flagged (do not repeat these categories): "
        f"{sorted(set(existing_rule_ids))}\n\n"
        f"DOM extract (JSON):\n{json.dumps(dom_extract, indent=2)}"
    )

    response = client.messages.parse(
        model=model,
        max_tokens=4096,
        system=SEMANTIC_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}],
        output_format=SemanticReview,
    )
    review: SemanticReview = response.parsed_output

    findings: list[Finding] = []
    for i, item in enumerate(review.findings):
        raw_id = f"{page_url}|claude-semantic/{item.rule_slug}|{item.selector}"
        findings.append(
            Finding(
                finding_id=hashlib.sha256(raw_id.encode("utf-8")).hexdigest()[:16],
                rule_id=f"claude-semantic/{item.rule_slug}",
                wcag_criteria=item.wcag_criteria,
                wcag_level=item.wcag_level,
                severity=item.severity,
                description=item.description,
                selector=item.selector,
                html_snippet=item.html_snippet[:500],
                source="claude-semantic",
                confidence=item.confidence,
                instance_count=1,
                # Placed after all axe findings; true DOM order is unknown for AI-sourced findings.
                dom_order_index=10_000 + i,
            )
        )
    return findings
