"""Merge the passes of one scan (desktop/mobile, light/dark) into a single report.

Each problem is listed once and tagged where it was seen ("mobile only") unless that's everywhere. The
dark pass only runs some rules, so a light-mode finding from a rule it skipped counts as seen in dark
mode too.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable, Iterable
from dataclasses import dataclass
from typing import TypeVar

from magnacoda.findings.models import (
    CriterionEntry,
    FeatureExample,
    Finding,
    PageImage,
    RuleResult,
    ScanReport,
)

T = TypeVar("T")

_STATUS_RANK = {"failed": 0, "needs_review": 1, "passed": 2, "no_elements": 3, "not_automated": 4}
_EXAMPLES = 20  # as many examples as one pass keeps (browser/features.py)


@dataclass
class Pass:
    label: str  # "screen.theme", such as "desktop.light" or "mobile.dark"
    report: ScanReport
    covered: set[str] | None = None  # None: a full scan; else the only rules this pass ran

    @property
    def screen(self) -> str:
        return self.label.split(".")[0]


def label(screen: str | None, theme: str | None) -> str:
    return f"{screen or 'desktop'}.{theme or 'light'}"


def key(finding: Finding) -> tuple[str, str]:
    """The same problem in two passes: its rule and its element (or, without one, its description)."""
    return (finding.rule_id, finding.selector or finding.description)


def merge(passes: list[Pass], dark_theme: bool | None = None) -> ScanReport:
    """Merge the passes into one report. `dark_theme`: did dark mode change the page (None: not tried)."""
    variants = [p.label for p in passes]
    full = [p for p in passes if p.covered is None]
    base = passes[0].report.model_copy(deep=True)

    seen: dict[tuple[str, str, int], tuple[Finding, set[str]]] = {}
    for p in passes:
        counted: dict[tuple[str, str], int] = {}  # two of the same in one pass stay two
        for finding in p.report.findings:
            same = counted[key(finding)] = counted.get(key(finding), -1) + 1
            entry = seen.setdefault((*key(finding), same), (finding.model_copy(deep=True), set()))
            entry[1].add(p.label)
            if p.covered is None:
                for short in passes:
                    if (
                        short.covered is not None
                        and short.screen == p.screen
                        and finding.rule_id not in short.covered
                    ):
                        entry[1].add(short.label)
    findings = []
    for finding, where in seen.values():
        finding.seen_in = _where(where, variants)
        findings.append(finding)
    failing = {f.rule_id for f in findings}

    base.findings = findings
    base.passed = [
        r
        for r in _union((r for p in full for r in p.report.passed), lambda r: r.rule_id)
        if r.rule_id not in failing
    ]
    base.needs_review = _merge_reviews([r for p in passes for r in p.report.needs_review])
    base.checklist = _merge_checklist(passes)
    base.element_names = {}
    for p in passes:
        for selector, name in p.report.element_names.items():
            base.element_names.setdefault(selector, name)
    base.images = _merge_images(passes, variants)
    base.images_total = max((p.report.images_total for p in passes), default=0)
    _merge_page_results(base, [p.report for p in full[1:]])

    meta = base.meta
    screens = list(dict.fromkeys(label.split(".")[0] for label in variants))
    themes = list(dict.fromkeys(label.split(".")[1] for label in variants))
    meta.variants = variants
    meta.dark_theme = dark_theme
    meta.screen = screens[0] if len(screens) == 1 else None  # type: ignore[assignment]
    meta.color_scheme = themes[0] if len(themes) == 1 else None  # type: ignore[assignment]
    meta.device = next((p.report.meta.device for p in passes if p.report.meta.device), None)
    base.fingerprint = None
    return base


def _where(labels: set[str], variants: list[str]) -> list[str]:
    """Where something was seen, in scan order; empty when it was seen everywhere the scan looked."""
    if labels >= set(variants):
        return []
    return [v for v in variants if v in labels]


def _union(items: Iterable[T], by: Callable[[T], Hashable]) -> list[T]:
    """Each item once (the first with its key), in order."""
    kept: dict[Hashable, T] = {}
    for item in items:
        kept.setdefault(by(item), item)
    return list(kept.values())


def _examples(*lists: list[FeatureExample]) -> list[FeatureExample]:
    return _union((e for examples in lists for e in examples), lambda e: e.selector)[:_EXAMPLES]


def _merge_reviews(results: list[RuleResult]) -> list[RuleResult]:
    merged: dict[str, RuleResult] = {}
    for result in results:
        kept = merged.get(result.rule_id)
        if kept is None:
            merged[result.rule_id] = result.model_copy(deep=True)
            continue
        kept.instance_count = max(kept.instance_count, result.instance_count)
        kept.details = list(dict.fromkeys([*kept.details, *result.details]))
    return list(merged.values())


def _merge_checklist(passes: list[Pass]) -> list[CriterionEntry]:
    """Worst status per criterion across passes; a short pass's failures count too."""
    entries = {e.num: e.model_copy(deep=True) for e in passes[0].report.checklist}
    for p in passes[1:]:
        for other in p.report.checklist:
            entry = entries.get(other.num)
            if entry is None:
                continue
            worse = other if _STATUS_RANK[other.status] < _STATUS_RANK[entry.status] else entry
            merged = worse.model_copy(deep=True)
            merged.rules = list(dict.fromkeys([*entry.rules, *other.rules]))
            merged.examples = _examples(entry.examples, other.examples)
            entries[other.num] = merged
        if p.covered is not None:
            for finding in p.report.findings:
                for num in finding.wcag_criteria:
                    entry = entries.get(num)
                    if entry is None:
                        continue
                    if entry.status != "failed":
                        entry.status, entry.tier, entry.reason = "failed", "automated", None
                    if finding.rule_id not in entry.rules:
                        entry.rules.append(finding.rule_id)
    return list(entries.values())


