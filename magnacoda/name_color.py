"""The color of magnacoda's name in the shell: a blue that keeps 7:1 contrast on the terminal's background.

The terminal is asked for its background (OSC 11). Without an answer, or without 256 or more colors,
the name is just bold.
"""

from __future__ import annotations

import os
import sys

from rich.console import Console

from magnacoda.pager.colors import contrast, nearest256, xterm256
from magnacoda.pager.screen import terminal_colors, title_blue

MIN_CONTRAST = 7.0
PLAIN = "bold"


def for_background(background: str, color_system: str | None) -> str:
    """A Rich style: the pager title's blue for that background (in 256 colors, the nearest that still
    reaches 7:1), or plain bold."""
    if color_system not in ("truecolor", "256"):
        return PLAIN
    blue = title_blue(tuple(bytes.fromhex(background[1:])))  # type: ignore[arg-type]
    if blue is None:
        return PLAIN
    color = "#{:02x}{:02x}{:02x}".format(*blue)
    if color_system == "256":
        near = (xterm256(n) for n in nearest256(color))
        color = next((c for c in near if contrast(c, background) >= MIN_CONTRAST), "")
    return f"bold {color}" if color else PLAIN


def _background() -> str | None:
    if os.name != "posix":
        return None
    import termios
    import tty

    try:
        fd = sys.stdin.fileno()
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            return None
        old = termios.tcgetattr(fd)
    except (AttributeError, OSError, ValueError, termios.error):
        return None
    try:
        tty.setcbreak(fd)
        pair = terminal_colors(fd, sys.stdout)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    return "#{:02x}{:02x}{:02x}".format(*pair[1]) if pair else None


def style(console: Console) -> str:
    if console.no_color or not console.is_terminal:
        return PLAIN
    background = _background()
    return for_background(background, console.color_system) if background else PLAIN
