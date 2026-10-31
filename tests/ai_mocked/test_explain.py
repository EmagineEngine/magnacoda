from types import SimpleNamespace

from magnacoda.ai.explain import build_explanations
from magnacoda.ai.prompts import Explanation, ExplanationBatch
from magnacoda.findings.models import Finding


class _FakeMessages:
    def __init__(self, batch: ExplanationBatch):
        self._batch = batch

    def parse(self, **kwargs):
        return SimpleNamespace(parsed_output=self._batch)


class _FakeClient:
    def __init__(self, batch: ExplanationBatch):
        self.messages = _FakeMessages(batch)


def _finding(finding_id: str, severity: str = "minor") -> Finding:
    return Finding(
        finding_id=finding_id,
        rule_id="image-alt",
        wcag_level="A",
        severity=severity,
        description="d",
        selector="img",
        html_snippet="<img>",
        source="axe-core",
    )


def test_build_explanations_copies_fix_group_from_the_response():
    findings = [_finding("f1"), _finding("f2")]
    batch = ExplanationBatch(
        explanations=[
            Explanation(finding_id="f1", why_it_matters="w", how_to_fix="h", fix_group="shared"),
            Explanation(finding_id="f2", why_it_matters="w", how_to_fix="h", fix_group=None),
        ]
    )
    client = _FakeClient(batch)

    build_explanations(findings, client=client, model="claude-sonnet-5", top_n=10)

    assert findings[0].explanation.fix_group == "shared"
    assert findings[1].explanation.fix_group is None


def test_build_explanations_populates_top_n_only():
    findings = [_finding(f"f{i}") for i in range(12)]
    top = sorted(findings, key=Finding.sort_key)[:10]
    batch = ExplanationBatch(
        explanations=[
            Explanation(finding_id=f.finding_id, why_it_matters="why", how_to_fix="fix") for f in top
        ]
    )
    client = _FakeClient(batch)

    build_explanations(findings, client=client, model="claude-sonnet-5", top_n=10)

    explained = [f for f in findings if f.explanation is not None]
    assert len(explained) == 10
    assert all(f.explanation.generated_by == "claude-explain" for f in explained)


def test_build_explanations_includes_fix_when_requested():
    findings = [_finding("f1")]
    batch = ExplanationBatch(
        explanations=[
            Explanation(
                finding_id="f1",
                why_it_matters="why",
                how_to_fix="fix",
                corrected_snippet="<img alt='x'>",
            )
        ]
    )
    client = _FakeClient(batch)

    build_explanations(findings, client=client, model="claude-sonnet-5", top_n=10, include_fixes=True)

    assert findings[0].fix is not None
    assert findings[0].fix.corrected_snippet == "<img alt='x'>"
    assert findings[0].fix.generated_by == "claude-explain"


def test_build_explanations_noop_on_empty_findings():
    client = _FakeClient(ExplanationBatch(explanations=[]))
    build_explanations([], client=client, model="claude-sonnet-5")