def _merge_images(passes: list[Pass], variants: list[str]) -> list[PageImage]:
    where: dict[str, set[str]] = {}
    images: dict[str, PageImage] = {}
    for p in passes:
        for image in p.report.images:
            images.setdefault(image.selector, image)
            where.setdefault(image.selector, set()).add(p.label)
    taken = {p.label for p in passes if p.report.images}  # passes that photographed images at all
    merged = []
    for selector, image in images.items():
        image = image.model_copy()  # the screenshot (png) stays shared, not copied
        image.seen_in = _where(where[selector], [v for v in variants if v in taken])
        merged.append(image)
    return merged


def _merge_page_results(base: ScanReport, others: list[ScanReport]) -> None:
    """Add other screens' interaction results to the base report."""
    for other in others:
        base.option_groups = _union([*base.option_groups, *other.option_groups], lambda g: g.element.selector)
        if base.page_features is None:
            base.page_features = other.page_features
        elif other.page_features is not None:
            features, more = base.page_features, other.page_features
            for name, value in more.model_dump(exclude={"examples"}).items():
                setattr(features, name, max(getattr(features, name), value))
            for name, examples in more.examples.items():
                features.examples[name] = _examples(features.examples.get(name, []), examples)
        if base.on_input is None or other.on_input is None:
            base.on_input = base.on_input or other.on_input
        else:
            base.on_input.tested = max(base.on_input.tested, other.on_input.tested)
            base.on_input.problems = _union(
                [*base.on_input.problems, *other.on_input.problems], lambda p: (p.element.selector, p.effect)
            )
        if base.empty_submit is None or other.empty_submit is None:
            base.empty_submit = base.empty_submit or other.empty_submit
        else:
            base.empty_submit.tested = max(base.empty_submit.tested, other.empty_submit.tested)
            base.empty_submit.forms = _union(
                [*base.empty_submit.forms, *other.empty_submit.forms], lambda f: f.form.selector
            )
        if base.keyboard is None or other.keyboard is None:
            base.keyboard = base.keyboard or other.keyboard
        else:
            keyboard, more_keys = base.keyboard, other.keyboard
            keyboard.stops = max(keyboard.stops, more_keys.stops)
            keyboard.complete = keyboard.complete and more_keys.complete
            keyboard.problems = _union(
                [*keyboard.problems, *more_keys.problems], lambda p: (p.element.selector, p.kind)
            )
            if "broken" in (keyboard.skip_link, more_keys.skip_link):
                keyboard.skip_link = "broken"
            elif "works" in (keyboard.skip_link, more_keys.skip_link):
                keyboard.skip_link = "works"
            keyboard.jumps = _union(
                [*keyboard.jumps, *more_keys.jumps], lambda j: (j[0].selector, j[1].selector)
            )
        if base.layout is None or other.layout is None:
            base.layout = base.layout or other.layout
        else:
            base.layout.tested = base.layout.tested or other.layout.tested
            base.layout.overflow = max(base.layout.overflow, other.layout.overflow)
            base.layout.problems = _union(
                [*base.layout.problems, *other.layout.problems], lambda p: (p.element.selector, p.kind)
            )
        if base.fields is None or other.fields is None:
            base.fields = base.fields or other.fields
        else:
            fields, more_fields = base.fields, other.fields
            fields.tested = max(fields.tested, more_fields.tested)
            fields.secrets = max(fields.secrets, more_fields.secrets)
            fields.problems = _union(
                [*fields.problems, *more_fields.problems], lambda p: (p.element.selector, p.kind)
            )
            fields.purposes = _union([*fields.purposes, *more_fields.purposes], lambda p: p.element.selector)
        if base.interaction is None or other.interaction is None:
            base.interaction = base.interaction or other.interaction
        else:
            interaction, more_tries = base.interaction, other.interaction
            for name, count in more_tries.tested.items():
                interaction.tested[name] = max(interaction.tested.get(name, 0), count)
            interaction.problems = _union(
                [*interaction.problems, *more_tries.problems],
                lambda p: (p.element.selector, p.kind, p.detail if not p.element.selector else ""),
            )
            interaction.notes = _union(
                [*interaction.notes, *more_tries.notes], lambda n: (n.element.selector, n.num)
            )


