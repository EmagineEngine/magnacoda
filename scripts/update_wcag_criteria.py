"""Regenerate magnacoda/data/wcag_criteria.json from the W3C's machine-readable WCAG 2.2 data.

Usage: python scripts/update_wcag_criteria.py
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

SOURCE = "https://www.w3.org/WAI/WCAG22/wcag.json"
UNDERSTANDING = "https://www.w3.org/WAI/WCAG22/Understanding/{id}.html"
OUT = Path(__file__).resolve().parent.parent / "magnacoda" / "data" / "wcag_criteria.json"


def main() -> None:
    with urllib.request.urlopen(SOURCE, timeout=60) as response:
        data = json.load(response)

    criteria = []
    for principle in data["principles"]:
        for guideline in principle["guidelines"]:
            for sc in guideline["successcriteria"]:
                criteria.append(
                    {
                        "num": sc["num"],
                        "id": sc["id"],
                        "title": sc["handle"],
                        # 4.1.1 is obsolete in 2.2 and has an empty level; it was Level A in 2.0/2.1.
                        "level": sc["level"] or "A",
                        "versions": sc["versions"],
                        "principle": principle["handle"],
                        "guideline": f"{guideline['num']} {guideline['handle']}",
                        "url": UNDERSTANDING.format(id=sc["id"]),
                    }
                )
    criteria.sort(key=lambda c: [int(part) for part in c["num"].split(".")])
    OUT.write_text(json.dumps(criteria, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {len(criteria)} criteria to {OUT}")


if __name__ == "__main__":
    main()
