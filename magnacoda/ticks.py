"""Tick and untick checklist items by ID (`<!-- id:... -->` at the end of each line).

checklist.md is the source of truth. Each change re-reads the file and touches one line, so edits made
in a Markdown editor meanwhile survive. results.json keeps a copy in `ticked`.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

_LINE = re.compile(r"^(?P<lead>- \[)(?P<box>[ xX])(?P<rest>\] .*<!-- id:(?P<id>[A-Za-z0-9._-]+) -->.*)$")


class UnknownItem(LookupError):
    """No line in the checklist has this ID (the file was changed, or the ID is wrong)."""


def read_ticks(checklist: Path) -> dict[str, bool]:
    """{item ID: ticked} for every tickable line with an ID, in file order."""
    found: dict[str, bool] = {}
    for line in checklist.read_text(encoding="utf-8").splitlines():
        match = _LINE.match(line)
        if match:
            found[match["id"]] = match["box"] in "xX"
    return found


def has_ids(checklist: Path) -> bool:
    """Whether the checklist can be ticked by ID (saved by a magnacoda that writes IDs)."""
    try:
        return bool(read_ticks(checklist))
    except (OSError, UnicodeError):
        return False


def set_tick(checklist: Path, item: str, ticked: bool, report: Path | None = None) -> None:
    """Tick or untick one item and copy the ticked IDs into `report`. Raises UnknownItem."""
    text = checklist.read_text(encoding="utf-8")
    lines = text.split("\n")
    for index, line in enumerate(lines):
        match = _LINE.match(line)
        if match and match["id"] == item:
            lines[index] = f"{match['lead']}{'x' if ticked else ' '}{match['rest']}"
            break
    else:
        raise UnknownItem(item)
    write(checklist, "\n".join(lines))
    if report is not None:
        mirror(checklist, report)


# A note a recheck adds to a Fix line (recheck.py); a later recheck replaces it.
_RECHECK_NOTE = re.compile(r" \*\((?:fixed|still failing|not found)[^)]*recheck[^)]*\)\*")


def mark(checklist: Path, changes: dict[str, tuple[bool | None, str]], report: Path | None = None) -> None:
    """Set several items (None leaves a box alone) and replace their recheck notes, in one write."""
    lines = checklist.read_text(encoding="utf-8").split("\n")
    for index, line in enumerate(lines):
        match = _LINE.match(line)
        if not match or match["id"] not in changes:
            continue
        ticked, note = changes[match["id"]]
        box = match["box"] if ticked is None else ("x" if ticked else " ")
        rest = _RECHECK_NOTE.sub("", match["rest"])
        marker = f" <!-- id:{match['id']} -->"
        rest = rest.replace(marker, f"{note}{marker}", 1)
        lines[index] = f"{match['lead']}{box}{rest}"
    write(checklist, "\n".join(lines))
    if report is not None:
        mirror(checklist, report)


def carries_over(item: str) -> bool:
    """Only human checks carry over to a new scan, never Fix items: if it's found again, it's still
    broken. (`-check-` IDs are from older scans.)"""
    return item.startswith("c-") or "-done-" in item or "-check-" in item


def mirror(checklist: Path, report: Path) -> None:
    """Copy the checklist's ticked IDs into the scan's results file (`ticked`)."""
    if report.exists():
        _mirror(report, [i for i, done in read_ticks(checklist).items() if done])


def _mirror(report: Path, ticked: list[str]) -> None:
    try:
        data = json.loads(report.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return  # the JSON is only a copy; the checklist has the ticks
    data["ticked"] = ticked
    write(report, json.dumps(data, indent=2))


def write(path: Path, text: str) -> None:
    """Replace the file in one step (a temporary file, then a rename), so it's never half written."""
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)
