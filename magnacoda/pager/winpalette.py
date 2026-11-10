"""The colors a Windows terminal that doesn't answer the color question (OSC 10 and 11) is set to.

The classic console keeps its palette where a program can read it. Git Bash's mintty keeps its colors
in its settings file (and the theme file that names). Both are only guesses at what is on screen, used
when the terminal itself gives no answer. Standard library only.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
from collections.abc import Mapping
from pathlib import Path

RGB = tuple[int, int, int]
Pair = tuple[RGB, RGB]  # (text, background)

_VALUE = re.compile(r"^\s*(ForegroundColour|BackgroundColour|Theme|ThemeFile)\s*=\s*(.*?)\s*$", re.M)
_DECIMAL = re.compile(r"^(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})$")
_HEX = re.compile(r"^#([0-9a-fA-F]{2})([0-9a-fA-F]{2})([0-9a-fA-F]{2})$")


def configured(env: Mapping[str, str] | None = None, home: Path | None = None) -> Pair | None:
    """The (text, background) the terminal is set to, or None when that can't be found."""
    env = os.environ if env is None else env
    if env.get("TERM_PROGRAM") == "mintty" or env.get("MSYSTEM"):
        return mintty(env, home or Path.home())
    return console_palette()


def console_palette() -> Pair | None:
    """The classic console's default text and background, from its palette. Windows only."""
    if sys.platform != "win32":
        return None
    try:
        return _read_console()
    except (AttributeError, OSError, ValueError):
        return None


def _read_console() -> Pair | None:  # pragma: no cover - only runs on Windows
    import ctypes
    from ctypes import wintypes

    class Coord(ctypes.Structure):
        _fields_ = [("X", ctypes.c_short), ("Y", ctypes.c_short)]

    class Rect(ctypes.Structure):
        _fields_ = [(name, ctypes.c_short) for name in ("Left", "Top", "Right", "Bottom")]

    class Info(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.ULONG),
            ("dwSize", Coord),
            ("dwCursorPosition", Coord),
            ("wAttributes", wintypes.WORD),
            ("srWindow", Rect),
            ("dwMaximumWindowSize", Coord),
            ("wPopupAttributes", wintypes.WORD),
            ("bFullscreenSupported", wintypes.BOOL),
            ("ColorTable", wintypes.DWORD * 16),
        ]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    k32.GetStdHandle.restype = wintypes.HANDLE
    info = Info()
    info.cbSize = ctypes.sizeof(Info)
    if not k32.GetConsoleScreenBufferInfoEx(k32.GetStdHandle(-11), ctypes.byref(info)):
        return None
    return palette_pair(list(info.ColorTable), info.wAttributes)


def palette_pair(table: list[int], attributes: int) -> Pair:
    """(text, background) from the 16 console colors (0x00BBGGRR) and the current attributes."""

    def color(index: int) -> RGB:
        value = table[index]
        return value & 0xFF, (value >> 8) & 0xFF, (value >> 16) & 0xFF

    return color(attributes & 0xF), color((attributes >> 4) & 0xF)


def mintty(env: Mapping[str, str], home: Path) -> Pair | None:
    """The text and background colors in mintty's settings, and its theme's behind them."""
    folders = [home / ".config" / "mintty"]
    if env.get("APPDATA"):
        folders.append(Path(env["APPDATA"]) / "mintty")
    files = [home / ".minttyrc"] + [folder / "config" for folder in folders]
    found: dict[str, str] = {}
    for path in files:
        settings = _settings(path)
        if settings:
            found = settings
            break
    colors = dict(found)
    theme = found.get("Theme") or found.get("ThemeFile")
    if theme:
        shipped = (root / "usr" / "share" / "mintty" / "themes" for root in _git_folders(env))
        for place in [
            Path(theme),
            *(folder / "themes" / theme for folder in folders),
            *(f / theme for f in shipped),
        ]:
            theme_colors = _settings(place)
            if theme_colors:
                colors = {**theme_colors, **found}
                break
    text, back = _color(colors.get("ForegroundColour")), _color(colors.get("BackgroundColour"))
    return (text, back) if text and back else None


def _git_folders(env: Mapping[str, str]) -> list[Path]:
    """Where Git for Windows (which brings mintty and its themes) is installed, as far as we can tell."""
    found = [Path(env["EXEPATH"])] if env.get("EXEPATH") else []
    if git := shutil.which("git"):
        found.append(Path(git).resolve().parent.parent)  # <root>/cmd/git.exe
    for variable, name in (("ProgramFiles", "Git"), ("LOCALAPPDATA", "Programs/Git")):
        if env.get(variable):
            found.append(Path(env[variable]) / name)
    return found


def _settings(path: Path) -> dict[str, str]:
    try:
        return dict(_VALUE.findall(path.read_text(encoding="utf-8", errors="replace")))
    except OSError:
        return {}


def _color(value: str | None) -> RGB | None:
    if not value:
        return None
    if match := _DECIMAL.match(value):
        rgb = tuple(int(part) for part in match.groups())
    elif match := _HEX.match(value):
        rgb = tuple(int(part, 16) for part in match.groups())
    else:
        return None
    return rgb if max(rgb) <= 255 else None  # type: ignore[return-value]
