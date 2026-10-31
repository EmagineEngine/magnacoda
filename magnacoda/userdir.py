from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

# Deliberately outside any project directory (and so outside any .gitignore's reach) - the
# per-user config location convention used by gh, aws, npm, docker, etc.
APP_NAME = "magnacoda"


def config_dir() -> Path:
    """Per-user config directory for magnacoda, following each OS's convention."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / APP_NAME
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / APP_NAME


def write_private(path: Path, text: str) -> None:
    """Atomic write (temp file + rename), creating the folder, owner-only on POSIX."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    try:
        temporary.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0o600; a no-op in effect on Windows
    except OSError:
        pass
    os.replace(temporary, path)
