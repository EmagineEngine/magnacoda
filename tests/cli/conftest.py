from __future__ import annotations

import dataclasses

import pytest


@pytest.fixture(autouse=True)
def _quick_scans(monkeypatch: pytest.MonkeyPatch) -> None:
    """The real scans these tests run are quick (as with `quick = on` in preferences.ini), so they
    leave out the slowest page tests; tests/integration covers those. --thorough still overrides it.
    The wizard doesn't check the page to estimate the time (`estimate = off`), except in the tests of
    that (tests/cli/test_estimate.py), which turn it back on."""
    from magnacoda import preferences

    load = preferences.load
    monkeypatch.setattr(preferences, "load", lambda: dataclasses.replace(load(), quick=True, estimate=False))
