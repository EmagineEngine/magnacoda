import re
from pathlib import Path

import pytest

from magnacoda import readme
from magnacoda.help_sections import help_file_text
from magnacoda.pager import find_section, markdown

ROOT = Path(__file__).parent.parent.parent
DOCUMENTS = ["README.md", "docs/manual.md"]


def _text(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def _slug(heading: str) -> str:
    """GitHub/GitLab-style heading anchor."""
    return re.sub(r"\s", "-", re.sub(r"[^\w\s-]", "", heading.strip().lower()))


def _headings(text: str, max_level: int = 6) -> list[tuple[int, str]]:
    found, in_code = [], False
    for line in text.splitlines():
        if line.startswith("```"):
            in_code = not in_code
        match = re.match(rf"^(#{{2,{max_level}}}) (.+)$", line)
        if match and not in_code:
            found.append((len(match.group(1)), match.group(2)))
    return found


def _contents_block(text: str) -> str:
    start = text.index("**Contents**")
    return text[start : text.index("\n## ", start)]


@pytest.mark.parametrize("name", DOCUMENTS)
def test_contents_lists_every_heading_from_the_second_to_the_fourth_level_in_order(name):
    """`make toc` writes it (scripts/readme_toc.py)."""
    text = _text(name)
    listed = re.findall(r"^( *)- (?:\*\*)?\[(.+?)\]\(#(.+?)\)(?:\*\*)?$", _contents_block(text), re.M)
    assert [(title, slug) for _, title, slug in listed] == [(t, _slug(t)) for _, t in _headings(text, 4)]
    depth = {title: len(indent) for indent, title, _ in listed}
    for level, title in _headings(text, 4):
        assert depth[title] == 2 * (level - 2)  # each level indented under the one above


@pytest.mark.parametrize("name", DOCUMENTS)
def test_every_link_within_the_repository_points_at_a_real_file_and_heading(name):
    """Relative, so they work on GitHub and in any copy of the repository."""
    text = _text(name)
    links = re.findall(r"\]\(([^)\s]+)\)", text)
    assert links, "expected links"
    for target in links:
        if target.startswith(("http://", "https://")):
            assert "github.com/emagineengine/magnacoda/blob/" not in target, target
            continue
        path, _, anchor = target.partition("#")
        linked = (ROOT / name).parent / path if path else ROOT / name
        assert linked.is_file(), target
        if anchor:
            assert anchor in {_slug(t) for _, t in _headings(linked.read_text(encoding="utf-8"))}, target


def test_the_wizard_has_its_own_section_and_is_mentioned_in_the_quick_start():
    text = _text("README.md")
    assert "Guided wizard" in [title for _, title in _headings(text, 3)]
    quick_start = text[text.index("## Quick start") : text.index("## Guided wizard")]
    assert "magnacoda wizard" in quick_start and "(#guided-wizard)" in quick_start


def test_the_viewer_gets_full_links_for_relative_ones():
    manual = readme.manual_text()
    assert "(https://github.com/emagineengine/magnacoda/blob/main/README.md#help)" in manual
    assert "](../" not in manual and "](#scan-options)" in manual


@pytest.mark.parametrize("text", [help_file_text, lambda: _text("README.md")], ids=["help", "README"])
def test_every_docs_pointer_opens_a_section_of_the_manual(text):
    names = [name for name, _ in markdown.parse(readme.manual_text()).sections]
    pointers = set(re.findall(r"`docs ([a-z ]+)`|\(docs ([a-z ]+)\)", text()))
    assert pointers
    for pointer in {a or b for a, b in pointers}:
        index, _ = find_section(names, pointer)
        assert index is not None, pointer
