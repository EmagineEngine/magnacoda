"""The title screen: the name, the slogan and the version, centered, when the shell starts (by default
on the first start of the day; the `title` preference, or `--title` to show it now).

A soft glow passes once along the name, on the title or else in the banner, where the terminal has full
color and tells its background; its colors move away from the background, so the name never drops below
its 7:1 contrast. Off wherever text isn't typed out (teletype.enabled), so never for a screen reader.
"""

from __future__ import annotations

import math
import sys
import textwrap
import time
from datetime import date
from pathlib import Path

from rich.console import Console
from rich.markup import escape
from rich.text import Text

from magnacoda import __version__, news, preferences, teletype
from magnacoda.pager.screen import RGB, title_blue
from magnacoda.userdir import config_dir, write_private

SLOGAN = ("Scan for web accessibility issues.", "Learn to fix them.")
SITE = "magnacoda.dev"
PRESS = "Press Enter to continue"
MIN_SPACED_ROWS = 12  # fewer rows than this: the lines without the space around them
GLOW_SECONDS = 1.0  # one pass along the name
GLOW_FRAMES = 30
GLOW_WIDTH = 2.5  # letters on each side of the band's middle
GLOW_STRENGTH = 0.6  # how far the middle of the band goes toward white (or black)


def state_path() -> Path:
    return config_dir() / "title-shown"


def due(console: Console, forced: bool = False, today: str | None = None) -> bool:
    """Whether to show the title: at a terminal, as the `title` preference says (daily: not yet today),
    and only with typing on unless `forced`."""
    try:
        if not (sys.stdin.isatty() and console.is_terminal):
            return False
    except (AttributeError, ValueError):
        return False
    if forced:
        return True
    when = preferences.load().title
    if when == "never" or not teletype.enabled(console.file):
        return False
    if when == "always":
        return True
    try:
        return state_path().read_text(encoding="utf-8").strip() != (today or date.today().isoformat())
    except OSError:
        return True


def mark_shown(today: str | None = None) -> None:
    try:
        write_private(state_path(), (today or date.today().isoformat()) + "\n")
    except OSError:
        pass


def lines(name: str, width: int, height: int) -> tuple[int, list[str]]:
    """(blank lines above, the title's lines centered on `width`); the last line is PRESS."""
    version = f"version {news.release_label(__version__)} · {SITE}"
    spaced = height >= MIN_SPACED_ROWS
    block = [name, *SLOGAN, "", version, *([""] * (3 if spaced else 1)), PRESS]
    top = (height - len(block)) // 3 if spaced else 0
    centered = []
    for line in block:
        for part in textwrap.wrap(line, width) or [""]:
            centered.append(part.center(width).rstrip())
    return max(top, 0), centered


def _mix(color: RGB, toward: RGB, amount: float) -> RGB:
    r, g, b = (round(c + (t - c) * amount) for c, t in zip(color, toward, strict=True))
    return r, g, b


def glow_colors(base: RGB, background: RGB, letters: int, frames: int = GLOW_FRAMES) -> list[list[RGB]]:
    """Each frame's color for each letter: a soft band passing left to right, then the plain name."""
    toward = (255, 255, 255) if sum(background) < sum(base) else (0, 0, 0)
    start, end = -GLOW_WIDTH, letters - 1 + GLOW_WIDTH
    out = []
    for frame in range(frames):
        middle = start + (end - start) * frame / max(frames - 1, 1)
        row = []
        for letter in range(letters):
            distance = abs(letter - middle) / GLOW_WIDTH
            amount = GLOW_STRENGTH * (math.cos(math.pi * distance) + 1) / 2 if distance < 1 else 0.0
            row.append(_mix(base, toward, amount))
        out.append(row)
    out.append([base] * letters)
    return out


def _rgb(color: str) -> RGB:
    r, g, b = bytes.fromhex(color[1:])
    return r, g, b


def _name_text(name: str, colors: list[RGB] | None, plain_style: str) -> Text:
    if colors is None:
        return Text(name, style=f"{plain_style} italic")
    text = Text()
    for letter, (r, g, b) in zip(name, colors, strict=True):
        text.append(letter, style=f"bold italic #{r:02x}{g:02x}{b:02x}")
    return text


def glow(console: Console, name: str, plain_style: str, background: str | None, pad: str = "") -> None:
    """Print the name, with the glow passing along it where the terminal allows; the line goes on."""
    back = _rgb(background) if background else None
    base = title_blue(back) if back else None
    moving = console.color_system == "truecolor" and teletype.enabled(console.file)
    if back and base and moving:
        console.show_cursor(False)
    try:
        if back and base and moving:
            start = time.monotonic()
            for frame, colors in enumerate(glow_colors(base, back, len(name))):
                console.file.write("\r" + pad)
                console.print(_name_text(name, colors, plain_style), end="")
                console.file.flush()
                # Kept to the clock, so drawing time on a low-end device doesn't stretch it.
                time.sleep(max(start + (frame + 1) * GLOW_SECONDS / GLOW_FRAMES - time.monotonic(), 0))
            return
    except KeyboardInterrupt:
        console.file.write("\r")
    finally:
        if back and base and moving:
            console.show_cursor(True)
    console.print(Text(pad) + _name_text(name, None, plain_style), end="")


def show(console: Console, name: str, plain_style: str, background: str | None) -> str:
    """Draw the title and wait for Enter; -> what was typed ("" for Enter alone). Ctrl+D raises
    EOFError, as at the prompt; Ctrl+C just goes on."""
    mark_shown()
    top, centered = lines(name, console.width, console.height)
    teletype.page_feed(console)
    console.file.write("\n" * top)
    glow(console, name, plain_style, background, pad=" " * (len(centered[0]) - len(centered[0].lstrip())))
    console.print()
    rest = centered[1:]
    for n, line in enumerate(rest[:-1]):
        dim = n >= len(SLOGAN)  # the version line
        console.print(f"[dim]{escape(line)}[/dim]" if dim and line else escape(line), highlight=False)
    press = rest[-1]
    try:
        return console.input(f"[dim]{escape(press)}[/dim] ").strip()
    except KeyboardInterrupt:
        console.print()
        return ""
