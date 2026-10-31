import subprocess
import sys
from importlib import metadata


def test_the_program_has_one_command_and_two_typo_aliases():
    scripts = {
        ep.name: ep.value
        for ep in metadata.distribution("magnacoda").entry_points
        if ep.group == "console_scripts"
    }
    assert scripts == {
        "magnacoda": "magnacoda.start:main",
        "magnacode": "magnacoda.start:run_as_magnacoda",
        "magnaconda": "magnacoda.start:run_as_magnacoda",
    }


def test_an_alias_still_calls_itself_magnacoda():
    code = (
        "import sys; sys.argv = ['magnacode', '--version']\n"
        "from magnacoda.cli import run_as_magnacoda\n"
        "run_as_magnacoda()"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0
    assert result.stdout.startswith("magnacoda, version") and "magnacode," not in result.stdout
