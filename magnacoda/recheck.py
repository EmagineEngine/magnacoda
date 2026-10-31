"""Recheck a saved scan's Fix items with only the rules that found them, and update the checklist.

Fixed items get ticked and failing ones unticked, with a dated note. It can't find new problems or
recheck Review/Check items. Behind a login it reuses the scan's login file, or takes cookies and
headers again (cookies are never saved).
"""

from __future__ import annotations

import contextlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from magnacoda import progress, ticks
from magnacoda.browser import redirects, theme
from magnacoda.browser.axe_injector import run_axe
from magnacoda.browser.features import find_option_groups
from magnacoda.browser.fields import check_fields
from magnacoda.browser.forms import try_empty_submit, try_form_fields
from magnacoda.browser.hover import try_hover_content
from magnacoda.browser.keyboard import press_tab_through
from magnacoda.browser.launcher import launch_page
from magnacoda.browser.layout import check_layout
from magnacoda.browser.media import read_motion, start_motion_watch
from magnacoda.browser.shortcuts import try_shortcuts
from magnacoda.browser.stability import wait_for_stable
from magnacoda.browser.widgets import try_widgets
from magnacoda.config import ScanConfig
from magnacoda.findings import normalize
from magnacoda.findings.models import Finding, InteractionResult, ScanReport
from magnacoda.report.markdown_export import fix_targets
from magnacoda.review_page import Variant

# Which of magnacoda's own tests found each kind of problem (by rule, without "magnacoda/").
_TESTS = {
    "redirect": {"timed-redirect"},
    "layout": {"reflow", "reflow-table", "text-spacing-clipped", "text-spacing-spills", "resize-clipped"},
    "keyboard": {"focus-not-visible", "focus-obscured", "on-focus", "keyboard-trap", "skip-link-broken"},
    "fields": {"paste-blocked", "password-autocomplete-off", "missing-autocomplete"},
    "empty_submit": {"error-without-text", "error-not-tied", "error-not-announced"},
    "on_input": {"on-input"},
    "groups": {"group-without-name"},
    "hover": {"hover-not-persistent", "hover-not-hoverable", "hover-not-dismissible"},
    "shortcuts": {"single-key-shortcut"},
    "widgets": {"expanded-not-updated", "toggle-without-expanded", "click-only", "keys-dont-work"},
    "motion": {"moving-no-pause"},
}


@dataclass
class Login:
    """The login for a recheck: given now (never saved), else the scan's saved login file."""

    cookies: list[tuple[str, str]] = field(default_factory=list)  # name, value
    headers: dict[str, str] = field(default_factory=dict)
    storage_state: Path | None = None


@dataclass
class VariantResult:
    label: str  # "" for a scan with one variant
    fixed: int = 0  # Fix items confirmed fixed
    failing: int = 0  # still failing
    not_found: int = 0  # their element is gone: the page changed
    error: str | None = None  # the recheck couldn't run (the page didn't load, ...)

    @property
    def total(self) -> int:
        return self.fixed + self.failing + self.not_found


@dataclass
class RecheckResult:
    when: datetime
    variants: list[VariantResult] = field(default_factory=list)

    def summary(self) -> str:
        """'4 of 6 problems fixed; 2 still fail', for all the variants together."""
        fixed = sum(v.fixed for v in self.variants)
        total = sum(v.total for v in self.variants)
        if not total:
            return "There were no problems to recheck"
        parts = [f"{fixed} of {total} problem{'s' if total != 1 else ''} fixed"]
        failing = sum(v.failing for v in self.variants)
        if failing:
            parts.append(f"{failing} still fail{'s' if failing == 1 else ''}")
        missing = sum(v.not_found for v in self.variants)
        if missing:
            parts.append(f"{missing} could not be found (the page has changed: scan again)")
        return "; ".join(parts)


