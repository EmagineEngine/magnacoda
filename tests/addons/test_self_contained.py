"""Add-ons that come with magnacoda live in magnacoda_addons/, one folder each. These tests keep each
folder self-contained, so it stays a true example of an add-on and can be copied out as a stand-alone
one, and keep the rest of magnacoda from depending on them."""

import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "magnacoda"
ADDONS = sorted(path.parent for path in (ROOT / "magnacoda_addons").glob("*/plugin.py"))

# What an add-on may import from magnacoda (CONTRIBUTING, "Add-ons"); everything else is internal.
PUBLIC = {
    "magnacoda.plugins",
    "magnacoda.savedcommand",
    "magnacoda.userdir",
    "magnacoda.preferences",
    "magnacoda.wrapping",
    "magnacoda.questions",
    "magnacoda.sections",
    "magnacoda.estimate",
    "magnacoda.findings.models",
}
THIRD_PARTY = {"click"}


def _imports(path: Path) -> list[tuple[str, int]]:
    """(module, level) for every import; level > 0 is a relative import."""
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found += [(alias.name, 0) for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module in ("magnacoda", "magnacoda_addons"):
                found += [(f"{node.module}.{alias.name}", 0) for alias in node.names]
            else:
                found.append((node.module or "", node.level))
    return found


def test_magnacoda_comes_with_add_ons():
    assert [path.name for path in ADDONS] == ["favorites"]


@pytest.mark.parametrize("addon", ADDONS, ids=lambda path: path.name)
def test_an_add_on_folder_uses_only_itself_magnacodas_public_parts_and_the_standard_library(addon):
    for path in addon.glob("*.py"):
        for module, level in _imports(path):
            if level == 1:
                continue  # from . import ...: its own folder
            top = module.split(".")[0]
            assert level == 0, f"{path.name}: imports from outside its folder ({'.' * level}{module})"
            if top == "magnacoda":
                assert module in PUBLIC, f"{path.name}: {module} is internal to magnacoda"
            else:
                assert top in sys.stdlib_module_names or top in THIRD_PARTY or top == "__future__", (
                    f"{path.name}: imports {module}"
                )


@pytest.mark.parametrize("addon", ADDONS, ids=lambda path: path.name)
def test_an_add_on_folder_finds_its_own_files_wherever_it_is_copied(addon):
    for path in addon.glob("*.py"):
        assert 'resources.files("magnacoda' not in path.read_text(encoding="utf-8"), path.name


def test_the_rest_of_magnacoda_never_imports_its_add_ons():
    for path in PACKAGE.rglob("*.py"):
        where = path.relative_to(PACKAGE)
        for module, _level in _imports(path):
            assert not module.startswith("magnacoda_addons"), f"{where} imports {module}"
