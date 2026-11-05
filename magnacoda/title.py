"""The title screen: the name, the slogan and the version, centered, when the shell starts (by default
on the first start of the day; the `title` preference, or `--title` to show it now).

On the title the name is reversed, in a block of its blue. A soft glow passes once along the name, on
the title (through the block) or else in the banner, where the terminal has full color and tells its
background; its colors move away from the background, so the name never drops below its 7:1 contrast.
On a light background the block's band brightens instead, nearly to white, since darkening is hard to
see there; the letters in it turn dark where that reads better, so it stays at 4.5:1 or more.
Off wherever text isn't typed out (teletype.enabled), so never for a screen reader.
"""

from __future__ import annotations

import math
import sys
import textwrap
import time
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from rich.console import Console
from rich.markup import escape
from rich.text import Text

from magnacoda import __version__, news, preferences, teletype
from magnacoda.pager.colors import contrast
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
BRIGHT_STRENGTH = 0.85  # on a light background, how far the block's band goes toward white


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


def lines(name: str, width: int, height: int, notices: Sequence[str] = ()) -> tuple[int, list[str]]:
    """(blank lines above, the title's lines centered on `width`); the last line is PRESS. `notices`
    (updates, news) come under the version line."""
    version = f"version {news.release_label(__version__)} · {SITE}"
    spaced = height >= MIN_SPACED_ROWS
    under = ["", *notices] if notices else []
    block = [name, *SLOGAN, "", version, *under, *([""] * (3 if spaced else 1)), PRESS]
    top = (height - len(block)) // 3 if spaced else 0
    centered = []
    for line in block:
        for part in textwrap.wrap(line, width) or [""]:
            centered.append(part.center(width).rstrip())
    return max(top, 0), centered


def _mix(color: RGB, toward: RGB, amount: float) -> RGB:
    r, g, b = (round(c + (t - c) * amount) for c, t in zip(color, toward, strict=True))
    return r, g, b


def _band(letters: int, frames: int) -> list[list[float]]:
    """Each frame's strength for each letter, 0 to 1: a soft band passing left to right."""
    start, end = -GLOW_WIDTH, letters - 1 + GLOW_WIDTH
    out = []
    for frame in range(frames):
        middle = start + (end - start) * frame / max(frames - 1, 1)
        distances = (abs(letter - middle) / GLOW_WIDTH for letter in range(letters))
        out.append([(math.cos(math.pi * d) + 1) / 2 if d < 1 else 0.0 for d in distances])
    return out


def glow_colors(base: RGB, background: RGB, letters: int, frames: int = GLOW_FRAMES) -> list[list[RGB]]:
    """Each frame's color for each letter: a soft band passing left to right, then the plain name."""
    toward = (255, 255, 255) if sum(background) < sum(base) else (0, 0, 0)
    out = [[_mix(base, toward, GLOW_STRENGTH * a) for a in row] for row in _band(letters, frames)]
    out.append([base] * letters)
    return out


def bright_band(
    base: RGB, background: RGB, letters: int, frames: int = GLOW_FRAMES
) -> list[list[tuple[RGB, RGB]]]:
    """The reversed name's glow on a light background: each frame's (letter, block) colors. The block
    brightens nearly to white; each letter in it turns white or navy, whichever reads better on its
    block (white rather than the background's color, which on cream would drop below 4.5:1 where the
    letters switch). Then the plain name."""
    white, dark = (255, 255, 255), _mix(base, (0, 0, 0), 0.75)
    out = []
    for row in _band(letters, frames):
        cells = []
        for amount in row:
            if amount == 0:
                cells.append((background, base))
                continue
            block = _mix(base, white, BRIGHT_STRENGTH * amount)
            light_reads = contrast(_hex(white), _hex(block)) >= contrast(_hex(dark), _hex(block))
            cells.append((white if light_reads else dark, block))
        out.append(cells)
    out.append([(background, base)] * letters)
    return out


