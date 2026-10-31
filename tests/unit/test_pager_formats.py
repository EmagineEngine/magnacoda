"""The pager's formats: Markdown, plain text, and a command reference laid out like a man page."""

from magnacoda.pager import formats, reference


def test_sections_drop_comments_and_anything_above_the_first_and_keep_order():
    text = (
        "# Title\n<!-- note\nspanning lines -->\n## Overview\nhello <!-- hidden -->\n\n"
        "## two\nsecond\n### Not a section\n## three\nbye\n"
    )
    parsed = reference.sections(text)
    assert list(parsed) == ["overview", "two", "three"]
    assert reference.layout(parsed["overview"]) == "hello"
    assert reference.layout(parsed["two"]) == "second\nNot a section"


def test_lists_become_term_lines_with_descriptions_beneath_or_beside():
    text = (
        "### Flags:\n\n- `--level [A|AA]`\n  Conformance **level**.\n- `--save`\n  Save it.\n\n"
        "### Short:\n\n- `scan URL` Scan a page\n- `about` Author\n\nA *plain* paragraph with `code`.\n"
    )
    assert reference.layout(text) == (
        "Flags:\n"
        "  --level [A|AA]\n"
        "      Conformance **level**.\n"  # the pager shows it in bold, or plain when printing
        "  --save\n"
        "      Save it.\n"
        "\n"
        "Short:\n"
        "  scan URL   Scan a page\n"
        "  about      Author\n"
        "\n"
        "A *plain* paragraph with `code`."
    )


def test_an_item_with_several_terms_shows_them_together():
    text = "- `readme`, `readme NAME`\n  Read it.\n- `a`, `b` Beside\n"
    assert reference.layout(text) == "  readme, readme NAME\n      Read it.\n  a, b   Beside"


def test_terms_are_never_wrapped_and_descriptions_wrap_under_themselves():
    text = "- `scan URL --level AA --screen both`\n  One two three four five six seven eight.\n"
    assert reference.render(text, 24) == [
        "  scan URL --level AA --screen both",
        "      One two three four",
        "      five six seven",
        "      eight.",
    ]


def test_each_format_says_whether_the_pager_styles_its_emphasis():
    assert formats.REFERENCE.emphasis and not formats.MARKDOWN.emphasis and not formats.TEXT.emphasis
    assert formats.TEXT.render("one two three", 7) == ["one two", "three"]
