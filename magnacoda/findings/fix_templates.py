from __future__ import annotations

import re
from collections.abc import Callable

from magnacoda.findings.contrast import (
    _parse_hex,
    contrast_ratio,
    parse_expected_ratio,
    suggest_passing_color,
)
from magnacoda.findings.models import Finding, FindingFix


def _parse_rgb(value: str) -> tuple[int, int, int]:
    rgb = _parse_hex(value)
    assert rgb is not None
    return rgb


_TEMPLATES: dict[str, Callable[[Finding], FindingFix]] = {}


def _register(
    rule_id: str,
) -> Callable[[Callable[[Finding], FindingFix]], Callable[[Finding], FindingFix]]:
    def decorator(fn: Callable[[Finding], FindingFix]) -> Callable[[Finding], FindingFix]:
        _TEMPLATES[rule_id] = fn
        return fn

    return decorator


@_register("image-alt")
def _fix_image_alt(finding: Finding) -> FindingFix:
    snippet = finding.html_snippet.rstrip(">") or "<img>"
    return FindingFix(
        corrected_snippet=f'{snippet} alt="Describe the image content here">',
        summary='Add a concise, descriptive `alt` attribute (or `alt=""` if the image is purely decorative).',
        generated_by="template",
    )


@_register("label")
def _fix_label(finding: Finding) -> FindingFix:
    return FindingFix(
        corrected_snippet=f'<label for="...">Field label</label>\n{finding.html_snippet}',
        summary="Associate a visible `<label>` with this control via `for`/`id`, or add `aria-label`.",
        generated_by="template",
    )


@_register("color-contrast")
def _fix_color_contrast(finding: Finding) -> FindingFix:
    data = finding.check_data or {}
    fg, bg = str(data.get("fgColor", "")), str(data.get("bgColor", ""))
    target = parse_expected_ratio(data.get("expectedContrastRatio")) or 4.5
    suggestion = suggest_passing_color(fg, bg, target) if fg and bg else None
    if suggestion is None:
        return FindingFix(
            corrected_snippet=finding.html_snippet,
            summary=f"Increase the text/background contrast ratio to at least {target:g}:1.",
            generated_by="template",
        )
    ratio = contrast_ratio(_parse_rgb(suggestion), _parse_rgb(bg))
    return FindingFix(
        corrected_snippet=f"/* {finding.selector} */\ncolor: {suggestion};",
        summary=(
            f"Change the text color from {fg} to {suggestion} ({ratio:.2f}:1 on {bg}; needs {target:g}:1)."
        ),
        generated_by="template",
    )


@_register("link-in-text-block")
def _fix_link_in_text_block(finding: Finding) -> FindingFix:
    """Same text for every such link, so they group as one fix; the CSS source goes per element."""
    return FindingFix(
        corrected_snippet=f"/* {finding.selector} */\ntext-decoration: underline;",
        summary=(
            "Underline links that sit in text, so they don't depend on color alone. (Or give the link at "
            "least 3:1 contrast with the surrounding text and an underline or other visible change on "
            "hover and keyboard focus.)"
        ),
        generated_by="template",
    )


@_register("html-has-lang")
def _fix_html_lang(finding: Finding) -> FindingFix:
    return FindingFix(
        corrected_snippet='<html lang="en">',
        summary="Add a `lang` attribute to `<html>` identifying the page's primary language.",
        generated_by="template",
    )


@_register("link-name")
def _fix_link_name(finding: Finding) -> FindingFix:
    return FindingFix(
        corrected_snippet=finding.html_snippet,
        summary='Use discernible link text (avoid "click here"); use `aria-label` if text can\'t change.',
        generated_by="template",
    )


@_register("heading-order")
def _fix_heading_order(finding: Finding) -> FindingFix:
    return FindingFix(
        corrected_snippet=finding.html_snippet,
        summary="Fix heading levels so they increase by one at a time (e.g. h2 must not skip to h4).",
        generated_by="template",
    )


def _not_allowed(finding: Finding) -> str:
    """Disallowed children from axe's message ("not allowed: span, div"), as `<span>`, `<div>`."""
    _, found, values = (finding.detail or "").partition("not allowed: ")
    if not found:
        return ""
    names = [value.strip() for value in values.split(",") if value.strip()]
    return ", ".join(f"`<{name}>`" if name.isalnum() else f"`{name}`" for name in names)


