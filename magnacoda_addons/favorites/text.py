"""Printing for the favorites add-on, wrapped to the terminal like magnacoda's own messages."""

from __future__ import annotations

import sys

import click

from magnacoda import questions
from magnacoda.wrapping import wrap_for_stream


def echo(message: str = "", *, err: bool = False) -> None:
    # No dim gray: it can be too faint to read, especially on Windows (as in magnacoda itself).
    text = wrap_for_stream(message, sys.stderr if err else sys.stdout)
    click.echo(text, err=err)
    questions.printed(message)  # so a question right after a blank line doesn't add another
