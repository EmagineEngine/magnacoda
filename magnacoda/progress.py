"""Progress steps for the spinner: the scan calls step(...), the CLI subscribes with listening(...)."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager

_listener: Callable[[str], None] | None = None


def step(text: str) -> None:
    """Announce what the scan is doing now (lower case, no full stop: "loading the page")."""
    if _listener is not None:
        _listener(text)


@contextmanager
def listening(listener: Callable[[str], None]) -> Iterator[None]:
    global _listener
    previous, _listener = _listener, listener
    try:
        yield
    finally:
        _listener = previous
