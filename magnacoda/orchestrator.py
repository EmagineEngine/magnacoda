from __future__ import annotations

from magnacoda import __version__, progress
from magnacoda.browser import redirects
from magnacoda.browser.axe_injector import axe_core_version, run_axe
from magnacoda.browser.css_sources import attach_sources
from magnacoda.browser.features import detect_page_features, find_option_groups, name_axe_elements
from magnacoda.browser.fields import check_fields
from magnacoda.browser.forms import try_empty_submit, try_form_fields
from magnacoda.browser.hover import try_hover_content
from magnacoda.browser.images import capture_images
from magnacoda.browser.keyboard import press_tab_through
from magnacoda.browser.launcher import DEFAULT_MOBILE_DEVICE, launch_page
from magnacoda.browser.layout import check_layout
from magnacoda.browser.media import note_media_tracks, read_motion, start_motion_watch
from magnacoda.browser.shortcuts import try_shortcuts
from magnacoda.browser.stability import StabilityReport, wait_for_stable
from magnacoda.browser.theme import OWN_RULES, axe_rules, fingerprint
from magnacoda.browser.widgets import try_widgets
from magnacoda.config import ScanConfig
from magnacoda.consent import confirm_ai_usage
from magnacoda.findings.checklist import build_checklist
from magnacoda.findings.fix_templates import template_fix
from magnacoda.findings.models import InteractionResult, ScanMeta, ScanReport
from magnacoda.findings.normalize import (
    axe_raw_to_findings,
    axe_rule_results,
    empty_submit_findings,
    fields_findings,
    interaction_findings,
    keyboard_findings,
    layout_findings,
    on_input_findings,
    option_group_findings,
)


def _run_ai_step(fn):  # type: ignore[no-untyped-def]
    """Run an AI call, turning the SDK's AuthenticationError into ours so cli.py needn't import anthropic."""
    from magnacoda.ai.client import is_authentication_error
    from magnacoda.exceptions import AIAuthenticationError

    try:
        return fn()
    except Exception as exc:
        if is_authentication_error(exc):
            raise AIAuthenticationError(
                "The Anthropic API rejected the configured key (invalid, revoked, or expired)."
            ) from exc
        raise


def run_scan(config: ScanConfig, *, consent_given: bool = False) -> ScanReport:
    if config.ai.tier != "off" and not consent_given:
        confirm_ai_usage(config.ai)

    semantic_dom_extract = None

    progress.step("loading the page")
    with launch_page(config) as page:
        progress.step("waiting for the page to settle")
        stability = wait_for_stable(page, config.stability)
        # Where the page really is (after any redirect), and from now on it stays there: a page load it
        # tries by itself is held and noted, for the timed-redirect check (browser/redirects.py).
        landed = redirects.landed(page)
        redirects.hold(page)
        colors = fingerprint(page)  # before anything changes the page: to compare with dark mode
        progress.step("running the accessibility checks")
        raw = run_axe(page, config.wcag_version, config.level, config.include_best_practice)
        progress.step("looking at what's on the page")
        features = detect_page_features(page)
        if not config.quick:
            start_motion_watch(page)  # read before the page is tried: what moves by itself (2.2.2)
        element_names = name_axe_elements(page, raw)
        option_groups = find_option_groups(page)
        if config.capture_images:
            progress.step("photographing the page's images")
        images, images_total = capture_images(page) if config.capture_images else ([], 0)

        if config.ai.tier == "semantic":
            from magnacoda.ai.semantic import extract_semantic_context

            semantic_dom_extract = extract_semantic_context(page)

        # These change the page, so they run last (with requests blocked). Forms are sent empty
        # before the field test fills them in.
        interaction = InteractionResult()
        if not config.quick:
            progress.step("watching for content that moves by itself")
            read_motion(page, interaction)
        note_media_tracks(page, interaction)
        progress.step("checking the layout when zoomed in")
        layout = check_layout(page)
        progress.step("pressing Tab through the page")
        keyboard = press_tab_through(page)
        progress.step("looking at the form fields")
        fields = check_fields(page)
        progress.step("sending the forms empty")
        empty_submit = try_empty_submit(page)
        progress.step("trying the form fields")
        on_input = try_form_fields(page)
        if not config.quick:
            progress.step("hovering, clicking and pressing single keys")
            try_hover_content(page, interaction)
            try_shortcuts(page, interaction)
            try_widgets(page, interaction)

        redirects.note_timed(page, interaction)
        findings = axe_raw_to_findings(raw, config.url)
        findings += option_group_findings(option_groups, config.url, start=len(findings))
        findings += interaction_findings(interaction, config.url, start=len(findings))
        findings += layout_findings(layout, config.url, start=len(findings))
        findings += keyboard_findings(keyboard, config.url, start=len(findings))
        findings += fields_findings(fields, config.url, start=len(findings))
        findings += empty_submit_findings(empty_submit, config.url, start=len(findings))
        findings += on_input_findings(on_input, config.url, start=len(findings))
        progress.step("finding the CSS behind the problems")
        attach_sources(page, findings)

    if config.fixes_tier == "template":
        for finding in findings:
            finding.fix = template_fix(finding)

    if config.ai.tier == "semantic" and semantic_dom_extract is not None:
        from magnacoda.ai.client import build_client
        from magnacoda.ai.semantic import run_semantic_review

        client = build_client(config.ai)
        progress.step("asking Claude to look at the page")
        semantic_findings = _run_ai_step(
            lambda: run_semantic_review(
                page_url=config.url,
                existing_rule_ids=[f.rule_id for f in findings],
                dom_extract=semantic_dom_extract,
                client=client,
                model=config.ai.model,
            )
        )
        findings.extend(semantic_findings)

    if config.ai.tier in ("explain", "semantic"):
        from magnacoda.ai.client import build_client
        from magnacoda.ai.explain import build_explanations

        client = build_client(config.ai)
        progress.step("asking Claude to explain the top findings")
        _run_ai_step(
            lambda: build_explanations(
                findings,
                client=client,
                model=config.ai.model,
                top_n=10,
                include_fixes=config.fixes_tier == "ai",
            )
        )

    meta = _meta(config, stability)
    if landed != config.url:
        meta.requested_url = config.url  # the scan is of where the page landed
    violation_ids = {v["id"] for v in raw.get("violations", [])}
    return ScanReport(
        url=landed,
        meta=meta,
        findings=findings,
        passed=axe_rule_results(raw, "passes", exclude_ids=violation_ids),
        needs_review=axe_rule_results(raw, "incomplete"),
        inapplicable_count=len(raw.get("inapplicable", [])),
        page_features=features,
        checklist=build_checklist(
            raw,
            features,
            config.wcag_version,
            config.level,
            on_input,
            keyboard,
            layout,
            interaction,
            option_groups,
        ),
        images=images,
        images_total=images_total,
        element_names=element_names,
        option_groups=option_groups,
        on_input=on_input,
        empty_submit=empty_submit,
        keyboard=keyboard,
        layout=layout,
        fields=fields,
        interaction=interaction,
        fingerprint=colors,
    )


