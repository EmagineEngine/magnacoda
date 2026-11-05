"""Enable virtual terminal processing on the classic Windows console (like colorama's
just_fix_windows_console), and ask the terminal for its background. Windows Terminal and the IDE
terminals that bring their own console bridge answer; the classic console and Git Bash's mintty on
Windows 10 don't. Elsewhere this does nothing.
"""

from __future__ import annotations

import re
import sys
import time
from typing import Any

from magnacoda.pager.screen import RGB

_ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
_STD_INPUT_HANDLE, _STD_OUTPUT_HANDLE, _STD_ERROR_HANDLE = -10, -11, -12
_LINE_INPUT, _ECHO_INPUT, _VIRTUAL_TERMINAL_INPUT = 0x0002, 0x0004, 0x0200
_QUESTION = "\x1b]11;?\x1b\\\x1b[c"  # the background, then a question every terminal answers (DA1)
_BACKGROUND = re.compile(r"\x1b\]11;rgb:([0-9a-fA-F]{1,4})/([0-9a-fA-F]{1,4})/([0-9a-fA-F]{1,4})")
_LAST_REPLY = re.compile(r"\x1b\[\?[0-9;]*c")


def enable_virtual_terminal() -> bool:
    """True if stdout handles control codes now (always True off Windows)."""
    if sys.platform != "win32":
        return True
    _enable(_STD_ERROR_HANDLE)
    return _enable(_STD_OUTPUT_HANDLE)


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


def _kernel32() -> Any:
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    k32.GetStdHandle.restype = wintypes.HANDLE
    k32.GetConsoleMode.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    k32.SetConsoleMode.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    return k32


def _mode(k32: Any, handle: Any) -> int | None:
    import ctypes
    from ctypes import wintypes

    mode = wintypes.DWORD()
    return mode.value if k32.GetConsoleMode(handle, ctypes.byref(mode)) else None


def background(wait: float = 0.2) -> RGB | None:
    """The terminal's background, or None when it doesn't say or isn't a console."""
    if sys.platform != "win32":
        return None
    try:
        return _ask_background(wait)
    except (AttributeError, OSError, ValueError):
        return None


def _ask_background(wait: float) -> RGB | None:  # pragma: no cover - only runs on Windows
    import msvcrt

    k32 = _kernel32()
    hin, hout = k32.GetStdHandle(_STD_INPUT_HANDLE), k32.GetStdHandle(_STD_OUTPUT_HANDLE)
    in_mode, out_mode = _mode(k32, hin), _mode(k32, hout)
    if in_mode is None or out_mode is None:
        return None
    reply = ""
    try:
        k32.SetConsoleMode(hin, (in_mode | _VIRTUAL_TERMINAL_INPUT) & ~(_LINE_INPUT | _ECHO_INPUT))
        k32.SetConsoleMode(hout, out_mode | _ENABLE_VIRTUAL_TERMINAL_PROCESSING)
        while msvcrt.kbhit():  # type: ignore[attr-defined]
            msvcrt.getwch()  # type: ignore[attr-defined]
        sys.stdout.write(_QUESTION)
        sys.stdout.flush()
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline and not _LAST_REPLY.search(reply):
            if msvcrt.kbhit():  # type: ignore[attr-defined]
                reply += msvcrt.getwch()  # type: ignore[attr-defined]
            else:
                time.sleep(0.001)
    finally:
        k32.SetConsoleMode(hin, in_mode)
        k32.SetConsoleMode(hout, out_mode)
    return parse_background(reply)


def parse_background(reply: str) -> RGB | None:
    """The color in the terminal's answer to the background question (1 to 4 hex digits a channel)."""
    match = _BACKGROUND.search(reply)
    if match is None:
        return None
    r, g, b = (int(digits, 16) * 255 // (16 ** len(digits) - 1) for digits in match.groups())
    return r, g, b