def where_text(seen_in: list[str], variants: list[str]) -> str:
    """Where it was seen, e.g. "only on mobile"; "" if seen everywhere."""
    if not seen_in or set(seen_in) >= set(variants):
        return ""
    all_screens = list(dict.fromkeys(v.split(".")[0] for v in variants))
    all_themes = list(dict.fromkeys(v.split(".")[1] for v in variants))
    screens = [s for s in all_screens if any(v.startswith(s + ".") for v in seen_in)]
    themes = [t for t in all_themes if any(v.endswith("." + t) for v in seen_in)]

    def one(screen_list: list[str], theme_list: list[str]) -> str:
        parts = []
        if screen_list != all_screens:
            parts.append("on " + " and ".join(screen_list))
        if theme_list != all_themes:
            parts.append("in " + " and ".join(theme_list) + " mode")
        return " ".join(parts)

    if {f"{s}.{t}" for s in screens for t in themes} == set(seen_in):
        return "only " + one(screens, themes)
    return "only " + "; ".join(one([v.split(".")[0]], [v.split(".")[1]]) or v for v in seen_in)


def tested_text(meta_variants: list[str], device: str | None, dark_theme: bool | None) -> str:
    """One line, e.g. "Tested on desktop and mobile (Pixel 8 Pro), in light and dark mode." """
    if not meta_variants:
        return ""
    screens = list(dict.fromkeys(v.split(".")[0] for v in meta_variants))
    themes = list(dict.fromkeys(v.split(".")[1] for v in meta_variants))
    named = [f"mobile ({device})" if s == "mobile" and device else s for s in screens]
    text = "Tested on " + " and ".join(named)
    if len(themes) > 1:
        text += ", in light and dark mode"
    elif dark_theme is False:
        text += f", in {themes[0]} mode (the page looks the same in dark mode)"
    else:
        text += f", in {themes[0]} mode"
    return text + "."
