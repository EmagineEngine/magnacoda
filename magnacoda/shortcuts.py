"""Menu and desktop shortcuts that open a terminal with the magnacoda shell, made by pyshortcuts.

The menu is the app menu on Linux, the Start menu on Windows and the Applications folder on macOS.
pyshortcuts has no way to remove a shortcut, so remove() deletes the files it makes.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

NAME = "magnacoda"
DESCRIPTION = "Scan for web accessibility issues. Learn to fix them."
WINDOWS_KEY = "Ctrl+Alt+M"
_ICONS = Path(__file__).parent / "data" / "icons"


class ShortcutError(Exception):
    """A shortcut couldn't be made; the message says why, for the user."""


def menu_name() -> str:
    if sys.platform == "win32":
        return "Start menu"
    if sys.platform == "darwin":
        return "Applications folder"
    return "app menu"


def _pyshortcuts() -> ModuleType:
    # On Windows, importing it prints a line about conda environments.
    with contextlib.redirect_stdout(io.StringIO()):
        import pyshortcuts
    return pyshortcuts


@dataclass(frozen=True)
class Places:
    menu: Path
    desktop: Path


def places() -> Places:
    """Where the shortcuts go, whether or not they exist."""
    pyshortcuts = _pyshortcuts()
    folders = pyshortcuts.get_folders()
    target = f"{NAME}.{pyshortcuts.scut_ext}"
    menu = Path("/Applications") if sys.platform == "darwin" else Path(folders.startmenu)
    return Places(menu / target, Path(folders.desktop) / target)


def existing() -> list[Path]:
    where = places()
    return [path for path in (where.menu, where.desktop) if path.exists()]


def _launcher() -> Path:
    """The magnacoda command. pipx and uv keep it beside the tool's own Python."""
    name = "magnacoda.exe" if sys.platform == "win32" else "magnacoda"
    beside = Path(sys.executable).parent / name
    if beside.exists():
        return beside
    found = shutil.which("magnacoda")
    if found is None:
        raise ShortcutError("Couldn't find the magnacoda command, so there's nothing for a shortcut to open.")
    return Path(found)


def _icon() -> Path:
    kind = {"win32": "ico", "darwin": "icns"}.get(sys.platform, "svg")
    return _ICONS / f"magnacoda.{kind}"


def add(menu: bool = True, desktop: bool = False) -> list[Path]:
    """Make the shortcuts asked for; the paths made."""
    pyshortcuts = _pyshortcuts()
    launcher = _launcher()
    # pyshortcuts splits the command at its first space and joins it back up after, so quotes keep a path
    # with spaces in one piece. On Windows it quotes the program itself.
    program = str(launcher) if sys.platform == "win32" else f'"{launcher}"'
    mac = sys.platform == "darwin"
    try:
        pyshortcuts.make_shortcut(
            "shell --from-shortcut",
            name=NAME,
            description=DESCRIPTION,
            icon=str(_icon()),
            executable=program,
            terminal=True,
            desktop=desktop,
            startmenu=menu and not mac,
            macos_app=menu and mac,
        )
    except OSError as error:
        raise ShortcutError(f"Couldn't make the shortcut: {error}") from error
    where = places()
    made = [path for path, wanted in ((where.menu, menu), (where.desktop, desktop)) if wanted]
    if sys.platform == "win32":
        _finish_windows(made, where.menu)
    elif not mac:
        _finish_linux(where.menu if menu else None, where.desktop if desktop else None)
    return made


def _finish_windows(made: list[Path], menu: Path) -> None:
    """A normal window (pyshortcuts asks for style 0), and the shortcut key on the Start menu's."""
    import win32com.client  # comes with pyshortcuts on Windows

    shell = win32com.client.Dispatch("WScript.Shell")
    for path in made:
        link = shell.CreateShortCut(str(path))
        link.WindowStyle = 1
        if path == menu:
            link.Hotkey = WINDOWS_KEY.upper()
        link.save()


def _finish_linux(menu: Path | None, desktop: Path | None) -> None:
    """A menu category, and on the desktop, the trust GNOME and Xfce ask for before opening it."""
    if menu is not None:
        text = menu.read_text(encoding="utf-8")
        if "Categories=" not in text:
            menu.write_text(text + "Categories=Development;\n", encoding="utf-8")
    if desktop is not None:
        checksum = hashlib.sha256(desktop.read_bytes()).hexdigest()
        for key, value in (("metadata::trusted", "true"), ("metadata::xfce-exe-checksum", checksum)):
            with contextlib.suppress(OSError):
                subprocess.run(["gio", "set", "-t", "string", str(desktop), key, value], capture_output=True)


def remove() -> list[Path]:
    """Delete the shortcuts that exist; the paths deleted."""
    gone = existing()
    for path in gone:
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
    return gone
