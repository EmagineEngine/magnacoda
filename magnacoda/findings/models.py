from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

Severity = Literal["critical", "serious", "moderate", "minor"]
WcagLevel = Literal["A", "AA", "AAA"]
Source = Literal["axe-core", "claude-semantic", "magnacoda"]  # magnacoda: its own tests (browser/forms.py)
Confidence = Literal["certain", "low", "medium", "high"]

# Lower rank = higher priority. Used for the deterministic top-10 ordering:
# severity -> WCAG level -> instance count -> DOM order.
SEVERITY_RANK: dict[Severity, int] = {"critical": 0, "serious": 1, "moderate": 2, "minor": 3}
WCAG_LEVEL_RANK: dict[WcagLevel, int] = {"A": 0, "AA": 1, "AAA": 2}


class FindingExplanation(BaseModel):
    why_it_matters: str
    how_to_fix: str
    generated_by: Literal["claude-explain", "claude-semantic"]
    model: str
    fix_group: str | None = None


class FindingFix(BaseModel):
    corrected_snippet: str
    summary: str
    generated_by: Literal["template", "claude-explain", "claude-semantic"]


class CssSource(BaseModel):
    """Where a CSS property is set: rule, file and line, plus the source-mapped file if any."""

    property: str  # what was looked for: "text-decoration-line", "color", "outline-style", ...
    declaration: str = ""  # as written: "text-decoration: none"
    selector: str = ""  # the rule's selector: ".entry-content a"
    # style-element is a <style> tag, style-attribute is style="...", script means set by JS (no file)
    kind: Literal["stylesheet", "style-element", "style-attribute", "script", "browser-default", "not-set"]
    file: str | None = None  # the stylesheet: its path on the scanned site, or its full address
    line: int | None = None  # 1-based, in that file (for a <style> element, in the page's HTML)
    original_file: str | None = None  # through the source map: the file the developer edits
    original_line: int | None = None
    inherited: bool = False  # set on an ancestor, and inherited
    utility_class: bool = (
        False  # the rule is one class the element has: perhaps a utility (Tailwind's .no-underline)
    )
    state: str = ""  # ":focus" when read with the keyboard focus on the element


class Finding(BaseModel):
    finding_id: str
    rule_id: str
    wcag_criteria: list[str] = Field(default_factory=list)
    wcag_level: WcagLevel | None = None
    severity: Severity
    description: str
    detail: str | None = None
    check_data: dict[str, object] | None = None
    help_url: str | None = None
    selector: str
    html_snippet: str
    source: Source
    confidence: Confidence | None = None
    instance_count: int = 1
    dom_order_index: int = 0
    explanation: FindingExplanation | None = None
    fix: FindingFix | None = None
    # Where it was found, for a scan of several screens or themes: variant labels such as "mobile.dark"
    # (ScanMeta.variants). Empty: everywhere the scan looked (and in every scan of one variant).
    seen_in: list[str] = Field(default_factory=list)
    # Where the CSS behind it is set, for problems a CSS property causes (browser/css_sources.py).
    css: list[CssSource] = Field(default_factory=list)

    def sort_key(self) -> tuple[int, int, int, int]:
        """Deterministic top-10 ordering: severity, WCAG level, instance count, DOM order."""
        level_rank = WCAG_LEVEL_RANK[self.wcag_level] if self.wcag_level else len(WCAG_LEVEL_RANK)
        return (
            SEVERITY_RANK[self.severity],
            level_rank,
            -self.instance_count,
            self.dom_order_index,
        )


def group_by_fix(findings: list[Finding]) -> list[list[Finding]]:
    """Group findings by their AI-assigned fix_group (others stay alone), in order of first appearance.

    Grouping uses the tag only; the prose can differ within a group.
    """
    seen: set[str] = set()
    groups: list[list[Finding]] = []
    for finding in findings:
        key = finding.explanation.fix_group if finding.explanation else None
        if key:
            if key in seen:
                continue
            seen.add(key)
            groups.append([f for f in findings if f.explanation and f.explanation.fix_group == key])
        else:
            groups.append([finding])
    return groups


