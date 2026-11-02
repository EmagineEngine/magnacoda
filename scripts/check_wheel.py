"""Build the wheel, install it into a fresh environment and try the installed copy.

Tests run against an editable install, which reads the source folders, so they can't notice a file that
is missing from the wheel. This check can: it looks at what the wheel holds and runs the installed
magnacoda from an empty folder, with its own settings folder, the pager off and no network checks.
GitHub runs it on every pull request and push to main (`make check-wheel`); it needs no browser.

    python scripts/check_wheel.py              build the wheel, then check it
    python scripts/check_wheel.py dist/X.whl   check a wheel that is already built
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import venv
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Files the installed program reads at run time. A missing one breaks a command for everyone.
REQUIRED = [
    "magnacoda/data/README.md",
    "magnacoda/data/manual.md",
    "magnacoda/data/documents.md",
    "magnacoda/data/CHANGELOG.md",
    "magnacoda/data/CONTRIBUTING.md",
    "magnacoda/data/LICENSE.md",
    "magnacoda/data/LICENSE-ADDITIONAL-PERMISSION.md",
    "magnacoda/data/NOTICE.md",
    "magnacoda/data/TRADEMARK.md",
    "magnacoda/data/help.md",
    "magnacoda/data/tips.md",
    "magnacoda/data/whats-new.md",
    "magnacoda/data/wcag_criteria.json",
    "magnacoda/data/criteria_guidance.json",
    "magnacoda/data/review.html",
    "magnacoda/data/logo.svg",
    "magnacoda/data/icons/magnacoda.svg",
    "magnacoda/data/icons/magnacoda.ico",
    "magnacoda/data/icons/magnacoda.icns",
    "magnacoda/vendor/axe-core/axe.min.js",
    "magnacoda_addons/favorites/plugin.py",
    "magnacoda_addons/favorites/help.md",
    "magnacoda_addons/favorites/messages.md",
]


def build_wheel(out: Path) -> Path:
    subprocess.run([sys.executable, "-m", "build", "--wheel", "--outdir", str(out), str(ROOT)], check=True)
    return next(out.glob("*.whl"))


def pypi_page_problems(metadata: str) -> list[str]:
    """PyPI's copy of the README (hatch-fancy-pypi-readme, in pyproject.toml), in the wheel's METADATA."""
    page = metadata.partition("\n\n")[2]
    problems = []
    relative = re.findall(r"\]\((?!https?://|#|mailto:)([^)\s]+)\)", page)
    if relative:
        problems.append(f"the PyPI page has relative links, which go nowhere there: {relative}")
    pictures = re.findall(r'(?:src|srcset)="(?!https://raw\.githubusercontent\.com/)([^"]+)"', page)
    if pictures:
        problems.append(f"the PyPI page has pictures it can't show: {pictures}")
    for left_out in ("not-on-pypi", "once published to PyPI", "or straight from GitHub"):
        if left_out in page:
            problems.append(f"the PyPI page still has {left_out!r}")
    return problems


def wheel_problems(wheel: Path) -> list[str]:
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        entry_points = next((archive.read(n).decode() for n in names if n.endswith("entry_points.txt")), "")
        metadata = next((archive.read(n).decode() for n in names if n.endswith(".dist-info/METADATA")), "")
    problems = [f"the wheel is missing {name}" for name in REQUIRED if name not in names]
    problems += pypi_page_problems(metadata)
    twine = subprocess.run(
        [sys.executable, "-m", "twine", "check", "--strict", str(wheel)], capture_output=True, text=True
    )
    if twine.returncode != 0:
        problems.append(f"twine check: {twine.stdout.strip()[-300:]}")
    problems += [f"the wheel holds a test file: {name}" for name in names if "/tests/" in name]
    if "magnacoda_addons.favorites.plugin" not in entry_points:
        problems.append("the wheel doesn't register the favorites add-on (entry_points.txt)")
    return problems


def install(wheel: Path, where: Path) -> Path:
    """A fresh environment with only the wheel and its dependencies; returns its bin folder."""
    venv.create(where, with_pip=True)
    bin_dir = where / ("Scripts" if os.name == "nt" else "bin")
    subprocess.run([str(bin_dir / "python"), "-m", "pip", "install", "--quiet", str(wheel)], check=True)
    return bin_dir


def run_problems(bin_dir: Path, scratch: Path) -> list[str]:
    folder = scratch / "cwd"
    folder.mkdir()
    env = dict(os.environ)
    env.update(
        XDG_CONFIG_HOME=str(scratch / "config"),
        APPDATA=str(scratch / "config"),
        MAGNACODA_PAGER="off",
        MAGNACODA_NEWS="off",
        NO_COLOR="1",
    )
    env.pop("MAGNACODA_PLUGINS", None)
    checks = [
        (["magnacoda", "--version"], "magnacoda, version"),
        (["magnacoda", "about"], "favorites (built in"),
        (["magnacoda", "readme"], "Quick start"),
        (["magnacoda", "docs", "scan"], "--wait-for-selector"),
        (["magnacoda", "help"], "Save this as a favorite?"),
        (["python", "-c", "import magnacoda_addons.favorites.plugin"], ""),
    ]
    problems = []
    for command, expected in checks:
        program = str(bin_dir / command[0])
        result = subprocess.run(
            [program, *command[1:]],
            cwd=folder,
            env=env,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
        )
        shown = " ".join(command)
        if result.returncode != 0:
            problems.append(f"{shown} failed (exit {result.returncode}): {result.stderr.strip()[-300:]}")
        elif expected not in result.stdout:
            problems.append(f"{shown} didn't show {expected!r}")
    return problems


def main(argv: list[str]) -> int:
    with tempfile.TemporaryDirectory() as temporary:
        scratch = Path(temporary)
        wheel = Path(argv[0]).resolve() if argv else build_wheel(scratch / "dist")
        print(f"Checking {wheel.name}")
        problems = wheel_problems(wheel)
        if not problems:
            problems = run_problems(install(wheel, scratch / "venv"), scratch)
    for problem in problems:
        print(f"  {problem}")
    print("The wheel is fine." if not problems else f"{len(problems)} problem(s) found.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
