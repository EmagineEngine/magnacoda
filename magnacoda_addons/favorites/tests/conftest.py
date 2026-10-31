"""Favorites' tests, set up as any add-on's tests should be: they never touch the user's real files or
the network, and run with add-ons on."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from magnacoda import cli, plugins


@pytest.fixture(autouse=True)
def _isolated(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    """Each test gets its own empty settings folder and working folder, so the user's real favorites,
    history, preferences and saved scans are never read or written."""
    import platformdirs

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path_factory.mktemp("config")))
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.chdir(tmp_path_factory.mktemp("cwd"))
    monkeypatch.setattr(platformdirs, "user_documents_dir", lambda: str(Path.cwd()))


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    """No network, no name lookups, and no Claude Code, whatever is installed on the machine."""
    from magnacoda import addresses, news

    def offline(url: str, max_bytes: int) -> bytes:
        raise OSError("tests don't use the network")

    monkeypatch.setenv("MAGNACODA_NEWS", "off")
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setattr(news, "_fetch", offline)
    monkeypatch.setattr(addresses, "resolves", lambda host, timeout=0: False)
    real_which = shutil.which
    monkeypatch.setattr(
        shutil, "which", lambda name, *a, **k: None if name == "claude" else real_which(name, *a, **k)
    )


@pytest.fixture(autouse=True)
def _no_dark_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    """These tests replace the scan with a made-up report, so there is no page for the dark-mode pass."""
    monkeypatch.setattr(cli, "run_dark_pass", lambda config, light_colors: None)


@pytest.fixture(autouse=True)
def _addons_on(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Turns add-ons back on (the root conftest turns them off), so favorites is found through its
    real entry point, as in a normal install."""
    monkeypatch.delenv("MAGNACODA_PLUGINS", raising=False)
    commands = dict(cli.main.commands)
    plugins.reset()
    yield
    plugins.reset()
    cli.main.commands = commands


@pytest.fixture(autouse=True)
def _no_page_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """Running a favorite doesn't check the page to estimate the time (`estimate = off`), except in the
    test of that, which turns it back on with a fake page check."""
    import dataclasses

    from magnacoda import preferences

    load = preferences.load
    monkeypatch.setattr(preferences, "load", lambda: dataclasses.replace(load(), estimate=False))
