from types import SimpleNamespace

from magnacoda.ai.prompts import SemanticFinding, SemanticReview
from magnacoda.ai.semantic import run_semantic_review


class _FakeMessages:
    def __init__(self, review: SemanticReview):
        self._review = review

    def parse(self, **kwargs):
        return SimpleNamespace(parsed_output=self._review)


class _FakeClient:
    def __init__(self, review: SemanticReview):
        self.messages = _FakeMessages(review)


def test_run_semantic_review_produces_tagged_findings():
    review = SemanticReview(
        findings=[
            SemanticFinding(
                rule_slug="vague-alt-text",
                wcag_criteria=["1.1.1"],
                wcag_level="A",
                severity="moderate",
                confidence="medium",
                selector="#hero-img",
                html_snippet="<img alt='image'>",
                description="Alt text is not descriptive",
                rationale="the alt text just repeats the word image",
            )
        ]
    )
    client = _FakeClient(review)

    findings = run_semantic_review(
        page_url="http://example.test",
        existing_rule_ids=["color-contrast"],
        dom_extract={"images": [], "headings": [], "links": []},
        client=client,
        model="claude-sonnet-5",
    )

    assert len(findings) == 1
    finding = findings[0]
    assert finding.source == "claude-semantic"
    assert finding.rule_id == "claude-semantic/vague-alt-text"
    assert finding.confidence == "medium"
    assert finding.severity == "moderate"
