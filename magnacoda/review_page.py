"""The review page for one saved scan: findings from results.json, and checklist.md with real checkboxes.

Everything from the report or the scanned page is escaped (markdown-it with HTML off, html.escape). The
page itself should pass its own scan at AAA; only saving ticks needs JavaScript.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from markdown_it import MarkdownIt

from magnacoda import checklist, plugins
from magnacoda.browser.redirects import from_elsewhere
from magnacoda.findings.merge import tested_text, where_text
from magnacoda.findings.models import ScanReport
from magnacoda.report.markdown_export import anchor

_ITEM = re.compile(r"^- \[(?P<box>[ xX])\] (?P<text>.*?) <!-- id:(?P<id>[A-Za-z0-9._-]+) -->(?P<after>.*)$")
_BOX_TOKEN = re.compile(r"<li>@@BOX:(?P<id>[A-Za-z0-9._-]+):(?P<on>[01])@@ (?P<label>.*?)(?=\n<ul>|</li>)")
_EXTERNAL = re.compile(r'<a href="(https?://[^"]+)">(.*?)</a>', re.DOTALL)
_SEVERITIES = ("critical", "serious", "moderate", "minor")


@dataclass(frozen=True)
class Variant:
    label: str  # "" for a scan with one variant, else e.g. "dark" or "mobile.light"
    checklist: Path
    results: Path | None

    @property
    def title(self) -> str:
        return " · ".join(part.capitalize() for part in self.label.split(".")) if self.label else "Scan"


# A wide table scrolls sideways in its own box (reachable and named for keyboard and screen reader
# users), so the page itself fits a narrow window (WCAG 1.4.10).
_SCROLL = '<div class="table-scroll" role="region" aria-label="{label}" tabindex="0">'


_HEADING = re.compile(r"<h([2-6])>(.*?)</h\1>")


def _with_id(match: re.Match[str]) -> str:
    """A heading with the id its anchor in checklist.md has, so the checklist's own links work here."""
    text = html.unescape(re.sub(r"<[^>]+>", "", match[2]))
    return f'<h{match[1]} id="{anchor(text)}">{match[2]}</h{match[1]}>'


def _markdown() -> MarkdownIt:
    return MarkdownIt("commonmark", {"html": False}).enable("table")


def checklist_html(text: str) -> str:
    """checklist.md as HTML: title, contents and footer dropped, headings shifted down a level, and a
    labelled checkbox per tickable line."""
    lines = text.rstrip("\n").split("\n")
    if len(lines) >= 3 and lines[-3:-1] == ["---", ""] and lines[-1].startswith("Accessibility scan by "):
        lines = lines[:-3]  # the checklist's footer: the page has its own
    out: list[str] = []
    skipping_contents = False
    for line in lines:
        if line.startswith("# "):
            continue
        if line.startswith("## "):
            skipping_contents = line.strip() == "## Contents"
            if skipping_contents:
                continue
        elif skipping_contents:
            continue
        item = _ITEM.match(line)
        if item:
            on = "1" if item["box"] in "xX" else "0"
            line = f"- @@BOX:{item['id']}:{on}@@ {item['text']}{item['after']}"
        if line.startswith("#"):
            line = "#" + line
        out.append(line)
    rendered = _markdown().render("\n".join(out))

    def box(match: re.Match[str]) -> str:
        item_id, label = match["id"], match["label"]
        checked = " checked" if match["on"] == "1" else ""
        return (
            f'<li class="item"><input type="checkbox" id="cb-{item_id}" data-id="{item_id}" '
            f'aria-labelledby="t-{item_id}"{checked}> <span id="t-{item_id}">{label}</span>'
        )

    rendered = _BOX_TOKEN.sub(box, rendered)
    rendered = _HEADING.sub(_with_id, rendered)
    # Links leave the page in a new tab, so the review page (and its unsaved place) stays open.
    return _EXTERNAL.sub(
        r'<a href="\1" target="_blank" rel="noopener noreferrer">\2'
        r'<span class="visually-hidden"> (opens in a new tab)</span></a>',
        rendered,
    )


def _with_code(text: str) -> str:
    """A fix's own words, escaped, with what's between backticks shown as code (`<li>`, `alt=""`)."""
    parts = re.split(r"`([^`\n]+)`", text)  # plain text, code, plain text, ...
    return "".join(
        f"<code>{html.escape(part)}</code>" if i % 2 else html.escape(part) for i, part in enumerate(parts)
    )


