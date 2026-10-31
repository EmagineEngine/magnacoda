"""Enable virtual terminal processing on the classic Windows console (like colorama's
just_fix_windows_console). Windows Terminal already has it; elsewhere this does nothing.
"""

from __future__ import annotations

import sys

_ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
_STD_OUTPUT_HANDLE, _STD_ERROR_HANDLE = -11, -12


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
