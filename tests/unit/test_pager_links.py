"""Web addresses in the pager: real terminal hyperlinks, and never broken across lines."""

import pytest

from magnacoda.pager import formats, links, markdown, options
from magnacoda.pager import screen as pager

LONG = "https://dequeuniversity.com/rules/axe/4.10/color-contrast?application=magnacoda"
OSC = "\x1b]8;"
NESTED = "https://docs.test/a/b/c/d/e/f/g/h/i/j/k/l/m/n/o/p/q/r/s/t/u/v/w/x/y/z/0/1/2/3"
KNOWN = {LONG, NESTED}


def _link_targets(line: str) -> list[str]:
    """The address in each hyperlink code of the line, "" for each code that ends a link."""
    codes = [code for code in links._CODE.findall(line) if code.startswith(OSC)]
    return [code[len(OSC) :].split(";", 1)[1][:-2] for code in codes]


# --- finding and shortening ------------------------------------------------------------------------


def test_addresses_are_found_without_the_punctuation_around_them():
    text = "See https://a.test/x, (https://b.test/y). Or http:// alone, and nohttps://c.test."
    assert [text[s:e] for s, e in links.found(text)] == ["https://a.test/x", "https://b.test/y"]


def test_an_address_too_long_for_its_line_is_shortened_in_the_middle():
    assert links.shorten("https://a.test", 40) == "https://a.test"
    short = links.shorten(LONG, 40)
    assert len(short) == 40 and "…" in short and short.startswith("https://dequeuniversity.com")
    assert short == "https://dequeuniversity.com…" + LONG[-12:]  # the whole site name, then the end


def test_prepare_shortens_only_what_wont_fit_and_leaves_code_and_markdown_link_addresses_alone():
    text = f"Read {LONG}\n- `{LONG}`\n[rule]({LONG})\n```\n{LONG}\n```\nhttps://a.test"
    prepared, full = links.prepare(text, 50)
    lines = prepared.splitlines()
    assert "…" in lines[0] and full == {lines[0][5:]: LONG}
    assert lines[1:6] == text.splitlines()[1:6]  # code, a link's address, a fenced block
    assert lines[6] == "https://a.test"


# --- links -----------------------------------------------------------------------------------------


def test_each_address_becomes_an_underlined_hyperlink_and_a_shortened_one_keeps_the_full_address():
    short = links.shorten(LONG, 30)
    line = links.linkify(f"Go to https://a.test or {short}.", {short: LONG})
    assert _link_targets(line) == ["https://a.test", "", LONG, ""]
    assert links.visible(line) == f"Go to https://a.test or {short}."
    assert line.count("\x1b[4m") == 2 and line.count("\x1b[24m") == 2


def test_a_link_the_line_already_has_is_left_as_it_is():
    drawn = "\x1b]8;id=1;https://a.test\x1b\\\x1b[4mhttps://a.test\x1b[24m\x1b]8;;\x1b\\ and https://b.test"
    assert _link_targets(links.linkify(drawn)) == ["https://a.test", "", "https://b.test", ""]


@pytest.mark.parametrize("width", [40, 60, 80, 120])
def test_in_markdown_no_address_is_ever_broken_and_every_line_fits(width):
    text = (
        f"Some words, then [the rule]({LONG}) and {LONG} too.\n\n- a list item: {LONG}\n"
        f"  - nested: {NESTED}\n\n"
        f"> quoted {LONG}"
    )
    lines = links.wrapper(markdown.render)(text, width)
    for line in lines:
        shown = links.visible(line)
        assert len(shown) <= width, shown
        targets = [url for url in _link_targets(line) if url]
        for start, end in links.found(shown):
            address = shown[start:end]
            assert address in KNOWN or ("…" in address and len(address) <= width), address  # never a piece
        assert all(url in KNOWN for url in targets)  # the link itself always holds the whole address
    joined = "\n".join(lines)
    assert joined.count(LONG) >= 4  # every one is in a link whole: the Markdown link, and three bare
    assert "(https://" not in links.visible(joined)  # a link shows its text, not "text (address)"


