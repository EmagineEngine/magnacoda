"""The `readme` command's README viewer (readme.py): sections, terminal rendering, and the command."""

import pytest
from click.testing import CliRunner

from magnacoda import readme
from magnacoda.cli import main
from magnacoda.pager import markdown

SAMPLE = """# *tool*

Intro with a [link to usage](#usage) and `code`.

**Contents**

- [Usage](#usage)
  - [Nested](#nested)

After the contents.

## Usage

```
## not a heading
run --this
```

### Nested

See [https://example.org](https://example.org).
"""


def test_sections_split_at_level_two_headings_but_not_inside_code():
    found = markdown.parse(SAMPLE).sections
    assert [name for name, _ in found] == ["Introduction", "Usage"]
    intro = found[0][1]
    assert "# *tool*" not in intro and "**Contents**" not in intro and "[Nested]" not in intro
    assert intro.startswith("Intro with") and "After the contents." in intro
    assert "## not a heading" in found[1][1]


def test_rendering_keeps_backticks_and_turns_links_into_text():
    lines = markdown.render(markdown.parse(SAMPLE).sections[0][1], 60)
    assert lines[0] == "Intro with a link to usage (section 2) and `code`."
    usage = markdown.render(markdown.parse(SAMPLE).sections[1][1], 60)
    assert usage[0] == "Usage" and "Nested" in usage
    assert "See https://example.org." in usage
    assert "  ## not a heading" in usage and "  run --this" in usage


def test_a_link_to_another_section_gets_its_number():
    sections = [
        (
            "Introduction",
            "### Start\n\nSee [Usage](#usage), [Nested](#nested), [here](#start) and [gone](#gone).",
        ),
        (
            "Usage",
            "## Usage\n\nBack to [the start](#start).\n\n```\n[not a link](#introduction)\n```\n\n### Nested",
        ),
    ]
    first, second = (text for _, text in markdown.number_links(sections))
    assert markdown.render(first, 80)[-1:] == ["See Usage (section 2), Nested (section 2), here and gone."]
    assert (
        "Back to the start (section 1)." in markdown.render(second, 80)
        and "[not a link](#introduction)" in second
    )


def test_section_and_its_number_stay_on_one_line():
    linked = markdown.number_links(
        [("Introduction", "word " * 13 + "[Usage](#usage)."), ("Usage", "## Usage")]
    )
    assert markdown.render(linked[0][1], 80)[-1] == "(section 2)."


def test_a_long_code_line_continues_indented_further():
    lines = markdown.render("```\ncommand " + "word " * 20 + "\n```", 40)
    assert lines[0].startswith("  command") and all(line.startswith("    ") for line in lines[1:])
    assert all(len(line) <= 40 for line in lines)


@pytest.mark.parametrize("width", [40, 60, 79, 120])
@pytest.mark.parametrize(
    "document, first, some",
    [
        (readme.readme_text, "What is magnacoda?", {"Quick start", "Credits and disclaimer"}),
        (readme.manual_text, "Introduction", {"Scan options", "Related tools"}),
    ],
)
def test_the_real_readme_and_manual_fit_every_width(width, document, first, some):
    found = markdown.parse(document()).sections
    names = [name for name, _ in found]
    assert names[0] == first and some <= set(names)
    for name, text in found:
        lines = markdown.render(text, width)
        assert lines and lines[0].strip(), name
        assert all(len(line) <= width for line in lines), (name, max(lines, key=len))


def test_readme_prints_everything_when_there_is_no_pager_in_any_capitalization():
    for word in ("readme", "README", "ReadMe"):
        result = CliRunner().invoke(main, [word])
        assert result.exit_code == 0, word
        assert "Quick start" in result.output and "Credits and disclaimer" in result.output
        assert "**Contents**" not in result.output


@pytest.mark.parametrize("command, source", [("readme", "readme_text"), ("docs", "manual_text")])
def test_without_its_copy_it_says_where_to_read_it(monkeypatch, command, source):
    monkeypatch.setattr(readme, source, lambda: None)
    result = CliRunner().invoke(main, [command])
    assert result.exit_code == 1 and "https://github.com/emagineengine/magnacoda" in result.output


def test_docs_prints_the_manual_or_opens_at_a_named_section():
    whole = CliRunner().invoke(main, ["docs"])
    assert whole.exit_code == 0 and "Scan options" in whole.output and "Related tools" in whole.output
    scan = CliRunner().invoke(main, ["docs", "scan"]).output
    assert "--wait-for-selector" in scan and "Related tools" not in scan
    assert "Scan options" in CliRunner().invoke(main, ["help", "docs"]).output


def test_readme_is_in_the_help_but_not_the_banner():
    assert "readme" in CliRunner().invoke(main, ["help"]).output
    banner = CliRunner().invoke(main, ["shell"], input="exit\n").output
    assert "readme" not in banner.split("Commands:")[1].splitlines()[0]


def test_a_logo_and_tagline_in_html_are_left_out_and_the_title_under_them_still_found():
    logo = '<h1 align="center">\n<picture>\n<source srcset="d.svg">\n<img src="l.svg">\n</picture>\n'
    tagline = '<br><sub>Scan pages.<br>Fix them.</sub>\n</h1>\n<p align="center">Or here.</p>'
    text = logo + tagline + '\n\n# Manual\n\n<p align="center">Kept.</p>\n\n```\n<img src="x">\n```\n'
    document = markdown.parse(text)
    assert document.title == "Manual"
    assert document.sections[0][1] == '<p align="center">Kept.</p>\n\n```\n<img src="x">\n```'


def test_a_picture_is_shown_as_its_file_in_the_terminal():
    lines = markdown.render("- Image 1\n  - ![Screenshot of image 1](images/1.png)", 60)
    assert "Screenshot of image 1: `images/1.png`" in " ".join(lines)


def test_a_loose_list_keeps_a_blank_line_between_its_items():
    assert markdown.render("- one\n- two", 40) == [" • one", " • two"]
    assert markdown.render("- one\n\n- two", 40) == [" • one", "", " • two"]
    assert markdown.render("1. first\n\n2. second", 40) == [" 1 first", "", " 2 second"]


def test_a_tight_list_inside_a_loose_one_stays_tight():
    lines = markdown.render("- one\n\n- two\n  - a\n  - b", 40)
    assert lines == [" • one", "", " • two", "    • a", "    • b"]


def test_heading_lines_are_marked_for_the_pager_only():
    lines = markdown.render("## Usage\n\ntext", 40, mark_code=True)
    assert lines[0].startswith(markdown.HEADING_MARK) and not lines[2].startswith(markdown.HEADING_MARK)
    assert markdown.render("## Usage\n\ntext", 40) == ["Usage", "", "text"]


@pytest.mark.parametrize(
    ("heading", "start"),
    [
        ("## What is *it*?", markdown.HEADING_MARK + "\x1b[1m"),
        ("## Done.", markdown.HEADING_MARK + "\x1b[1m"),
        ("### Ready?", markdown.HEADING_MARK + "\x1b[3m"),
        ("#### Steps", markdown.HEADING_MARK * 2 + "\x1b[3m"),
    ],
)
def test_headings_bold_then_italic_then_marked_dimmer_without_their_asterisks(heading, start):
    line = markdown.render(f"{heading}\n\ntext", 40, mark_code=True)[0]
    assert "*" not in line and line.startswith(start), line
