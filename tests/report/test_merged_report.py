"""A scan of several screens and themes shown as one report: what was tested, and the problems found in
one place only (findings/merge.py, in the checklist, the review page and the terminal)."""

from magnacoda import review_page
from magnacoda.findings import merge
from magnacoda.report.markdown_export import to_markdown
from magnacoda.report.terminal import render_report
from tests.unit.test_merge import DARK_RULES, _finding, _report


def _merged():
    light = _report([_finding("label", "input", criteria=("1.3.1",))])
    dark = _report([_finding("color-contrast", "p.note")], theme="dark")
    mobile = _report([_finding("label", "input", criteria=("1.3.1",))], screen="mobile")
    return merge.merge(
        [
            merge.Pass("desktop.light", light),
            merge.Pass("desktop.dark", dark, covered=DARK_RULES),
            merge.Pass("mobile.light", mobile),
        ],
        dark_theme=True,
    )


def test_the_checklist_says_what_was_tested_and_marks_problems_found_in_one_place():
    report = _merged()
    text = to_markdown(report)
    # Mid-sentence, after the level the scan used (whatever it is): lowercase "tested".
    level = report.meta.wcag_level
    assert f"Level {level} - tested on desktop and mobile (Pixel 8 Pro), in light and dark mode." in text
    contrast = next(line for line in text.splitlines() if "rule color-contrast" in line)
    assert "only on desktop in dark mode" in contrast
    label = next(line for line in text.splitlines() if "rule label" in line)
    assert "only" not in label


def test_the_review_page_and_the_terminal_do_too(capsys):
    html = review_page.findings_html(_merged())
    assert "Tested on desktop and mobile (Pixel 8 Pro), in light and dark mode." in html
    assert "<code>p.note</code> (only on desktop in dark mode)" in html
    render_report(_merged(), no_color=True)
    out = "".join(capsys.readouterr().out.split())
    assert "Testedondesktopandmobile(Pixel8Pro),inlightanddarkmode." in out