def recheck_scan(
    variants: list[Variant],
    on_variant: Callable[[int, int, str], None] | None = None,
    login: Login | None = None,
) -> RecheckResult:
    """Recheck each variant of a saved scan (light and dark, desktop and mobile) in turn."""
    result = RecheckResult(datetime.now())
    for number, variant in enumerate(variants, start=1):
        if on_variant:
            on_variant(number, len(variants), variant.label)
        if variant.results is None:
            result.variants.append(VariantResult(variant.label, error="its results file is missing"))
            continue
        result.variants.append(
            recheck_variant(variant.checklist, variant.results, variant.label, result.when, login)
        )
    return result


def recheck_variant(
    checklist: Path,
    results: Path,
    label: str = "",
    when: datetime | None = None,
    login: Login | None = None,
) -> VariantResult:
    """Recheck one variant's Fix items and update its checklist (and results) in place."""
    when = when or datetime.now()
    outcome = VariantResult(label)
    try:
        report = ScanReport.model_validate(json.loads(results.read_text(encoding="utf-8")))
    except (OSError, ValueError) as exc:
        outcome.error = f"couldn't read {results.name}: {exc}"
        return outcome
    targets = fix_targets(report)
    present = set(ticks.read_ticks(checklist))
    targets = {box: findings for box, findings in targets.items() if box in present and findings}
    if not targets:
        return outcome
    old = [f for findings in targets.values() for f in findings]
    try:
        found, exists = _test_again(report, old, login or Login())
    except Exception as exc:  # noqa: BLE001 - the page didn't load, or the browser failed
        outcome.error = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
        return outcome
    day = f"{when:%Y-%m-%d}"
    changes: dict[str, tuple[bool | None, str]] = {}
    for box, findings in targets.items():
        failing = [f for f in findings if _key(f) in found]
        gone = [f for f in findings if _key(f) not in found and not exists.get(f.finding_id, True)]
        if failing:
            outcome.failing += 1
            which = ""
            if len(findings) > 1:
                which = f": {len(failing)} of {len(findings)}"
            changes[box] = (False, f" *(still failing on recheck, {day}{which})*")
        elif gone:
            outcome.not_found += 1
            changes[box] = (None, f" *(not found on recheck, {day}: the page has changed; scan again)*")
        else:
            outcome.fixed += 1
            changes[box] = (True, f" *(fixed, confirmed by recheck on {day})*")
    ticks.mark(checklist, changes, results)
    _note_in_results(results, when, outcome)
    return outcome


def _key(finding: Finding) -> tuple[str, str]:
    """Identity of a failure: rule and element (or its description if page-level)."""
    return (finding.rule_id, finding.selector or finding.description)


def _test_again(
    report: ScanReport, old: list[Finding], login: Login
) -> tuple[set[tuple[str, str]], dict[str, bool]]:
    """Rerun the relevant checks per screen and theme; returns (still failing, {id: element present})."""
    meta = report.meta
    if not meta.variants:  # saved before scans were merged: one screen and theme
        return _test_in(report, old, login, meta.screen, meta.color_scheme)
    themed = theme.covered(meta.wcag_level, include_best_practice=True)
    per_variant: dict[str, list[Finding]] = {}
    for finding in old:
        where = finding.seen_in or meta.variants
        wanted = [
            v
            for v in where
            if not v.endswith(".dark")
            or finding.rule_id in themed
            or v.replace(".dark", ".light") not in meta.variants
        ]
        for variant in wanted or where:
            per_variant.setdefault(variant, []).append(finding)
    found: set[tuple[str, str]] = set()
    exists: dict[str, bool] = {}
    for variant in meta.variants:
        if variant not in per_variant:
            continue
        screen, scheme = variant.split(".")
        still, there = _test_in(report, per_variant[variant], login, screen, scheme)
        found |= still
        for finding_id, present in there.items():
            exists[finding_id] = exists.get(finding_id, False) or present
    return found, exists


