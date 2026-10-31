"""Sections of the shell: a command that opens one starts on a page of its own, with the banner on top,
its own word highlighted there, and its name as a heading. Public for add-ons."""

from __future__ import annotations

import click
from rich.console import Console


def new_page(ctx: click.Context, name: str) -> bool:
    """In the shell, a page of its own for the section `name` (the word the banner lists, such as
    "wizard"), ending in a blank line under its heading; the scrollback keeps the rest. Outside the
    shell, or with output piped or captured, nothing: the output stays plain. Whether a page began."""
    start = ctx.obj.get("new_page") if isinstance(ctx.obj, dict) else None
    if not (callable(start) and Console().is_terminal):
        return False
    start(name)
    return True
