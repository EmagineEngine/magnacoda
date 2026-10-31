"""Images in the checklist: each one is a page element, shown with its screenshot and text alternative,
and its own checks underneath (markdown_export)."""

from magnacoda.findings.models import PageImage
from magnacoda.report.markdown_export import to_markdown, write_markdown
from tests.report.test_markdown import _entry, _report


def _with_images():
    report = _report()
    report.checklist.append(_entry("1.1.1", "automated", "passed", follow_up="read each alt text"))
    report.checklist.append(_entry("1.4.5", "relevant", reason="found 4 images"))
    report.images = [
        PageImage(
            selector="#team",
            kind="img",
            alt="Our team",
            src="https://x.test/a.png",
            width=40,
            height=30,
            png=b"\x89PNG1",
        ),
        PageImage(selector="img.logo", kind="img", alt=None, png=b"\x89PNG2"),
        PageImage(selector="img.spacer", kind="img", alt=""),
        PageImage(selector="#chart", kind="svg", label="Sales *chart*", png=b"\x89PNG3"),
    ]
    report.images_total = 6
    return report


def _element(md: str, selector: str) -> str:
    start = md.index(f"`{selector}`")
    return md[start : md.index("\n### ", start) if "\n### " in md[start:] else len(md)]


def test_each_image_is_an_element_with_its_screenshot_text_alternative_and_checks(tmp_path):
    report = _with_images()
    write_markdown(report, tmp_path / "checklist.md", tmp_path / "images")
    md = (tmp_path / "checklist.md").read_text()
    assert "Screenshots show the first 4 of the page's 6 images." in md
    # The four images have the same checks: one stack, each with its own box, picture and alt text.
    assert "Check these 4 elements, all in the same way" in md
    team = _element(md, "#team")
    assert team.startswith('`#team` ("Our team") <!-- id:e-')
    assert team.split("\n")[1] == "  - ![Screenshot of image 1](images/1.png) (40×30)"
    assert '  - alt text: "Our team"' in team and "  - source: `https://x.test/a.png`" in team
    assert "- **Check** **[1.1.1 Title 1.1.1]" in md and "- **Check** **[1.4.5 Title 1.4.5]" in md
    logo = _element(md, "img.logo")
    assert '  - alt text: **none**. Is it purely decorative? **Yes:** add `alt=""`. **No:**' in logo
    spacer = _element(md, "img.spacer")
    assert '  - alt text: marked decorative (`alt=""`). Is it purely decorative? **No:**' in spacer
    assert "(no screenshot" in spacer
    chart = _element(md, "#chart")
    assert '  - text alternative: see below\n  - named by aria-label or title: "Sales \\*chart\\*"' in chart


def test_an_svg_with_no_text_alternative_asks_whether_it_is_decorative():
    report = _with_images()
    report.images[3] = report.images[3].model_copy(update={"label": None})
    md = to_markdown(report)
    assert 'add `aria-hidden="true"`' in md and 'add `role="img"`' in md  # both answers


def test_screenshots_are_saved_and_their_file_names_kept_for_the_json_report(tmp_path):
    report = _with_images()
    write_markdown(report, tmp_path / "checklist.dark.md", tmp_path / "images", prefix="dark-")
    assert (tmp_path / "images" / "dark-1.png").read_bytes() == b"\x89PNG1"
    assert (tmp_path / "images" / "dark-4.png").exists() and not (tmp_path / "images" / "dark-3.png").exists()
    assert [image.file for image in report.images] == [
        "images/dark-1.png",
        "images/dark-2.png",
        None,
        "images/dark-4.png",
    ]


def test_with_every_image_checked_one_by_one_the_criteria_have_no_second_box():
    md = to_markdown(_with_images())
    assert "- **[1.1.1 Title 1.1.1]" in md
    assert "a person still needs to judge each one: see [Page elements](#page-elements-" in md
    assert "- [ ] **[1.1.1 Title 1.1.1]" not in md  # no separate box to tick for the whole criterion


def test_without_images_there_are_no_image_items():
    md = to_markdown(_report())
    assert "Screenshot of image" not in md and "Screenshots show" not in md
