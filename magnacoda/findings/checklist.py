from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources
from typing import Any

from magnacoda.findings.models import (
    CriterionEntry,
    CriterionStatus,
    FeatureExample,
    InteractionResult,
    KeyboardResult,
    LayoutResult,
    OnInputResult,
    OptionGroup,
    PageFeatures,
)
from magnacoda.findings.normalize import _INTERACTION_RULES
from magnacoda.findings.wcag_map import parse_wcag_criteria

_LEVELS_INCLUDED = {"A": {"A"}, "AA": {"A", "AA"}, "AAA": {"A", "AA", "AAA"}}

# Highest priority first: the worst outcome across an SC's rules wins.
_STATUS_ORDER: list[tuple[str, CriterionStatus]] = [
    ("violations", "failed"),
    ("incomplete", "needs_review"),
    ("passes", "passed"),
    ("inapplicable", "no_elements"),
]

_FEATURE_LABELS = {
    "video": "video element",
    "audio": "audio element",
    "autoplay_media": "autoplaying media element",
    "iframes": "iframe (may embed media or widgets)",
    "embeds": "object or embed element (may hold a player)",
    "canvas": "canvas element",
    "images": "image",
    "svg": "inline SVG",
    "forms": "form",
    "inputs": "form control",
    "password_inputs": "password field",
    "captcha": "CAPTCHA",
    "live_regions": "live region",
    "custom_widgets": "custom ARIA widget",
    "popups": "tooltip/popup trigger",
    "draggable": "draggable element",
    "animated": "continuously animated element",
    "meta_refresh": "meta refresh",
    "fixed_elements": "fixed/sticky element",
    "labelled_controls": "control with an aria-label",
    "hidden_reachable": "element hidden visually but reachable by keyboard and screen readers",
}


