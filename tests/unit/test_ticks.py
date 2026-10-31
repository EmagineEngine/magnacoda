"""Ticking checklist items by ID (ticks.py), and the IDs the checklist carries (markdown_export)."""

import json

import pytest

from magnacoda import ticks
from magnacoda.report.markdown_export import to_markdown
from tests.report.test_markdown import _report


def _saved(tmp_path):
    checklist = tmp_path / "checklist.md"
    checklist.write_text(to_markdown(_report()))
    report = tmp_path / "report.json"
    report.write_text(json.dumps({"url": "http://example.test"}))
    return checklist, report


def test_every_tickable_line_has_an_id_and_ids_are_the_same_each_time():
    md = to_markdown(_report())
    boxes = [line for line in md.splitlines() if line.startswith(("- [ ]", "- [x]"))]
    assert boxes and all("<!-- id:" in line for line in boxes)
    assert to_markdown(_report()) == md  # stable: the same report gives the same IDs
    ids = [line.split("<!-- id:")[1].split(" -->")[0] for line in boxes]
    assert len(ids) == len(set(ids)) and "c-3.3.8" in ids and any(i.startswith("e-") for i in ids)


def test_setting_a_tick_changes_only_that_line_and_keeps_other_edits(tmp_path):
    checklist, report = _saved(tmp_path)
    before = checklist.read_text()
    checklist.write_text(before.replace("dark color scheme", "dark color scheme (edited in Typora)"))
    ticks.set_tick(checklist, "c-3.3.8", True, report)
    after = checklist.read_text()
    assert "(edited in Typora)" in after  # an edit made meanwhile survives
    changed = [(a, b) for a, b in zip(before.splitlines(), after.splitlines(), strict=True) if a != b]
    assert len(changed) == 2  # the edited header line, and the one ticked line
    assert ticks.read_ticks(checklist)["c-3.3.8"] is True
    assert "c-3.3.8" in json.loads(report.read_text())["ticked"]
    ticks.set_tick(checklist, "c-3.3.8", False, report)
    assert (
        ticks.read_ticks(checklist)["c-3.3.8"] is False
        and "c-3.3.8" not in json.loads(report.read_text())["ticked"]
    )


def test_an_unknown_id_is_refused_and_old_checklists_have_none(tmp_path):
    checklist, _ = _saved(tmp_path)
    with pytest.raises(ticks.UnknownItem):
        ticks.set_tick(checklist, "c-9.9.9", True)
    old = tmp_path / "old.md"
    old.write_text("# Old\n\n- [ ] **[1.1.1 Non-text](https://x)** (A) - check it\n")
    assert ticks.has_ids(checklist) and not ticks.has_ids(old)