def _styled(line: str) -> str:
    """The version line dim; a notice's command ("- type update") bold; the rest as it is."""
    if f"· {SITE}" in line:
        return f"[dim]{escape(line)}[/dim]"
    head, typed, command = line.rpartition(" type ")
    if typed and command.strip().isalpha():
        return f"{escape(head)} type [bold]{escape(command)}[/bold]"
    return escape(line)


def _rgb(color: str) -> RGB:
    r, g, b = bytes.fromhex(color[1:])
    return r, g, b


def _hex(color: RGB) -> str:
    return "#{:02x}{:02x}{:02x}".format(*color)


def _name_text(
    name: str, colors: list[RGB] | None, plain_style: str, reverse: bool = False, back: RGB | None = None
) -> Text:
    """The name in its colors, one per letter. With `reverse`, the colors are a block's and the
    letters take the background's color (`back`), as reverse video does."""
    if colors is None:
        return Text(name, style=f"{plain_style} italic" + (" reverse" if reverse else ""))
    if reverse and back:
        return _pairs_text(name, [(back, color) for color in colors])
    text = Text()
    for letter, color in zip(name, colors, strict=True):
        text.append(letter, style=f"bold italic {_hex(color)}")
    return text


def _pairs_text(name: str, pairs: list[tuple[RGB, RGB]]) -> Text:
    """The name with a (letter, block) color pair for each letter."""
    text = Text()
    for letter, (front, block) in zip(name, pairs, strict=True):
        text.append(letter, style=f"bold italic {_hex(front)} on {_hex(block)}")
    return text


def glow(
    console: Console,
    name: str,
    plain_style: str,
    background: str | None,
    pad: str = "",
    reverse: bool = False,
) -> None:
    """Print the name, with the glow passing along it where the terminal allows; the line goes on.
    With `reverse` (the title), the name sits in a block with a space at each end, and the glow moves
    through the block: away from the letters, which have the background's color, so the contrast only
    rises; on a light background, the bright band (`bright_band`)."""
    if reverse and console.color_system:  # the block's padding, only where the block shows
        name = f" {name} "
    back = _rgb(background) if background else None
    base = title_blue(back) if back else None
    moving = console.color_system == "truecolor" and teletype.enabled(console.file)
    if back and base and moving:
        console.show_cursor(False)
    try:
        if back and base and moving:
            start = time.monotonic()
            light = reverse and sum(back) > sum(base)
            frames: Sequence[Text] = (
                [_pairs_text(name, pairs) for pairs in bright_band(base, back, len(name))]
                if light
                else [
                    _name_text(name, c, plain_style, reverse, back)
                    for c in glow_colors(base, back, len(name))
                ]
            )
            for frame, drawn in enumerate(frames):
                console.file.write("\r" + pad)
                console.print(drawn, end="")
                console.file.flush()
                # Kept to the clock, so drawing time on a low-end device doesn't stretch it.
                time.sleep(max(start + (frame + 1) * GLOW_SECONDS / GLOW_FRAMES - time.monotonic(), 0))
            return
    except KeyboardInterrupt:
        console.file.write("\r")
    finally:
        if back and base and moving:
            console.show_cursor(True)
    plain = [base] * len(name) if back and base and console.color_system == "truecolor" else None
    console.print(Text(pad) + _name_text(name, plain, plain_style, reverse, back), end="")


def show(
    console: Console, name: str, plain_style: str, background: str | None, notices: Sequence[str] = ()
) -> str:
    """Draw the title and wait for Enter; -> what was typed ("" for Enter alone). Ctrl+D raises
    EOFError, as at the prompt; Ctrl+C just goes on."""
    mark_shown()
    top, centered = lines(name, console.width, console.height, notices)
    teletype.page_feed(console)
    console.file.write("\n" * top)
    indent = len(centered[0]) - len(centered[0].lstrip())
    glow(
        console, name, plain_style, background, pad=" " * max(indent - 1, 0), reverse=True
    )  # its block's space
    console.print()
    rest = centered[1:]
    for line in rest[:-1]:
        console.print(_styled(line), highlight=False)
    press = rest[-1]
    try:
        return console.input(f"[dim]{escape(press)}[/dim] ").strip()
    except KeyboardInterrupt:
        console.print()
        return ""
