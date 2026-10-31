from __future__ import annotations

import hashlib

from magnacoda.findings.models import (
    Confidence,
    EmptySubmitResult,
    FieldsResult,
    Finding,
    InteractionResult,
    KeyboardResult,
    LayoutResult,
    OnInputResult,
    OptionGroup,
    RuleResult,
    Severity,
    WcagLevel,
)
from magnacoda.findings.wcag_map import parse_wcag_criteria, resolve_wcag_level

_IMPACT_TO_SEVERITY: dict[str, Severity] = {
    "critical": "critical",
    "serious": "serious",
    "moderate": "moderate",
    "minor": "minor",
}


def _finding_id(page_url: str, rule_id: str, selector: str) -> str:
    raw = f"{page_url}|{rule_id}|{selector}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


_UNDERSTANDING = "https://www.w3.org/WAI/WCAG22/Understanding/"


def _own_finding(
    page_url: str,
    rule: str,
    num: str,
    level: WcagLevel,
    severity: Severity,
    page: str,
    description: str,
    selector: str,
    html: str,
    index: int,
    *,
    key: str | None = None,
    confidence: Confidence = "high",
    check_data: dict[str, object] | None = None,
) -> Finding:
    """A finding from one of magnacoda's own tests: `page` is its Understanding page, `key` (default:
    the selector) makes its ID, `index` its place in the page's order."""
    return Finding(
        finding_id=_finding_id(page_url, rule, selector if key is None else key),
        rule_id=rule,
        wcag_criteria=[num],
        wcag_level=level,
        severity=severity,
        description=description,
        check_data=check_data,
        help_url=_UNDERSTANDING + page,
        selector=selector,
        html_snippet=html,
        source="magnacoda",
        confidence=confidence,
        dom_order_index=index,
    )


def _node_detail(node: dict) -> str | None:
    """First check message on the node (e.g. the measured contrast ratio and colours)."""
    for group in ("any", "all", "none"):
        for check in node.get(group) or []:
            message = check.get("message")
            if message:
                return message
    return None


_CONTRAST_KEYS = ("fgColor", "bgColor", "contrastRatio", "expectedContrastRatio", "fontSize", "fontWeight")


def _node_check_data(node: dict) -> dict[str, object] | None:
    """Structured contrast data (colours, ratios) when the node carries it; otherwise None."""
    for group in ("any", "all", "none"):
        for check in node.get(group) or []:
            data = check.get("data")
            if isinstance(data, dict) and "fgColor" in data:
                return {k: data[k] for k in _CONTRAST_KEYS if k in data}
    return None


def axe_raw_to_findings(raw: dict, page_url: str) -> list[Finding]:
    """Flatten a raw axe.run() result into one Finding per rule x affected node."""
    findings: list[Finding] = []
    dom_index = 0

    for violation in raw.get("violations", []):
        rule_id = violation["id"]
        tags = violation.get("tags", [])
        wcag_criteria = parse_wcag_criteria(tags)
        wcag_level = resolve_wcag_level(tags)
        severity = _IMPACT_TO_SEVERITY.get(violation.get("impact") or "minor", "minor")
        nodes = violation.get("nodes", [])
        instance_count = len(nodes)

        for node in nodes:
            selector = " ".join(node.get("target", []))
            findings.append(
                Finding(
                    finding_id=_finding_id(page_url, rule_id, selector),
                    rule_id=rule_id,
                    wcag_criteria=wcag_criteria,
                    wcag_level=wcag_level,
                    severity=severity,
                    description=violation.get("help") or violation.get("description", ""),
                    detail=_node_detail(node),
                    check_data=_node_check_data(node),
                    help_url=violation.get("helpUrl"),
                    selector=selector,
                    html_snippet=(node.get("html") or "")[:500],
                    source="axe-core",
                    confidence="certain",
                    instance_count=instance_count,
                    dom_order_index=dom_index,
                )
            )
            dom_index += 1

    return findings


def _sc_sort_key(result: RuleResult) -> tuple[list[int], str]:
    first = result.wcag_criteria[0] if result.wcag_criteria else "99.99.99"
    return [int(part) for part in first.split(".")], result.rule_id


