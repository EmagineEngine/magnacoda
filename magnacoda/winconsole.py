"""Enable virtual terminal processing on the classic Windows console (like colorama's
just_fix_windows_console), and ask the terminal for its background. Windows Terminal and the IDE
terminals that bring their own console bridge answer; the classic console and Git Bash's mintty on
Windows 10 don't. Elsewhere this does nothing.
"""

from __future__ import annotations

import os
import re
import sys

from magnacoda.pager.screen import RGB, windows_console_reply

_ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
_STD_OUTPUT_HANDLE, _STD_ERROR_HANDLE = -11, -12
_QUESTION = "\x1b]11;?\x1b\\\x1b[c"  # the background, then a question every terminal answers (DA1)
_BACKGROUND = re.compile(r"\x1b\]11;rgb:([0-9a-fA-F]{1,4})/([0-9a-fA-F]{1,4})/([0-9a-fA-F]{1,4})")


def enable_virtual_terminal() -> bool:
    """True if stdout handles control codes now (always True off Windows). Every Windows console that
    does handles full color, but none says so in COLORTERM, which the pager goes by; so this does."""
    if sys.platform != "win32":
        return True
    _enable(_STD_ERROR_HANDLE)
    enabled = _enable(_STD_OUTPUT_HANDLE)
    if enabled and not os.environ.get("COLORTERM"):
        os.environ["COLORTERM"] = "truecolor"
    return enabled


def _enable(which: int) -> bool:  # pragma: no cover - only runs on Windows
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.GetStdHandle(which)
        mode = wintypes.DWORD()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        if mode.value & _ENABLE_VIRTUAL_TERMINAL_PROCESSING:
            return True
        return bool(kernel32.SetConsoleMode(handle, mode.value | _ENABLE_VIRTUAL_TERMINAL_PROCESSING))
    except Exception:  # noqa: BLE001 - if unsure, leave the console as it is
        return False


def background(wait: float = 0.2) -> RGB | None:
    """The terminal's background, or None when it doesn't say or isn't a console."""
    if sys.platform != "win32":
        return None
    try:
        return _ask_background(wait)
    except (AttributeError, OSError, ValueError):
        return None


def _ask_background(wait: float) -> RGB | None:  # pragma: no cover - only runs on Windows
    return parse_background(windows_console_reply(_QUESTION, sys.stdout, wait))


def parse_background(reply: str) -> RGB | None:
    """The color in the terminal's answer to the background question (1 to 4 hex digits a channel)."""
    match = _BACKGROUND.search(reply)
    if match is None:
        return None
    r, g, b = (int(digits, 16) * 255 // (16 ** len(digits) - 1) for digits in match.groups())
    return r, g, b
