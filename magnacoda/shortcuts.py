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
    return [path for path in (where.menu, where.desktop) if path.exists() or path.is_symlink()]


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
            desktop=desktop and not mac,
            startmenu=menu and not mac,
            macos_app=mac,  # on a Mac the app always goes in Applications; the desktop gets a link to it
        )
    except OSError as error:
        raise ShortcutError(f"Couldn't make the shortcut: {error}") from error
    where = places()
    made = [path for path, wanted in ((where.menu, menu), (where.desktop, desktop)) if wanted]
    if sys.platform == "win32":
        _finish_windows(made, where.menu)
    elif mac:
        _finish_mac(where.menu, where.desktop if desktop else None, launcher)
        made = [where.menu, *([where.desktop] if desktop else [])]
    else:
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


def mac_launcher(command: str) -> str:
    """The app's AppleScript: Terminal comes to the front; when it wasn't running, magnacoda takes the
    window it opens at startup (if it opened just one), instead of a second, empty one; and the shell
    exits after magnacoda (which then has Terminal close the window, see `window.close_mac_window`)."""
    quoted = (command + "; exit").replace("\\", "\\\\").replace('"', '\\"')
    return "\n".join(
        [
            "#!/usr/bin/osascript",
            'set wasRunning to application "Terminal" is running',
            'tell application "Terminal"',
            "    activate",
            "    if wasRunning then",
            f'        do script "{quoted}"',
            "    else",
            "        repeat 50 times",
            "            if (count of windows) > 0 then exit repeat",
            "            delay 0.1",
            "        end repeat",
            "        if (count of windows) is 1 then",
            f'            do script "{quoted}" in window 1',
            "        else",
            f'            do script "{quoted}"',
            "        end if",
            "    end if",
            "    activate",
            "end tell",
            "",
        ]
    )


def _finish_mac(app: Path, desktop: Path | None, launcher: Path) -> None:
    """Our own launcher in the app, and on the desktop a link to the app rather than a second copy,
    which Launchpad would show as a second icon."""
    import shlex

    script = app / "Contents" / "MacOS" / NAME
    script.write_text(mac_launcher(f"{shlex.quote(str(launcher))} shell --from-shortcut"), encoding="utf-8")
    script.chmod(0o755)
    if desktop is not None:
        _delete(desktop)
        desktop.symlink_to(app)


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
        _delete(path)
    return gone


def _delete(path: Path) -> None:
    """A shortcut file, folder (a Mac app) or link; a link goes, never what it points to."""
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)
