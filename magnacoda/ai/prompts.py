from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

SEMANTIC_SYSTEM_PROMPT = """You are a WCAG 2 accessibility expert reviewing a web page for issues \
that automated rule engines (like axe-core) cannot reliably detect mechanically: whether alt text is \
actually descriptive, whether reading/heading order makes sense, whether link text is meaningful out \
of context, and whether the heading structure represents the content.

You are given a bounded DOM extract (images with alt text, the heading outline, and links with their \
accessible name and surrounding context) plus a list of axe-core rule IDs that already fired on this \
page — do not repeat those categories. Only report genuine, specific issues you can point to in the \
given extract; do not speculate about content you were not shown. In the extract, `name` is what a \
screen reader reads (alt text and aria-label included, hidden parts left out); an image with `shown` false \
isn't displayed right now, such as the other theme's version of a logo; links with the same `goes_to` number \
lead to the same address (the addresses themselves aren't given). Use each item's `selector` exactly as \
given. Assign a severity (critical/serious/\
moderate/minor) and a WCAG level (A/AA/AAA) so your findings rank alongside automated ones on the same \
scale, and a confidence (low/medium/high) reflecting how certain you are this is a real issue versus a \
judgment call."""

EXPLAIN_SYSTEM_PROMPT = """You are a WCAG 2 accessibility educator. For each finding, in plain language \
a developer without accessibility background can understand, explain why it matters to real users and \
how to fix it concretely and specifically to the given selector/snippet — not generic boilerplate.

If two or more findings in this batch need the exact same fix (e.g. several elements share one CSS class, \
or the same root cause applies to all of them), give every one of them the identical fix_group value — a \
short slug you choose, such as "req-class-contrast". Only the first one's why_it_matters/how_to_fix/\
corrected_snippet will be shown to the user (as the fix for the whole group), so make that one complete and \
not dependent on the others. Leave fix_group null when a finding's fix is specific to it alone — don't \
invent a shared group for findings that only superficially resemble each other."""


class SemanticFinding(BaseModel):
    rule_slug: str = Field(description="short kebab-case slug, e.g. 'vague-alt-text'")
    wcag_criteria: list[str]
    wcag_level: Literal["A", "AA", "AAA"]
    severity: Literal["critical", "serious", "moderate", "minor"]
    confidence: Literal["low", "medium", "high"]
    selector: str
    html_snippet: str
    description: str
    rationale: str


class SemanticReview(BaseModel):
    findings: list[SemanticFinding]


class Explanation(BaseModel):
    finding_id: str
    why_it_matters: str
    how_to_fix: str
    corrected_snippet: str | None = None
    fix_group: str | None = Field(
        default=None,
        description=(
            "Short slug shared by every finding in this batch that needs this exact same fix "
            "(e.g. 'req-class-contrast'). Null if this fix is specific to this finding alone."
        ),
    )


class ExplanationBatch(BaseModel):
    explanations: list[Explanation]
