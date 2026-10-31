"""The console scripts. cli.py takes about a second to import; Ctrl+C then ends quietly, no traceback."""

import sys


def _run(name: str) -> None:
    try:
        from magnacoda import cli
    except KeyboardInterrupt:
        sys.stderr.write("\nCancelled.\n")
        sys.exit(130)
    getattr(cli, name)()


def main() -> None:
    _run("main")


def run_as_magnacoda() -> None:
    """For aliases like `magnacode` (see cli.run_as_magnacoda)."""
    _run("run_as_magnacoda")
