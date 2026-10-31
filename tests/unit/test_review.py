"""The browser review: the page (review_page.py), the local server (review_server.py), and how
`reports` lists scans and chooses between the browser and the terminal."""

import http.client
import json
from pathlib import Path

import click
import pytest
from click.testing import CliRunner

from magnacoda import cli, preferences, review_page, review_server, saved_reports, ticks
from magnacoda.cli import main
from magnacoda.pager import browser
from magnacoda.report.markdown_export import to_markdown
from tests.report.test_markdown import _report


def _scan_folder(tmp_path: Path, labels=("",)) -> Path:
    folder = tmp_path / "magnacoda-scans" / "example.test_20261011-120000"
    (folder / "images").mkdir(parents=True)
    (folder / "images" / "1.png").write_bytes(b"\x89PNG fake")
    (tmp_path / "secret.txt").write_text("not for the browser")
    for label in labels:
        suffix = f".{label}" if label else ""
        report = _report()
        (folder / f"checklist{suffix}.md").write_text(to_markdown(report))
        (folder / f"results{suffix}.json").write_text(report.model_dump_json())
    return folder


def _variants(folder: Path) -> list[review_page.Variant]:
    scan = saved_reports.scans(folder.parent)[0]
    return [
        review_page.Variant(
            scan.variant_label(r),
            r.path,
            r.path.with_name("results" + r.path.name[len("checklist") : -3] + ".json"),
        )
        for r in scan.reports
    ]


# The page


def test_every_tickable_line_becomes_a_labelled_checkbox_and_page_text_is_escaped():
    report = _report()
    report.findings[0] = report.findings[0].model_copy(update={"description": "<script>alert(1)</script>"})
    page_html = review_page.checklist_html(to_markdown(report))
    assert "<script>" not in page_html and "&lt;script&gt;" in page_html
    boxes = page_html.count('type="checkbox"')
    assert boxes == to_markdown(report).count("<!-- id:")
    for box_id in [part.split('"')[0] for part in page_html.split('aria-labelledby="t-')[1:]]:
        assert f'<span id="t-{box_id}">' in page_html  # each checkbox has its label
    assert "Contents" not in page_html and "<h1>" not in page_html  # the page has its own
    assert 'target="_blank" rel="noopener noreferrer">' in page_html and "(opens in a new tab)" in page_html


def test_the_checklists_own_links_to_its_sections_work_on_the_page():
    md = "## Page elements (2)\n\nText.\n\n## Passed (1)\n\n- see [Page elements](#page-elements-2)\n"
    page_html = review_page.checklist_html(md)
    assert '<h3 id="page-elements-2">Page elements (2)</h3>' in page_html
    assert '<a href="#page-elements-2">Page elements</a>' in page_html  # stays on the page


def test_the_page_has_one_h1_the_variant_links_progress_and_the_report(tmp_path):
    variants = _variants(_scan_folder(tmp_path, ("light", "dark")))
    dark = next(v for v in variants if v.label == "dark")
    html_text = review_page.page(variants, dark)
    visible = html_text.split("<script>")[0]  # the script holds the "Done" page's own heading
    assert visible.count("<h1") == 1 and "Accessibility review: http://example.test (Dark)" in visible
    # Findings first and open, the checklist after and closed; each line says what's inside.
    findings, checklist_part = visible.index('id="findings-part" open'), visible.index('id="checklist-part">')
    assert (
        findings < checklist_part
        and '<span class="count">1 problem on 1 element (1 serious)</span>' in visible
    )
    assert '<a href="#top">Back to top</a>' in visible and '<h1 id="top">' in visible
    assert (
        '<nav aria-label="Variant"' in html_text and 'href="?variant=dark" aria-current="page"' in html_text
    )
    assert (
        'id="progress">1 of 8 checked' in html_text
    )  # the passed criterion comes ticked and '<h2 id="findings">Findings</h2>' in html_text
    assert "Problems found, by severity" in html_text and "{{" not in html_text


# The server


class _Session:
    def __init__(self, folder: Path) -> None:
        self.server = review_server.ReviewServer(folder, _variants(folder))
        self.server.start()

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=5)
        headers = {"Host": f"127.0.0.1:{self.server.port}", **(headers or {})}
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        return response.status, response.read()


@pytest.fixture
def session(tmp_path):
    folder = _scan_folder(tmp_path)
    running = _Session(folder)
    yield running, folder
    running.server.stop()