class RuleResult(BaseModel):
    """A rule axe evaluated that produced no violation (passed) or could not be decided (needs review)."""

    rule_id: str
    description: str
    wcag_criteria: list[str] = Field(default_factory=list)
    wcag_level: WcagLevel | None = None
    instance_count: int = 0
    details: list[str] = Field(default_factory=list)


class FeatureExample(BaseModel):
    """One element that made a manual check relevant: where it is, and what it looks like."""

    selector: str  # a short CSS selector that finds it
    hint: str = ""  # its label, alt text, title, placeholder or first words


class PageFeatures(BaseModel):
    """Feature counts that trigger manual checks, with up to twenty examples each."""

    video: int = 0
    audio: int = 0
    autoplay_media: int = 0
    iframes: int = 0
    embeds: int = 0  # object and embed elements, which can hold a player
    canvas: int = 0
    images: int = 0
    svg: int = 0
    forms: int = 0
    inputs: int = 0
    password_inputs: int = 0
    captcha: int = 0
    live_regions: int = 0
    custom_widgets: int = 0
    popups: int = 0
    draggable: int = 0
    animated: int = 0
    meta_refresh: int = 0
    fixed_elements: int = 0
    labelled_controls: int = 0
    hidden_reachable: int = 0  # invisible, yet reachable with Tab and by screen readers
    examples: dict[str, list[FeatureExample]] = Field(default_factory=dict)


CriterionStatus = Literal["failed", "needs_review", "passed", "no_elements", "not_automated"]
CriterionTier = Literal["automated", "relevant", "every_page", "depends", "likely_na", "not_applicable"]


class OptionGroup(BaseModel):
    """Radios or checkboxes sharing a name; the checklist lists them once, under the group."""

    element: FeatureExample  # its fieldset or role="radiogroup", else the element around all the options
    options: list[FeatureExample] = Field(default_factory=list)
    # Whether the question is named for screen readers: a fieldset's legend, or a group's aria-label or
    # aria-labelledby. Without it each option is read without the question (WCAG 1.3.1).
    named: bool = True
    html: str = ""


class PageImage(BaseModel):
    """An image and its text alternative, for 1.1.1 and 1.4.5. JSON keeps the screenshot's file name only."""

    selector: str
    kind: str  # img, svg, canvas, role-img or input-image
    alt: str | None = None  # None: no alt attribute at all; "": marked decorative
    label: str | None = None  # an aria-label, aria-labelledby text or title that names it instead
    src: str | None = None
    width: int = 0
    height: int = 0
    file: str | None = None  # the screenshot, relative to the checklist, once saved
    png: bytes | None = Field(default=None, exclude=True, repr=False)
    seen_in: list[str] = Field(default_factory=list)  # as Finding.seen_in: empty, wherever the scan looked


class OnInputProblem(BaseModel):
    """A form field whose value change caused a change of context (WCAG 3.2.2)."""

    element: FeatureExample
    effect: str  # "submitted the form", "started loading another page", "opened a new window", ...
    html: str = ""  # the field's HTML, shortened


class OnInputResult(BaseModel):
    """Field-change test results (3.2.2): how many were tried and which changed context."""

    tested: int = 0
    problems: list[OnInputProblem] = Field(default_factory=list)


class FormFieldError(BaseModel):
    """A field after its form was sent empty: marked invalid, and the message it got, if any."""

    element: FeatureExample
    invalid: bool = False  # aria-invalid="true"
    message: str | None = (
        None  # error text tied to it (aria-describedby, aria-errormessage), or the browser's own
    )


class EmptySubmitCheck(BaseModel):
    """What one form did when sent empty (browser/forms.py), for WCAG 3.3.1, 3.3.3 and 4.1.3."""

    form: FeatureExample
    # page: the page showed its own error messages or marked fields invalid; browser: the browser's own
    # validation stopped it; sent: it went out (stopped by magnacoda); nothing: none of these
    outcome: Literal["page", "browser", "sent", "nothing"]
    required: int = 0  # fields marked required (required or aria-required)
    messages: list[str] = Field(default_factory=list)  # error text that appeared, not tied to a field
    announced: bool = False  # in a live region, or the focus moved to it or to a field it's tied to
    fields: list[FormFieldError] = Field(default_factory=list)


