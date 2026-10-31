from __future__ import annotations

import json
from typing import Any, Literal

from magnacoda.ai.prompts import EXPLAIN_SYSTEM_PROMPT, ExplanationBatch
from magnacoda.findings.models import Finding, FindingExplanation, FindingFix


def build_explanations(
    findings: list[Finding],
    *,
    client: Any,
    model: str,
    top_n: int = 10,
    include_fixes: bool = False,
) -> None:
    """Populate .explanation (and, if requested, .fix) for exactly the top-N findings, in one call."""
    ranked = sorted(findings, key=Finding.sort_key)
    top = ranked[:top_n]
    if not top:
        return

    payload = [
        {
            "finding_id": f.finding_id,
            "rule_id": f.rule_id,
            "wcag_criteria": f.wcag_criteria,
            "severity": f.severity,
            "selector": f.selector,
            "html_snippet": f.html_snippet,
            "description": f.description,
        }
        for f in top
    ]

    instruction = (
        "Explain each of these accessibility findings."
        + (" Also include a corrected_snippet fixing each one." if include_fixes else "")
        + f"\n\nFindings (JSON):\n{json.dumps(payload, indent=2)}"
    )

    response = client.messages.parse(
        model=model,
        max_tokens=4096,
        system=EXPLAIN_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": instruction}],
        output_format=ExplanationBatch,
    )
    batch: ExplanationBatch = response.parsed_output
    by_id = {e.finding_id: e for e in batch.explanations}

    for finding in top:
        explanation = by_id.get(finding.finding_id)
        if explanation is None:
            continue
        generated_by: Literal["claude-explain", "claude-semantic"] = (
            "claude-semantic" if finding.source == "claude-semantic" else "claude-explain"
        )
        finding.explanation = FindingExplanation(
            why_it_matters=explanation.why_it_matters,
            how_to_fix=explanation.how_to_fix,
            generated_by=generated_by,
            model=model,
            fix_group=explanation.fix_group,
        )
        if include_fixes and explanation.corrected_snippet:
            finding.fix = FindingFix(
                corrected_snippet=explanation.corrected_snippet,
                summary=explanation.how_to_fix,
                generated_by=generated_by,
            )