def test_the_page_and_its_images_are_served_only_with_the_secret_token(session):
    running, _ = session
    token = running.server.token
    assert running.request("GET", f"/{token}/")[0] == 200
    assert running.request("GET", "/")[0] == 404 and running.request("GET", "/wrong-token/")[0] == 404
    assert running.request("GET", f"/{token}/images/1.png") == (200, b"\x89PNG fake")
    for sneaky in (
        "images/../../../secret.txt",
        "images/%2e%2e/results.json",
        "results.json",
        "images/none.png",
    ):
        assert running.request("GET", f"/{token}/{sneaky}")[0] == 404, sneaky


def test_other_host_names_and_other_websites_are_refused(session):
    running, _ = session
    token = running.server.token
    assert running.request("GET", f"/{token}/", headers={"Host": "evil.example"})[0] == 403
    tick = json.dumps({"id": "c-3.3.8", "checked": True})
    headers = {"Content-Type": "application/json", "Origin": "https://evil.example"}
    assert running.request("POST", f"/{token}/tick", tick, headers)[0] == 403


def test_ticking_in_the_page_saves_to_the_checklist_and_the_json(session):
    running, folder = session
    token = running.server.token
    body = json.dumps({"id": "c-3.3.8", "checked": True, "variant": ""})
    headers = {"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{running.server.port}"}
    assert running.request("POST", f"/{token}/tick", body, headers)[0] == 204
    assert ticks.read_ticks(folder / "checklist.md")["c-3.3.8"] is True
    assert "c-3.3.8" in json.loads((folder / "results.json").read_text())["ticked"]
    bad = json.dumps({"id": "c-9.9.9", "checked": True})
    assert running.request("POST", f"/{token}/tick", bad, headers)[0] == 400


def test_done_stops_the_review(session):
    running, _ = session
    assert running.request("POST", f"/{running.server.token}/done")[0] == 200
    assert running.server.wait() is False  # returns at once: Done already stopped it


def test_ctrl_c_stops_the_review_and_says_so(session, monkeypatch):
    running, _ = session

    def interrupted(timeout):
        raise KeyboardInterrupt

    monkeypatch.setattr(running.server._stopped, "wait", interrupted)
    assert running.server.wait() is True  # the caller then starts its message on a new line, past ^C


# Opening the browser


def test_a_new_window_starts_the_default_browser_with_its_new_window_option(monkeypatch):
    launched, opened = [], []
    monkeypatch.setattr(browser, "_default_browser_program", lambda: "/usr/bin/brave-browser-stable")
    monkeypatch.setattr(browser.webbrowser, "open", lambda url, new=0: opened.append(url))
    monkeypatch.setattr(browser, "_browser_command", lambda url: None)
    browser.open_in_browser("http://127.0.0.1:1/t/", "new", launch=launched.append)
    assert (
        launched == [["/usr/bin/brave-browser-stable", "--new-window", "http://127.0.0.1:1/t/"]]
        and not opened
    )
    monkeypatch.setattr(browser, "_default_browser_program", lambda: "/usr/bin/some-other-browser")
    browser.open_in_browser("http://127.0.0.1:1/t/", "new", launch=launched.append)
    browser.open_in_browser("http://127.0.0.1:1/t/", "tab", launch=launched.append)
    assert len(launched) == 1 and len(opened) == 2  # unknown browser, and tab: the usual way


def test_the_browser_is_started_with_its_output_thrown_away(monkeypatch):
    started = []
    monkeypatch.setattr(browser.subprocess, "Popen", lambda args, **kwargs: started.append((args, kwargs)))
    monkeypatch.setattr(browser.webbrowser, "get", lambda: browser.webbrowser.BackgroundBrowser("xdg-open"))
    browser.open_in_browser("http://127.0.0.1:1/t/")
    ((args, kwargs),) = started
    assert args == ["xdg-open", "http://127.0.0.1:1/t/"]
    assert kwargs["stdout"] == kwargs["stderr"] == browser.subprocess.DEVNULL


def test_the_window_preference_is_read_from_the_review_section():
    assert preferences.load().review_window == "tab"
    path = preferences.preferences_path()
    path.write_text(path.read_text().replace("window = tab", "window = new"))
    assert preferences.load().review_window == "new"


# The report list


def test_a_scan_with_several_variants_is_listed_once(tmp_path):
    folder = _scan_folder(tmp_path, ("light", "dark"))
    (scan,) = saved_reports.scans(folder.parent)
    assert [scan.variant_label(r) for r in scan.reports] == ["light", "dark"]
    assert scan.line().startswith("example.test  2026-10-11 12:00  (light; dark)  - 2 of 16 checked")