def _children_fix(finding: Finding, parent: str, wrapper: str, allowed: str, tip: str) -> FindingFix:
    """Fix text for a list or definition list with children it can't have."""
    stray = _not_allowed(finding)
    what = stray or "anything that isn't allowed"
    one = stray and "," not in stray
    return FindingFix(
        corrected_snippet=finding.html_snippet,
        summary=(
            f"Take {what} out from directly inside the {parent}: move {'it' if one else 'them'} into "
            f"{wrapper}, or out of the list. A {parent} may only directly contain {allowed}. {tip}"
        ),
        generated_by="template",
    )


@_register("list")
def _fix_list(finding: Finding) -> FindingFix:
    return _children_fix(
        finding,
        "`<ul>` or `<ol>`",
        "an `<li>` (such as the one beside it)",
        "`<li>`, `<script>` and `<template>`",
        'A separator between items can come from CSS instead, e.g. `li + li::before { content: "• "; }`.',
    )


@_register("definition-list")
def _fix_definition_list(finding: Finding) -> FindingFix:
    return _children_fix(
        finding,
        "`<dl>`",
        "a `<dt>` or `<dd>`",
        "`<dt>` and `<dd>` groups (each group may be wrapped in a `<div>`), `<script>` and `<template>`",
        "Each `<dt>` (the term) comes before its `<dd>` (the description).",
    )


def _fallback_fix(finding: Finding) -> FindingFix:
    """Fallback: axe's help text and message, plus links to the rule's page and the Understanding docs."""
    summary = _sentence(finding.description)
    if finding.detail:
        summary = f"{summary} Found: {_sentence(finding.detail)}"
    links = []
    if finding.help_url:
        links.append(f"{'axe-core rule' if finding.source == 'axe-core' else 'more'}: {finding.help_url}")
    links += [f"WCAG {num}: {url}" for num, url in _understanding(finding.wcag_criteria)]
    if links:
        summary = f"{summary} See {'; '.join(links)}"
    return FindingFix(corrected_snippet=finding.html_snippet, summary=summary, generated_by="template")


def _sentence(text: str) -> str:
    """The text with a closing period, unless it already ends a sentence."""
    text = text.strip()
    return text if not text or text[-1] in ".!?" else f"{text}."


def _understanding(nums: list[str]) -> list[tuple[str, str]]:
    """(criterion, its W3C Understanding page) for each criterion that has one, in order."""
    from magnacoda.findings.checklist import load_criteria  # here: checklist imports normalize, then us

    pages = {c["num"]: c["url"] for c in load_criteria()}
    return [(num, pages[num]) for num in nums if num in pages]


@_register("magnacoda/on-input")
def _fix_on_input(finding: Finding) -> FindingFix:
    return FindingFix(
        corrected_snippet="",
        summary=(
            "Let people change the field freely and act only when they press a button (such as Go or "
            "Send); or, if the change must happen at once, say so next to the field beforehand."
        ),
        generated_by="template",
    )


@_register("magnacoda/error-without-text")
def _fix_error_without_text(finding: Finding) -> FindingFix:
    return FindingFix(
        corrected_snippet=(
            '<input id="card" aria-invalid="true" aria-describedby="card-error">\n'
            '<p id="card-error">Enter the 16-digit number on the front of your card.</p>'
        ),
        summary="Show the error in words next to the field, saying what's wrong, and tie it to the field "
        "with `aria-describedby` (color or an icon alone isn't enough).",
        generated_by="template",
    )


@_register("magnacoda/error-not-tied")
def _fix_error_not_tied(finding: Finding) -> FindingFix:
    return FindingFix(
        corrected_snippet='<input id="email" aria-invalid="true" aria-describedby="email-error">\n'
        '<p id="email-error">Enter an email address, such as ana@example.com.</p>',
        summary="Give the error text an `id` and point the field's `aria-describedby` (or "
        "`aria-errormessage`) at it, so screen readers read it with the field.",
        generated_by="template",
    )


@_register("magnacoda/error-not-announced")
def _fix_error_not_announced(finding: Finding) -> FindingFix:
    return FindingFix(
        corrected_snippet='<div role="alert">\n  <p>Fill in your phone number.</p>\n</div>',
        summary='Put the messages in a container that is on the page from the start, with `role="alert"` '
        "(or `aria-live`), and fill it in when there are errors; or move the focus to the first field "
        "in error, with its message tied to it.",
        generated_by="template",
    )


