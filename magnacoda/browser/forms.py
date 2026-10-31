"""Use the page's forms: send each one empty (3.3.1, 3.3.3, 4.1.3) and change each field (3.2.2).

Error messages are kept for a person to judge. These run last since they change the page, with every
request blocked, so nothing reaches the site.
"""

from __future__ import annotations

import contextlib
from typing import Literal

from playwright.sync_api import Page

from magnacoda.browser.blocking import blocked
from magnacoda.browser.features import PAGE_HELPERS
from magnacoda.findings.models import (
    EmptySubmitCheck,
    EmptySubmitResult,
    FeatureExample,
    FormFieldError,
    OnInputProblem,
    OnInputResult,
)

FIELD_LIMIT = 20
FORM_LIMIT = 5
_SETTLE_MS = 200
_SUBMIT_SETTLE_MS = 600  # error messages often appear after a short animation or a check
_MARK = "data-magnacoda-field"
_FORM_MARK = "data-magnacoda-form"
_SUBMIT_MARK = "data-magnacoda-submit"

_FIELDS = (
    '\'input:not([type="hidden"]):not([type="submit"]):not([type="button"]):not([type="reset"])\''
    ' + \':not([type="image"]):not([type="file"]), select, textarea\''
)

_FIND_SCRIPT = (
    """
([limit, mark]) => {
"""
    + PAGE_HELPERS
    + f"""
    const fields = {_FIELDS};"""
    + """
    const found = [];
    for (const el of document.querySelectorAll(fields)) {
        if (found.length >= limit) break;
        const box = el.getBoundingClientRect();
        const cs = getComputedStyle(el);
        if (el.disabled || el.readOnly || box.width < 2 || box.height < 2
            || cs.display === 'none' || cs.visibility === 'hidden') continue;
        const html = htmlOf(el);  // before marking it, so the mark isn't shown
        el.setAttribute(mark, String(found.length));
        const kind = el.localName === 'select' ? 'select'
            : (el.type === 'checkbox' || el.type === 'radio') ? 'choice' : 'text';
        found.push({ selector: selectorFor(el), hint: hintFor(el), kind, html });
    }
    return found;
}
"""
)

_FOCUS_SCRIPT = f"(index) => document.activeElement === document.querySelector('[{_MARK}=\"' + index + '\"]')"

# Shared by the scripts below: the form's visible fields, the text tied to a field, and the error text
# that can be seen in and around a form (its own text, alerts anywhere, and text its fields point to).
_FORM_HELPERS = (
    PAGE_HELPERS
    + f"""
    const fieldSelector = {_FIELDS};"""
    + """
    const visible = (el) => {
        const box = el.getBoundingClientRect();
        const cs = getComputedStyle(el);
        return box.width >= 2 && box.height >= 2 && cs.display !== 'none' && cs.visibility !== 'hidden';
    };
    const formFields = (form) => Array.from(form.elements).filter(
        (el) => el.matches(fieldSelector) && !el.disabled && visible(el));
    const byIds = (ids) => (ids || '').split(/\\s+/).filter(Boolean)
        .map((id) => document.getElementById(id)).filter(Boolean);
    const tiedText = (el) => {
        const parts = byIds(el.getAttribute('aria-describedby'))
            .concat(byIds(el.getAttribute('aria-errormessage')))
            .filter((t) => visible(t)).map((t) => t.innerText.trim()).filter(Boolean);
        return Array.from(new Set(parts)).join(' ').slice(0, 200);
    };
    const shownLines = (form) => {
        const boxes = [form, ...document.querySelectorAll('[role="alert"]')];
        for (const el of formFields(form)) boxes.push(...byIds(el.getAttribute('aria-describedby')),
            ...byIds(el.getAttribute('aria-errormessage')));
        const lines = [];
        for (const box of boxes) {
            if (!visible(box)) continue;
            for (const line of box.innerText.split('\\n')) {
                const text = line.trim();
                if (text.length >= 2 && text.length <= 200) lines.push(text);
            }
        }
        return lines;
    };
"""
)