def axe_rule_results(raw: dict, key: str, *, exclude_ids: set[str] | None = None) -> list[RuleResult]:
    """Summarise raw['passes'] or raw['incomplete'] as RuleResults, ordered by WCAG success criterion."""
    exclude = exclude_ids or set()
    results = []
    for rule in raw.get(key, []):
        if rule["id"] in exclude:
            continue
        tags = rule.get("tags", [])
        details = []
        if key == "incomplete":
            for node in rule.get("nodes", [])[:5]:
                reason = _node_detail(node) or "needs manual review"
                details.append(f"{' '.join(node.get('target', []))} - {reason}")
        results.append(
            RuleResult(
                rule_id=rule["id"],
                description=rule.get("help") or rule.get("description", ""),
                wcag_criteria=parse_wcag_criteria(tags),
                wcag_level=resolve_wcag_level(tags),
                instance_count=len(rule.get("nodes", [])),
                details=details,
            )
        )
    return sorted(results, key=_sc_sort_key)


ON_INPUT_RULE = "magnacoda/on-input"


def on_input_findings(result: OnInputResult | None, page_url: str, start: int) -> list[Finding]:
    """3.2.2 findings for fields whose change caused a change of context, numbered from `start`."""
    if result is None:
        return []
    return [
        _own_finding(
            page_url,
            ON_INPUT_RULE,
            "3.2.2",
            "A",
            "serious",
            "on-input.html",
            f"Changing this field's value {problem.effect}, with no button pressed",
            problem.element.selector,
            problem.html,
            start + i,
        )  # fmt: skip
        for i, problem in enumerate(result.problems)
    ]


ERROR_WITHOUT_TEXT_RULE = "magnacoda/error-without-text"
ERROR_NOT_TIED_RULE = "magnacoda/error-not-tied"
ERROR_NOT_ANNOUNCED_RULE = "magnacoda/error-not-announced"


def empty_submit_findings(result: EmptySubmitResult | None, page_url: str, start: int) -> list[Finding]:
    """Findings from submitting forms empty (3.3.1, 4.1.3)."""
    if result is None:
        return []
    found: list[Finding] = []

    def add(rule: str, num: str, page: str, severity: Severity, selector: str, description: str) -> None:
        level: WcagLevel = "A" if num == "3.3.1" else "AA"
        at = start + len(found)
        found.append(_own_finding(page_url, rule, num, level, severity, page, description, selector, "", at))

    for form in (f for f in result.forms if f.outcome == "page"):
        texts = form.messages + [f.message for f in form.fields if f.message]
        for field in form.fields:
            if not field.invalid or field.message:
                continue
            if texts:
                add(
                    ERROR_NOT_TIED_RULE, "3.3.1", "error-identification.html", "moderate",
                    field.element.selector,
                    "Sent empty, the form marked this field as invalid (aria-invalid), but its error text "
                    "isn't tied to it (aria-describedby or aria-errormessage), so screen readers say only "
                    "\"invalid\", not what's wrong",
                )  # fmt: skip
            else:
                add(
                    ERROR_WITHOUT_TEXT_RULE, "3.3.1", "error-identification.html", "serious",
                    field.element.selector,
                    "Sent empty, the form marked this field as invalid, but showed no error text: "
                    "nobody is told in words what's wrong",
                )  # fmt: skip
        if texts and not form.announced:
            add(
                ERROR_NOT_ANNOUNCED_RULE, "4.1.3", "status-messages.html", "serious", form.form.selector,
                f'Sent empty, the form showed "{texts[0]}", but screen readers aren\'t told: it isn\'t '
                'in a live region (role="alert" or aria-live), and the focus didn\'t move to it',
            )  # fmt: skip
    return found


# What each kind of keyboard problem (browser/keyboard.py) is: rule, criterion, level, severity, its
# Understanding page, and the description (with the problem's detail where it has one).
_KEYBOARD_RULES: dict[str, tuple[str, str, WcagLevel, Severity, str, str]] = {
    "focus-not-visible": (
        "magnacoda/focus-not-visible", "2.4.7", "AA", "serious", "focus-visible.html",
        "With the keyboard focus on it, it looks exactly the same as without: nothing shows where the "
        "focus is",
    ),
    "focus-obscured": (
        "magnacoda/focus-obscured", "2.4.11", "AA", "serious", "focus-not-obscured-minimum.html",
        "With the keyboard focus on it, it's completely hidden: {detail}",
    ),
    "on-focus": (
        "magnacoda/on-focus", "3.2.1", "A", "serious", "on-focus.html",
        "Just getting the keyboard focus, it {detail}",
    ),
    "keyboard-trap": (
        "magnacoda/keyboard-trap", "2.1.2", "A", "critical", "no-keyboard-trap.html",
        "The keyboard gets stuck here: {detail}, and neither Escape nor Shift+Tab gets out",
    ),
    "skip-link": (
        "magnacoda/skip-link-broken", "2.4.1", "A", "serious", "bypass-blocks.html",
        "This skip link doesn't move the keyboard focus: after using it, Tab carries on from before the "
        "content it should skip to",
    ),
}  # fmt: skip