def _load(name: str) -> Any:
    return json.loads((resources.files("magnacoda") / "data" / name).read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_criteria() -> list[dict[str, Any]]:
    return _load("wcag_criteria.json")  # type: ignore[no-any-return]


@lru_cache(maxsize=1)
def load_guidance() -> dict[str, dict[str, Any]]:
    return _load("criteria_guidance.json")  # type: ignore[no-any-return]


def _axe_outcomes(raw: dict) -> dict[str, tuple[CriterionStatus, list[str]]]:
    """Per success criterion: the worst axe outcome and the rules that touched it."""
    priority = {status: i for i, (_, status) in enumerate(_STATUS_ORDER)}
    outcomes: dict[str, tuple[CriterionStatus, list[str]]] = {}
    for key, status in _STATUS_ORDER:
        for rule in raw.get(key, []):
            for num in parse_wcag_criteria(rule.get("tags", [])):
                current, rules = outcomes.get(num, (status, []))
                if priority[status] < priority[current]:
                    current = status
                if rule["id"] not in rules:
                    rules.append(rule["id"])
                outcomes[num] = (current, rules)
    return outcomes


def _describe_features(features: PageFeatures, names: list[str]) -> list[str]:
    parts = []
    for name in names:
        count = getattr(features, name)
        if count:
            label = _FEATURE_LABELS[name]
            parts.append(f"{count} {label}{'' if count == 1 else 's'}")
    return parts


_EXAMPLES_PER_CRITERION = 20  # all listed under "Page elements"; the terminal shows the first two


def _examples(features: PageFeatures, names: list[str]) -> list[FeatureExample]:
    """Up to twenty distinct elements behind a manual check, in trigger order."""
    found: list[FeatureExample] = []
    for name in names:
        for example in features.examples.get(name, []):
            if len(found) == _EXAMPLES_PER_CRITERION:
                return found
            if all(example.selector != kept.selector for kept in found):
                found.append(example)
    return found


# Criteria only about audio and video: on a page with none, and no embedded player, they don't apply.
_MEDIA_CRITERIA = {
    "1.2.1",
    "1.2.2",
    "1.2.3",
    "1.2.4",
    "1.2.5",
    "1.2.6",
    "1.2.7",
    "1.2.8",
    "1.2.9",
    "1.4.2",
    "1.4.7",
}
NO_MEDIA = "no audio, video or embedded player (iframe, object, embed) on this page"


def _has_media(features: PageFeatures) -> bool:
    return bool(features.video or features.audio or features.iframes or features.embeds)


_ON_INPUT_FOLLOW_UP = (
    "if changing a field is meant to do something at once, make sure the page says so beforehand."
)
_OPENED = "things that open, such as menus and dialogs"

# Criteria settled by pressing Tab through the page: the kind of problem (browser/keyboard.py), its rule,
# and what's left for a person when none was found.
_KEYBOARD_CRITERIA = {
    "2.4.7": ("focus-not-visible", f"check that the focus also shows inside {_OPENED}."),
    "2.4.11": ("focus-obscured", f"check {_OPENED}, and the page with any banner shown."),
    "2.1.2": ("keyboard-trap", f"check {_OPENED}, and embedded players: Tab must get out of each."),
    "3.2.1": ("on-focus", f"check {_OPENED}."),
}


# Criteria settled by the layout tests: their kinds of problem (browser/layout.py), and what's left.
_LAYOUT_CRITERIA = {
    "1.4.10": (
        ("reflow", "reflow-table"),
        "magnacoda/reflow",
        "the page doesn't scroll sideways at 320 px wide; check that nothing is cut off, overlapping or "
        "missing there, and that everything still works.",
    ),
    "1.4.12": (
        ("spacing-clipped", "spacing-spills"),
        "magnacoda/text-spacing",
        "with WCAG's text spacing no text is cut off or spills out of its box; check that nothing overlaps.",
    ),
    "1.4.4": (
        ("resize-clipped",),
        "magnacoda/resize",
        "no text is cut off at 200% zoom; check in a browser that everything still works there.",
    ),
}


def _own_outcomes(
    on_input: OnInputResult | None,
    keyboard: KeyboardResult | None,
    layout: LayoutResult | None = None,
    interaction: InteractionResult | None = None,
    option_groups: list[OptionGroup] | None = None,
) -> dict[str, tuple[CriterionStatus, str, str | None]]:
    """Criteria settled by magnacoda's tests: {criterion: (status, rule, follow-up)}; "" = nothing left."""
    own: dict[str, tuple[CriterionStatus, str, str | None]] = {}
    if on_input is not None and on_input.tested:
        own["3.2.2"] = (
            "failed" if on_input.problems else "passed",
            "magnacoda/on-input",
            _ON_INPUT_FOLLOW_UP,
        )
    if keyboard is not None and keyboard.stops:
        kinds = {problem.kind for problem in keyboard.problems}
        for num, (kind, left) in _KEYBOARD_CRITERIA.items():
            rule = f"magnacoda/{kind}"
            if kind in kinds:
                own[num] = ("failed", rule, None)
            elif keyboard.complete:
                done = f"Tab went through all {keyboard.stops} elements without a problem; {left}"
                own[num] = ("passed", rule, done)
        if keyboard.skip_link == "broken":
            own["2.4.1"] = ("failed", "magnacoda/skip-link-broken", None)
        elif keyboard.skip_link == "works":
            own["2.4.1"] = ("passed", "magnacoda/skip-link", "")  # what axe asks a person to confirm
    if layout is not None and layout.tested:
        layout_kinds = {problem.kind for problem in layout.problems}
        for num, (failing, rule, left) in _LAYOUT_CRITERIA.items():
            own[num] = ("failed", rule, None) if layout_kinds & set(failing) else ("passed", rule, left)
    if any(not group.named for group in option_groups or []):
        own["1.3.1"] = ("failed", "magnacoda/group-without-name", None)
    # The interaction tests only fail criteria: what they try can't cover everything those ask.
    for problem in interaction.problems if interaction is not None else []:
        rule, num = _INTERACTION_RULES[problem.kind][:2]
        own[num] = ("failed", rule, None)
    return own


def build_checklist(
    raw: dict,
    features: PageFeatures,
    wcag_version: str,
    level: str,
    on_input: OnInputResult | None = None,
    keyboard: KeyboardResult | None = None,
    layout: LayoutResult | None = None,
    interaction: InteractionResult | None = None,
    option_groups: list[OptionGroup] | None = None,
) -> list[CriterionEntry]:
    """One entry per in-scope criterion: what was tested automatically and what a person still checks.

    magnacoda's own tests settle some criteria axe can't: on_input (3.2.2), keyboard (2.4.7, 2.4.11, 2.1.2,
    3.2.1, 2.4.1), layout (1.4.10, 1.4.12, 1.4.4), and anything interaction found a problem for.
    """
    outcomes = _axe_outcomes(raw)
    own = _own_outcomes(on_input, keyboard, layout, interaction, option_groups)
    priority = {status: i for i, (_, status) in enumerate(_STATUS_ORDER)}
    for num, (status, rule, _) in own.items():
        current, rules = outcomes.get(num, (status, []))
        worse = status if priority[status] < priority.get(current, len(priority)) else current
        outcomes[num] = (worse, [*rules, rule])
    guidance = load_guidance()
    entries = []
    for criterion in load_criteria():
        if wcag_version not in criterion["versions"] or criterion["level"] not in _LEVELS_INCLUDED[level]:
            continue
        num = criterion["num"]
        note = guidance.get(num, {})
        status, rules = outcomes.get(num, ("not_automated", []))
        reason: str | None = None
        conditional = note.get("tier") == "relevant_if"
        found = _describe_features(features, note["triggers"]) if conditional else []

        if status == "not_automated":
            if not note:
                tier, reason = "depends", "no curated guidance yet - read the Understanding page"
            elif conditional:
                tier, reason = (
                    ("relevant", "found " + ", ".join(found)) if found else ("likely_na", note["absent"])
                )
            else:
                tier, reason = note["tier"], note.get("reason")
        elif status == "no_elements" and found:
            # axe found nothing to check, but the page has features it cannot see (e.g. embedded media).
            tier, reason = "relevant", "found " + ", ".join(found)
        else:
            tier = "automated"
        if num in _MEDIA_CRITERIA and status in ("not_automated", "no_elements") and not _has_media(features):
            tier, reason = "not_applicable", NO_MEDIA

        entries.append(
            CriterionEntry(
                num=num,
                title=criterion["title"],
                level=criterion["level"],
                principle=criterion["principle"],
                url=criterion["url"],
                status=status,
                tier=tier,  # type: ignore[arg-type]
                how_to_check=note.get("how"),
                reason=reason,
                follow_up=(
                    (own[num][2] if own[num][2] is not None else note.get("follow_up")) or None
                    if num in own and status == own[num][0]
                    else note.get("follow_up")
                    if status != "not_automated"
                    else None
                ),
                rules=rules,
                examples=_examples(features, note["triggers"]) if tier == "relevant" else [],
            )
        )
    return entries
