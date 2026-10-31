"""Questions with consistent spacing: a blank line before and after. Public for add-ons.

The same three rules at every question: Ctrl+C or q cancels (click.Abort: "Cancelled."; clear does
too, as Cleared, and the shell starts a fresh page), and Enter takes what the brackets show ([Y/n],
[back], a default). Call printed() after printing, so a question doesn't add a second blank line.
"""

from __future__ import annotations

import sys
from typing import Any

import click
from click.types import convert_type

from magnacoda import teletype
from magnacoda.wrapping import wrap_for_stream

_last_blank = True  # whether the last line printed was blank
CANCEL_WORDS = ("q",)  # typed alone at any question, like Ctrl+C
CLEAR_WORDS = ("clear", "cls")  # cancel too, and the shell starts a fresh page, as clear does there
CANCEL_HINT = "Ctrl+C or q cancels at any time."


def printed(message: str) -> None:
    """Note a message that was just printed as one or more whole lines."""
    global _last_blank
    _last_blank = message == "" or message.endswith("\n")


def _space_above() -> None:
    global _last_blank
    if not _last_blank:
        click.echo()
    _last_blank = True


def _space_below() -> None:
    global _last_blank
    click.echo()
    _last_blank = True


def _intro(intro: str | None, err: bool) -> None:
    if not intro:
        return
    stream = sys.stderr if err else sys.stdout
    text = wrap_for_stream(intro, stream)
    if err:
        click.echo(text, err=True)
    else:
        teletype.write(stream, text + "\n")  # typed out in the shell, like magnacoda's other text


class Cleared(click.Abort):
    """Cancelled with clear (or cls)."""


def _check_cancel(value: Any) -> None:
    """Raise click.Abort for a cancel word, Cleared for a clear word."""
    word = value.strip().lower() if isinstance(value, str) else None
    if word in CLEAR_WORDS:
        raise Cleared
    if word in CANCEL_WORDS:
        raise click.Abort


def ask(text: str, *, intro: str | None = None, err: bool = False, **kwargs: Any) -> Any:
    """click.prompt with the standard spacing; `intro` (wrapped to the terminal) is shown just above.
    q cancels, as Ctrl+C does."""
    _space_above()
    _intro(intro, err)
    given = kwargs.pop("value_proc", None) or convert_type(kwargs.get("type"), kwargs.get("default"))

    def value_proc(value: Any) -> Any:
        _check_cancel(value)
        return given(value)

    answer = click.prompt(text, err=err, value_proc=value_proc, **kwargs)
    _space_below()
    return answer


def ask_yes_no(text: str, *, intro: str | None = None, default: bool = False, err: bool = False) -> bool:
    """A yes/no question shown as click.confirm shows it ([Y/n]: Enter takes the capital), with the
    standard spacing; q cancels, as Ctrl+C does."""
    _space_above()
    _intro(intro, err)

    def value_proc(value: str) -> bool:
        _check_cancel(value)
        answer = value.strip().lower()
        if not answer:
            return default
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        raise click.BadParameter("type y or n, or press Enter.")

    suffix = "[Y/n]" if default else "[y/N]"
    answer: bool = click.prompt(
        f"{text} {suffix}", default="", show_default=False, value_proc=value_proc, err=err
    )
    _space_below()
    return answer
