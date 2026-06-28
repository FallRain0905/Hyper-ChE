"""Print a compact summary from a normalization report JSON."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize normalization_report.json")
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()

    report = json.loads(args.report.read_text(encoding="utf-8"))
    keys = [
        "raw_entity_count",
        "exact_match_count",
        "fuzzy_auto_match_count",
        "llm_judged_count",
        "created_new_count",
        "need_review_count",
        "canonical_entity_count",
        "merge_ratio",
        "raw_hyperedge_count",
        "normalized_hyperedge_count",
        "unresolved_hyperedge_count",
    ]
    for key in keys:
        print(f"{key}: {report.get(key, 0)}")


if __name__ == "__main__":
    main()