def _fixed(summary: str, snippet: str = "") -> Callable[[Finding], FindingFix]:
    return lambda finding: FindingFix(corrected_snippet=snippet, summary=summary, generated_by="template")


_TEMPLATES["magnacoda/focus-not-visible"] = _fixed(
    "Give it a visible focus style, and don't remove the outline without a replacement: for example "
    "an outline of at least 2px in a color with 3:1 contrast against the background.",
    ":focus-visible {\n  outline: 3px solid #1a4fd0;\n  outline-offset: 2px;\n}",
)
_TEMPLATES["magnacoda/focus-obscured"] = _fixed(
    "Keep focused elements out from under fixed and sticky parts: add `scroll-padding` for their height "
    "(so the page scrolls the focused element clear of them), or let a banner be closed before it covers "
    "the page.",
    "html {\n  scroll-padding-bottom: 130px; /* the height of the fixed banner, and a little more */\n}",
)
_TEMPLATES["magnacoda/on-focus"] = _fixed(
    "Do nothing on focus that changes the context: open, send or move on only when the person activates "
    "the control (a click, Enter or Space), not when it gets the focus."
)
_TEMPLATES["magnacoda/keyboard-trap"] = _fixed(
    "Let Tab and Shift+Tab move on past the last and first element (don't cancel the Tab key), or, for a "
    'dialog that keeps the focus on purpose, close it with Escape and mark it `aria-modal="true"`.'
)
_TEMPLATES["magnacoda/skip-link-broken"] = _fixed(
    "Point the skip link at an element that exists and can take the focus: give the main content an id "
    'and `tabindex="-1"`, and link to it.',
    '<a class="skip" href="#main">Skip to content</a>\n<main id="main" tabindex="-1">',
)


_TEMPLATES["magnacoda/group-without-name"] = _fixed(
    "Put the options in a `<fieldset>` whose `<legend>` is the question (or give their container "
    '`role="radiogroup"`, or `role="group"` for checkboxes, and `aria-labelledby` pointing at the question).',
    '<fieldset>\n  <legend>Size</legend>\n  <label><input type="radio" name="size" value="s"> Small</label>\n'
    '  <label><input type="radio" name="size" value="l"> Large</label>\n</fieldset>',
)
_TEMPLATES["magnacoda/reflow"] = _fixed(
    "Let it shrink with the window: use `max-width: 100%` instead of a fixed width (and `height: auto` "
    "for images), let long words break (`overflow-wrap: anywhere`), and put side-by-side parts under "
    "each other on narrow screens with a media query.",
    ".banner {\n  width: auto;\n  max-width: 100%;\n}",
)
_TEMPLATES["magnacoda/reflow-table"] = _fixed(
    "Put it in a container that scrolls sideways on its own, and make that container reachable by "
    "keyboard and named, so the rest of the page fits the window.",
    '<div class="table-scroll" role="region" aria-label="Prices" tabindex="0">\n  <table>...</table>\n'
    "</div>\n\n.table-scroll {\n  overflow-x: auto;\n}",
)
_text_room = (
    "Let the box grow with its text: use `min-height` instead of `height`, and don't hide what doesn't fit "
    "(`overflow: hidden`) on boxes that hold text."
)
_TEMPLATES["magnacoda/text-spacing-clipped"] = _fixed(_text_room, ".card-title {\n  min-height: 40px;\n}")
_TEMPLATES["magnacoda/text-spacing-spills"] = _fixed(_text_room, ".card-title {\n  min-height: 40px;\n}")
_TEMPLATES["magnacoda/resize-clipped"] = _fixed(_text_room, ".card-title {\n  min-height: 40px;\n}")


def _with_autocomplete(html: str, value: str) -> str:
    """The field's opening tag with this autocomplete value (replacing one that's there)."""
    tag = re.sub(r'\s+autocomplete="[^"]*"', "", html.split(">")[0]).rstrip("/ ")
    return f'{tag} autocomplete="{value}">' if tag else f'<input autocomplete="{value}">'


@_register("magnacoda/missing-autocomplete")
def _fix_missing_autocomplete(finding: Finding) -> FindingFix:
    value = str((finding.check_data or {}).get("autocomplete", ""))
    return FindingFix(
        corrected_snippet=_with_autocomplete(finding.html_snippet, value),
        summary=f'Add `autocomplete="{value}"`, if the field asks for the visitor\'s own details (for '
        "someone else's, such as a gift's recipient, leave it out).",
        generated_by="template",
    )


