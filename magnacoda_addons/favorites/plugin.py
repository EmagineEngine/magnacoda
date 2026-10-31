"""Favorites: a bundled add-on, and the worked example for writing one.

Registered under `magnacoda.plugins` in pyproject.toml like any other add-on. It only imports its own
files, the standard library, click and magnacoda's public modules, so it can be copied out as is
(tests/addons/test_self_contained.py enforces that).
"""

from __future__ import annotations

from importlib import resources

import click

from magnacoda.plugins import StartGroup
from magnacoda.savedcommand import SavedScan

from . import commands, wizard

PLUGIN_API = 2


def register_commands(group: click.Group) -> None:
    group.add_command(commands.favorites_cmd)
    group.add_command(commands.fav_cmd)
    group.add_command(commands.favs_cmd)


def help_text() -> str:
    # Shown after magnacoda's own sections in `help`; read each time, so edits show at once.
    return (resources.files(__name__.rpartition(".")[0]) / "help.md").read_text(encoding="utf-8")


def wizard_start_options() -> list[StartGroup]:
    return wizard.start_options()


def wizard_before_run(scan: SavedScan) -> None:
    wizard.offer_to_save(scan)
