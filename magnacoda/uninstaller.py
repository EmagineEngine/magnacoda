"""The `uninstall` command's parts: the command that removes magnacoda, and the folders it can take along.

Installers never run a package's own code when they remove it, so this is where the rest goes: the
shortcuts, and if the user says so, the settings folder, Playwright's Chromium and the saved scans.
"""

from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from magnacoda import saved_reports, updater
from magnacoda.report import paths
from magnacoda.updater import DEV, PIPX, SHOW, UV, VENV, Plan

UNINSTALL_WORDS = updater.Words(
    action="uninstall",
    waiting="magnacoda will be uninstalled as soon as it has stopped.",
    go="Press Enter to uninstall now (or close this window to cancel)",
    again="magnacoda was started again, so nothing was uninstalled. Quit it and run uninstall again.",
    starting=("Uninstalling. Please wait: nothing more appears here until it has finished.",),
    done="Done. magnacoda is uninstalled.",
    failed="The uninstall did not finish. The last lines of its log:",
    fix="To finish it yourself, run:",
)

# What `playwright install chromium` downloads. Other Playwright browsers (firefox-*, webkit-*) stay.
_CHROMIUM_PARTS = ("chromium-", "chromium_headless_shell-", "ffmpeg-", "winldd-")


def plan(addons: list[str], kind: str | None = None, pipx: str | None = None, uv: str | None = None) -> Plan:
    """The commands that remove magnacoda (and, from a virtual environment, its add-on packages)."""
    kind = updater.install_kind() if kind is None else kind
    if kind == DEV:
        return Plan(
            DEV,
            [],
            "This is a development install, so the program stays: delete the checkout "
            "yourself when you no longer need it.",
        )
    if kind == PIPX:
        pipx = shutil.which("pipx") if pipx is None else pipx
        commands = [[pipx or "pipx", "uninstall", "magnacoda"]]  # add-ons go with its environment
        if pipx:
            return Plan(PIPX, commands)
        python = "py" if sys.platform == "win32" else "python3"
        return Plan(
            SHOW,
            [*commands, [python, "-m", "pipx", "uninstall", "magnacoda"]],
            "pipx isn't on your PATH here, so run this yourself. If you run pipx through Python, use the "
            "second one:",
        )
    if kind == UV:
        uv = shutil.which("uv") if uv is None else uv
        commands = [[uv or "uv", "tool", "uninstall", "magnacoda"]]
        if uv:
            return Plan(UV, commands)
        return Plan(SHOW, commands, "uv isn't on your PATH here, so run this yourself:")
    if kind == VENV:
        return Plan(
            VENV,
            [[sys.executable, "-m", "pip", "uninstall", "--yes", "magnacoda", *addons]],
            f"The virtual environment itself stays ({sys.prefix}). Delete it too if you made it just "
            "for magnacoda.",
        )
    return Plan(
        SHOW,
        [["pipx", "uninstall", "magnacoda"], ["python", "-m", "pip", "uninstall", "magnacoda", *addons]],
        "magnacoda can't tell how it was installed here, so it won't remove the program itself. Run the "
        "command that matches how you installed it: pipx, or pip for the Python you used.",
    )


def chromium_parts(folder: Path) -> list[Path]:
    """The Chromium that setup downloaded, in Playwright's browser folder; [] if none."""
    try:
        return sorted(entry for entry in folder.iterdir() if entry.name.startswith(_CHROMIUM_PARTS))
    except OSError:
        return []


@dataclass(frozen=True)
class Scans:
    folder: Path
    paths: list[Path]  # each scan's folder, or an old loose checklist
    count: int


def saved_scans(folder: Path | None = None) -> Scans:
    """The saved scans in the scans folder; only what magnacoda made there, never other files."""
    folder = paths.scans_folder() if folder is None else folder
    found = saved_reports.scans(folder, limit=1_000_000)
    entries: list[Path] = []
    for scan in found:
        entries += [scan.folder] if scan.folder else [report.path for report in scan.reports]
    return Scans(folder, entries, len(found))


def size(path: Path) -> int:
    """Bytes in a file or folder; what can't be read counts as 0."""
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    for item in path.rglob("*"):
        try:
            if item.is_file() and not item.is_symlink():
                total += item.stat().st_size
        except OSError:
            pass
    return total


def megabytes(count: int) -> str:
    return f"{max(round(count / 1_000_000), 1):,} MB"


def delete(path: Path) -> bool:
    """Delete a file or folder; False if it (or part of it) couldn't be."""
    try:
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)
    except OSError:
        return False
    return True


def delete_scans(scans: Scans) -> bool:
    """Delete the scans, then the folder if nothing else is left in it. False if a scan stayed."""
    done = all([delete(path) for path in scans.paths])
    if _ours(scans.folder / ".gitignore"):
        delete(scans.folder / ".gitignore")
    try:
        scans.folder.rmdir()  # only if empty: anything else the user keeps there stays
    except OSError:
        pass
    return done


def _ours(marker: Path) -> bool:
    try:
        return marker.read_text(encoding="utf-8") == paths.SELF_IGNORE
    except OSError:
        return False


def delete_chromium(folder: Path) -> bool:
    """Delete Chromium, then Playwright's folder if only its bookkeeping (.links) is left."""
    done = all([delete(path) for path in chromium_parts(folder)])
    try:
        if {entry.name for entry in folder.iterdir()} <= {".links"}:
            shutil.rmtree(folder)
    except OSError:
        pass
    return done
