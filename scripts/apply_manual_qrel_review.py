"""Apply explicitly reviewed judgments to unresolved shared-qrel rows.

This utility is intentionally separate from the automated LLM labeler.  It
keeps provider-generated judgments unchanged, only fills rows that are still
unjudged, and records the supplemental review method in both the row and the
protocol metadata.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


LABELS = {
    0: "IRRELEVANT",
    1: "BACKGROUND",
    2: "STRONG_SUPPORT",
    3: "DIRECT",
}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qrels", required=True, type=Path)
    parser.add_argument("--reviews", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()

    qrels_obj = load_json(args.qrels)
    rows = qrels_obj.get("qrels")
    if not isinstance(rows, list):
        parser.error("--qrels must contain a qrels list")

    review_obj = load_json(args.reviews)
    reviews = review_obj.get("reviews")
    if not isinstance(reviews, list) or not reviews:
        parser.error("--reviews must contain a non-empty reviews list")

    row_map = {
        (str(row.get("query_id")), str(row.get("chunk_id"))): row
        for row in rows
    }
    seen: set[tuple[str, str]] = set()
    applied: list[dict[str, Any]] = []
    reviewed_at = datetime.now(timezone.utc).isoformat()

    for review in reviews:
        key = (str(review.get("query_id")), str(review.get("chunk_id")))
        if key in seen:
            raise ValueError(f"duplicate review key: {key!r}")
        seen.add(key)
        row = row_map.get(key)
        if row is None:
            raise KeyError(f"review key absent from qrels: {key!r}")
        if row.get("relevance_grade") is not None:
            raise ValueError(f"refusing to overwrite an existing judgment: {key!r}")

        grade = int(review.get("relevance_grade"))
        if grade not in LABELS:
            raise ValueError(f"invalid relevance grade for {key!r}: {grade}")
        rationale = str(review.get("rationale") or "").strip()
        if not rationale:
            raise ValueError(f"missing rationale for {key!r}")

        judgment = {
            "query_id": key[0],
            "chunk_id": key[1],
            "relevance_grade": grade,
            "relevance_label": LABELS[grade],
            "rationale": rationale,
            "supported_elements": list(review.get("supported_elements") or []),
            "conflicts": list(review.get("conflicts") or []),
            "annotation_status": "codex_semantic_review_after_provider_failure",
            "review_method": "direct_semantic_evidence_review",
            "review_agent": "Codex",
            "reviewed_at": reviewed_at,
        }
        row.clear()
        row.update(judgment)
        applied.append(judgment)

    unresolved = sum(row.get("relevance_grade") is None for row in rows)
    grade_counts = Counter(
        int(row["relevance_grade"])
        for row in rows
        if row.get("relevance_grade") is not None
    )
    metadata = dict(qrels_obj.get("metadata") or {})
    metadata.update(
        {
            "created_at": reviewed_at,
            "status": "complete_shared_qrels" if unresolved == 0 else "incomplete_shared_qrels",
            "gold_status": "llm_judged_pending_final_audit",
            "pooled_pairs": len(rows),
            "judged_pairs": len(rows) - unresolved,
            "unjudged_pairs": unresolved,
            "grade_distribution": {str(key): grade_counts.get(key, 0) for key in LABELS},
            "supplemental_review": {
                "method": "codex_semantic_review_after_provider_failures",
                "reviewed_pairs": len(applied),
                "review_file": str(args.reviews.resolve()),
                "reviewed_at": reviewed_at,
                "note": (
                    "Only previously unresolved rows were filled. Automated judgments and "
                    "provider-failure audit records were preserved."
                ),
            },
        }
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.output_dir / "shared_qrels.json", {"metadata": metadata, "qrels": rows})
    write_json(args.output_dir / "shared_qrels_protocol.json", metadata)
    write_json(args.output_dir / "shared_qrels_errors.json", [])

    audit_path = args.output_dir / "shared_qrels_audit.jsonl"
    with audit_path.open("a", encoding="utf-8") as handle:
        for judgment in applied:
            handle.write(
                json.dumps(
                    {
                        "status": "supplemental_review_success",
                        "created_at": reviewed_at,
                        "judgment": judgment,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

    print(json.dumps(metadata, ensure_ascii=False, indent=2))
    if unresolved:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