def keyboard_findings(result: KeyboardResult | None, page_url: str, start: int) -> list[Finding]:
    """A finding for each problem pressing Tab through the page showed."""
    if result is None:
        return []
    found = []
    for i, problem in enumerate(result.problems):
        rule, num, level, severity, page, text = _KEYBOARD_RULES[problem.kind]
        found.append(
            _own_finding(
                page_url,
                rule,
                num,
                level,
                severity,
                page,
                text.format(detail=problem.detail),
                problem.element.selector,
                problem.html,
                start + i,
            )  # fmt: skip
        )
    return found


_ZOOM = "At 320 px wide (what 400% zoom gives on a common screen)"
# What each kind of layout problem (browser/layout.py) is, as for keyboard problems above.
_LAYOUT_RULES: dict[str, tuple[str, str, WcagLevel, Severity, str, str]] = {
    "reflow": (
        "magnacoda/reflow", "1.4.10", "AA", "serious", "reflow.html",
        _ZOOM + ", it sticks out {detail} past the edge, so the page scrolls sideways",
    ),
    "reflow-table": (
        "magnacoda/reflow-table", "1.4.10", "AA", "moderate", "reflow.html",
        _ZOOM + ", it sticks out {detail} past the edge and the whole page scrolls sideways; a table may "
        "scroll, but on its own",
    ),
    "spacing-clipped": (
        "magnacoda/text-spacing-clipped", "1.4.12", "AA", "serious", "text-spacing.html",
        "With WCAG's text spacing (more room between lines, paragraphs, letters and words), part of its "
        "text is cut off",
    ),
    "spacing-spills": (
        "magnacoda/text-spacing-spills", "1.4.12", "AA", "moderate", "text-spacing.html",
        "With WCAG's text spacing, its text spills out of its box and may cover what comes after it",
    ),
    "resize-clipped": (
        "magnacoda/resize-clipped", "1.4.4", "AA", "serious", "resize-text.html",
        "At 200% zoom, part of its text is cut off",
    ),
}  # fmt: skip


def layout_findings(result: LayoutResult | None, page_url: str, start: int) -> list[Finding]:
    """A finding for each problem the layout tests showed."""
    if result is None:
        return []
    found = []
    for i, problem in enumerate(result.problems):
        rule, num, level, severity, page, text = _LAYOUT_RULES[problem.kind]
        description = text.format(detail=problem.detail)
        if not problem.element.selector:  # no one element to blame
            description = (
                f"{_ZOOM}, the page is {problem.detail} wider than the window, so it scrolls sideways"
            )
        found.append(
            _own_finding(
                page_url,
                rule,
                num,
                level,
                severity,
                page,
                description,
                problem.element.selector,
                problem.html,
                start + i,
            )  # fmt: skip
        )
    return found


def fields_findings(result: FieldsResult | None, page_url: str, start: int) -> list[Finding]:
    """Findings from the form fields' autocomplete values and pasting (browser/fields.py)."""
    if result is None:
        return []
    found = []
    for i, problem in enumerate(result.problems):
        severity: Severity
        if problem.kind == "paste-blocked":
            rule, num, severity, page = (
                "magnacoda/paste-blocked",
                "3.3.8",
                "serious",
                "accessible-authentication-minimum.html",
            )
            text = (
                "Pasting into this field is blocked, so a password manager or a copied code can't be used: "
                "people have to remember or retype it"
            )
        elif problem.kind == "password-autocomplete-off":
            rule, num, severity, page = (
                "magnacoda/password-autocomplete-off",
                "3.3.8",
                "moderate",
                "accessible-authentication-minimum.html",
            )
            text = (
                'This password field has autocomplete="off", which asks password managers not to fill it in'
            )
        else:
            rule, num, severity, page = (
                "magnacoda/missing-autocomplete",
                "1.3.5",
                "moderate",
                "identify-input-purpose.html",
            )
            has = 'autocomplete="off"' if problem.off else "no autocomplete value"
            text = (
                f"It looks like it asks for the visitor's own {problem.purpose}, but has {has}, so browsers "
                "can't fill it in and assistive tools can't show what it's for"
            )
        found.append(
            _own_finding(
                page_url,
                rule,
                num,
                "AA",
                severity,
                page,
                text,
                problem.element.selector,
                problem.html,
                start + i,
                confidence="medium" if problem.kind == "missing-autocomplete" else "high",
                check_data={"autocomplete": problem.detail} if problem.detail else None,
            )  # fmt: skip
        )
    return found


