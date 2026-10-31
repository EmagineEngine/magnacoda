"""Whether a screen reader seems to be running, and a one-time offer to turn off what reads poorly with
one: typed-out text, the spinner and paging. The `screenreader` command turns them off and on.

Offered once, at the start of the shell or the wizard, only when a screen reader is found and one of
those is still on. Nothing changes unless the person says yes; the answer is kept in
screen-reader-state.json, so it's never asked again.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import click

from magnacoda import preferences, questions
from magnacoda.userdir import config_dir, write_private
from magnacoda.wrapping import wrap_for_stream

# Process names of screen readers: Orca and Fenrir (Linux), VoiceOver (macOS).
_LINUX_READERS = ("orca", "fenrir")
_SPEAKUP = Path("/sys/accessibility/speakup")  # Linux's console screen reader, when loaded
_SPI_GETSCREENREADER = 0x0046  # Windows: set by NVDA, JAWS, Narrator and others
# (section, key); each key is also a Preferences field.
_SETTINGS = (("display", "typing"), ("display", "spinner"), ("pager", "paging"))


def state_path() -> Path:
    return config_dir() / "screen-reader-state.json"


def running() -> bool:
    """Whether a screen reader seems to be running on this computer. Never raises."""
    if os.environ.get("SSH_CONNECTION") or os.environ.get("SSH_TTY"):
        return False  # any screen reader is on the other computer
    try:
        if sys.platform == "win32":
            return _windows()
        if sys.platform == "darwin":
            return _voiceover()
        return _linux()
    except Exception:  # noqa: BLE001 - a check that fails means no offer, nothing more
        return False


def _windows() -> bool:
    import ctypes

    flag = ctypes.c_int(0)
    ctypes.windll.user32.SystemParametersInfoW(_SPI_GETSCREENREADER, 0, ctypes.byref(flag), 0)  # type: ignore[attr-defined]
    return bool(flag.value)


def _voiceover() -> bool:
    return subprocess.run(["pgrep", "-x", "VoiceOver"], capture_output=True, timeout=2).returncode == 0


def _linux() -> bool:
    if _SPEAKUP.exists():
        return True
    for comm in Path("/proc").glob("[0-9]*/comm"):
        try:
            name = comm.read_text(encoding="utf-8").strip().lower()
        except OSError:
            continue  # the process ended, or isn't ours to read
        if name.startswith(_LINUX_READERS):
            return True
    return False


def _asked() -> bool:
    try:
        return bool(json.loads(state_path().read_text(encoding="utf-8")).get("asked"))
    except (OSError, ValueError, AttributeError):
        return False


def offer() -> None:
    """Ask once, if a screen reader is running, whether to turn off typing, the spinner and paging."""
    try:
        if not (sys.stdin.isatty() and sys.stdout.isatty()) or _asked():
            return
    except (AttributeError, ValueError):
        return
    current = preferences.load()
    still_on = [(section, key) for section, key in _SETTINGS if getattr(current, key)]
    if not still_on or not running():
        return
    try:
        write_private(state_path(), json.dumps({"asked": True}) + "\n")  # Ctrl+C or q is an answer too
    except OSError:
        pass
    click.echo(
        wrap_for_stream(
            "A screen reader seems to be running. Text typed out a little at a time, the spinner and "
            "paging can be hard to follow with one.",
            sys.stdout,
        )
    )
    questions.printed("\n")
    try:
        if not questions.ask_yes_no("Turn them off?", default=True):
            click.echo("Left on. To turn them off later, type screenreader on.\n")
            return
    except click.Abort:
        return
    try:
        for section, key in still_on:
            preferences.set_value(section, key, "off")
    except OSError as exc:
        click.echo(f"Couldn't change {preferences.preferences_path()}: {exc}.\n")
        return
    click.echo("Turned off. To turn them back on, type screenreader off.\n")


def settings_on() -> list[str]:
    """Which of typing, the spinner and paging are on."""
    current = preferences.load()
    return [key for _, key in _SETTINGS if getattr(current, key)]


def set_mode(reader: bool) -> None:
    """With `reader`, typing, the spinner and paging off; else on. The offer isn't made again.
    Raises OSError."""
    for section, key in _SETTINGS:
        preferences.set_value(section, key, "off" if reader else "on")
    try:
        write_private(state_path(), json.dumps({"asked": True}) + "\n")
    except OSError:
        pass
