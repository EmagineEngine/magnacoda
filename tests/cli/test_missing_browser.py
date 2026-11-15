import dataclasses

import pytest
from click.testing import CliRunner

from magnacoda import cli, estimate, preferences
from magnacoda.browser import redirects
from magnacoda.cli import main
from magnacoda.exceptions import BrowserNotInstalledError
from tests.cli.test_estimate import PROBE
from tests.cli.test_screen import _fake_run

MISSING = "chromium browser binary not found. Run `magnacoda setup` first."


@pytest.fixture
def no_browser(monkeypatch, tmp_path):
    def scan(config, *, consent_given=False):
        raise BrowserNotInstalledError(MISSING)

    monkeypatch.setattr(cli, "run_scan", scan)
    monkeypatch.chdir(tmp_path)
    downloads = []
    monkeypatch.setattr(cli, "_install_chromium", lambda: downloads.append(1) or 0)
    return downloads


def _scan(*args, answer=""):
    return CliRunner().invoke(main, ["scan", "http://example.test", *args], input=answer)


def test_a_missing_browser_is_offered_in_a_terminal_and_downloaded_on_yes(monkeypatch, no_browser):
    monkeypatch.setattr(cli, "_is_interactive", lambda: True)

    result = _scan(answer="defaults\ny\n")

    assert no_browser == [1]
    assert "Run the scan again to start it." in result.output
    assert result.exit_code == 2


def test_declining_the_download_shows_the_error(monkeypatch, no_browser):
    monkeypatch.setattr(cli, "_is_interactive", lambda: True)

    result = _scan(answer="defaults\nn\n")

    assert no_browser == []
    assert MISSING in result.output
    assert result.exit_code == 2


def test_a_script_is_never_asked_and_downloads_nothing(monkeypatch, no_browser):
    monkeypatch.setattr(cli, "_is_interactive", lambda: False)

    result = _scan()

    assert no_browser == []
    assert MISSING in result.output
    assert result.exit_code == 2


def _estimating(monkeypatch, downloads, answer):
    """A scan whose estimate step finds no browser until it is downloaded."""
    seen: list = []

    def probe(config):
        if not downloads:
            raise BrowserNotInstalledError(MISSING)
        return PROBE

    load = preferences.load
    monkeypatch.setattr(preferences, "load", lambda: dataclasses.replace(load(), estimate=True))
    monkeypatch.setattr(estimate, "probe_page", probe)
    monkeypatch.setattr(cli, "run_scan", _fake_run(seen))
    monkeypatch.setattr(cli, "_is_interactive", lambda: True)
    monkeypatch.setattr(redirects, "check_address", lambda url, **kw: None)
    return _scan(answer=answer), seen


def test_the_estimate_offers_the_download_and_then_goes_on_to_the_scan(monkeypatch, no_browser):
    result, seen = _estimating(monkeypatch, no_browser, "defaults\ny\n\n")  # download, then start

    assert no_browser == [1] and seen
    assert "Couldn't check the page" not in result.output and MISSING not in result.output
    assert result.output.index("Download it now?") < result.output.index("Estimated time")


def test_declining_at_the_estimate_shows_the_error_and_asks_nothing_more(monkeypatch, no_browser):
    result, seen = _estimating(monkeypatch, no_browser, "defaults\nn\n")

    assert no_browser == [] and seen == []
    assert MISSING in result.output and "Start the scan?" not in result.output
    assert result.exit_code == 2