_FIND_FORMS_SCRIPT = (
    """
([limit, formMark, submitMark]) => {
"""
    + _FORM_HELPERS
    + """
    const found = [];
    for (const form of document.forms) {
        if (found.length >= limit) break;
        if (!visible(form)) continue;
        const submit = Array.from(form.elements).find((el) => el.matches(
            'button:not([type]), button[type="submit"], input[type="submit"], input[type="image"]')
            && !el.disabled && visible(el));
        const fields = formFields(form);
        if (!submit || !fields.length) continue;
        form.setAttribute(formMark, String(found.length));
        submit.setAttribute(submitMark, String(found.length));
        found.push({ selector: selectorFor(form), hint: hintFor(form) });
    }
    return found;
}
"""
)

# Before sending: what's already shown, and a watch on live regions (what screen readers are told).
_BEFORE_SUBMIT_SCRIPT = (
    """
([index, formMark]) => {
"""
    + _FORM_HELPERS
    + """
    const form = document.querySelector(`[${formMark}="${index}"]`);
    const fields = formFields(form);
    const announced = [];
    const liveSelector = '[aria-live]:not([aria-live="off"]), [role="alert"], [role="status"], '
        + '[role="log"], output';
    const observer = new MutationObserver((records) => {
        for (const record of records) {
            const nodes = record.type === 'childList' ? Array.from(record.addedNodes) : [record.target];
            for (const node of nodes) {
                const el = node.nodeType === 1 ? node : node.parentElement;
                if (!el || !el.closest(liveSelector)) continue;
                const text = (el.innerText || node.textContent || '').trim();
                if (text) announced.push(text);
            }
        }
    });
    observer.observe(document.body, {
        subtree: true, childList: true, characterData: true,
        attributes: true, attributeFilter: ['class', 'style', 'hidden'],
    });
    window.__magnacodaSubmit = {
        observer, announced,
        before: new Set(shownLines(form)),
        tied: fields.map((el) => tiedText(el)),
        native: !form.noValidate && fields.some((el) => !el.validity.valid),
        required: fields.filter((el) => el.required || el.getAttribute('aria-required') === 'true').length,
    };
}
"""
)

# After sending: what appeared, what got tied to which field, and whether screen readers were told.
_AFTER_SUBMIT_SCRIPT = (
    """
([index, formMark]) => {
"""
    + _FORM_HELPERS
    + """
    const state = window.__magnacodaSubmit;
    state.observer.disconnect();
    const form = document.querySelector(`[${formMark}="${index}"]`);
    const fields = formFields(form);
    const results = [];
    const tiedNow = new Set();
    fields.forEach((el, i) => {
        const invalid = el.getAttribute('aria-invalid') === 'true';
        const tied = tiedText(el);
        let message = null;
        if (tied && (tied !== state.tied[i] || invalid)) message = tied;
        else if (state.native && !el.validity.valid) message = el.validationMessage || null;
        if (tied) for (const line of tied.split('\\n')) tiedNow.add(line.trim());
        if (invalid || message) {
            results.push({ selector: selectorFor(el), hint: hintFor(el), invalid, message });
        }
    });
    const fresh = Array.from(new Set(shownLines(form))).filter((line) => !state.before.has(line));
    const messages = fresh
        .filter((line) => !Array.from(tiedNow).some((t) => t && t.includes(line))).slice(0, 10);
    const focused = document.activeElement;
    const focusTold = focused && focused !== document.body && (
        (!focused.matches(fieldSelector) && fresh.some((line) => (focused.innerText || '').includes(line)))
        || (focused.matches(fieldSelector) && tiedText(focused) !== ''
            && focused.getAttribute('aria-invalid') === 'true'));
    return {
        fields: results, messages, native: state.native, required: state.required,
        announced: state.announced.length > 0 || Boolean(focusTold),
    };
}
"""
)


