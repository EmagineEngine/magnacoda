from __future__ import annotations

import json
from pathlib import Path

from magnacoda.findings.models import ScanReport

SCHEMA_VERSION = "1"


def to_json(report: ScanReport) -> str:
    payload = {"schema_version": SCHEMA_VERSION, **report.model_dump(mode="json")}
    return json.dumps(payload, indent=2)


def write_json(report: ScanReport, path: Path) -> None:
    path.write_text(to_json(report), encoding="utf-8")