# What each kind of problem from the interaction tests is (browser/hover.py, widgets.py, media.py,
# shortcuts.py), as for keyboard problems above. {detail} is what the test saw.
_INTERACTION_RULES: dict[str, tuple[str, str, WcagLevel, Severity, str, str]] = {
    "hover-vanishes": (
        "magnacoda/hover-not-persistent", "1.4.13", "AA", "serious", "content-on-hover-or-focus.html",
        "Hovering over it shows {detail}, which then disappears by itself while the pointer is still there",
    ),
    "hover-not-hoverable": (
        "magnacoda/hover-not-hoverable", "1.4.13", "AA", "serious", "content-on-hover-or-focus.html",
        "Hovering over it shows {detail}, which disappears when the pointer moves onto it (people who "
        "magnify the screen must move onto it to read it)",
    ),
    "hover-not-dismissible": (
        "magnacoda/hover-not-dismissible", "1.4.13", "AA", "moderate", "content-on-hover-or-focus.html",
        "Hovering over it shows {detail}, which Escape doesn't close, so it can't be put away without "
        "moving the pointer",
    ),
    "expanded-stale": (
        "magnacoda/expanded-not-updated", "4.1.2", "A", "serious", "name-role-value.html",
        'Clicking it opens or closes what it controls, but its aria-expanded stays "{detail}", so screen '
        "readers announce the wrong state",
    ),
    "toggle-no-expanded": (
        "magnacoda/toggle-without-expanded", "4.1.2", "A", "moderate", "name-role-value.html",
        "Clicking it shows {detail}, but it has no aria-expanded, so screen reader users aren't told that "
        "it opens and closes something, or whether it's open",
    ),
    "click-only": (
        "magnacoda/click-only", "2.1.1", "A", "serious", "keyboard.html",
        "It reacts to a mouse click, but Tab can't reach it, so keyboard users can't use it",
    ),
    "keys-dont-work": (
        "magnacoda/keys-dont-work", "2.1.1", "A", "serious", "keyboard.html",
        "Tab reaches it, but neither Enter nor Space works it: it reacts only to the mouse",
    ),
    "timed-redirect": (
        "magnacoda/timed-redirect", "2.2.1", "A", "serious", "timing-adjustable.html",
        "The page goes on to {detail} by itself, so people who read slowly or use a screen reader can "
        "be taken away before they've finished",
    ),
    "moving-no-pause": (
        "magnacoda/moving-no-pause", "2.2.2", "A", "serious", "pause-stop-hide.html",
        "It {detail} for more than 5 seconds, with no pause, stop or hide button near it",
    ),
    "single-key-shortcut": (
        "magnacoda/single-key-shortcut", "2.1.4", "A", "moderate", "character-key-shortcuts.html",
        "{detail}: a shortcut of one key needs a way to turn it off or change it, or must work only while "
        "its own control has the focus",
    ),
}  # fmt: skip


def interaction_findings(result: InteractionResult | None, page_url: str, start: int) -> list[Finding]:
    """A finding for each problem the interaction tests found."""
    if result is None:
        return []
    found = []
    for i, problem in enumerate(result.problems):
        rule, num, level, severity, page, text = _INTERACTION_RULES[problem.kind]
        found.append(
            _own_finding(
                page_url,
                rule,
                num,
                level,
                severity,
                page,
                text.format(detail=problem.detail),
                problem.element.selector,
                problem.html,
                start + i,
                key=problem.element.selector or problem.detail,
            )  # fmt: skip
        )
    return found


def option_group_findings(groups: list[OptionGroup], page_url: str, start: int) -> list[Finding]:
    """A finding for each radio or checkbox group whose question isn't named for screen readers."""
    rule = "magnacoda/group-without-name"
    return [
        _own_finding(
            page_url,
            rule,
            "1.3.1",
            "A",
            "moderate",
            "info-and-relationships.html",
            f"These {len(group.options)} options answer one question, but nothing names it for screen "
            "readers (a fieldset's legend, or a group's label), so each option is read without the question",
            group.element.selector,
            group.html,
            start + i,
        )  # fmt: skip
        for i, group in enumerate(g for g in groups if not g.named)
    ]
