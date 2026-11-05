"""Progress in a Markdown checklist (checklist.py). (tests/unit/test_checklist.py is about building the
checklist from a scan, findings/checklist.py.)"""

import pytest

from magnacoda import checklist
from magnacoda.pager import markdown

TEXT = """# Accessibility checklist: https://example.com/

Intro.

## Fix these (2)

- [x] **1.4.3 Contrast** - fixed
- [ ] **1.1.1 Non-text Content**

## Check first (2)

- [X] **2.4.7 Focus Visible**
- [x] **1.4.13 Content on Hover**

## Notes

No boxes here.
"""


def test_progress_counts_ticked_and_all_boxes():
    assert checklist.progress(TEXT) == checklist.Progress(3, 4)
    assert str(checklist.progress(TEXT)) == "3 of 4 checked"


def test_prepare_adds_progress_counts_and_check_marks():
    prepared = checklist.prepare(markdown.parse(TEXT).sections)
    names = [name for name, _ in prepared]
    assert names == ["Introduction", "Fix these (2) - 1 checked", "Check first (2) - all 2 checked", "Notes"]
    assert prepared[0][1].startswith("**Progress:** 3 of 4 checked")
    fix = prepared[1][1]
    assert "- [✓] **1.4.3 Contrast**" in fix and "- [ ] **1.1.1" in fix and "[x]" not in fix


def test_a_document_without_checkboxes_is_left_alone():
    sections = [("Intro", "Just text, and [x] in a sentence.")]
    assert checklist.prepare(sections) == sections


@pytest.mark.parametrize(
    ("platform", "env", "mark"),
    [
        ("linux", {}, "[✓]"),
        ("win32", {"WT_SESSION": "1"}, "[✓]"),
        ("win32", {"TERM_PROGRAM": "vscode"}, "[✓]"),
        ("win32", {"TERMINAL_EMULATOR": "JetBrains-JediTerm"}, "[✓]"),
        ("win32", {}, "[x]"),
    ],
)
def test_the_classic_windows_console_gets_a_plain_x(platform, env, mark):
    assert checklist.checked_mark(env, platform) == mark
