"""Build a shared retrieval candidate pool keyed by (query_id, chunk_id).

Formal multi-system evaluation must judge the union of every system's Top-k.
The same corpus chunk is therefore annotated once and reused by all systems.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


GRADE_LABELS = {0: "IRRELEVANT", 1: "BACKGROUND", 2: "STRONG_SUPPORT", 3: "DIRECT"}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def get_rows(value: Any, keys: tuple[str, ...]) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [row for row in value if isinstance(row, dict)]
    if isinstance(value, dict):
        for key in keys:
            rows = value.get(key)
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
    raise ValueError(f"Could not find rows under any of: {', '.join(keys)}")


def parse_system(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("--system must be NAME=PATH")
    name, raw_path = (part.strip() for part in value.split("=", 1))
    if not name or not raw_path:
        raise argparse.ArgumentTypeError("--system must be NAME=PATH")
    return name, Path(raw_path)


def query_id(row: dict[str, Any]) -> str:
    value = str(row.get("query_id") or "").strip()
    if not value:
        raise ValueError("Row has no query_id")
    return value


def chunk_id(row: dict[str, Any]) -> str:
    value = str(row.get("chunk_id") or "").strip()
    if value:
        return value
    candidate_id = str(row.get("candidate_id") or row.get("id") or "").strip()
    if ":" in candidate_id:
        return candidate_id.rsplit(":", 1)[-1]
    raise ValueError(f"Row has no chunk_id: {candidate_id or '<missing candidate_id>'}")


def retrieval_rank(row: dict[str, Any], fallback: int) -> int:
    for key in ("retrieval_rank", "rank"):
        try:
            value = int(row.get(key))
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return fallback


def load_seed_qrels(paths: list[Path]) -> tuple[dict[tuple[str, str], list[dict[str, Any]]], int]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    total = 0
    for path in paths:
        for row in get_rows(load_json(path), ("qrels", "retrieval_qrels")):
            copied = dict(row)
            copied["_seed_file"] = str(path.resolve())
            grouped[(query_id(row), chunk_id(row))].append(copied)
            total += 1
    return grouped, total


def main() -> None:
    parser = argparse.ArgumentParser(description="Pool retrieval systems by (query_id, chunk_id).")
    parser.add_argument("--system", action="append", required=True, type=parse_system, metavar="NAME=PATH")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--seed-qrels", action="append", default=[], type=Path)
    args = parser.parse_args()
    if args.top_k <= 0:
        parser.error("--top-k must be positive")
    names = [name for name, _ in args.system]
    if len(names) != len(set(names)):
        parser.error("Each system name must be unique")

    pooled: dict[tuple[str, str], dict[str, Any]] = {}
    system_stats: dict[str, dict[str, Any]] = {}
    query_system_counts: dict[str, Counter[str]] = defaultdict(Counter)

    for system_name, path in args.system:
        candidates = get_rows(load_json(path), ("candidate_evidence", "candidates", "results"))
        by_query: dict[str, list[tuple[int, int, dict[str, Any]]]] = defaultdict(list)
        for index, row in enumerate(candidates, start=1):
            by_query[query_id(row)].append((retrieval_rank(row, index), index, row))

        kept = 0
        internal_duplicates = 0
        for qid, rows in by_query.items():
            rows.sort(key=lambda item: (item[0], item[1]))
            seen: set[str] = set()
            contributed = 0
            for rank, _index, row in rows:
                cid = chunk_id(row)
                if cid in seen:
                    internal_duplicates += 1
                    continue
                seen.add(cid)
                if contributed >= args.top_k:
                    continue
                contributed += 1
                kept += 1
                query_system_counts[qid][system_name] += 1
                key = (qid, cid)
                docs = [str(x) for x in (row.get("source_doc_ids") or []) if str(x)]
                if not docs and row.get("source_doc_id"):
                    docs = [str(row["source_doc_id"])]
                item = pooled.setdefault(key, {
                    "query_id": qid,
                    "chunk_id": cid,
                    "source_doc_ids": [],
                    "source_file": row.get("source_file"),
                    "content": row.get("content") or row.get("text") or "",
                    "system_occurrences": [],
                })
                item["source_doc_ids"] = sorted(set(item["source_doc_ids"]) | set(docs))
                text = str(row.get("content") or row.get("text") or "")
                if len(text) > len(str(item.get("content") or "")):
                    item["content"] = text
                if not item.get("source_file") and row.get("source_file"):
                    item["source_file"] = row.get("source_file")
                item["system_occurrences"].append({
                    "system": system_name,
                    "candidate_id": row.get("candidate_id") or row.get("id"),
                    "candidate_group": row.get("candidate_group"),
                    "retrieval_rank": rank,
                    "retrieval_score": row.get("retrieval_score", row.get("score")),
                    "retrieval_channels": row.get("retrieval_channels") or [],
                })

        system_stats[system_name] = {
            "candidate_file": str(path.resolve()),
            "input_candidates": len(candidates),
            "queries": len(by_query),
            "pooled_candidates_contributed": kept,
            "duplicates_within_system_removed": internal_duplicates,
        }

    union_rows: list[dict[str, Any]] = []
    for item in pooled.values():
        item["system_occurrences"].sort(key=lambda row: (str(row["system"]), int(row["retrieval_rank"])))
        item["pool_system_count"] = len(item["system_occurrences"])
        item["best_retrieval_rank"] = min(int(row["retrieval_rank"]) for row in item["system_occurrences"])
        union_rows.append(item)
    union_rows.sort(key=lambda row: (row["query_id"], row["best_retrieval_rank"], row["chunk_id"]))

    seed_by_key, seed_input_count = load_seed_qrels(args.seed_qrels)
    qrel_rows: list[dict[str, Any]] = []
    seeded = 0
    conflicts = 0
    for item in union_rows:
        key = (item["query_id"], item["chunk_id"])
        seeds = seed_by_key.get(key, [])
        grades = {int(row["relevance_grade"]) for row in seeds if row.get("relevance_grade") is not None}
        is_conflict = len(grades) > 1
        grade = next(iter(grades)) if len(grades) == 1 else None
        seeded += int(grade is not None)
        conflicts += int(is_conflict)
        primary = seeds[0] if seeds else {}
        qrel_rows.append({
            "query_id": item["query_id"],
            "chunk_id": item["chunk_id"],
            "relevance_grade": grade,
            "relevance_label": GRADE_LABELS.get(grade) if grade is not None else None,
            "rationale": primary.get("rationale", ""),
            "supported_elements": primary.get("supported_elements") or [],
            "conflicts": primary.get("conflicts") or [],
            "annotation_status": "seed_conflict_needs_review" if is_conflict else "provisional_seed_mapped_by_chunk_id" if grade is not None else "unjudged",
            "seed_sources": [{
                "file": row["_seed_file"],
                "candidate_id": row.get("candidate_id"),
                "candidate_group": row.get("candidate_group"),
                "relevance_grade": row.get("relevance_grade"),
                "review_status": row.get("review_status"),
            } for row in seeds],
        })

    created_at = datetime.now(timezone.utc).isoformat()
    pool_obj = {
        "metadata": {
            "created_at": created_at,
            "status": "shared_candidate_pool",
            "pool_key": ["query_id", "chunk_id"],
            "top_k_per_system": args.top_k,
            "benchmark_scope": "chemistry_high_order_compositional_retrieval",
            "fairness_rule": "all systems share one pooled qrels set and one IDCG per query",
            "systems": system_stats,
        },
        "candidate_union": union_rows,
    }
    qrels_obj = {
        "metadata": {
            "created_at": created_at,
            "status": "provisional_seeded" if seeded == len(qrel_rows) and not conflicts else "incomplete_needs_annotation",
            "gold_status": "not_gold_until_human_confirmation",
            "qrel_key": ["query_id", "chunk_id"],
            "grade_schema": {str(key): value for key, value in GRADE_LABELS.items()},
            "seed_qrels": [str(path.resolve()) for path in args.seed_qrels],
            "warning": "Seeded grades remain provisional and all systems must use the same relevance standard.",
        },
        "qrels": qrel_rows,
    }
    per_query = Counter(row["query_id"] for row in union_rows)
    contributed = sum(value["pooled_candidates_contributed"] for value in system_stats.values())
    summary = {
        "created_at": created_at,
        "systems": system_stats,
        "query_count": len(per_query),
        "candidate_occurrences_before_cross_system_dedup": contributed,
        "unique_query_chunk_pairs": len(union_rows),
        "cross_system_duplicates_removed": contributed - len(union_rows),
        "seed_qrels_input_rows": seed_input_count,
        "seeded_qrels": seeded,
        "unjudged_qrels": len(qrel_rows) - seeded,
        "seed_conflicts": conflicts,
        "per_query_unique_pool_size": dict(sorted(per_query.items())),
        "per_query_system_contributions": {qid: dict(sorted(counts.items())) for qid, counts in sorted(query_system_counts.items())},
    }

    write_json(args.output_dir / "candidate_union.json", pool_obj)
    write_json(args.output_dir / "shared_qrels_template.json", qrels_obj)
    write_json(args.output_dir / "pool_summary.json", summary)
    print(json.dumps({
        "output_dir": str(args.output_dir.resolve()),
        "systems": names,
        "queries": len(per_query),
        "unique_query_chunk_pairs": len(union_rows),
        "seeded_qrels": seeded,
        "unjudged_qrels": len(qrel_rows) - seeded,
        "seed_conflicts": conflicts,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