class EmptySubmitResult(BaseModel):
    tested: int = 0
    forms: list[EmptySubmitCheck] = Field(default_factory=list)


KeyboardProblemKind = Literal["focus-not-visible", "focus-obscured", "on-focus", "keyboard-trap", "skip-link"]


class KeyboardProblem(BaseModel):
    """Something pressing Tab through the page showed (browser/keyboard.py)."""

    element: FeatureExample
    kind: KeyboardProblemKind
    detail: str = ""  # what happened, in words ("moved the focus somewhere else", "covered by ...")
    html: str = ""  # the element's HTML, shortened


class KeyboardResult(BaseModel):
    """Pressing Tab through the page, for 2.4.7, 2.4.11, 2.1.2, 3.2.1, 2.4.1 and 2.4.3."""

    stops: int = 0  # elements the focus reached
    complete: bool = False  # Tab went all the way through the page (not stopped by the limit or a trap)
    problems: list[KeyboardProblem] = Field(default_factory=list)
    skip_link: Literal["works", "broken", "none"] = "none"
    # Where the focus jumped back up the page: (from, to), for a person to judge the order (2.4.3).
    jumps: list[tuple[FeatureExample, FeatureExample]] = Field(default_factory=list)


FieldProblemKind = Literal["paste-blocked", "password-autocomplete-off", "missing-autocomplete"]


class FieldProblem(BaseModel):
    """A form field problem browser/fields.py found."""

    element: FeatureExample
    kind: FieldProblemKind
    detail: str = ""  # missing-autocomplete: the autocomplete value it seems to need
    purpose: str = ""  # missing-autocomplete: what it seems to ask for ("email address")
    off: bool = False  # missing-autocomplete: it has autocomplete="off" (itself or its form)
    html: str = ""


class FieldPurpose(BaseModel):
    """A field's autocomplete value, and the one it seems to need, for 1.3.5's Check items."""

    element: FeatureExample
    autocomplete: str | None = None  # its own value, if it has a real one
    guess: str | None = None  # what its label, name or id suggests


class FieldsResult(BaseModel):
    """Form fields' autocomplete values and pasting (browser/fields.py), for 1.3.5 and 3.3.8."""

    tested: int = 0
    secrets: int = 0  # password and one-time code fields tried for pasting
    problems: list[FieldProblem] = Field(default_factory=list)
    purposes: list[FieldPurpose] = Field(default_factory=list)


class PageProblem(BaseModel):
    """An interaction test result; `kind` keys normalize._INTERACTION_RULES. Empty selector: whole page."""

    element: FeatureExample
    kind: str
    detail: str = ""
    html: str = ""


class PageNote(BaseModel):
    """Something for a person to judge on a Check item (empty selector: the criterion's own line)."""

    element: FeatureExample
    num: str
    note: str  # Markdown, page text already escaped


class InteractionResult(BaseModel):
    """The interaction tests (browser/hover.py, widgets.py, media.py, shortcuts.py)."""

    tested: dict[str, int] = Field(default_factory=dict)  # per test, how many things it tried
    problems: list[PageProblem] = Field(default_factory=list)
    notes: list[PageNote] = Field(default_factory=list)


LayoutProblemKind = Literal["reflow", "reflow-table", "spacing-clipped", "spacing-spills", "resize-clipped"]


class LayoutProblem(BaseModel):
    """Something the layout tests showed (browser/layout.py)."""

    element: FeatureExample
    kind: LayoutProblemKind
    detail: str = ""
    html: str = ""


class LayoutResult(BaseModel):
    """The page at 320 px wide (1.4.10), with WCAG's text spacing (1.4.12), and at 200% zoom (1.4.4)."""

    tested: bool = False
    overflow: int = 0  # how far the page scrolls sideways at 320 px
    problems: list[LayoutProblem] = Field(default_factory=list)


class CriterionEntry(BaseModel):
    """One WCAG success criterion in the checklist, with what axe-core covered and what is left."""

    num: str
    title: str
    level: WcagLevel
    principle: str
    url: str
    status: CriterionStatus
    tier: CriterionTier
    how_to_check: str | None = None
    reason: str | None = None
    follow_up: str | None = None
    rules: list[str] = Field(default_factory=list)
    # For a manual check made relevant by page features: up to twenty of those elements, so the reader
    # knows where to look (PageFeatures.examples).
    examples: list[FeatureExample] = Field(default_factory=list)


