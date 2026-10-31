from __future__ import annotations

import re

from magnacoda.findings.models import WcagLevel

# axe-core tags success criteria as e.g. "wcag111" -> 1.1.1, "wcag1411" -> 1.4.11
# (principle digit, guideline digit, then the criterion number, which may be >1 digit).
_SC_TAG_RE = re.compile(r"^wcag(\d)(\d)(\d+)$")

_LEVEL_TAGS: dict[str, WcagLevel] = {
    "wcag2a": "A",
    "wcag21a": "A",
    "wcag22a": "A",
    "wcag2aa": "AA",
    "wcag21aa": "AA",
    "wcag22aa": "AA",
    "wcag2aaa": "AAA",
    "wcag21aaa": "AAA",
    "wcag22aaa": "AAA",
}

_VERSION_TAG_PREFIXES: dict[str, list[str]] = {
    "2.0": ["wcag2"],
    "2.1": ["wcag2", "wcag21"],
    "2.2": ["wcag2", "wcag21", "wcag22"],
}

_LEVEL_ORDER = ["a", "aa", "aaa"]


def parse_wcag_criteria(tags: list[str]) -> list[str]:
    """Extract WCAG success criterion numbers (e.g. '1.4.11') from axe-core tags."""
    criteria = []
    for tag in tags:
        match = _SC_TAG_RE.match(tag)
        if match:
            criteria.append(f"{match.group(1)}.{match.group(2)}.{int(match.group(3))}")
    return sorted(set(criteria))


def resolve_wcag_level(tags: list[str]) -> WcagLevel | None:
    """Resolve the WCAG conformance level a rule belongs to, or None for best-practice-only rules."""
    levels = {_LEVEL_TAGS[tag] for tag in tags if tag in _LEVEL_TAGS}
    if "AAA" in levels:
        return "AAA"
    if "AA" in levels:
        return "AA"
    if "A" in levels:
        return "A"
    return None


def axe_tags_for(wcag_version: str, level: str, include_best_practice: bool) -> list[str]:
    """axe-core runOnly tags for a WCAG version and level (cumulative: AA includes A)."""
    version_prefixes = _VERSION_TAG_PREFIXES[wcag_version]
    level_suffix = {"A": "a", "AA": "aa", "AAA": "aaa"}[level]
    included_suffixes = _LEVEL_ORDER[: _LEVEL_ORDER.index(level_suffix) + 1]

    tags = [f"{prefix}{suffix}" for prefix in version_prefixes for suffix in included_suffixes]
    if include_best_practice:
        tags.append("best-practice")
    return tags
