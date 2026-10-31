from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import platformdirs

from magnacoda import preferences

DEFAULT_SCANS_DIR = "magnacoda-scans"
_SELF_IGNORE = "# Created by magnacoda: keeps saved scans out of git.\n*\n"


def scans_folder() -> Path:
    """Where scans are saved and looked for: [scan] folder in preferences.ini, else magnacoda-scans in
    Documents (platformdirs knows where that is, moved into OneDrive or renamed)."""
    chosen = preferences.load().scans_folder
    if chosen:
        return Path(chosen).expanduser()
    return Path(platformdirs.user_documents_dir()) / DEFAULT_SCANS_DIR


def short(path: Path) -> str:
    """The full path, with the home folder written as ~ so it fits on one line more often."""
    full = path.resolve()
    try:
        return os.path.join("~", str(full.relative_to(Path.home())))
    except ValueError:
        return str(full)


def make_self_ignoring(folder: Path) -> bool:
    """Put a `*` .gitignore in the scans folder, like pytest and mypy do for their caches.

    Never overwrites one. True if it wrote it.
    """
    marker = folder / ".gitignore"
    if marker.exists():
        return False
    try:
        marker.write_text(_SELF_IGNORE, encoding="utf-8")
    except OSError:
        return False
    return True


def default_report_stem(url: str, now: datetime) -> str:
    """File name (without extension) for an auto-saved report: site, path and time, e.g.
    'example.com_docs_intro_20260920-153012'."""
    parsed = urlparse(url)
    site = re.sub(r"[^A-Za-z0-9.-]+", "_", f"{parsed.netloc}{parsed.path}").strip("_")[:60].strip("_")
    return f"{site or 'scan'}_{now:%Y%m%d-%H%M%S}"
