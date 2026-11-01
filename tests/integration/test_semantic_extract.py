import pytest
from playwright.sync_api import sync_playwright

from magnacoda.ai.semantic import extract_semantic_context

pytestmark = pytest.mark.integration


def test_the_ai_is_told_what_screen_readers_read_what_shows_and_which_links_go_to_the_same_place(
    fixture_server,
):
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.goto(f"{fixture_server}/semantic.html")
        extract = extract_semantic_context(page)
        browser.close()
    assert [h["name"] for h in extract["headings"]] == ["Acme", "Plans"]
    assert [image["shown"] for image in extract["images"]] == [True, False]
    assert [(link["name"], link["goes_to"]) for link in extract["links"]] == [
        ("Privacy", 1),
        ("Privacy", 1),
        ("Terms of use", 2),
    ]
    assert "/privacy" not in str(extract["links"])
    assert len({link["selector"] for link in extract["links"]}) == 3