def test_reports_opens_the_browser_when_it_can_and_the_terminal_otherwise(tmp_path, monkeypatch):
    _scan_folder(tmp_path)
    monkeypatch.chdir(tmp_path)
    reviewed = []
    monkeypatch.setattr(cli, "_review_in_browser", lambda scan: reviewed.append(scan) or True)
    out = CliRunner().invoke(main, ["review"], input="1\n\n").output
    assert len(reviewed) == 1 and "Page elements" not in out
    monkeypatch.setattr(cli, "_review_in_browser", lambda scan: False)  # no browser here
    out = CliRunner().invoke(main, ["review"], input="1\n\n").output
    assert "Page elements" in out  # shown in the help viewer instead
    monkeypatch.setattr(cli, "_review_in_browser", lambda scan: reviewed.append(scan) or True)
    out = CliRunner().invoke(main, ["review", "--no-browser"], input="1\n\n").output
    assert len(reviewed) == 1 and "Page elements" in out


def test_without_a_display_or_with_an_old_report_there_is_no_browser_review(tmp_path, monkeypatch):
    folder = _scan_folder(tmp_path)
    (scan,) = saved_reports.scans(folder.parent)
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setattr(browser.sys, "platform", "linux")
    assert browser.browser_available() is False and cli._review_in_browser(scan) is False
    old = tmp_path / "old"
    old.mkdir()
    (old / "site_20261001-090000.md").write_text("# Old\n\n- [ ] **[1.1.1 X](https://x)** (A) - a\n")
    (legacy,) = saved_reports.scans(old)
    assert legacy.folder is None and cli._review_in_browser(legacy) is False


def test_a_fix_in_the_page_shows_what_is_between_backticks_as_code_and_escapes_the_rest():
    assert review_page._with_code('Add `alt=""` to <img> & `<b>`') == (
        "Add <code>alt=&quot;&quot;</code> to &lt;img&gt; &amp; <code>&lt;b&gt;</code>"
    )


def test_the_page_ends_with_a_footer_naming_magnacoda_and_its_website(tmp_path):
    (tmp_path / "checklist.md").write_text(to_markdown(_report()), encoding="utf-8")
    variant = review_page.Variant("", tmp_path / "checklist.md", None)
    page = review_page.page([variant], variant)
    assert (
        'Accessibility scan by <em>magnacoda</em>: <a href="https://magnacoda.dev/">https://magnacoda.dev/</a>'
        in page.split("</main>", 1)[1].split("</footer>", 1)[0]
    )
    assert page.count("Accessibility scan by") == 1  # the checklist's own footer is left out


def test_review_asks_again_without_listing_again_until_q_or_enter_cancels(tmp_path, monkeypatch):
    _scan_folder(tmp_path)
    monkeypatch.chdir(tmp_path)
    reviewed = []
    monkeypatch.setattr(cli, "_review_in_browser", lambda scan: reviewed.append(scan) or True)
    for cancel in ("", "q"):
        reviewed.clear()
        out = CliRunner().invoke(main, ["review"], input=f"1\n1\n{cancel}\n").output
        assert len(reviewed) == 2 and out.count("Saved scans in") == 1 and out.rstrip().endswith("Cancelled.")
        assert out.count("Type a number to review that scan, or press Enter to cancel") == 1
        assert out.count("Type a number to review another scan, or press Enter to cancel") == 2


def _shell_after_a_scan(tmp_path, monkeypatch, between: str = "") -> tuple[str, list]:
    """The shell: a scan of example.test (faked), maybe another command, then review."""
    folder = _scan_folder(tmp_path)
    monkeypatch.chdir(tmp_path)
    reviewed: list = []
    monkeypatch.setattr(cli, "_review_in_browser", lambda scan: reviewed.append(scan.folder) or True)

    def fake_scan(**kwargs):
        click.get_current_context().obj["scanned"] = folder.relative_to(tmp_path)

    monkeypatch.setattr(cli.scan_cmd, "callback", fake_scan)
    lines = ["scan example.test", *([between] if between else []), "review", "q", "exit"]
    out = CliRunner().invoke(main, ["shell"], input="\n".join(lines) + "\n").output
    return out, reviewed


def test_review_right_after_a_scan_opens_that_scan_then_the_prompt(tmp_path, monkeypatch):
    out, reviewed = _shell_after_a_scan(tmp_path, monkeypatch)
    assert [f.name for f in reviewed] == ["example.test_20261011-120000"]
    assert "Saved scans in" not in out  # no list


def test_review_after_another_command_lists_the_scans(tmp_path, monkeypatch):
    out, reviewed = _shell_after_a_scan(tmp_path, monkeypatch, between="--version")
    assert reviewed == [] and "Saved scans in" in out


def test_review_right_after_a_scan_stays_on_the_same_page(tmp_path, monkeypatch):
    from rich.console import Console

    monkeypatch.setattr(Console, "is_terminal", property(lambda self: True))
    out, reviewed = _shell_after_a_scan(tmp_path, monkeypatch)
    assert reviewed and out.count("\x1b[H") == 1  # only the shell's own start feeds a page
