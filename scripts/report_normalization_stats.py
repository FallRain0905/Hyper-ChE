"""Export compact JSON/CSV statistics from a normalization report."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def flatten_report(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "raw_entity_count": report.get("raw_entity_count", 0),
        "canonical_entity_count": report.get("canonical_entity_count", 0),
        "merged_count": report.get("merged_count", 0),
        "merge_ratio": report.get("merge_ratio", 0),
        "unit_parse_count": report.get("unit_parse_count", 0),
        "unit_parse_success_rate": report.get("unit_parse_success_rate", 0),
        "raw_hyperedge_count": report.get("raw_hyperedge_count", 0),
        "normalized_hyperedge_count": report.get("normalized_hyperedge_count", 0),
        "hyperedge_deduplicated_count": report.get("hyperedge_deduplicated_count", 0),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Write summary CSV from normalization_report.json.")
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--csv", required=True, type=Path)
    args = parser.parse_args()

    report = json.loads(args.report.read_text(encoding="utf-8"))
    row = flatten_report(report)
    args.csv.parent.mkdir(parents=True, exist_ok=True)
    with args.csv.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)
    print(json.dumps(row, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
