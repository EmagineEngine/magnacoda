"""Rechecking a saved scan's fixes (recheck.py): only its Fix items are tested again, and the saved
checklist is updated in place, from the shell command and from the review page's button."""

import functools
import json
import shutil
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from magnacoda import recheck, review_page, review_server, saved_reports, ticks
from magnacoda.config import ScanConfig
from magnacoda.orchestrator import run_scan
from magnacoda.report.json_export import write_json
from magnacoda.report.markdown_export import write_markdown
from tests.conftest import FIXTURES_DIR

pytestmark = pytest.mark.integration


@pytest.fixture
def site(tmp_path):
    """The test page in a folder of its own, so a test can change it between the scan and the recheck."""
    folder = tmp_path / "site"
    folder.mkdir()
    shutil.copy(FIXTURES_DIR / "recheck.html", folder / "page.html")
    shutil.copy(FIXTURES_DIR / "red.png", folder / "red.png")

    class Quiet(SimpleHTTPRequestHandler):
        def log_message(self, format, *args):  # noqa: A002
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(folder)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield folder, f"http://127.0.0.1:{server.server_address[1]}/page.html"
    server.shutdown()


def _saved_scan(tmp_path, url) -> Path:
    scan = tmp_path / "magnacoda-scans" / "127.0.0.1_20261012-090000"
    scan.mkdir(parents=True)
    report = run_scan(ScanConfig(url=url, quick=True))
    write_markdown(report, scan / "checklist.md", scan / "images")
    write_json(report, scan / "results.json")
    return scan


def _fix_boxes(scan: Path) -> dict[str, bool]:
    return {k: v for k, v in ticks.read_ticks(scan / "checklist.md").items() if "-fix-" in k}


def test_fixed_problems_are_ticked_and_the_others_unticked_with_a_note(site, tmp_path):
    folder, url = site
    scan = _saved_scan(tmp_path, url)
    boxes = _fix_boxes(scan)
    assert len(boxes) == 3  # no alt text, too little contrast, no focus ring
    contrast = next(k for k in boxes if "color-contrast" in k)
    ticks.set_tick(scan / "checklist.md", contrast, True)  # someone thought they'd fixed it
    page = folder / "page.html"
    page.write_text(page.read_text().replace('id="photo"', 'id="photo" alt="A red square"'))
    page.write_text(page.read_text().replace('<p><a href="#x" id="ring">No ring</a></p>', ""))
    outcome = recheck.recheck_variant(scan / "checklist.md", scan / "results.json")
    assert (outcome.fixed, outcome.failing, outcome.not_found, outcome.error) == (1, 1, 1, None)
    now = _fix_boxes(scan)
    alt = next(k for k in now if "image-alt" in k)
    assert now[alt] is True and now[contrast] is False  # confirmed; and still failing, so unticked
    text = (scan / "checklist.md").read_text()
    assert "*(fixed, confirmed by recheck on " in text and "*(still failing on recheck, " in text
    assert "*(not found on recheck, " in text and "the page has changed; scan again" in text
    assert json.loads((scan / "results.json").read_text())["rechecked"]["fixed"] == 1
    # A second recheck replaces the notes rather than adding more.
    recheck.recheck_variant(scan / "checklist.md", scan / "results.json")
    again = (scan / "checklist.md").read_text()
    assert again.count("by recheck on ") + again.count("on recheck, ") == 3


def test_the_review_pages_button_rechecks_and_shows_the_outcome(site, tmp_path):
    from playwright.sync_api import sync_playwright

    folder, url = site
    scan_folder = _saved_scan(tmp_path, url)
    page_file = folder / "page.html"
    page_file.write_text(page_file.read_text().replace('id="photo"', 'id="photo" alt="A red square"'))
    (scan,) = saved_reports.scans(scan_folder.parent)
    variants = [review_page.Variant("", r.path, scan_folder / "results.json") for r in scan.reports]
    server = review_server.ReviewServer(scan_folder, variants)
    server.start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(server.url)
            page.get_by_role("button", name="Recheck fixes").click()
            page.wait_for_function(
                "() => document.getElementById('status').textContent.startsWith('Rechecked')", timeout=60_000
            )
            assert page.locator("#status").text_content() == "Rechecked: 1 of 3 problems fixed; 2 still fail."
            browser.close()
    finally:
        server.stop()
    assert sum(_fix_boxes(scan_folder).values()) == 1


@pytest.fixture
def private_site(tmp_path):
    """The test page behind a login: without the session cookie, a login page instead."""
    folder = tmp_path / "private"
    folder.mkdir()
    shutil.copy(FIXTURES_DIR / "recheck.html", folder / "page.html")
    shutil.copy(FIXTURES_DIR / "red.png", folder / "red.png")

    class Private(SimpleHTTPRequestHandler):
        def log_message(self, format, *args):  # noqa: A002
            pass

        def do_GET(self):  # noqa: N802
            if self.path.startswith("/page.html") and "session=ok" not in (self.headers.get("Cookie") or ""):
                body = (
                    b'<!doctype html><html lang="en"><title>Log in</title><main><h1>Log in</h1></main></html>'
                )
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(body)
                return
            super().do_GET()

    server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Private, directory=str(folder)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    login = tmp_path / "login.json"
    login.write_text(
        json.dumps(
            {
                "cookies": [
                    {"name": "session", "value": "ok", "domain": "127.0.0.1", "path": "/", "expires": -1,
                     "httpOnly": False, "secure": False, "sameSite": "Lax"}
                ],
                "origins": [],
            }
        )
    )  # fmt: skip
    yield folder, f"http://127.0.0.1:{port}/page.html", login
    server.shutdown()


def test_a_page_behind_a_login_is_rechecked_with_the_scans_saved_login(private_site, tmp_path):
    folder, url, login = private_site
    scan = tmp_path / "magnacoda-scans" / "127.0.0.1_20261012-100000"
    scan.mkdir(parents=True)
    report = run_scan(ScanConfig(url=url, quick=True, storage_state=login))
    assert report.meta.storage_state == str(login.resolve())  # the path, not the contents
    assert "session" not in (report.model_dump_json().split('"storage_state"')[0])
    write_markdown(report, scan / "checklist.md", scan / "images")
    write_json(report, scan / "results.json")
    assert len(_fix_boxes(scan)) == 3  # the real page was scanned, not the login page
    page = folder / "page.html"
    page.write_text(page.read_text().replace('id="photo"', 'id="photo" alt="A red square"'))
    outcome = recheck.recheck_variant(scan / "checklist.md", scan / "results.json")
    assert (outcome.fixed, outcome.failing, outcome.error) == (1, 2, None)  # logged in with the same file
    login.unlink()
    gone = recheck.recheck_variant(scan / "checklist.md", scan / "results.json")
    assert gone.error and "is gone: give one with --storage-state" in gone.error
    given = recheck.recheck_variant(
        scan / "checklist.md", scan / "results.json", login=recheck.Login(cookies=[("session", "ok")])
    )
    assert (given.fixed, given.failing, given.error) == (1, 2, None)  # a cookie given for this recheck