def test_help_and_plain_text_get_links_too():
    lines = links.wrapper(formats.REFERENCE.render)("Report problems at https://docs.test/issues.", 60)
    assert any(OSC in line for line in lines)
    plain = links.wrapper(pager.default_wrap)(f"Report: {LONG}", 40)
    assert [links.visible(line) for line in plain][0] == "Report:"
    assert LONG in plain[1] and len(links.visible(plain[1])) <= 40


def test_without_hyperlinks_markdown_is_as_before():
    assert markdown.render(f"[rule]({LONG})", 120) == [f"rule ({LONG})"]


# --- drawing and when -------------------------------------------------------------------------------


def test_the_row_cut_counts_only_what_shows_and_closes_an_open_link():
    row = "ab\x1b]8;;https://x.test\x1b\\\x1b[4mlinktext\x1b[24m\x1b]8;;\x1b\\ tail"
    assert pager._cut(row, 6) == "ab\x1b]8;;https://x.test\x1b\\\x1b[4mlink\x1b[24m\x1b]8;;\x1b\\"
    assert pager._cut(row, 50) == row
    assert pager._cut("plain text", 5) == "plain"


@pytest.mark.parametrize(
    ("env", "platform", "expected"),
    [
        ({"TERM": "xterm-256color"}, "linux", True),
        ({"TERM": "linux"}, "linux", False),
        ({"TERM": "xterm-256color", "TERM_PROGRAM": "Apple_Terminal"}, "darwin", False),
        ({"TERM_PROGRAM": "iTerm.app"}, "darwin", True),
        ({}, "win32", False),
        ({"WT_SESSION": "x"}, "win32", True),
        ({"TERM_PROGRAM": "vscode"}, "win32", True),
        ({"TERMINAL_EMULATOR": "JetBrains-JediTerm"}, "win32", True),
    ],
)
def test_hyperlinks_only_where_the_terminal_is_likely_to_have_them(env, platform, expected):
    assert links.supported(env, platform) is expected


def test_the_setting_turns_them_off(tmp_path, monkeypatch):
    path = tmp_path / "app.ini"
    path.write_text("[pager]\nhyperlinks = off\n")
    seen = {}

    def fake_page(sections, **kwargs):
        seen.update(kwargs)

    import magnacoda.pager as package

    monkeypatch.setattr(package, "pager_available", lambda off_switch=None: True)
    monkeypatch.setattr(package, "page_sections", fake_page)
    monkeypatch.setattr(links, "supported", lambda env=None, platform=None: True)
    package.show([("One", f"[rule]({LONG})")], options.resolve(path), format=formats.MARKDOWN)
    assert OSC not in "".join(seen["wrap"](f"[rule]({LONG})", 60))  # "rule (address)", as before
    path.write_text("[pager]\n")
    package.show([("One", f"[rule]({LONG})")], options.resolve(path), format=formats.MARKDOWN)
    assert OSC in seen["wrap"](f"[rule]({LONG})", 60)[0]


def test_nothing_in_code_and_no_placeholder_address_becomes_a_link():
    text = (
        "Read [the docs](https://docs.test/a), [a demo](https://example.com/x), https://example.org/y, "
        "`https://code.test/z` and https://real.test/b.\n\n```\ncurl https://api.test/v1\n```\n"
    )
    lines = links.wrapper(markdown.render)(text, 60)
    targets = [url for line in lines for url in _link_targets(line) if url]
    assert targets == ["https://docs.test/a", "https://real.test/b"]
    assert "a demo (https://example.com/x)" in links.visible("\n".join(lines))  # its address still shows
    assert links.found("See https://www.Example.com/x, http://mysite:8080 and `https://a.test`.") == []
