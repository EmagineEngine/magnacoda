"""Wizard hooks: the Favorites start group, and before the scan "Save this as a favorite?" (or, for
a changed favorite, an offer to update it)."""

from __future__ import annotations

import click

from magnacoda import questions, savedcommand
from magnacoda.plugins import StartGroup

from . import settings, store
from .text import echo as _echo


def pick_number(text: str, count: int, enter: str = "back") -> int | None:
    """Ask for one of 1..count, or Enter for none, which the brackets name. Re-asks on anything else."""

    def check(value: str) -> int:
        value = value.strip()
        if not value:
            return 0
        if value.isdigit() and 1 <= int(value) <= count:
            return int(value)
        raise click.BadParameter(f"type one of the numbers above (1 to {count}), or press Enter ({enter}).")

    chosen = questions.ask(f"{text} [{enter}]", default="", show_default=False, value_proc=check)
    return int(chosen) - 1 if chosen else None


def start_options() -> list[StartGroup]:
    """The Favorites start group; creates favorites.md and the setting on first use."""
    store.ensure_file()
    settings.ensure_section()
    saved, problems = store.load()
    for problem in problems:
        _echo(problem)
    return [StartGroup("Favorites", [(fav.name, fav.command) for fav in saved], word="fav")]


def offer_to_save(scan: savedcommand.SavedScan) -> None:
    """Started from a favorite: nothing to ask if unchanged, else offer to update it. Otherwise, or if
    not updated, offer to save it as a new one."""
    saved, _ = store.load()
    origin = getattr(scan, "origin", "")  # the command it was started from (newer magnacoda only)
    index = store.find_by_command(saved, origin) if origin else None
    if index is not None:
        command = savedcommand.to_command(scan)
        if store.find_by_command([saved[index]], command) is not None:
            return  # the favorite as it is
        name = saved[index].name
        if questions.ask_yes_no(f"Update the favorite '{name}' with these settings?", default=True):
            saved[index] = store.Favorite(name, command, saved[index].notes)
            _store(saved, command)
            return
    if questions.ask_yes_no("Save this as a favorite?", default=False):
        save_favorite(scan, settings.favorites_max())


def save_favorite(scan: savedcommand.SavedScan, limit: int) -> None:
    """Keep this command in favorites.md, asking which to replace when the list is full."""
    saved, _ = store.load()
    command = savedcommand.to_command(scan)
    same = store.find_by_command(saved, command)
    if same is not None:
        _echo(f"Already saved as '{saved[same].name}'.")
        return

    def named(value: str) -> str:
        name = store.sanitize_name(value)
        if len(name) < store.MIN_NAME_LENGTH:
            raise click.BadParameter(f"a name needs at least {store.MIN_NAME_LENGTH} characters.")
        return name

    name = questions.ask("Name for this favorite", default=store.default_name(scan), value_proc=named)
    entry = store.Favorite(name, command)
    existing = store.find_by_name(saved, name)
    if existing is not None:
        saved[existing] = store.Favorite(name, command, saved[existing].notes)
    elif len(saved) >= limit:
        _echo(f"Your favorites are full ({limit}). Which one should this replace?")
        for number, fav in enumerate(saved, start=1):
            _echo(f"  {number}. {fav.name}")
        index = pick_number("Type its number", len(saved), enter="none")
        if index is None:
            _echo("Not saved.")
            return
        saved[index] = entry
    else:
        saved.append(entry)
    _store(saved, command)


def _store(saved: list[store.Favorite], command: str) -> None:
    try:
        store.save_all(saved)
    except OSError as exc:
        _echo(f"Could not save the favorite: {exc.strerror or exc}", err=True)
        return
    _echo(
        f"Saved to {store.favorites_path()}\n  {command}\n"
        f"Inside the shell, type it as it is; from a terminal, put magnacoda in front."
    )
