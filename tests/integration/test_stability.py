import pytest
from playwright.sync_api import sync_playwright

from magnacoda.browser.stability import wait_for_stable
from magnacoda.config import StabilityConfig

pytestmark = pytest.mark.integration


def test_stability_waits_for_late_dom_mutation(fixture_server):
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.goto(f"{fixture_server}/spa_dynamic.html", wait_until="domcontentloaded")
        # min_wait_ms must span the fixture's 800ms injection delay, otherwise the waiter
        # can correctly-but-uselessly declare quiescence before the mutation ever happens —
        # min_wait_ms is exactly the guard against that.
        report = wait_for_stable(
            page, StabilityConfig(quiet_period_ms=300, min_wait_ms=1000, stability_timeout_ms=5000)
        )
        assert report.settled
        assert report.reason == "quiescent"
        assert page.query_selector("#app img") is not None
        browser.close()


def test_stability_timeout_ceiling_on_perpetual_polling(fixture_server):
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.goto(f"{fixture_server}/polling_widget.html", wait_until="domcontentloaded")
        report = wait_for_stable(
            page, StabilityConfig(quiet_period_ms=300, min_wait_ms=100, stability_timeout_ms=1000)
        )
        assert not report.settled
        assert report.reason == "timeout"
        assert report.elapsed_ms >= 1000
        browser.close()
