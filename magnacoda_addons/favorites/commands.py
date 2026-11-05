"""The `favorites` command: list, run or delete saved favorites. Wording lives in messages.md."""

from __future__ import annotations

import shlex
import sys

import click

from magnacoda import questions, savedcommand

from . import messages, settings, store
from .text import echo


def _list_unless_a_subcommand_follows(ctx: click.Context) -> None:
    if ctx.invoked_subcommand is None:
        _list(ctx)


def _favorites_group(name: str, hidden: bool) -> click.Group:
    """`favorites`, or hidden `fav`/`favs`. Separate objects: hidden is per command, not per name."""
    return click.Group(
        name,
        callback=click.pass_context(_list_unless_a_subcommand_follows),
        invoke_without_command=True,
        hidden=hidden,
        help="List your saved favorites, or delete one with `favorites delete NUMBER` (or its name).",
    )


def _list(ctx: click.Context) -> None:
    saved, problems = store.load()
    for problem in problems:
        echo(problem)
    if not saved:
        echo(messages.text("favorites-empty"))
        return
    echo(messages.text("favorites-heading", count=len(saved), limit=settings.favorites_max()) + "\n")
    for number, favorite in enumerate(saved, start=1):
        echo(f"  {number}. {favorite.name}")
        echo(f"     {favorite.command}")
    if not _interactive():
        return  # a script listing favorites gets the list, never a question
    while (index := _pick(len(saved))) == "help":
        _show_help(ctx)
    if isinstance(index, int):
        _run(ctx, saved[index])


def _pick(count: int) -> int | str:
    """A favorite's index or "help"; Enter cancels, as q does."""

    def check(value: str) -> int | str:
        value = value.strip()
        if not value:
            raise click.Abort
        if value.lower() == "help":
            return value.lower()
        if value.isdigit() and 1 <= int(value) <= count:
            return int(value) - 1
        raise click.BadParameter(messages.text("pick-again", count=count))

    chosen: int | str = questions.ask(
        messages.text("pick-prompt"), default="", show_default=False, value_proc=check
    )
    return chosen


def _show_help(ctx: click.Context) -> None:
    """The favorites section of magnacoda's help."""
    root = ctx.find_root()
    command = root.command.get_command(root, "help") if isinstance(root.command, click.Group) else None
    if command is None:
        return
    with command.make_context("help", ["favorites"], parent=root) as help_ctx:
        command.invoke(help_ctx)


def _interactive() -> bool:
    return sys.stdin.isatty()


def _run(ctx: click.Context, favorite: store.Favorite) -> None:
    """Show the favorite's command, ask, and run it (the scan says how long it will take).

    Parsed via savedcommand, which drops options that no longer exist.
    """
    planned = savedcommand.parse(favorite.command)
    if planned is not None:
        args = savedcommand.to_tokens(planned)[1:]
        echo(savedcommand.display_command(planned))
    else:
        tokens = shlex.split(favorite.command)
        args = tokens[1:] if tokens and tokens[0] == "scan" else tokens
        echo(favorite.command)
    if not questions.ask_yes_no(messages.text("run-confirm", name=favorite.name), default=True):
        return
    root = ctx.find_root()
    scan = root.command.get_command(root, "scan") if isinstance(root.command, click.Group) else None
    if scan is None:
        raise click.ClickException("magnacoda's scan command isn't available.")
    with scan.make_context("scan", args, parent=root) as scan_ctx:
        scan.invoke(scan_ctx)


@click.command("delete")
@click.argument("which")
@click.option("-y", "--yes", is_flag=True, default=False, help="Delete without asking.")
def delete_cmd(which: str, yes: bool) -> None:
    """Delete one favorite, by its number in the list or by its name."""
    saved, _ = store.load()
    index = _find(saved, which)
    if index is None:
        raise click.UsageError(messages.text("delete-unknown", which=which))
    favorite = saved[index]
    question = messages.text("delete-confirm", number=index + 1, name=favorite.name)
    if not yes and not questions.ask_yes_no(question, default=False):
        echo(messages.text("delete-cancelled"))
        return
    del saved[index]
    try:
        store.save_all(saved)
    except OSError as exc:
        raise click.ClickException(messages.text("save-failed", reason=exc.strerror or exc)) from exc
    left = messages.text("delete-done-left", count=len(saved)) if saved else messages.text("delete-done-none")
    echo(messages.text("delete-done", name=favorite.name, left=left))


def _find(saved: list[store.Favorite], which: str) -> int | None:
    """A 1-based number ("#3" works too) or a name, case-insensitive."""
    text = which.strip()
    if text.startswith("#") and text[1:].isdigit():
        text = text[1:]
    if text.isdigit():
        number = int(text)
        return number - 1 if 1 <= number <= len(saved) else None
    return store.find_by_name(saved, text)


favorites_cmd = _favorites_group("favorites", hidden=False)
fav_cmd = _favorites_group("fav", hidden=True)  # not in the banner or `about`
favs_cmd = _favorites_group("favs", hidden=True)
for _group in (favorites_cmd, fav_cmd, favs_cmd):
    _group.add_command(delete_cmd)