def run_dark_pass(config: ScanConfig, light_colors: str | None) -> ScanReport | None:
    """Reload in dark mode and rerun the color-dependent checks; None if the page doesn't change.

    Uses template fixes only; the AI tiers only see the full scan.
    """
    config = config.model_copy(update={"color_scheme": "dark"})
    url = config.url
    progress.step("loading the page in dark mode")
    with launch_page(config) as page:
        stability = wait_for_stable(page, config.stability)
        url = redirects.landed(page)
        redirects.hold(page)  # as in run_scan: the page stays where it is
        if light_colors is not None and fingerprint(page) == light_colors:
            return None
        progress.step("checking contrast and images in dark mode")
        raw = run_axe(
            page,
            config.wcag_version,
            config.level,
            False,
            rules=axe_rules(config.level, config.include_best_practice),
        )
        element_names = name_axe_elements(page, raw)
        images, images_total = capture_images(page) if config.capture_images else ([], 0)
        progress.step("pressing Tab through the page in dark mode")
        keyboard = press_tab_through(page)
        findings = axe_raw_to_findings(raw, url)
        findings += [
            f for f in keyboard_findings(keyboard, url, start=len(findings)) if f.rule_id in OWN_RULES
        ]
        attach_sources(page, findings)  # the dark theme's own rules
    if config.fixes_tier == "template":
        for finding in findings:
            finding.fix = template_fix(finding)
    return ScanReport(
        url=url,
        meta=_meta(config, stability),
        findings=findings,
        needs_review=axe_rule_results(raw, "incomplete"),
        element_names=element_names,
        images=images,
        images_total=images_total,
    )


def _meta(config: ScanConfig, stability: StabilityReport) -> ScanMeta:
    return ScanMeta(
        tool_version=__version__,
        axe_core_version=axe_core_version(),
        wcag_version=config.wcag_version,
        wcag_level=config.level,
        ai_tier=config.ai.tier,
        fixes_tier=config.fixes_tier,
        color_scheme=config.color_scheme,
        screen=config.screen,
        stability_settled=stability.settled,
        stability_elapsed_ms=stability.elapsed_ms,
        stability_reason=stability.reason,
        quick=config.quick,
        storage_state=str(config.storage_state.resolve()) if config.storage_state else None,
        device=config.device or (DEFAULT_MOBILE_DEVICE if config.screen == "mobile" else None),
    )
