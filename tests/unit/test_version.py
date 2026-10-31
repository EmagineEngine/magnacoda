import importlib
import re
from importlib import metadata
from pathlib import Path

import magnacoda

PYPROJECT = (Path(__file__).parent.parent.parent / "pyproject.toml").read_text(encoding="utf-8")


def test_version_comes_from_the_installed_package_metadata():
    assert magnacoda.__version__ == metadata.version("magnacoda")
    assert magnacoda.__version__ != "0+unknown"


def test_version_falls_back_when_the_package_is_not_installed(monkeypatch):
    def missing(name):
        raise metadata.PackageNotFoundError(name)

    monkeypatch.setattr(metadata, "version", missing)
    try:
        assert importlib.reload(magnacoda).__version__ == "0+unknown"
    finally:
        monkeypatch.undo()
        importlib.reload(magnacoda)
    assert magnacoda.__version__ == metadata.version("magnacoda")


def test_pyproject_takes_the_version_from_git_tags_not_a_hand_written_number():
    assert re.search(r'^dynamic = \[[^]]*"version"', PYPROJECT, re.M)
    assert '[tool.hatch.version]\nsource = "vcs"' in PYPROJECT
    assert "hatch-vcs" in PYPROJECT.split("[project]")[0]
    assert not [line for line in PYPROJECT.splitlines() if line.startswith("version =")]
