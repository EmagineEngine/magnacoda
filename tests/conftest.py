from __future__ import annotations

import functools
import shutil
import threading
from collections.abc import Iterator
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from magnacoda.pager import markdown

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "pages"


@pytest.fixture(scope="session")
def fixture_server() -> Iterator[str]:
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(FIXTURES_DIR))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        thread.join()


@pytest.fixture(autouse=True)
def _pages_by_section(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test documents are tiny: they keep their sections unless a test asks for one page."""
    monkeypatch.setattr(markdown, "ONE_PAGE_WORDS", 0)


@pytest.fixture(autouse=True)
def _no_installed_addons(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Installed add-ons are ignored, so core tests give the same results with or without one in the
    environment. Tests that need an add-on use the `addons` fixture in tests/cli/test_plugins.py."""
    from magnacoda import cli, plugins

    monkeypatch.setenv("MAGNACODA_PLUGINS", "off")
    commands = dict(cli.main.commands)
    plugins.reset()
    yield
    plugins.reset()
    cli.main.commands = commands


@pytest.fixture(autouse=True)
def _no_claude_code_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests behave the same whether or not Claude Code happens to be installed on the machine running
    them: `claude` is not found unless a test installs a fake one (see test_claude_code_client.py)."""
    real_which = shutil.which
    monkeypatch.setattr(
        shutil, "which", lambda name, *a, **k: None if name == "claude" else real_which(name, *a, **k)
    )


@pytest.fixture(autouse=True)
def _isolated_config_dir(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test gets its own empty per-user config folder, so nothing (history, preferences, saved keys)
    is ever read from or written to the developer's real ~/.config/magnacoda."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path_factory.mktemp("config")))
    monkeypatch.delenv("APPDATA", raising=False)


@pytest.fixture(autouse=True)
def _screen_reader_offer_already_made(_isolated_config_dir: None) -> None:
    """The one-time screen-reader offer counts as made, so no test (pty ones included) is asked
    because a screen reader runs on the test machine. Tests of the offer remove the file."""
    from magnacoda import screenreader
    from magnacoda.userdir import write_private

    write_private(screenreader.state_path(), '{"asked": true}\n')


@pytest.fixture(autouse=True)
def _no_news_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test reaches the network: the daily checks are switched off, and any request (even one the
    `update` command forces) fails as if offline. Tests that need answers pass their own fetch or
    replace news._fetch."""
    from magnacoda import news

    def offline(url: str, max_bytes: int) -> bytes:
        raise OSError("tests don't use the network")

    monkeypatch.setenv("MAGNACODA_NEWS", "off")
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setattr(news, "_fetch", offline)


@pytest.fixture(autouse=True)
def _no_name_lookups(monkeypatch: pytest.MonkeyPatch) -> None:
    """A one-word address is looked up as a computer name (addresses.resolves); tests never do real
    lookups: no such computer exists unless a test says otherwise."""
    from magnacoda import addresses

    monkeypatch.setattr(addresses, "resolves", lambda host, timeout=0: False)


@pytest.fixture(autouse=True)
def _run_in_a_temporary_folder(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every test runs from its own empty folder, so a scan that saves reports (the wizard now saves by
    default) never writes into the project, where the developer's real magnacoda-scans folder is."""
    monkeypatch.chdir(tmp_path_factory.mktemp("cwd"))


@pytest.fixture(autouse=True)
def _short_motion_watch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Scans in tests watch for moving content for 1.5 seconds, not 6: the test pages move at once."""
    from magnacoda.browser import media

    monkeypatch.setattr(media, "MOTION_MS", 1500)


@pytest.fixture(autouse=True)
def _no_dark_pass_with_a_made_up_scan(monkeypatch: pytest.MonkeyPatch) -> None:
    """A test that replaces the scan with a made-up report has no page for the dark-mode pass to load:
    it then finds the page looks the same in dark mode. Real scans run it for real."""
    from magnacoda import cli, orchestrator

    real = cli.run_dark_pass

    def dark_pass(config, light_colors):  # type: ignore[no-untyped-def]
        if cli.run_scan is not orchestrator.run_scan:
            return None
        return real(config, light_colors)

    monkeypatch.setattr(cli, "run_dark_pass", dark_pass)


@pytest.fixture(autouse=True)
def _shortcuts_in_tmp(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Shortcuts go to a temporary home's menu and desktop, never the real ones."""
    import sys

    from magnacoda import shortcuts

    home = tmp_path_factory.mktemp("home")
    folders = shortcuts._pyshortcuts().get_folders()
    fake = type(folders)(str(home), str(home / "Desktop"), str(home / ".local" / "share" / "applications"))
    pyshortcuts = shortcuts._pyshortcuts()
    monkeypatch.setattr(pyshortcuts, "get_folders", lambda public=False: fake)
    monkeypatch.setattr(
        sys.modules[pyshortcuts.make_shortcut.__module__], "get_folders", lambda public=False: fake
    )
    return home


@pytest.fixture(autouse=True)
def _scans_in_the_current_folder(monkeypatch: pytest.MonkeyPatch) -> None:
    """Scans go to magnacoda-scans in the folder a test is in (most tests change to a temporary one),
    never to the real Documents."""
    import platformdirs

    monkeypatch.setattr(platformdirs, "user_documents_dir", lambda: str(Path.cwd()))