def _test_in(
    report: ScanReport, old: list[Finding], login: Login, screen: str | None, scheme: str | None
) -> tuple[set[tuple[str, str]], dict[str, bool]]:
    """One page load, on one screen and in one theme: see _test_again."""
    meta = report.meta
    storage_state = login.storage_state
    if storage_state is None and meta.storage_state:
        saved = Path(meta.storage_state)
        if saved.is_file():
            storage_state = saved
        elif not (login.cookies or login.headers):
            raise FileNotFoundError(
                f"the saved login the scan used ({saved}) is gone: give one with --storage-state"
            )
    config = ScanConfig(
        url=report.url,
        wcag_version=meta.wcag_version,  # type: ignore[arg-type]
        level=meta.wcag_level,
        color_scheme=scheme,  # type: ignore[arg-type]
        screen=screen,  # type: ignore[arg-type]
        device=meta.device if screen == "mobile" else None,
        storage_state=storage_state,
        cookies=[{"name": name, "value": value, "url": report.url} for name, value in login.cookies],
        extra_http_headers=login.headers,
    )
    axe_rules = sorted({f.rule_id for f in old if f.source == "axe-core"})
    own = {f.rule_id.removeprefix("magnacoda/") for f in old if f.source == "magnacoda"}
    needed = {name for name, kinds in _TESTS.items() if kinds & own}
    found: list[Finding] = []
    exists: dict[str, bool] = {}
    url = report.url
    progress.step("loading the page")
    with launch_page(config) as page:
        wait_for_stable(page, config.stability)
        redirects.hold(page)  # the page stays where it is, as in a scan
        if "motion" in needed:
            start_motion_watch(page)
        for finding in old:
            if finding.selector:
                with contextlib.suppress(Exception):  # a selector that no longer parses: unknown
                    exists[finding.finding_id] = page.query_selector(finding.selector) is not None
        if axe_rules:
            progress.step("running the accessibility checks that failed")
            raw = run_axe(page, meta.wcag_version, meta.wcag_level, False, rules=axe_rules)
            found += normalize.axe_raw_to_findings(raw, url)
        if "groups" in needed:
            found += normalize.option_group_findings(find_option_groups(page), url, 0)
        interaction = InteractionResult()
        if "motion" in needed:
            progress.step("watching for content that moves by itself")
            read_motion(page, interaction)
        if "redirect" in needed:
            # As long as the scan saw the page take to move on, and a second more (at most 30).
            delays = [int(m) for f in old for m in re.findall(r"after (\d+) seconds?", f.description)]
            progress.step("waiting to see whether the page moves on by itself")
            page.wait_for_timeout(1000 * min(30, max(delays, default=5) + 1))
            redirects.note_timed(page, interaction)
        steps: list[tuple[str, str, Callable[[], list[Finding]]]] = [
            ("layout", "checking the layout", lambda: normalize.layout_findings(check_layout(page), url, 0)),
            (
                "keyboard",
                "pressing Tab through the page",
                lambda: normalize.keyboard_findings(press_tab_through(page), url, 0),
            ),
            (
                "fields",
                "looking at the form fields",
                lambda: normalize.fields_findings(check_fields(page), url, 0),
            ),
            (
                "empty_submit",
                "sending the forms empty",
                lambda: normalize.empty_submit_findings(try_empty_submit(page), url, 0),
            ),
            (
                "on_input",
                "trying the form fields",
                lambda: normalize.on_input_findings(try_form_fields(page), url, 0),
            ),
        ]
        for name, step, run in steps:
            if name in needed:
                progress.step(step)
                found += run()
        for name, run_test in (
            ("hover", try_hover_content),
            ("shortcuts", try_shortcuts),
            ("widgets", try_widgets),
        ):
            if name in needed:
                progress.step("hovering, clicking and pressing single keys")
                run_test(page, interaction)
        found += normalize.interaction_findings(interaction, url, 0)
    return {_key(f) for f in found}, exists


def _note_in_results(results: Path, when: datetime, outcome: VariantResult) -> None:
    """Keep the last recheck's outcome in the results file too, for other tools."""
    try:
        data = json.loads(results.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    data["rechecked"] = {
        "at": when.isoformat(timespec="seconds"),
        "fixed": outcome.fixed,
        "still_failing": outcome.failing,
        "not_found": outcome.not_found,
    }
    ticks.write(results, json.dumps(data, indent=2))
