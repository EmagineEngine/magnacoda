from __future__ import annotations

import json
import stat
from pathlib import Path

from magnacoda.userdir import config_dir


def credentials_dir() -> Path:
    """Per-user config directory for magnacoda, following each OS's convention."""
    return config_dir()


def credentials_path() -> Path:
    return credentials_dir() / "credentials.json"


def _read_all() -> dict[str, str]:
    path = credentials_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def load_stored_key(api_key_env: str) -> str | None:
    value = _read_all().get(api_key_env)
    return value if isinstance(value, str) and value else None


def save_key(api_key_env: str, value: str) -> Path:
    """Save a key under its env var name, owner-only on POSIX (Windows relies on %APPDATA% being per-user)."""
    path = credentials_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _read_all()
    data[api_key_env] = value
    path.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0o600
    except OSError:
        pass
    return path


def clear_key(api_key_env: str) -> bool:
    """Remove a stored key. Returns True if something was actually removed."""
    data = _read_all()
    if api_key_env not in data:
        return False
    del data[api_key_env]
    path = credentials_path()
    if data:
        path.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
    else:
        path.unlink(missing_ok=True)
    return True
