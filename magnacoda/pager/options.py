"""What the pager does, from three places in order: these defaults, a settings file, then the options
the program passes when it opens the pager (any it passes win).

On its own the pager reads its own settings file (default_settings_path). A program that uses it can
point it at a section of the program's own file instead, so its users keep one settings file.
"""

from __future__ import annotations

import configparser
import dataclasses
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from magnacoda.pager.themes import FILE_NAME as COLORS_FILE

DocumentTitle = Literal["drop", "first_page"]
Start = Literal["first_page", "section_list"]

# The folder for the pager's own settings file. Rename it with the package.
SETTINGS_FOLDER = "pager"
SETTINGS_SECTION = "pager"


@dataclass(frozen=True)
class PagerOptions:
    # Text on the top row, such as "myapp - README". None: no title row.
    title_bar: str | None = None
    # A document's own `# Title` line: drop it (when the title bar already names the document) or show
    # it in bold at the top of the first page.
    document_title: DocumentTitle = "first_page"
    # Open on the first page, or on the list of sections (g) when there is more than one.
    start: Start = "first_page"
    # Leave out a document's own table of contents; the g list does its job.
    hide_contents: bool = True
    # Show a link to another section as "text (section N)", N as in the g list.
    number_links: bool = True
    # Page one screen at a time; off prints everything at once (as when output isn't a terminal).
    paging: bool = True
    # An environment variable that turns paging off when set to off, 0, false or no.
    off_switch_env: str | None = None
    # The name of the text before a document's first `##` section.
    first_section: str = "Introduction"
    # Colors: default (the terminal's own), a name from colors.py or one from the colors file. c
    # changes them.
    colors: str = "default"
    # Web addresses as terminal hyperlinks, never broken across lines (see links.py), where the
    # terminal is likely to have them; off shows links as "text (address)".
    hyperlinks: bool = True
    # Blend between a dark and a light background (opening, choosing under c, leaving), in full color.
    fade: bool = True
    # After the window was resized while paging, the screen the pager restores may look broken: ask the
    # program to start a fresh page when the pager closes (Outcome.resized tells it a resize happened).
    refresh_after_resize: bool = False
    # The Open list (o): a list file of documents (documents.py). None: no o key.
    documents: Path | None = None
    # The Open list also opens a .md or .txt file typed by name.
    typed_files: bool = True
    # The first section lists the others (as a news page lists its items): the g list numbers them
    # from 1 and leaves it out, and b goes back to it.
    front_page: bool = False
    # Where the settings came from, so a color chosen with c is saved there (set by resolve).
    settings_path: Path | None = None
    settings_section: str = SETTINGS_SECTION
    # The person's own color themes (themes.py), beside the settings file (set by resolve).
    colors_file: Path | None = None


# The settings a person may change in the file. The others belong to the program opening the pager.
FILE_SETTINGS = (
    "document_title",
    "start",
    "hide_contents",
    "number_links",
    "paging",
    "colors",
    "hyperlinks",
    "fade",
    "refresh_after_resize",
)
_CHOICES: dict[str, tuple[str, ...]] = {
    "document_title": ("drop", "first_page"),
    "start": ("first_page", "section_list"),
}
_COLOR_NAME = re.compile(r"[a-z][a-z0-9_]{0,29}")  # built in or from the colors file; unknown: default


def default_settings_path() -> Path:
    """The pager's own settings file, in the usual per-user settings folder for the system."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / SETTINGS_FOLDER / "pager.ini"


def read_settings(path: Path, section: str = SETTINGS_SECTION) -> dict[str, Any]:
    """The valid settings in `section` of an INI file. A missing file or a bad value is left out."""
    parser = configparser.ConfigParser(inline_comment_prefixes=("#", ";"))
    try:
        parser.read(path, encoding="utf-8")
    except (configparser.Error, OSError, UnicodeError):
        return {}
    if not parser.has_section(section):
        return {}
    found: dict[str, Any] = {}
    for key in FILE_SETTINGS:
        if not parser.has_option(section, key):
            continue
        if key in _CHOICES or key == "colors":
            value = parser.get(section, key).strip().lower().replace("-", "_").replace(" ", "_")
            if value in _CHOICES.get(key, ()) or (key == "colors" and _COLOR_NAME.fullmatch(value)):
                found[key] = value
            continue
        try:
            found[key] = parser.getboolean(section, key)  # on/off, yes/no, true/false, 1/0
        except ValueError:
            pass
    return found


def resolve(
    settings_file: Path | None = None, section: str = SETTINGS_SECTION, **launch: Any
) -> PagerOptions:
    """Defaults, then the settings file (default_settings_path() unless given), then `launch` (None
    values are ignored, so a program can pass through options it doesn't set)."""
    path = default_settings_path() if settings_file is None else settings_file
    unknown = set(launch) - {field.name for field in dataclasses.fields(PagerOptions)}
    if unknown:
        raise TypeError(f"unknown pager options: {', '.join(sorted(unknown))}")
    values: dict[str, Any] = {
        "settings_path": path,
        "settings_section": section,
        "colors_file": path.parent / COLORS_FILE,
    }
    values.update(read_settings(path, section))
    values.update({key: value for key, value in launch.items() if value is not None})
    return PagerOptions(**values)


_WORD = re.compile(r"[a-z0-9_-]{1,30}")


def _contents(text: str) -> dict[str, dict[str, str]]:
    parser = configparser.ConfigParser(inline_comment_prefixes=("#", ";"), interpolation=None)
    parser.read_string(text)
    return {name: dict(parser.items(name)) for name in parser.sections()}


def save_setting(path: Path, section: str, key: str, value: str) -> bool:
    """Set `key = value` in `section` of an INI file, keeping everything else as it is: the line is
    changed in place, added under the section's heading, or the section is added at the end.

    Nothing is written when the file can't be read cleanly, or when reading the new text back shows
    that anything else would change; the file is replaced in one step. Returns whether it was saved.
    """
    if not (_WORD.fullmatch(key) and _WORD.fullmatch(value) and _WORD.fullmatch(section)):
        return False
    try:
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        before = _contents(text)
    except (configparser.Error, OSError, UnicodeError):
        return False
    heading = re.search(rf"^\[{re.escape(section)}\][ \t]*$", text, re.MULTILINE | re.IGNORECASE)
    if heading is None:
        new = text + ("\n" if text and not text.endswith("\n") else "") + f"\n[{section}]\n{key} = {value}\n"
    else:
        rest = text[heading.end() :]
        end = re.search(r"^\[", rest, re.MULTILINE)
        body, after = (rest[: end.start()], rest[end.start() :]) if end else (rest, "")
        line = re.compile(rf"^({re.escape(key)}[ \t]*[=:]).*$", re.MULTILINE | re.IGNORECASE)
        if line.search(body):
            body = line.sub(lambda m: f"{m.group(1)} {value}", body, count=1)
        else:
            body = f"\n{key} = {value}" + body
        new = text[: heading.end()] + body + after
    expected = {name: dict(values) for name, values in before.items()}
    expected.setdefault(section, {})[key] = value
    try:
        if _contents(new) != expected:
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
        with os.fdopen(handle, "w", encoding="utf-8") as file:
            file.write(new)
        if path.exists():
            os.chmod(temporary, path.stat().st_mode & 0o777)
        os.replace(temporary, path)
    except (configparser.Error, OSError):
        return False
    return True