def findings_html(report: ScanReport) -> str:
    """The scan's findings, as the terminal shows them, as HTML."""
    e = html.escape
    counts: dict[str, int] = {str(severity): n for severity, n in report.counts_by_severity.items()}
    tested = tested_text(report.meta.variants, report.meta.device, report.meta.dark_theme)
    parts = [
        '<h3 id="summary">Summary</h3>',
        *([f"<p>{e(tested)}</p>"] if tested else []),
        _SCROLL.format(label="Problems found, by severity"),
        "<table><caption>Problems found, by severity</caption>",
    ]
    parts.append("<thead><tr><th scope='col'>Severity</th><th scope='col'>Count</th></tr></thead><tbody>")
    for severity in _SEVERITIES:
        parts.append(
            f'<tr><th scope="row"><span class="sev sev-{severity}">{severity}</span></th>'
            f"<td>{counts.get(severity, 0)}</td></tr>"
        )
    parts.append("</tbody></table></div>")
    if report.findings:
        by_rule: dict[str, list] = {}
        for finding in report.findings:
            by_rule.setdefault(finding.rule_id, []).append(finding)
        parts.append('<h3 id="problems">Problems found</h3>')
        parts.append(_SCROLL.format(label="Failing rules and where they are"))
        parts.append("<table><caption>Failing rules and where they are</caption><thead><tr>")
        parts += [f"<th scope='col'>{h}</th>" for h in ("Severity", "Rule", "WCAG", "Elements", "Where")]
        parts.append("</tr></thead><tbody>")
        for rule, findings in by_rule.items():
            first = findings[0]
            where = "".join(
                f"<li><code>{e(f.selector)}</code>"
                + (f" ({e(seen)})" if (seen := where_text(f.seen_in, report.meta.variants)) else "")
                + "</li>"
                for f in findings[:10]
            )
            more = f"<li>and {len(findings) - 10} more</li>" if len(findings) > 10 else ""
            parts.append(
                f'<tr><td><span class="sev sev-{e(first.severity)}">{e(first.severity)}</span></td>'
                f"<td><code>{e(rule)}</code><br>{e(first.description)}</td>"
                f"<td>{e(', '.join(first.wcag_criteria) or 'best practice')}</td><td>{len(findings)}</td>"
                f"<td><ul>{where}{more}</ul></td></tr>"
            )
        parts.append("</tbody></table></div>")
    explained = [f for f in report.top_10 if f.explanation]
    if explained:
        parts.append('<h3 id="top-10">Top 10, explained</h3><ol>')
        for finding in explained:
            assert finding.explanation is not None
            parts.append(
                f"<li><p><strong>{e(finding.rule_id)}</strong> at <code>{e(finding.selector)}</code></p>"
                f"<p><strong>Why it matters:</strong> {e(finding.explanation.why_it_matters)}</p>"
                f"<p><strong>How to fix:</strong> {_with_code(finding.explanation.how_to_fix)}</p></li>"
            )
        parts.append("</ol>")
    fixes: dict[tuple[str, str], int] = {}
    for finding in report.findings:
        if finding.fix:
            key = (finding.rule_id, finding.fix.summary)
            fixes[key] = fixes.get(key, 0) + 1
    if fixes:
        parts.append('<h3 id="fixes">Suggested fixes</h3><ul>')
        for (rule, summary), count in fixes.items():
            times = f" ({count} elements)" if count > 1 else ""
            parts.append(f"<li><code>{e(rule)}</code>: {_with_code(summary)}{times}</li>")
        parts.append("</ul>")
    if report.needs_review:
        parts.append(
            '<h3 id="needs-review">Needs manual review</h3><p>axe-core could not decide these.</p><ul>'
        )
        parts += [f"<li><code>{e(r.rule_id)}</code>: {e(r.description)}</li>" for r in report.needs_review]
        parts.append("</ul>")
    if report.passed:
        parts.append(f'<h3 id="passed">Passed checks ({len(report.passed)})</h3><ul>')
        parts += [f"<li><code>{e(r.rule_id)}</code>: {e(r.description)}</li>" for r in report.passed]
        parts.append("</ul>")
    parts.append(
        f"<p>{report.inapplicable_count} other rules did not apply to this page. Passing means axe-core "
        "found no violation; automated checks cover only part of WCAG, so this is not a full audit.</p>"
    )
    return "\n".join(parts)


def findings_count(report: ScanReport) -> str:
    """The Findings line's summary: "3 problems on 2 elements (1 critical, 2 serious)"."""
    if not report.findings:
        return "no problems the automated checks can see"
    problems = len(report.findings)
    elements = len({finding.selector for finding in report.findings})
    counts = ", ".join(f"{n} {severity}" for severity, n in report.counts_by_severity.items() if n)
    problem_s = "s" if problems != 1 else ""
    element_s = "s" if elements != 1 else ""
    return f"{problems} problem{problem_s} on {elements} element{element_s} ({counts})"


def page(variants: list[Variant], current: Variant) -> str:
    """The whole page for one variant of a saved scan."""
    e = html.escape
    text = current.checklist.read_text(encoding="utf-8")
    done = checklist.progress(text)
    report = None
    if current.results is not None and current.results.exists():
        try:
            report = ScanReport.model_validate(json.loads(current.results.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            report = None
    url = report.url if report else ""
    name = plugins.edition().display_name
    switcher = ""
    if len(variants) > 1:
        links = []
        for variant in variants:
            current_attr = ' aria-current="page"' if variant == current else ""
            links.append(
                f'<li><a href="?variant={e(variant.label)}"{current_attr}>{e(variant.title)}</a></li>'
            )
        switcher = f'<nav aria-label="Variant" class="variants"><ul>{"".join(links)}</ul></nav>'
    title_bits = f"{e(url)}" + (f" ({e(current.title)})" if len(variants) > 1 else "")
    elsewhere = from_elsewhere(url, report.meta.requested_url) if report else None
    heading_bits = title_bits + (f" (reached from {e(elsewhere)})" if elsewhere else "")
    report_part = (
        findings_html(report)
        if report
        else "<p>This scan's results.json isn't available, so only the checklist can be shown.</p>"
    )
    template = (resources.files("magnacoda") / "data" / "review.html").read_text(encoding="utf-8")
    values = {
        "title": f"Review: {title_bits} - {e(name)}",
        "product": e(name),
        "heading": f"Accessibility review: {heading_bits}",
        "switcher": switcher,
        "variant": e(current.label),
        "progress": e(str(done)) if done.total else "No items to tick",
        "checklist": checklist_html(text),
        "findings": report_part,
        "findings_count": e(findings_count(report)) if report else "",
    }
    # One pass, so text from the scan can never be mistaken for another {{slot}}.
    return re.sub(r"\{\{(\w+)\}\}", lambda m: values.get(m.group(1), m.group(0)), template)