class ScanMeta(BaseModel):
    tool_version: str
    axe_core_version: str
    scanned_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    wcag_version: str
    wcag_level: WcagLevel
    ai_tier: Literal["off", "explain", "semantic"]
    fixes_tier: Literal["off", "template", "ai"]
    color_scheme: Literal["light", "dark"] | None = None
    screen: Literal["desktop", "mobile"] | None = None
    stability_settled: bool
    stability_elapsed_ms: int
    stability_reason: str
    quick: bool = False  # the slowest tests that use the page were left out (ScanConfig.quick)
    # The saved login (--storage-state) the scan used: its path only, never its contents, so a recheck
    # can log in the same way. Cookies and headers given on the command line are never kept.
    storage_state: str | None = None
    # What one scan covered, as variant labels "screen.theme" ("desktop.light", "mobile.dark"), in the
    # order they were scanned; empty for scans saved before they were merged into one report.
    variants: list[str] = Field(default_factory=list)
    # Whether the page changes in dark mode: None when dark mode wasn't compared (one theme was chosen).
    dark_theme: bool | None = None
    device: str | None = None  # the phone emulated for mobile ("Pixel 8 Pro")
    # The address that was asked for, when the page landed somewhere else (a redirect); ScanReport.url
    # is where it landed, what was scanned.
    requested_url: str | None = None
    # How long the scan took, all its passes, and the estimate made before it (none when it was skipped),
    # in seconds; none for a recheck and for scans saved before these were kept.
    scan_seconds: float | None = None
    estimated_seconds: float | None = None


class ScanReport(BaseModel):
    url: str
    meta: ScanMeta
    findings: list[Finding]
    passed: list[RuleResult] = Field(default_factory=list)
    needs_review: list[RuleResult] = Field(default_factory=list)
    inapplicable_count: int = 0
    page_features: PageFeatures | None = None
    checklist: list[CriterionEntry] = Field(default_factory=list)
    # Screenshots of the page's images, taken when a Markdown checklist is written; images_total counts
    # all of them, which can be more than the screenshots kept (browser/images.py).
    images: list[PageImage] = Field(default_factory=list)
    images_total: int = 0
    # axe-core's selector for each failing or undecided element -> magnacoda's name for it (the selector
    # used by examples and screenshots, and a hint), so everything about one element can be grouped.
    element_names: dict[str, FeatureExample] = Field(default_factory=dict)
    # Radio buttons and checkboxes that share a name, each group listed once in the checklist.
    option_groups: list[OptionGroup] = Field(default_factory=list)
    # Trying the form fields for 3.2.2 On Input (browser/forms.py); None for reports saved before it.
    on_input: OnInputResult | None = None
    # Sending each form empty, for 3.3.1, 3.3.3 and 4.1.3 (browser/forms.py); None for older reports.
    empty_submit: EmptySubmitResult | None = None
    # Pressing Tab through the page (browser/keyboard.py); None for older reports.
    keyboard: KeyboardResult | None = None
    # The layout tests (browser/layout.py); None for older reports.
    layout: LayoutResult | None = None
    # Form fields' autocomplete values and pasting (browser/fields.py); None for older reports.
    fields: FieldsResult | None = None
    # Hover content, widgets, moving content, media tracks and shortcuts; None for older reports.
    interaction: InteractionResult | None = None
    # The page's colors as first loaded, to tell whether dark mode changes it (browser/theme.py). Only
    # kept while the scan runs.
    fingerprint: str | None = Field(default=None, exclude=True, repr=False)

    @property
    def counts_by_severity(self) -> dict[Severity, int]:
        counts: dict[Severity, int] = {"critical": 0, "serious": 0, "moderate": 0, "minor": 0}
        for finding in self.findings:
            counts[finding.severity] += 1
        return counts

    @property
    def top_10(self) -> list[Finding]:
        return sorted(self.findings, key=Finding.sort_key)[:10]
