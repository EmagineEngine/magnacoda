"""Teletype-style shell output: nothing is erased, and short text types out in quick chunks.

page_feed scrolls blank lines instead of clearing, so the scrollback keeps everything. Long text prints
at once, and typing always finishes within MAX_SECONDS. Off outside a terminal, with
MAGNACODA_TYPING=off, or `typing = off` (screen readers).
"""

from __future__ import annotations

import math
import os
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import IO, Any

from rich.console import Console
from rich.text import Text

from magnacoda import preferences

ENV_OFF_SWITCH = "MAGNACODA_TYPING"
OFF_VALUES = {"off", "0", "false", "no"}
MAX_TYPED_CHARS = 600  # longer text appears at once
CHUNK_DELAY = 0.012  # seconds between chunks
MAX_SECONDS = 0.6  # no typed text takes longer than this
MIN_CHUNK = 5  # characters per chunk, at least
LISTING_CHUNK = 18  # at least this many inside listing(): lists of several lines come out faster
_smallest = MIN_CHUNK


def enabled(stream: Any = None, env: dict[str, str] | None = None) -> bool:
    """Whether to type text out: only for a real terminal, and unless switched off."""
    stream = sys.stdout if stream is None else stream
    try:
        if not stream.isatty():
            return False
    except (AttributeError, ValueError):
        return False
    env = dict(os.environ) if env is None else env
    if env.get(ENV_OFF_SWITCH, "").strip().lower() in OFF_VALUES:
        return False
    return preferences.load().typing


def chunk_size(characters: int) -> int:
    """Characters per chunk, so that `characters` take at most MAX_SECONDS."""
    chunks_allowed = max(int(MAX_SECONDS / CHUNK_DELAY), 1)
    return max(_smallest, math.ceil(characters / chunks_allowed))


@contextmanager
def listing() -> Iterator[None]:
    """Type what's printed inside in bigger chunks (a list printed a line at a time, which would
    otherwise add up to seconds)."""
    global _smallest
    before, _smallest = _smallest, max(_smallest, LISTING_CHUNK)
    try:
        yield
    finally:
        _smallest = before


def write(stream: IO[str], text: str) -> None:
    """Plain text to `stream`, typed out if enabled and short enough, otherwise all at once."""
    if len(text) > MAX_TYPED_CHARS or not enabled(stream):
        stream.write(text)
        stream.flush()
        return
    size = chunk_size(len(text))
    for start in range(0, len(text), size):
        stream.write(text[start : start + size])
        stream.flush()
        time.sleep(CHUNK_DELAY)


def say(console: Console, content: str | Text, end: str = "\n", max_chars: int = MAX_TYPED_CHARS) -> None:
    """Type out styled text like `write`. Lines aren't re-wrapped. A longer `max_chars` types longer
    text too (about), in bigger chunks: it still takes at most MAX_SECONDS."""
    text = Text.from_markup(content) if isinstance(content, str) else content
    if len(text) > max_chars or not console.is_terminal or not enabled(console.file):
        console.print(text, end=end, soft_wrap=True, highlight=False)
        return
    size = chunk_size(len(text))
    for start in range(0, len(text), size):
        console.print(text[start : start + size], end="", soft_wrap=True, highlight=False)
        console.file.flush()
        time.sleep(CHUNK_DELAY)
    console.print(end=end)


def page_feed(console: Console) -> None:
    """Scroll a screen of blank lines instead of clearing, so the scrollback keeps everything."""
    if not console.is_terminal:
        return
    if console.legacy_windows:
        # A Windows console without control codes (see winconsole.py) can't move the cursor back
        # to the top; its own cls is the closest it has.
        console.file.flush()
        os.system("cls")  # noqa: S605, S607 - a fixed built-in command
        return
    console.file.write("\n" * console.height + "\x1b[H")
    console.file.flush()
