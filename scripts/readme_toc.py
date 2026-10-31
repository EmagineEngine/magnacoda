"""Write the contents lists of the README and the manual from their headings: `make toc`.

The list goes between the **Contents** line and the first `##` heading: `##` headings at the left,
`###` and `####` under them, each linked to its heading's anchor (as GitHub and GitLab make them).
Typora's own [toc] marker shows as plain text on GitHub and PyPI, so each keeps a written list, and
tests/unit/test_readme.py checks it matches the headings.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = [ROOT / "README.md", ROOT / "docs" / "manual.md"]
_HEADING = re.compile(r"^(#{2,4}) (.+?)\s*#*\s*$")


def slug(heading: str) -> str:
    return re.sub(r"\s", "-", re.sub(r"[^\w\s-]", "", heading.strip().lower()))


def contents(text: str) -> list[str]:
    lines, in_code = [], False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_code = not in_code
        match = None if in_code else _HEADING.match(line)
        if match:
            depth = len(match.group(1)) - 2
            lines.append(f"{'  ' * depth}- [{match.group(2)}](#{slug(match.group(2))})")
    return lines


def with_contents(text: str) -> str:
    start = text.index("**Contents**")
    end = text.index("\n## ", start)
    return text[:start] + "**Contents**\n\n" + "\n".join(contents(text)) + "\n" + text[end:]


def main() -> int:
    for document in DOCUMENTS:
        name = document.relative_to(ROOT).as_posix()
        text = document.read_text(encoding="utf-8")
        new = with_contents(text)
        if new != text:
            document.write_text(new, encoding="utf-8")
            print(f"{name}: contents list rewritten.")
        else:
            print(f"{name}: contents list already matches the headings.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
