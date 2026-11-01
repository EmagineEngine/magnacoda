"""Saved checklists for `review`, newest first.

Current layout: site_YYYYMMDD-HHMMSS/checklist[.label].md. Before 2026-10-10 they were loose files,
site_YYYYMMDD-HHMMSS[.label].md.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from magnacoda import checklist, ticks

_NAME = re.compile(r"^(?P<site>.+)_(?P<stamp>\d{8}-\d{6})(?:\.(?P<label>[a-z][a-z.]*))?\.md$")
LIMIT = 20


@dataclass(frozen=True)
class SavedReport:
    path: Path
    site: str
    when: datetime
    label: str  # "" or, for one of several passes, e.g. "dark" or "mobile, light"
    progress: checklist.Progress | None = None  # how many items are ticked; None if unreadable

    def line(self) -> str:
        variant = f"  ({self.label})" if self.label else ""
        done = f"  - {self.progress}" if self.progress and self.progress.total else ""
        return f"{self.site}  {self.when:%Y-%m-%d %H:%M}{variant}{done}"


_FOLDER = re.compile(r"^(?P<site>.+)_(?P<stamp>\d{8}-\d{6})$")
_CHECKLIST = re.compile(r"^checklist(?:\.(?P<label>[a-z][a-z.]*))?\.md$")


def _when(stamp: str) -> datetime | None:
    try:
        return datetime.strptime(stamp, "%Y%m%d-%H%M%S")
    except ValueError:
        return None


def find(folder: Path, limit: int = LIMIT) -> list[SavedReport]:
    """The newest `limit` checklists in `folder` (both layouts); [] if none."""
    try:
        entries = list(folder.iterdir())
    except OSError:
        return []
    found = []
    for entry in entries:
        if entry.is_dir():
            match = _FOLDER.match(entry.name)
            when = _when(match["stamp"]) if match else None
            if not match or when is None:
                continue
            for path in sorted(entry.glob("checklist*.md")):
                inner = _CHECKLIST.match(path.name)
                if inner:
                    label = ", ".join((inner["label"] or "").split("."))
                    found.append(SavedReport(path, match["site"], when, label))
            continue
        match = _NAME.match(entry.name)
        when = _when(match["stamp"]) if match else None
        if match and when is not None:
            label = ", ".join((match["label"] or "").split("."))
            found.append(SavedReport(entry, match["site"], when, label))
    found.sort(key=lambda report: (report.when, report.label), reverse=True)
    return [_with_progress(report) for report in found[:limit]]


def _with_progress(report: SavedReport) -> SavedReport:
    try:
        text = report.path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return report
    return SavedReport(report.path, report.site, report.when, report.label, checklist.progress(text))


@dataclass(frozen=True)
class SavedScan:
    """One saved scan and its checklists (one per variant). `folder` is None for old loose files."""

    folder: Path | None
    site: str
    when: datetime
    reports: list[SavedReport]

    def line(self) -> str:
        labels = [report.label for report in self.reports if report.label]
        variants = f"  ({'; '.join(labels)})" if labels else ""
        done = [report.progress for report in self.reports if report.progress and report.progress.total]
        progress = (
            f"  - {checklist.Progress(sum(p.checked for p in done), sum(p.total for p in done))}"
            if done
            else ""
        )
        return f"{self.site}  {self.when:%Y-%m-%d %H:%M}{variants}{progress}"

    def variant_label(self, report: SavedReport) -> str:
        """The variant as it appears in the file name ("dark", "mobile.light"), or "" for a single one."""
        name = report.path.name
        if self.folder is None:
            match = _NAME.match(name)
            return (match["label"] or "") if match else ""
        inner = _CHECKLIST.match(name)
        return (inner["label"] or "") if inner else ""


def scans(folder: Path, limit: int = LIMIT) -> list[SavedScan]:
    """The newest `limit` saved scans in `folder`, newest first, each listed once with its variants."""
    grouped: dict[Path, list[SavedReport]] = {}
    for report in find(folder, limit=10_000):
        key = report.path.parent if report.path.name.startswith("checklist") else report.path
        grouped.setdefault(key, []).append(report)
    found = []
    for key, reports in grouped.items():
        in_folder = reports[0].path.name.startswith("checklist")
        found.append(SavedScan(key if in_folder else None, reports[0].site, reports[0].when, reports))
    found.sort(key=lambda scan: scan.when, reverse=True)
    return found[:limit]


def scan_in(folder: Path) -> SavedScan | None:
    """The saved scan whose own folder this is, if it is one."""
    if not any(folder.glob("checklist*.md")):
        return None
    here = folder.resolve()
    found = scans(folder.parent, limit=10_000)
    return next((scan for scan in found if scan.folder and scan.folder.resolve() == here), None)


def previous_ticks(
    folder: Path, current: Path, url: str, label: str, wcag_version: str, level: str
) -> tuple[dict[str, bool], datetime | None]:
    """Carry-over ticks from the newest earlier scan of the same page, variant, version and level,
    and that scan's date."""
    for scan in scans(folder, limit=10_000):
        if scan.folder is None or scan.folder.resolve() == current.resolve():
            continue
        for report in scan.reports:
            if scan.variant_label(report) != label:
                continue
            json_path = report.path.with_name(
                "results" + report.path.name[len("checklist") : -len(".md")] + ".json"
            )
            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
                meta = data.get("meta", {})
                same = data.get("url") == url and meta.get("wcag_version") == wcag_version
                same = same and meta.get("wcag_level") == level
                found = ticks.read_ticks(report.path) if same else {}
            except (OSError, ValueError, AttributeError):
                continue
            if same:
                return {i: True for i, done in found.items() if done and ticks.carries_over(i)}, scan.when
    return {}, None