@_register("magnacoda/password-autocomplete-off")
def _fix_password_autocomplete_off(finding: Finding) -> FindingFix:
    return FindingFix(
        corrected_snippet=_with_autocomplete(finding.html_snippet, "current-password"),
        summary='Use `autocomplete="current-password"` (or `"new-password"` where a password is chosen) '
        "instead of `off`, so password managers can fill it in.",
        generated_by="template",
    )


@_register("magnacoda/paste-blocked")
def _fix_paste_blocked(finding: Finding) -> FindingFix:
    return FindingFix(
        corrected_snippet=re.sub(r'\s+onpaste="[^"]*"', "", finding.html_snippet.split(">")[0]) + ">",
        summary="Let people paste: remove the `onpaste` handler, or the script, that cancels pasting "
        "(`return false` or `preventDefault()`).",
        generated_by="template",
    )


_hover_fix = (
    "Show it while the pointer is over the trigger or over the content itself (put both in one container "
    "and listen for leaving that), keep it until the pointer leaves or Escape is pressed, and close it on "
    "Escape."
)
_hover_snippet = (
    '<span class="tip-wrap">\n  <button aria-describedby="tip">Help</button>\n'
    '  <span id="tip" role="tooltip" hidden>...</span>\n</span>\n\n'
    ".tip-wrap { position: relative; }  /* the tooltip right under the button, with no gap */"
)
for _rule in (
    "magnacoda/hover-not-persistent",
    "magnacoda/hover-not-hoverable",
    "magnacoda/hover-not-dismissible",
):
    _TEMPLATES[_rule] = _fixed(_hover_fix, _hover_snippet)
_TEMPLATES["magnacoda/expanded-not-updated"] = _fixed(
    'Set `aria-expanded` to `"true"` when it opens what it controls and back to `"false"` when it closes '
    "it, in the same script that shows and hides it.",
    "button.setAttribute('aria-expanded', String(!panel.hidden));",
)
_TEMPLATES["magnacoda/toggle-without-expanded"] = _fixed(
    'Add `aria-expanded="false"` and `aria-controls` naming what it opens, and switch `aria-expanded` to '
    '`"true"` while it\'s open.',
    '<button type="button" aria-expanded="false" aria-controls="more">More options</button>\n'
    '<div id="more" hidden>...</div>',
)
_TEMPLATES["magnacoda/click-only"] = _fixed(
    "Use a real `<button>` (or a link, if it goes somewhere): it can be reached with Tab and works with "
    "Enter and Space by itself. A `<div>` or `<span>` with a click handler can't.",
    '<button type="button">...</button>',
)
_TEMPLATES["magnacoda/keys-dont-work"] = _fixed(
    "Use a real `<button>`; or, for a custom control, make Enter and Space do what a click does (listen for "
    "`keydown`).",
    "el.addEventListener('keydown', (e) => {\n  if (e.key === 'Enter' || e.key === ' ') {\n"
    "    e.preventDefault();\n    el.click();\n  }\n});",
)
_TEMPLATES["magnacoda/moving-no-pause"] = _fixed(
    "Add a button that pauses it (and stops it moving by itself when the page asks for less motion, "
    "`prefers-reduced-motion`), or stop it after 5 seconds.",
    '<button type="button" aria-pressed="false">Pause</button>\n\n'
    "@media (prefers-reduced-motion: reduce) {\n  .ticker { animation: none; }\n}",
)
_TEMPLATES["magnacoda/timed-redirect"] = _fixed(
    "Redirect on the server instead (an HTTP 301), so visitors arrive at the new page straight away; or "
    "show a link and let people choose when to go. If it must be timed, give at least 20 seconds and a "
    "way to stop or extend it.",
    '<p>This page has moved to <a href="https://example.com/new">its new address</a>.</p>',
)
_TEMPLATES["magnacoda/single-key-shortcut"] = _fixed(
    "Make the shortcut use a modifier key (such as Ctrl or Alt), or let people turn it off or change it, "
    "or only react to the key while its own control has the focus.",
    "if (e.key === '/' && (e.ctrlKey || e.metaKey)) { search.focus(); }",
)


def template_fix(finding: Finding) -> FindingFix:
    """Deterministic, offline fix suggestion for any finding (falls back to axe's own guidance)."""
    handler = _TEMPLATES.get(finding.rule_id)
    return handler(finding) if handler is not None else _fallback_fix(finding)
