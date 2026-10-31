"""Add-ons: installed packages that extend magnacoda through a small set of hooks.

An add-on registers an entry point in the `magnacoda.plugins` group, pointing at an object (a module
or an instance) with a `PLUGIN_API` number and any of these hooks; hooks it lacks are skipped:

  register_commands(group)    add Click commands to the `magnacoda` group (they work in the shell too)
  wizard_start_options()      a list of StartGroup, shown in the wizard's start-up picker above
                              "Recent scans"
  wizard_before_run(scan)     called with the wizard's finished SavedScan, after the equivalent
                              command is shown and before "Run this scan now?"
  after_scan(report)          called with each finished ScanReport
  help_text()                 Markdown in the format of magnacoda's help.md; its sections are added
                              after magnacoda's own in `help`

A broken add-on (fails to load, wrong PLUGIN_API, raises in a hook) gets one warning and is ignored.
MAGNACODA_PLUGINS=off or --no-addons skips them all. See CONTRIBUTING for what add-ons may import.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from importlib import metadata
from typing import Any

import click

PLUGIN_API = 2
GROUP = "magnacoda.plugins"
ENV_OFF_SWITCH = "MAGNACODA_PLUGINS"


PRODUCT = "magnacoda"
_EDITION_WORD = re.compile(r"[a-z]{1,12}")


@dataclass(frozen=True)
class Edition:
    """The product name is fixed; an edition can only add one short word after it."""

    word: str = ""

    @property
    def display_name(self) -> str:  # prose: the banner, `about`, the checklist and review page titles
        return f"{PRODUCT} {self.word}" if self.word else PRODUCT


@dataclass
class StartGroup:
    title: str
    entries: list[tuple[str, str]] = field(default_factory=list)  # (label, stored command)
    # The word people type to open this group at the wizard's start (fav, recent). Default: the
    # title's first word, in lower case.
    word: str = ""

    @property
    def key(self) -> str:
        return (self.word or self.title.split()[0]).lower()


@dataclass
class Plugin:
    name: str  # the entry point's name
    package: str  # the distribution that provides it
    version: str
    hooks: Any

    @property
    def bundled(self) -> bool:  # comes with magnacoda itself (magnacoda_addons/)
        return self.package == PRODUCT

    @property
    def label(self) -> str:
        """How messages name it: an installed add-on by its package, a bundled one by its own name."""
        return self.name if self.bundled else self.package


_loaded: list[Plugin] | None = None
_edition: Edition | None = None
_commands_added: set[int] = set()
_added_by: dict[str, list[str]] = {}  # add-on label -> the commands it added (shown in the banner)


def _warn(message: str) -> None:
    click.echo(message, err=True)


def _entry_points() -> list[metadata.EntryPoint]:
    return list(metadata.entry_points(group=GROUP))


def _load() -> list[Plugin]:
    plugins: list[Plugin] = []
    if os.environ.get(ENV_OFF_SWITCH, "").strip().lower() in ("off", "0", "no", "false"):
        return plugins
    try:
        entry_points = _entry_points()
    except Exception as exc:  # noqa: BLE001 - broken package metadata must not stop the program
        _warn(f"Could not look for add-ons: {exc}")
        return plugins
    for entry_point in entry_points:
        dist = entry_point.dist
        package = dist.name if dist else entry_point.name
        version = dist.version if dist else "?"
        label = entry_point.name if package == PRODUCT else package
        try:
            hooks = entry_point.load()
        except Exception as exc:  # noqa: BLE001
            _warn(f"Skipped the add-on {label} {version}: it failed to load ({exc}).")
            continue
        wanted = getattr(hooks, "PLUGIN_API", None)
        if wanted != PLUGIN_API:
            _warn(
                f"Skipped the add-on {label} {version}: it was built for add-on interface {wanted}, "
                f"and this magnacoda has interface {PLUGIN_API}. Update the add-on or magnacoda."
            )
            continue
        plugins.append(Plugin(entry_point.name, package, version, hooks))
    return plugins


def loaded() -> list[Plugin]:
    """The working add-ons, found once per process."""
    global _loaded
    if _loaded is None:
        _loaded = _load()
    return _loaded


def reset() -> None:
    """Forget the add-ons found so far (for tests)."""
    global _loaded, _edition
    _loaded = None
    _edition = None
    _commands_added.clear()
    _added_by.clear()


def _call(plugin: Plugin, hook: str, *args: Any) -> tuple[bool, Any]:
    """(called, result). A hook that is missing is not called; one that raises gives a warning."""
    function: Callable[..., Any] | None = getattr(plugin.hooks, hook, None)
    if not callable(function):
        return False, None
    try:
        return True, function(*args)
    except (click.Abort, KeyboardInterrupt):
        raise  # Ctrl+C inside an add-on's prompt cancels, as it does anywhere else
    except Exception as exc:  # noqa: BLE001 - an add-on must never break magnacoda
        _warn(f"The add-on {plugin.label} failed in {hook}: {exc}")
        return False, None


def call_all(hook: str, *args: Any) -> None:
    for plugin in loaded():
        _call(plugin, hook, *args)


def add_commands(group: click.Group) -> None:
    """Let each add-on register its commands on `group`, once. Built-in commands always win."""
    if id(group) in _commands_added:
        return
    _commands_added.add(id(group))
    for plugin in loaded():
        before = dict(group.commands)
        called, _ = _call(plugin, "register_commands", group)
        if not called:
            group.commands = before
            continue
        for name in [n for n in group.commands if n in before and group.commands[n] is not before[n]]:
            group.commands[name] = before[name]
            _warn(
                f"The add-on {plugin.label} tried to replace the built-in command '{name}'; "
                "kept the built-in."
            )
        new = [n for n, command in group.commands.items() if n not in before and not command.hidden]
        if new:
            _added_by.setdefault(plugin.label, []).extend(new)


def added_commands() -> dict[str, list[str]]:
    """{add-on label: commands it added}. The core lists these itself."""
    return {label: list(names) for label, names in _added_by.items()}


def help_texts() -> list[tuple[Plugin, str]]:
    """[(add-on, help markdown)]; re-read each time help opens."""
    texts: list[tuple[Plugin, str]] = []
    for plugin in loaded():
        called, result = _call(plugin, "help_text")
        if not called or result is None:
            continue
        if isinstance(result, str):
            texts.append((plugin, result))
        else:
            _warn(f"The add-on {plugin.label} gave help that is not text; ignored.")
    return texts


def warn(message: str) -> None:
    """One warning line, as for every other add-on problem."""
    _warn(message)


def start_groups() -> list[StartGroup]:
    groups: list[StartGroup] = []
    for plugin in loaded():
        called, result = _call(plugin, "wizard_start_options")
        if called and result:
            groups += [g for g in result if isinstance(g, StartGroup)]
    return groups


def edition() -> Edition:
    """Cached edition name. An undocumented `edition()` hook may add one lowercase word (1-12
    letters) after "magnacoda"; anything else is ignored with a warning."""
    global _edition
    if _edition is None:
        claims = []
        for plugin in loaded():
            called, result = _call(plugin, "edition")
            if not called or result is None:
                continue
            if isinstance(result, str) and _EDITION_WORD.fullmatch(result):
                claims.append((plugin, Edition(result)))
            else:
                _warn(
                    f"The add-on {plugin.label} gave an edition name that is not one short "
                    "lowercase word; ignored."
                )
        disagreeing = [(plugin, claim) for plugin, claim in claims[1:] if claim != claims[0][1]]
        if disagreeing:  # several add-ons naming the same edition (one package's parts) is fine
            others = ", ".join(plugin.label for plugin, _ in disagreeing)
            _warn(
                f"More than one add-on names the edition; using {claims[0][0].label}'s (ignored: {others})."
            )
        _edition = claims[0][1] if claims else Edition()
    return _edition
