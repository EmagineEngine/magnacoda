"""Opening an address in the person's own web browser, quietly.

The browser is started with its output thrown away, so its log lines (Brave's "Broken pipe", say)
never land on the screen. A browser that would run inside the terminal (lynx, w3m) is never used:
with no graphical browser, nothing is opened. Standard library only.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import webbrowser
from collections.abc import Callable
from pathlib import Path


def browser_available() -> bool:
    """Whether a graphical web browser can be opened here (not over SSH without a display, and not
    a browser that runs inside the terminal, which would take over the screen)."""
    if sys.platform.startswith("linux") and not (
        os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
    ):
        return False
    try:
        browser = webbrowser.get()
    except webbrowser.Error:
        return False
    in_terminal = isinstance(browser, webbrowser.GenericBrowser) and not isinstance(
        browser, webbrowser.BackgroundBrowser
    )
    return not in_terminal


def open_link(url: str) -> str:
    """Open a web address from a document, for a pager; -> a short line saying what happened.

    Only http and https addresses are opened, so a file can't make it start anything else.
    """
    if not url.lower().startswith(("http://", "https://")):
        return "Only web addresses (http and https) open from here."
    if not browser_available():
        return "No browser to open it in here."
    try:
        open_in_browser(url)
    except (OSError, webbrowser.Error):
        return "The browser didn't start."
    return "Opened in your browser."


_NEW_WINDOW_BROWSERS = ("firefox", "chrome", "chromium", "brave", "msedge", "edge", "vivaldi")


def open_in_browser(
    url: str, window: str = "tab", launch: Callable[[list[str]], object] | None = None
) -> None:
    """Open the page in the user's own browser (not the scanning Chromium); window="new" asks for a new
    window where the browser supports --new-window."""
    launch = launch or _launch_quietly
    if window == "new":
        program = _default_browser_program()
        if program and any(name in Path(program).name.lower() for name in _NEW_WINDOW_BROWSERS):
            try:
                launch([program, "--new-window", url])
                return
            except OSError:
                pass
    command = _browser_command(url)
    if command:
        try:
            launch(command)
            return
        except OSError:
            pass
    webbrowser.open(url, new=1)


def _launch_quietly(args: list[str]) -> None:
    """Start the browser with its output thrown away, so its log lines don't land in the shell."""
    subprocess.Popen(  # noqa: S603
        args,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def _browser_command(url: str) -> list[str] | None:
    """The command webbrowser would run (xdg-open on Linux, say), or None where it doesn't run one."""
    try:
        browser = webbrowser.get()
    except webbrowser.Error:
        return None
    if not isinstance(browser, webbrowser.GenericBrowser):
        return None  # macOS and Windows open it through the system, with no output of their own
    return [browser.name, *(arg.replace("%s", url) for arg in browser.args)]


def _default_browser_program() -> str | None:
    """The default browser's program, where the system says which it is (Linux desktops, Windows)."""
    try:
        if sys.platform.startswith("linux"):
            name = subprocess.run(  # noqa: S603, S607 - a fixed, read-only query
                ["xdg-settings", "get", "default-web-browser"], capture_output=True, text=True, timeout=5
            ).stdout.strip()
            return _program_from_desktop_file(name)
        if sys.platform == "win32":  # pragma: no cover - only runs on Windows
            import winreg

            key = r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as choice:
                prog_id = winreg.QueryValueEx(choice, "ProgId")[0]
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, rf"{prog_id}\shell\open\command") as command:
                line = winreg.QueryValueEx(command, "")[0]
            return line.split('"')[1] if line.startswith('"') else line.split()[0]
    except (OSError, subprocess.SubprocessError, IndexError):
        return None
    return None


def _program_from_desktop_file(name: str) -> str | None:
    if not name.endswith(".desktop"):
        return None
    homes = [os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")]
    homes += (os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":")
    for base in homes:
        path = Path(base) / "applications" / name
        if path.is_file():
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.startswith("Exec="):
                    program = line[5:].split()[0]
                    return shutil.which(program) or program
    return None
