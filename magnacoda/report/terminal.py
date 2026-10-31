from __future__ import annotations

from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from magnacoda import plugins
from magnacoda.browser.redirects import from_elsewhere
from magnacoda.findings.merge import tested_text, where_text
from magnacoda.findings.models import CriterionEntry, Finding, RuleResult, ScanReport, group_by_fix
from magnacoda.report.css_lines import where_set

_SEVERITY_STYLE = {
    "critical": "bold red",
    "serious": "red",
    "moderate": "yellow",
    "minor": "",
}  # not dim: it must stay readable
_SOURCE_LABEL = {"axe-core": "axe-core", "claude-semantic": "claude (semantic)", "magnacoda": "magnacoda"}
_MAX_INSTANCES_SHOWN = 5


def _group_by_rule(ranked: list[Finding]) -> list[list[Finding]]:
    """Group findings sharing a rule, keeping the ranked order of each group's first member."""
    groups: dict[tuple[str, str, str], list[Finding]] = {}
    for finding in ranked:
        groups.setdefault((finding.rule_id, finding.severity, finding.source), []).append(finding)
    return list(groups.values())


def _instances_cell(group: list[Finding], variants: list[str]) -> str:
    lines = []
    for finding in group[:_MAX_INSTANCES_SHOWN]:
        line = f"[bold]{escape(finding.selector)}[/bold]"
        where = where_text(finding.seen_in, variants)
        if where:
            line += f" ({where})"
        for code, place in where_set(finding.css):
            line += f"\nset by {escape(code)} {escape(place)}"
        if finding.detail:
            line += f"\n{escape(finding.detail)}"
        lines.append(line)
    hidden = len(group) - _MAX_INSTANCES_SHOWN
    if hidden > 0:
        lines.append(f"+{hidden} more (all are in the scan's checklist and results.json)")
    return "\n\n".join(lines)


def _rule_table(results: list[RuleResult]) -> Table:
    table = Table(show_lines=False, header_style="bold")
    table.add_column("Check", no_wrap=True)
    table.add_column("WCAG SC", no_wrap=True)
    table.add_column("Level", no_wrap=True)
    table.add_column("Elements", justify="right", no_wrap=True)
    table.add_column("What it verifies", ratio=1)
    for result in results:
        table.add_row(
            result.rule_id,
            ", ".join(result.wcag_criteria) or "-",
            result.wcag_level or "-",
            str(result.instance_count),
            escape(result.description) + "".join(f"\n{escape(detail)}" for detail in result.details),
        )
    return table


def _render_coverage(console: Console, report: ScanReport) -> None:
    if report.needs_review:
        console.print(f"\n[bold yellow]Needs manual review ({len(report.needs_review)})[/bold yellow]")
        console.print("axe-core could not decide these automatically - check them by hand.")
        console.print(_rule_table(report.needs_review))
    if report.passed:
        console.print(f"\n[bold green]Passed checks ({len(report.passed)})[/bold green]")
        console.print(_rule_table(report.passed))
    console.print(
        f"\n{report.inapplicable_count} other rules did not apply to this page. Passing means axe-core "
        "found no violation; automated checks cover only part of WCAG, so this is not a full audit."
    )


def _why_here(entry: CriterionEntry) -> str:
    """Why a manual check applies, with the first two elements."""
    places = [
        example.selector + (f' ("{example.hint}")' if example.hint else "") for example in entry.examples[:2]
    ]
    return (entry.reason or "") + "".join(f"\ne.g. {place}" for place in places)


def _render_checklist(console: Console, report: ScanReport) -> None:
    relevant = [e for e in report.checklist if e.tier == "relevant"]
    counts = {
        t: sum(1 for e in report.checklist if e.tier == t)
        for t in ("every_page", "depends", "likely_na", "not_applicable")
    }
    if not report.checklist:
        return
    console.print(
        f"\n[bold cyan]Still to check manually: relevant to this page ({len(relevant)})[/bold cyan]"
    )
    if relevant:
        table = Table(show_lines=False, header_style="bold")
        table.add_column("SC", no_wrap=True)
        table.add_column("Level", no_wrap=True)
        table.add_column("Criterion")
        table.add_column("Why here")
        table.add_column("How to check", ratio=1)
        for entry in relevant:
            table.add_row(
                f"[link={entry.url}]{entry.num}[/link]",
                entry.level,
                escape(entry.title),
                escape(_why_here(entry)),
                escape(entry.how_to_check or ""),
            )
        console.print(table)
    else:
        console.print("No page features were detected that trigger extra manual checks.")
    hidden = report.page_features.hidden_reachable if report.page_features else 0
    if hidden:
        console.print(
            f"[bold]Hidden but reachable:[/bold] {hidden} element{'s are' if hidden != 1 else ' is'} "
            "invisible, yet "
            "reachable with Tab and by screen readers (a hidden honeypot field or an off-screen menu often "
            "does this). The scan's checklist says which, and how to fix them."
        )
    console.print(
        f"Also: {counts['every_page']} to check on every page, {counts['depends']} that depend on the "
        f"site or user flows, and {counts['likely_na']} probably not applicable"
        + (
            f"; {counts['not_applicable']} about audio and video don't apply (there is none)"
            if counts["not_applicable"]
            else ""
        )
        + ". The scan's checklist has the full list, with links to the W3C's guidance."
    )


