"""Form field checks axe-core only half covers.

- 3.3.8: password and one-time code fields must accept paste (tested with a synthetic paste event).
- 1.3.5: personal-data fields need an autocomplete value. axe-core only validates values that exist, so
  the purpose is guessed from the label and name, and reported as "looks like".

Runs with requests blocked, before the forms are sent empty.
"""

from __future__ import annotations

import re
from typing import Any

from playwright.sync_api import Page

from magnacoda.browser.blocking import blocked
from magnacoda.browser.features import PAGE_HELPERS
from magnacoda.findings.models import FeatureExample, FieldProblem, FieldPurpose, FieldsResult

FIELD_LIMIT = 50
_MARK = "data-magnacoda-input"

_FIND_SCRIPT = (
    """
([limit, mark]) => {
"""
    + PAGE_HELPERS
    + """
    const skip = ['hidden', 'submit', 'button', 'reset', 'image', 'file', 'checkbox', 'radio', 'range',
        'color'];
    const found = [];
    for (const el of document.querySelectorAll('input, select, textarea')) {
        if (found.length >= limit) break;
        if (el.localName === 'input' && skip.includes(el.type)) continue;
        const box = el.getBoundingClientRect();
        const cs = getComputedStyle(el);
        if (el.disabled || box.width < 2 || box.height < 2 || cs.display === 'none'
            || cs.visibility === 'hidden') continue;
        const byIds = (ids) => (ids || '').split(/\\s+/).map((id) => document.getElementById(id))
            .filter(Boolean).map((t) => t.innerText).join(' ');
        const label = [
            ...(el.labels ? Array.from(el.labels).map((l) => l.innerText) : []),
            el.getAttribute('aria-label') || '', byIds(el.getAttribute('aria-labelledby')),
            el.getAttribute('placeholder') || '',
        ].join(' ').replace(/\\s+/g, ' ').trim();
        const form = el.form;
        const html = htmlOf(el);
        el.setAttribute(mark, String(found.length));
        found.push({
            selector: selectorFor(el), hint: hintFor(el), html, label,
            type: el.localName === 'input' ? el.type : el.localName,
            name: el.getAttribute('name') || '', id: el.id || '',
            autocomplete: el.hasAttribute('autocomplete')
                ? el.getAttribute('autocomplete').trim().toLowerCase()
                : (form && form.getAttribute('autocomplete') === 'off' ? 'off' : null),
            search: el.type === 'search' || el.getAttribute('role') === 'searchbox'
                || Boolean(el.closest('[role="search"], search')),
        });
    }
    return found;
}
"""
)

# Send a made-up paste to the field and see whether the page cancels it.
_PASTE_SCRIPT = f"""
(index) => {{
    const el = document.querySelector('[{_MARK}="' + index + '"]');
    if (!el) return false;
    const data = new DataTransfer();
    data.setData('text/plain', 'pasted-by-magnacoda');
    const event = new ClipboardEvent('paste', {{ clipboardData: data, bubbles: true, cancelable: true }});
    el.focus({{ preventScroll: true }});
    el.dispatchEvent(event);
    el.blur();
    return event.defaultPrevented;
}}
"""

