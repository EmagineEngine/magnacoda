"""Code on a background of its own in the pager (tint.py, screen._paint_code, colors.code_color)."""

import io

import pytest

from magnacoda.pager import colors, formats, links, markdown, options, show, themes, tint
from magnacoda.pager import screen as pager

ON, OFF = tint.ON, tint.OFF
TRUE = {"COLORTERM": "truecolor"}


def test_each_pair_of_backticks_in_a_paragraph_is_code_and_a_lone_one_is_not():
    lines = ["Type `magnacoda", "scan` now, a lone ` here.", "", "one ` only"]
    assert tint.mark(lines) == [
        f"Type {ON}`magnacoda{OFF}",
        f"{ON}scan`{OFF} now, a lone ` here.",
        "",
        "one ` only",
    ]


def test_backticks_in_a_code_block_are_left_alone():
    assert tint.mark(["\x1b[10m    a `b` c"]) == ["\x1b[10m    a `b` c"]


def test_painting_drops_marked_backticks_and_puts_code_on_its_background():
    line = f"Type {ON}`scan`{OFF} now"
    assert pager._paint_code(line, "[", "]", 30) == "Type [scan] now"
    assert pager._paint_code(line, "", "", 30) == "Type `scan` now"  # no background: backticks stay
    assert pager._paint_code(line, "", "", 30, hide=True) == "Type scan now"  # while fading
    assert pager._paint_code(f"a {ON}`b", "[", "]", 30) == "a [b]"  # closed at the row's end
    highlighted = f"{ON}\x1b[7m`cli`\x1b[27m{OFF}"  # a link Tab is on, or a search match
    assert pager._paint_code(highlighted, "[", "]", 30) == "[\x1b[7mcli\x1b[27m]"


def test_a_code_blocks_rows_are_filled_to_the_width_with_a_row_above_and_below():
    rows = links.wrapper(formats.MARKDOWN.render, hyperlinks=False, code=True)("```\nls\n```\n", 12)
    painted = [pager._paint_code(row, "[", "]", 12).replace(links.CODE_MARK, "") for row in rows]
    assert painted == ["[            ]", "[  ls        ]", "[            ]"]
    assert markdown.render("```\nls\n```\n", 12) == ["  ls"]  # printed: the same indent


def test_with_an_accent_code_keeps_its_background_after_each_style():
    row = pager._accented(pager._prepare_code(f"a {ON}`b`{OFF}", "<t>", 20), "<c>", "<a>", "<r>", "<t>")
    assert row == "<c>a <c><t>b<c><c>"


def test_printed_text_keeps_its_backticks():
    out = io.StringIO()
    show([("One", "Type `scan`.")], options.PagerOptions(paging=False), format=formats.MARKDOWN, out=out)
    assert out.getvalue().strip() == "Type `scan`."


@pytest.mark.parametrize("scheme", colors.SCHEMES[1:], ids=lambda s: s.name)
def test_every_scheme_has_a_readable_code_background_in_full_and_256_colors(scheme):
    text, code = colors.code_colors(scheme.fg, scheme.bg)
    assert colors.contrast(text, code) >= 7 and colors.contrast(scheme.bg, code) >= 1.4  # easy to see
    assert colors.contrast(text, scheme.bg) > colors.contrast(scheme.fg, scheme.bg)  # brighter text
    text256 = colors.nearest256(text)[0]
    number = colors.code256(code, text256, scheme.bg256)
    assert number not in (None, scheme.bg256)
    assert colors.contrast(colors.xterm256(text256), colors.xterm256(number)) >= 7


def test_code_codes_in_full_color_256_colors_and_none():
    on, off = colors.code_codes("print", TRUE)
    assert on.startswith("\x1b[38;2;") and ";48;2;" in on
    assert off == "\x1b[38;2;16;16;16;48;2;232;228;216m"  # back to the scheme's text and background
    assert colors.code_codes("print", {})[0].startswith("\x1b[38;5;")
    assert colors.code_codes("default", TRUE) == ("", "")
    assert colors.code_codes("print", {**TRUE, "NO_COLOR": "1"}) == ("", "")


def test_with_an_accent_codes_text_keeps_its_color():
    accented = colors.Scheme("x", "", "#e8e4d8", "#101010", 254, 233, accent="#ffcc66", accent256=221)
    on, off = colors.code_codes(accented, TRUE)
    assert on.startswith("\x1b[48;2;") and off == "\x1b[48;2;16;16;16m"


def test_the_terminals_own_colors_get_a_code_background_only_if_it_said_which():
    on, off = colors.own_code_codes(((255, 255, 255), (0, 0, 0)), TRUE)
    assert on == "\x1b[48;2;64;64;64m" and off == "\x1b[49m"  # white can't be lifted: no text color
    on, off = colors.own_code_codes(((224, 154, 0), (0, 0, 0)), TRUE)
    assert on.startswith("\x1b[38;2;") and off == "\x1b[39;49m"
    assert colors.own_code_codes(None, TRUE) == ("", "")


def test_a_theme_may_set_codes_background_if_the_text_reads_on_it(tmp_path):
    base = "[slate]\ntext = #ffe8a6\nbackground = #293955\n"
    path = tmp_path / themes.FILE_NAME
    path.write_text(base + "code = #34466a\n", encoding="utf-8")
    (slate,) = themes.load(path).themes
    assert slate.code == "#34466a" and slate.code256 not in (0, slate.bg256)
    path.write_text(base + "code = #ffe8a6\n", encoding="utf-8")
    assert "text on code is" in themes.load(path).problems[0]


def test_a_code_block_inside_a_list_item_keeps_the_item_and_the_list_together():
    text = "1. One.\n\n2. Two:\n\n   ```\n   ls\n\n   pwd\n   ```\n\n   After the code.\n\n3. Three.\n"
    lines = markdown.render(text, 40)
    assert lines == [
        " 1 One.",
        "",
        " 2 Two:",
        "",
        "     ls",
        "",
        "     pwd",
        "",
        "   After the code.",
        "",
        " 3 Three.",
    ]
