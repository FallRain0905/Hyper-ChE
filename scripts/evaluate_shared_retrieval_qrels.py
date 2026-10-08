"""Evaluate systems with shared chunk-level qrels and one IDCG per query."""

from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Any


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def get_rows(value: Any, keys: tuple[str, ...]) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [row for row in value if isinstance(row, dict)]
    if isinstance(value, dict):
        for key in keys:
            rows = value.get(key)
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
    raise ValueError(f"Could not find rows under any of: {', '.join(keys)}")


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                fields.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def dcg(grades: list[int], k: int) -> float:
    return sum((2**grade - 1) / math.log2(index + 2) for index, grade in enumerate(grades[:k]))


def metrics(grades: list[int], ideal: list[int], threshold: int, k: int) -> dict[str, float]:
    binary = [int(grade >= threshold) for grade in grades]
    first = next((index + 1 for index, hit in enumerate(binary) if hit), None)
    denominator = dcg(ideal, k)
    return {
        "P@1": float(bool(binary[:1] and binary[0])),
        f"Hit@{k}": float(any(binary[:k])),
        "MRR": 1.0 / first if first else 0.0,
        f"gNDCG@{k}": dcg(grades, k) / denominator if denominator > 0 else 0.0,
        f"IDCG@{k}": denominator,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate pooled retrieval with shared qrels and IDCG.")
    parser.add_argument("--candidate-union", required=True, type=Path)
    parser.add_argument("--qrels", required=True, type=Path)
    parser.add_argument("--queries", type=Path, help="Optional query benchmark for difficulty/support/arity slice metrics.")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--thresholds", nargs="+", type=int, default=[1, 2, 3])
    parser.add_argument("--system", action="append", default=[])
    parser.add_argument("--allow-incomplete-qrels", action="store_true", help="Smoke test only: count unjudged candidates as grade 0.")
    parser.add_argument("--scope-label", default="chemistry_high_order_compositional_retrieval")
    args = parser.parse_args()
    if args.k <= 0:
        parser.error("--k must be positive")

    union_rows = get_rows(load_json(args.candidate_union), ("candidate_union", "candidate_evidence"))
    qrel_rows = get_rows(load_json(args.qrels), ("qrels", "retrieval_qrels"))
    query_map: dict[str, dict[str, Any]] = {}
    if args.queries:
        query_rows = get_rows(load_json(args.queries), ("queries", "retrieval_queries"))
        query_map = {str(row.get("query_id") or row.get("id") or ""): row for row in query_rows}

    qrel_map: dict[tuple[str, str], int | None] = {}
    conflicts: list[tuple[str, str]] = []
    for row in qrel_rows:
        key = (str(row.get("query_id") or ""), str(row.get("chunk_id") or ""))
        if not all(key):
            raise ValueError(f"qrel missing query_id or chunk_id: {row}")
        raw_grade = row.get("relevance_grade")
        grade = None if raw_grade is None or raw_grade == "" else int(raw_grade)
        if grade is not None and grade not in {0, 1, 2, 3}:
            raise ValueError(f"qrel grade must be 0..3: {row}")
        if key in qrel_map and qrel_map[key] != grade:
            conflicts.append(key)
        qrel_map[key] = grade
    if conflicts:
        sample = ", ".join(f"{qid}/{cid}" for qid, cid in conflicts[:5])
        raise ValueError(f"Conflicting duplicate qrels: {sample}")

    pool_keys: set[tuple[str, str]] = set()
    rankings: dict[tuple[str, str], list[tuple[int, str, dict[str, Any]]]] = defaultdict(list)
    detected_systems: set[str] = set()
    for row in union_rows:
        qid = str(row.get("query_id") or "")
        cid = str(row.get("chunk_id") or "")
        if not qid or not cid:
            raise ValueError(f"candidate union row missing query_id or chunk_id: {row}")
        pool_keys.add((qid, cid))
        for occurrence in row.get("system_occurrences") or []:
            system = str(occurrence.get("system") or "")
            if not system:
                raise ValueError(f"occurrence missing system: {occurrence}")
            detected_systems.add(system)
            try:
                rank = int(occurrence.get("retrieval_rank"))
            except (TypeError, ValueError):
                rank = 10**9
            rankings[(system, qid)].append((rank, cid, occurrence))

    missing = sorted(key for key in pool_keys if qrel_map.get(key) is None)
    if missing and not args.allow_incomplete_qrels:
        sample = ", ".join(f"{qid}/{cid}" for qid, cid in missing[:8])
        raise ValueError(f"{len(missing)} pooled candidates are unjudged; formal evaluation refuses to treat them as zero. Examples: {sample}")

    grades_by_key = {key: int(qrel_map.get(key) or 0) for key in pool_keys}
    extra_qrels = sorted(set(qrel_map) - pool_keys)
    systems = args.system or sorted(detected_systems)
    unknown = sorted(set(systems) - detected_systems)
    if unknown:
        parser.error(f"Unknown systems: {', '.join(unknown)}")
    query_ids = sorted({qid for qid, _cid in pool_keys})
    ideal_by_query = {
        qid: sorted([grade for (query_id, _cid), grade in grades_by_key.items() if query_id == qid], reverse=True)
        for qid in query_ids
    }

    summary_rows: list[dict[str, Any]] = []
    per_query_rows: list[dict[str, Any]] = []
    ranked_rows: list[dict[str, Any]] = []
    system_rankings: dict[tuple[str, str], list[str]] = {}

    for system in systems:
        for qid in query_ids:
            raw = sorted(rankings.get((system, qid), []), key=lambda item: (item[0], item[1]))
            seen: set[str] = set()
            chunk_ids: list[str] = []
            occurrences: list[dict[str, Any]] = []
            for _rank, cid, occurrence in raw:
                if cid in seen:
                    continue
                seen.add(cid)
                chunk_ids.append(cid)
                occurrences.append(occurrence)
            system_rankings[(system, qid)] = chunk_ids
            for output_rank, (cid, occurrence) in enumerate(zip(chunk_ids[:args.k], occurrences[:args.k]), start=1):
                ranked_rows.append({
                    "system": system,
                    "query_id": qid,
                    "rank": output_rank,
                    "chunk_id": cid,
                    "qrel_grade": grades_by_key[(qid, cid)],
                    "original_retrieval_rank": occurrence.get("retrieval_rank"),
                    "candidate_id": occurrence.get("candidate_id"),
                })

        for threshold in args.thresholds:
            metric_rows: list[dict[str, float]] = []
            for qid in query_ids:
                chunk_ids = system_rankings[(system, qid)]
                ranked_grades = [grades_by_key[(qid, cid)] for cid in chunk_ids]
                ideal = ideal_by_query[qid]
                row_metrics = metrics(ranked_grades, ideal, threshold, args.k)
                metric_rows.append(row_metrics)
                query = query_map.get(qid, {})
                try:
                    fact_arity = int(query.get("fact_arity"))
                except (TypeError, ValueError):
                    fact_arity = None
                arity_bucket = (
                    "low_order_arity_le_2"
                    if fact_arity is not None and fact_arity <= 2
                    else "high_order_arity_3_4"
                    if fact_arity is not None and fact_arity <= 4
                    else "high_order_arity_5_plus"
                    if fact_arity is not None
                    else "unknown"
                )
                answerability = (
                    "retrievable"
                    if bool(query.get("retrievable"))
                    else "unanswerable"
                )
                per_query_rows.append({
                    "system": system,
                    "threshold": f"grade>={threshold}",
                    "query_id": qid,
                    "difficulty": query.get("difficulty"),
                    "support_mode": query.get("support_mode"),
                    "fact_type": query.get("fact_type"),
                    "fact_arity": fact_arity,
                    "arity_bucket": arity_bucket,
                    "answerability": answerability,
                    "retrieved_candidates": len(chunk_ids),
                    "top1_grade": ranked_grades[0] if ranked_grades else 0,
                    f"top{args.k}_grades": " ".join(map(str, ranked_grades[:args.k])),
                    f"shared_ideal_top{args.k}_grades": " ".join(map(str, ideal[:args.k])),
                    **{key: round(value, 6) for key, value in row_metrics.items()},
                })
            averages = {key: sum(row[key] for row in metric_rows) / len(metric_rows) for key in metric_rows[0]}
            summary_rows.append({
                "system": system,
                "relevance_threshold": f"grade>={threshold}",
                "queries": len(query_ids),
                "P@1": round(averages["P@1"], 6),
                f"Hit@{args.k}": round(averages[f"Hit@{args.k}"], 6),
                "MRR": round(averages["MRR"], 6),
                f"gNDCG@{args.k}": round(averages[f"gNDCG@{args.k}"], 6),
                "shared_idcg": True,
            })

    slice_rows: list[dict[str, Any]] = []
    if query_map:
        metric_names = ["P@1", f"Hit@{args.k}", "MRR", f"gNDCG@{args.k}"]
        for dimension in (
            "answerability",
            "difficulty",
            "support_mode",
            "fact_type",
            "arity_bucket",
        ):
            grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
            for row in per_query_rows:
                value = str(row.get(dimension) or "unknown")
                grouped[(str(row["system"]), str(row["threshold"]), value)].append(row)
            for (system, threshold, value), rows in sorted(grouped.items()):
                slice_rows.append({
                    "system": system,
                    "threshold": threshold,
                    "slice_dimension": dimension,
                    "slice_value": value,
                    "queries": len(rows),
                    **{name: round(sum(float(row[name]) for row in rows) / len(rows), 6) for name in metric_names},
                    "shared_idcg": True,
                })

    zero_idcg = [qid for qid, values in ideal_by_query.items() if dcg(values, args.k) == 0]
    distribution = Counter(grades_by_key.values())
    status = (
        "incomplete_qrels_smoke_only"
        if missing
        else "single_system_smoke_only"
        if len(systems) < 2
        else "formal_shared_qrels"
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.output_dir / "shared_retrieval_summary.csv", summary_rows)
    write_csv(args.output_dir / "shared_retrieval_per_query.csv", per_query_rows)
    write_csv(args.output_dir / "shared_retrieval_ranked_topk.csv", ranked_rows)
    write_csv(args.output_dir / "shared_retrieval_slice_summary.csv", slice_rows)
    report = {
        "metadata": {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": status,
            "benchmark_scope": args.scope_label,
            "candidate_union": str(args.candidate_union.resolve()),
            "qrels": str(args.qrels.resolve()),
            "queries": str(args.queries.resolve()) if args.queries else None,
            "qrel_key": ["query_id", "chunk_id"],
            "idcg_policy": "one IDCG per query from the complete judged candidate union, shared by every system",
            "allow_incomplete_qrels": args.allow_incomplete_qrels,
        },
        "integrity": {
            "systems": systems,
            "queries": len(query_ids),
            "pooled_query_chunk_pairs": len(pool_keys),
            "judged_pairs": len(pool_keys) - len(missing),
            "unjudged_pairs": len(missing),
            "extra_qrels_not_in_pool": len(extra_qrels),
            "zero_idcg_queries": zero_idcg,
            "grade_distribution": {str(key): value for key, value in sorted(distribution.items())},
        },
        "summary": summary_rows,
        "outputs": {
            "summary_csv": str((args.output_dir / "shared_retrieval_summary.csv").resolve()),
            "per_query_csv": str((args.output_dir / "shared_retrieval_per_query.csv").resolve()),
            "ranked_topk_csv": str((args.output_dir / "shared_retrieval_ranked_topk.csv").resolve()),
            "slice_summary_csv": str((args.output_dir / "shared_retrieval_slice_summary.csv").resolve()),
        },
    }
    write_json(args.output_dir / "shared_retrieval_summary.json", report)
    print(json.dumps({
        "output_dir": str(args.output_dir.resolve()),
        "status": status,
        "systems": systems,
        "queries": len(query_ids),
        "pooled_pairs": len(pool_keys),
        "unjudged_pairs": len(missing),
        "zero_idcg_queries": len(zero_idcg),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