# Purposes from WCAG's list (HTML's autocomplete values), most specific first: the first that matches
# the field's label, name or id wins. (pattern, autocomplete value, what it asks for)
_PURPOSES: list[tuple[str, str, str]] = [
    (r"\be ?mail\b", "email", "email address"),
    (r"\b(phone|telephone|mobile|cell ?phone)\b", "tel", "phone number"),
    (r"\b(user ?name|login ?name)\b", "username", "user name"),
    (r"\b(name on (the )?card|card ?holder)\b", "cc-name", "name as on their card"),
    (r"\b(card ?number|credit ?card|cc ?num(ber)?)\b", "cc-number", "card number"),
    (r"\bexpir", "cc-exp", "card's expiry date"),
    (r"\b(cvc|cvv|csc|security code)\b", "cc-csc", "card's security code"),
    (r"\b(birth ?day|birth ?date|date of birth|dob)\b", "bday", "date of birth"),
    (r"\b(company|organi[sz]ation|employer)\b", "organization", "organization"),
    (r"\b(first ?name|given ?name|forename)\b", "given-name", "first name"),
    (r"\b(last ?name|surname|family ?name)\b", "family-name", "last name"),
    (r"\b(zip|zip ?code|postal ?code|post ?code|postcode)\b", "postal-code", "postal code"),
    (r"\b(city|town)\b", "address-level2", "city"),
    (r"\b(state|province|county)\b", "address-level1", "state or province"),
    (r"\bcountry\b", "country-name", "country"),
    (r"\b(street|address)\b", "street-address", "street address"),
    (r"^(your |full |your full )?name$", "name", "name"),
]
_SPLIT = re.compile(r"(?<=[a-z])(?=[A-Z])|[_\-.\[\]]+")


def _words(text: str) -> str:
    return " ".join(_SPLIT.sub(" ", text).lower().replace("*", " ").replace(":", " ").split())


def guess_purpose(label: str, name: str, field_id: str, field_type: str) -> tuple[str, str] | None:
    """(autocomplete value, what it asks for) that a field seems to ask for, or None."""
    if field_type == "email":
        return "email", "email address"
    if field_type == "tel":
        return "tel", "phone number"
    if field_type == "password":
        new = re.search(
            r"\b(new|confirm|repeat|create|choose)\b", _words(label + " " + name + " " + field_id)
        )
        return ("new-password", "new password") if new else ("current-password", "password")
    for text in (_words(label), _words(name), _words(field_id)):
        if not text:
            continue
        for pattern, value, words in _PURPOSES:
            if re.search(pattern, text):
                return value, words
    return None


def _one_time_code(field: dict[str, Any]) -> bool:
    text = _words(field["label"] + " " + field["name"] + " " + field["id"])
    return field["autocomplete"] == "one-time-code" or bool(
        re.search(r"\b(one time|otp|verification code|2fa|two factor)\b", text)
    )


def check_fields(page: Page, limit: int = FIELD_LIMIT) -> FieldsResult:
    """Check autocomplete on visible fields, and paste into password and one-time code fields."""
    fields = page.evaluate(_FIND_SCRIPT, [limit, _MARK])
    result = FieldsResult(tested=len(fields))
    with blocked(page, (_MARK,)):
        for index, field in enumerate(fields):
            element = FeatureExample(selector=field["selector"], hint=field["hint"])
            secret = field["type"] == "password" or _one_time_code(field)
            if secret:
                result.secrets += 1
                try:
                    blocked_paste = bool(page.evaluate(_PASTE_SCRIPT, index))
                except Exception:  # noqa: BLE001 - a field that can't be tried is just not judged
                    blocked_paste = False
                if blocked_paste:
                    result.problems.append(
                        FieldProblem(element=element, kind="paste-blocked", html=field["html"])
                    )
                if field["type"] == "password" and field["autocomplete"] == "off":
                    result.problems.append(
                        FieldProblem(element=element, kind="password-autocomplete-off", html=field["html"])
                    )
                    continue
            if field["search"]:
                continue
            guess = guess_purpose(field["label"], field["name"], field["id"], field["type"])
            given = field["autocomplete"]
            missing = given in (None, "", "on", "off")
            result.purposes.append(
                FieldPurpose(
                    element=element,
                    autocomplete=None if missing else given,
                    guess=guess[0] if guess else None,
                )
            )
            if guess and missing:
                result.problems.append(
                    FieldProblem(
                        element=element,
                        kind="missing-autocomplete",
                        detail=guess[0],
                        purpose=guess[1],
                        off=given == "off",
                        html=field["html"],
                    )
                )
    return result
