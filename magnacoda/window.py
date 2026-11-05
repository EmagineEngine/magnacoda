"""A window a shortcut opened closes as soon as magnacoda exits, so first it waits for Enter: the last
lines stay up for as long as the reading takes, with nothing counting down."""

from __future__ import annotations

import os
import subprocess
import sys

ENTER_PROMPT = "Press Enter to close this window."

# Terminal on a Mac keeps the window after the shell exits when the profile says "Don't close the
# window", so a detached script closes it: the window whose only tab is on our terminal, once the
# shell (our parent) has ended, so nothing is running there and Terminal doesn't ask.
MAC_CLOSER = """
on run argv
    set myTty to item 1 of argv
    set shellPid to item 2 of argv
    tell application "Terminal"
        set theWindow to missing value
        repeat with w in windows
            if (count of tabs of w) is 1 and tty of tab 1 of w is myTty then
                set theWindow to id of w
                exit repeat
            end if
        end repeat
    end tell
    if theWindow is missing value then return
    repeat 100 times
        try
            do shell script "kill -0 " & shellPid
        on error
            delay 0.3
            tell application "Terminal"
                if exists window id theWindow then close window id theWindow
            end tell
            return
        end try
        delay 0.1
    end repeat
end run
"""


def before_closing() -> None:
    """Wait for Enter before the window closes."""
    try:
        input(ENTER_PROMPT)
    except (EOFError, KeyboardInterrupt):
        pass
    if sys.platform == "darwin":
        close_mac_window()


def close_mac_window() -> None:
    """Have Terminal close this window once the shell has ended; quietly nothing if that can't start."""
    try:
        tty = os.ttyname(sys.stdin.fileno())
        subprocess.Popen(
            ["osascript", "-e", MAC_CLOSER, tty, str(os.getppid())],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except (OSError, ValueError):
        pass
