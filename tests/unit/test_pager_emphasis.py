"""Bold and italic in the pager: Markdown's own, and *italic* and **bold** in help and news."""

import io

from magnacoda.pager import emphasis, formats, links, markdown, options, show
from magnacoda.pager import screen as pager

ITALIC, BOLD = "\x1b[3m", "\x1b[1m"


def test_markdown_keeps_bold_and_italic_but_never_rich_s_colors_or_full_resets():
    lines = links.wrapper(markdown.render)(
        "## Head\n\nSome *italic* and **bold**, [a link](https://docs.test/x).", 60
    )
    joined = "\n".join(lines)
    assert f"{BOLD}Head" in joined and f"{ITALIC}italic" in joined and f"{BOLD}bold" in joined
    assert "\x1b[0m" not in joined and "\x1b[3" + "4m" not in joined  # no reset, no Rich blue
    assert links.visible(lines[2]) == "Some italic and bold, a link."


def test_printed_markdown_stays_plain():
    assert markdown.render("Some *italic*.", 60) == ["Some italic."]


def test_help_emphasis_is_styled_even_when_a_phrase_wraps_and_stops_at_each_line_end():
    lines = emphasis.style(pager.default_wrap(emphasis.mark("one *two three four* five **six**"), 16))
    assert [links.visible(line) for line in lines] == ["one two three", "four five six"]
    assert lines[0] == f"one {ITALIC}two three\x1b[22;23m"  # off at the end of the row
    assert lines[1] == f"{ITALIC}four\x1b[23m five {BOLD}six\x1b[22m"  # on again on the next


def test_asterisks_that_are_not_emphasis_stay():
    assert emphasis.mark("2 * 3 * 4 and a * b") == "2 * 3 * 4 and a * b"
    assert emphasis.plain("A *word* and **two words**.") == "A word and two words."


def test_show_styles_help_when_paging_and_drops_the_asterisks_when_printing(monkeypatch):
    seen = {}

    def fake_page(sections, **kwargs):
        seen.update(kwargs)

    import magnacoda.pager as package

    out = io.StringIO()
    show([("One", "A *word*.")], options.PagerOptions(paging=False), format=formats.REFERENCE, out=out)
    assert out.getvalue().strip() == "A word."
    monkeypatch.setattr(package, "pager_available", lambda off_switch=None: True)
    monkeypatch.setattr(package, "page_sections", fake_page)
    show([("One", "A *word*.")], options.PagerOptions(), format=formats.REFERENCE)
    assert f"{ITALIC}word" in seen["wrap"]("A *word*.", 40)[0]


def test_the_cut_turns_off_any_style_still_on():
    assert pager._cut("ab\x1b[1;3mcdef\x1b[22;23mgh", 4) == "ab\x1b[1;3mcd\x1b[22;23m"
    assert pager._cut("a\x1b[1mb\x1b[22mc", 10) == "a\x1b[1mb\x1b[22mc"