def try_empty_submit(page: Page, limit: int = FORM_LIMIT) -> EmptySubmitResult:
    """Submit each visible form as is and record its error messages, their fields and announcements."""
    forms = page.evaluate(_FIND_FORMS_SCRIPT, [limit, _FORM_MARK, _SUBMIT_MARK])
    if not forms:
        return EmptySubmitResult(tested=0)
    checks = []
    tested = 0
    with blocked(page, (_MARK, _FORM_MARK, _SUBMIT_MARK)) as watch:
        for index, form in enumerate(forms):
            watch.clear()
            submit = page.query_selector(f'[{_SUBMIT_MARK}="{index}"]')
            if submit is None:
                continue
            try:
                page.evaluate(_BEFORE_SUBMIT_SCRIPT, [index, _FORM_MARK])
                submit.click(timeout=2000)
                page.wait_for_timeout(_SUBMIT_SETTLE_MS)
                after = page.evaluate(_AFTER_SUBMIT_SCRIPT, [index, _FORM_MARK])
                navigated = bool(watch.events or watch.windows_opened())
                calls = watch.calls
            except Exception:  # noqa: BLE001 - a form that can't be sent is just skipped
                with contextlib.suppress(Exception):
                    page.evaluate(
                        "() => window.__magnacodaSubmit && window.__magnacodaSubmit.observer.disconnect()"
                    )
                continue
            tested += 1
            fields = [
                FormFieldError(
                    element=FeatureExample(selector=f["selector"], hint=f["hint"]),
                    invalid=f["invalid"],
                    message=f["message"],
                )
                for f in after["fields"]
            ]
            tied = any(f.invalid or (f.message and not after["native"]) for f in fields)
            # A form sent by a script may show text about the blocked request ("Something went wrong"):
            # that counts as sent unless fields were also marked invalid or got a message of their own.
            outcome: Literal["page", "browser", "sent", "nothing"]
            if navigated or (calls and not tied):
                outcome = "sent"
                fields = []
            elif tied or after["messages"]:
                outcome = "page"
            elif after["native"]:
                outcome = "browser"
            else:
                outcome = "nothing"
            checks.append(
                EmptySubmitCheck(
                    form=FeatureExample(selector=form["selector"], hint=form["hint"]),
                    outcome=outcome,
                    required=after["required"],
                    messages=after["messages"] if outcome == "page" else [],
                    announced=after["announced"],
                    fields=fields,
                )
            )
    return EmptySubmitResult(tested=tested, forms=checks)


def try_form_fields(page: Page, limit: int = FIELD_LIMIT) -> OnInputResult:
    """Change each visible form field's value and report the ones that caused a change of context."""
    fields = page.evaluate(_FIND_SCRIPT, [limit, _MARK])
    if not fields:
        return OnInputResult(tested=0)
    problems = []
    with blocked(page, (_MARK, _FORM_MARK, _SUBMIT_MARK)) as watch:
        for index, field_ in enumerate(fields):
            watch.clear()
            element = page.query_selector(f'[{_MARK}="{index}"]')
            if element is None:
                continue
            try:
                _change(element, field_["kind"])
                page.wait_for_timeout(_SETTLE_MS)
                if watch.windows_opened():
                    watch.events.append("opened a new window")
                if not page.evaluate(_FOCUS_SCRIPT, index) and not watch.events:
                    watch.events.append("moved the focus somewhere else")
            except Exception:  # noqa: BLE001 - a field that can't be changed is just skipped
                continue
            if watch.events:
                problems.append(
                    OnInputProblem(
                        element=FeatureExample(selector=field_["selector"], hint=field_["hint"]),
                        effect=" and ".join(dict.fromkeys(watch.events)),
                        html=field_["html"],
                    )
                )
    return OnInputResult(tested=len(fields), problems=problems)


def _change(element, kind: str) -> None:  # type: ignore[no-untyped-def]
    """Change the value the way a person would: type a letter, pick another option, tick a box."""
    if kind == "select":
        values = element.evaluate("(el) => Array.from(el.options).map((o) => o.value)")
        current = element.evaluate("(el) => el.value")
        other = next((value for value in values if value != current), None)
        if other is not None:
            element.focus()
            element.select_option(other, timeout=2000)
    elif kind == "choice":
        element.click(timeout=2000)
    else:
        element.focus()
        element.type("a", timeout=2000)
        element.dispatch_event("change")
