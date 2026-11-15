"""A little space at the left and right edges of the shell's text.

The shell's output all passes through sys.stdout and sys.stderr, so the left margin is added there: each
line that has text starts with WIDTH spaces. For the right margin, COLUMNS is kept at the window's width
less both margins, which everything that wraps text reads (Rich, shutil, Click). Only in a terminal,
and not in screen reader mode, where leading spaces can be announced.

The terminal itself wraps what a person types, so a typed line longer than the window continues at the
window's own edge. A program started from the shell (the browser download) writes straight to the
terminal, without the margin. The viewer draws the whole window itself: see paused().
"""

from __future__ import annotations

import builtins
import getpass
import os
import re
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from typing import IO, Any

import click.termui

from magnacoda import screenreader

WIDTH = 2  # columns at each side: about an em dash
_MIN_COLUMNS = 20
_PIECES = re.compile(r"\n|\r|\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b|[^\n\r\x1b]+")
_TO_FIRST_COLUMN = "HfGEF"  # cursor-movement codes that end at the left edge


class _State:
    """Shared by stdout and stderr: they are the same window."""

    def __init__(self, terminal: IO[str]) -> None:
        self.terminal = terminal
        self.at_start = True  # the cursor is at the window's left edge
        self.on = True
        self.columns_before = os.environ.get("COLUMNS")

    def fit(self) -> None:
        """Keep COLUMNS at the window's width less the margins (it follows a resized window)."""
        if self.columns_before and self.columns_before.isdigit():
            full = int(self.columns_before)
        else:
            try:
                full = os.get_terminal_size(self.terminal.fileno()).columns
            except (OSError, ValueError, AttributeError):
                return
            if full <= 0:  # a terminal that doesn't say
                return
        os.environ["COLUMNS"] = str(max(full - 2 * WIDTH, _MIN_COLUMNS))

    def unfit(self) -> None:
        if self.columns_before is None:
            os.environ.pop("COLUMNS", None)
        else:
            os.environ["COLUMNS"] = self.columns_before


class Margined:
    """A stream that starts each line of text WIDTH columns in. Empty lines stay empty."""

    def __init__(self, stream: IO[str], state: _State) -> None:
        self.stream, self._state = stream, state

    def write(self, text: str) -> int:
        state = self._state
        if not state.on:
            return self.stream.write(text)
        if state.at_start:
            state.fit()
        out: list[str] = []
        for piece in _PIECES.findall(text):
            if piece in ("\n", "\r") or (piece.startswith("\x1b[") and piece[-1] in _TO_FIRST_COLUMN):
                state.at_start = True
            elif not piece.startswith("\x1b") and state.at_start:
                out.append(" " * WIDTH)
                state.at_start = False
            out.append(piece)
        self.stream.write("".join(out))
        return len(text)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.stream, name)


_state: _State | None = None
_before: tuple[Any, ...] | None = None


def install() -> bool:
    """Start adding the margins. False (and nothing changes) outside a terminal, in screen reader mode,
    or when they are already there."""
    global _state, _before
    if _state is not None or screenreader.mode_on():
        return False
    try:
        if not (sys.stdout.isatty() and sys.stderr.isatty()):
            return False
    except (AttributeError, ValueError):
        return False
    state = _State(sys.stdout)
    _before = (
        sys.stdout,
        sys.stderr,
        builtins.input,
        getpass.getpass,
        click.termui.visible_prompt_func,
        click.termui.hidden_prompt_func,
    )
    read_line, read_hidden = builtins.input, getpass.getpass

    # A typed answer ends with Enter, which the terminal shows itself: the next text starts a line.
    def margined_input(prompt: object = "") -> str:
        if prompt:
            sys.stdout.write(str(prompt))
            sys.stdout.flush()
        answer = read_line("")
        state.at_start = True
        return answer

    def margined_getpass(prompt: str = "Password: ", stream: Any = None) -> str:
        if state.on and state.at_start:
            prompt = " " * WIDTH + prompt
        answer = read_hidden(prompt, stream)
        state.at_start = True
        return answer

    sys.stdout = Margined(sys.stdout, state)  # type: ignore[assignment]
    sys.stderr = Margined(sys.stderr, state)  # type: ignore[assignment]
    builtins.input, getpass.getpass = margined_input, margined_getpass
    # Click keeps its own references to both, taken when it was imported.
    click.termui.visible_prompt_func = margined_input
    click.termui.hidden_prompt_func = margined_getpass
    state.fit()
    _state = state
    return True


def uninstall() -> None:
    global _state, _before
    if _state is None or _before is None:
        return
    _state.unfit()
    (
        sys.stdout,
        sys.stderr,
        builtins.input,
        getpass.getpass,
        click.termui.visible_prompt_func,
        click.termui.hidden_prompt_func,
    ) = _before
    _state = _before = None


def sync() -> None:
    """After screen reader mode was switched: the margins are off with it, and back without it."""
    if _state is not None:
        _state.on = not screenreader.mode_on()
        if _state.on:
            _state.fit()
        else:
            _state.unfit()


@contextmanager
def paused() -> Iterator[None]:
    """No margins for what runs inside: the viewer, which lays out the whole window itself."""
    state = _state
    if state is None or not state.on:
        yield
        return
    state.on = False
    state.unfit()
    try:
        yield
    finally:
        state.on = True
        state.at_start = True
        state.fit()
