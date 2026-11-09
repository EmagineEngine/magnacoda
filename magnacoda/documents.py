"""The documents the viewer's Open list (o) offers: magnacoda's own (data/documents.md), then the
license files of installed add-ons."""

from __future__ import annotations

from importlib import metadata, resources
from pathlib import Path

from magnacoda import plugins
from magnacoda.pager import Entry, read_list

LIST = "documents.md"
# Where a checkout keeps each document the package copies into data/ (pyproject.toml's force-include).
SOURCES = {
    "README.md": "README.md",
    "manual.md": "docs/manual.md",
    "CHANGELOG.md": "CHANGELOG.md",
    "CONTRIBUTING.md": "CONTRIBUTING.md",
    "add-ons.md": "docs/add-ons.md",
    "LICENSE.md": "LICENSE.md",
    "LICENSE-ADDITIONAL-PERMISSION.md": "LICENSE-ADDITIONAL-PERMISSION.md",
    "NOTICE.md": "NOTICE.md",
    "TRADEMARK.md": "TRADEMARK.md",
}
# The documents opened through their own commands, so they show as those commands show them.
COMMANDS = {"help.md": "help", "manual.md": "docs", "README.md": "readme"}
ADDONS = "Add-ons"


def locate(name: str) -> Path | None:
    """data/`name` when installed, else the repository's own copy in a checkout."""
    copy = Path(str(resources.files("magnacoda") / "data" / name))
    if copy.is_file():
        return copy
    source = SOURCES.get(name)
    path = Path(__file__).resolve().parents[1] / source if source else None
    return path if path is not None and path.is_file() else None


def command_for(path: Path) -> str | None:
    """The command that shows the document at `path`, if it's one of those."""
    name = next((name for name in COMMANDS if locate(name) == path), None)
    return COMMANDS[name] if name else None


def entries() -> list[Entry]:
    listed = locate(LIST)
    return (read_list(listed, locate) if listed else []) + addon_licenses()


def addon_licenses() -> list[Entry]:
    """Each installed add-on package's license files, as its package metadata lists them."""
    found, seen = [], set()
    for addon in plugins.loaded():
        if addon.bundled or addon.package in seen:
            continue
        seen.add(addon.package)
        try:
            dist = metadata.distribution(addon.package)
        except metadata.PackageNotFoundError:
            continue
        named = set(dist.metadata.get_all("License-File") or [])
        for file in dist.files or []:
            in_metadata = any(part.endswith(".dist-info") for part in file.parts[:-1])
            if not in_metadata or not (file.parent.name == "licenses" or file.name in named):
                continue
            path = Path(str(dist.locate_file(file)))
            if path.is_file():
                found.append(Entry(f"{addon.package}: {file.name}", path, ADDONS))
    return found
