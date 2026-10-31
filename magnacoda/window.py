"""A window a shortcut opened closes as soon as magnacoda exits, so first it waits for Enter: the last
lines stay up for as long as the reading takes, with nothing counting down."""

from __future__ import annotations

ENTER_PROMPT = "Press Enter to close this window."


def before_closing() -> None:
    """Wait for Enter before the window closes."""
    try:
        input(ENTER_PROMPT)
    except (EOFError, KeyboardInterrupt):
        pass