def render_report(
    report: ScanReport, *, no_color: bool = False, heading: str | None = None, show_passed: bool = True
) -> None:
    console = Console(no_color=no_color)
    if heading:
        console.rule(f"[bold]{escape(heading)}[/bold]", style="cyan")
    ranked: list[Finding] = sorted(report.findings, key=Finding.sort_key)

    counts = report.counts_by_severity
    summary = "  ".join(f"{sev}: {n}" for sev, n in counts.items())
    meta = report.meta
    tested = tested_text(meta.variants, meta.device, meta.dark_theme)
    if tested:
        where = f"{escape(tested)}\n"
    else:  # saved before scans were merged: one screen and theme per report
        where = f"{meta.color_scheme or 'default'} color scheme · " + (
            f"{meta.screen} screen · " if meta.screen else ""
        )
    console.print(
        Panel(
            f"[bold]{escape(report.url)}[/bold]"
            + (
                f" (reached from {escape(elsewhere)})"
                if (elsewhere := from_elsewhere(report.url, meta.requested_url))
                else ""
            )
            + f"\n{summary}\n{where}"
            f"WCAG {meta.wcag_version} Level {meta.wcag_level} · "
            f"{len(report.findings)} finding(s) · ai={meta.ai_tier} · fixes={meta.fixes_tier}",
            title=f"[italic]{escape(plugins.edition().display_name)}[/italic]",
        )
    )

    if not report.meta.stability_settled:
        console.print(
            f"[yellow]Warning:[/yellow] page did not reach DOM quiescence within "
            f"{report.meta.stability_elapsed_ms}ms; the scan may have run against an "
            "incompletely-rendered page. For a slow page, scan again with --wait 30 (seconds).\n"
        )

    if not ranked:
        console.print("[green]No violations found for the selected WCAG version/level.[/green]")
        if show_passed:
            _render_coverage(console, report)
            _render_checklist(console, report)
        return

    groups = _group_by_rule(ranked)

    table = Table(show_lines=True)
    table.add_column("Severity", no_wrap=True)
    table.add_column("Source", no_wrap=True)
    table.add_column("Rule", no_wrap=True)
    table.add_column("WCAG SC", no_wrap=True)
    table.add_column("Count", justify="right", no_wrap=True)
    table.add_column("Where / details", ratio=1)
    for group in groups:
        first = group[0]
        style = _SEVERITY_STYLE.get(first.severity, "")
        table.add_row(
            f"[{style}]{first.severity}[/{style}]" if style else first.severity,
            _SOURCE_LABEL.get(first.source, first.source),
            first.rule_id,
            ", ".join(first.wcag_criteria) or "-",
            str(len(group)),
            f"{escape(first.description)}\n\n{_instances_cell(group, report.meta.variants)}",
        )
    console.print(table)

    top_10 = ranked[:10]
    explained = [f for f in top_10 if f.explanation]
    if explained:
        console.print("\n[bold]Top 10 — detailed explanations[/bold]\n")
        for i, group in enumerate(group_by_fix(explained), 1):
            first = group[0]
            assert first.explanation is not None
            body = (
                f"[bold]Why it matters:[/bold] {escape(first.explanation.why_it_matters)}\n\n"
                f"[bold]How to fix:[/bold] {escape(first.explanation.how_to_fix)}"
            )
            if first.fix:
                body += f"\n\n[bold]Suggested fix:[/bold]\n{escape(first.fix.corrected_snippet)}"
            if len(group) > 1:
                others = ", ".join(escape(f.selector) for f in group)
                body += f"\n\nSame fix applies to {len(group)} elements: {others}"
                title = f"{i}. {first.rule_id} ({len(group)} elements)"
            else:
                title = f"{i}. {first.rule_id} ({escape(first.selector)})"
            console.print(Panel(body, title=title))
    elif report.meta.fixes_tier == "template":
        console.print("\n[bold]Suggested fixes[/bold]\n")
        fix_counts: dict[tuple[str, str], int] = {}
        for finding in ranked:
            if finding.fix:
                key = (finding.rule_id, finding.fix.summary)
                fix_counts[key] = fix_counts.get(key, 0) + 1
        for (rule_id, summary), count in fix_counts.items():
            console.print(f"[cyan]{rule_id}[/cyan] ({count}×): {escape(summary)}")

    if show_passed:
        _render_coverage(console, report)
        _render_checklist(console, report)
