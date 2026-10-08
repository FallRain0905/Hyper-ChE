"""Aggregate exact-gold and source-document retrieval diagnostics by benchmark slice."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


RATE_FIELDS = (
    "entity_branch_gold_hit",
    "relation_branch_gold_hit",
    "candidate_union_gold_hit",
    "balanced_topk_gold_hit",
    "final_topk_gold_hit",
    "source_document_hit",
)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def arity_bucket(value: Any) -> str:
    try:
        arity = int(value)
    except (TypeError, ValueError):
        return "unknown"
    if arity <= 2:
        return "low_order_arity_le_2"
    if arity <= 4:
        return "high_order_arity_3_4"
    return "high_order_arity_5_plus"


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    retrievable = [row for row in rows if bool(row.get("retrievable"))]
    result: dict[str, Any] = {
        "query_count": len(rows),
        "retrievable_query_count": len(retrievable),
        "unanswerable_query_count": len(rows) - len(retrievable),
    }
    for field in RATE_FIELDS:
        result[f"{field}_count"] = sum(bool(row.get(field)) for row in retrievable)
        result[f"{field}_rate"] = (
            round(result[f"{field}_count"] / len(retrievable), 6)
            if retrievable
            else None
        )
    losses = Counter(str(row.get("loss_stage") or "unknown") for row in retrievable)
    result["loss_stage_counts"] = dict(sorted(losses.items()))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queries", required=True, type=Path)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()

    output_dir = args.output_dir or args.run_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    protocol_path = args.run_dir / "run_protocol.json"
    protocol = load_json(protocol_path) if protocol_path.exists() else {}
    query_payload = load_json(args.queries)
    queries = {
        str(item["query_id"]): item
        for item in query_payload.get("queries", [])
        if isinstance(item, dict) and item.get("query_id")
    }

    system_rows: dict[str, list[dict[str, Any]]] = {}
    for path in sorted(args.run_dir.glob("*/retrieval_loss_diagnostics.json")):
        payload = load_json(path)
        enriched = []
        for row in payload.get("per_query", []):
            query = queries.get(str(row.get("query_id")), {})
            enriched.append({
                **row,
                "retrievable": bool(query.get("retrievable")),
                "answerability": "retrievable" if bool(query.get("retrievable")) else "unanswerable",
                "difficulty": query.get("difficulty") or "unknown",
                "support_mode": query.get("support_mode") or "unknown",
                "fact_type": query.get("fact_type") or "unknown",
                "fact_arity": query.get("fact_arity"),
                "arity_bucket": arity_bucket(query.get("fact_arity")),
            })
        system_rows[path.parent.name] = enriched

    dimensions = ("answerability", "difficulty", "support_mode", "fact_type", "arity_bucket")
    summaries: list[dict[str, Any]] = []
    for system, rows_for_system in system_rows.items():
        summaries.append({
            "system": system,
            "slice_dimension": "all",
            "slice_value": "all",
            **summarize(rows_for_system),
        })
        for dimension in dimensions:
            grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for row in rows_for_system:
                grouped[str(row.get(dimension) or "unknown")].append(row)
            for value, group in sorted(grouped.items()):
                summaries.append({
                    "system": system,
                    "slice_dimension": dimension,
                    "slice_value": value,
                    **summarize(group),
                })

    csv_path = output_dir / "gold_diagnostic_stratified_summary.csv"
    if summaries:
        fieldnames = list(summaries[0])
        with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(summaries)

    report = {
        "metadata": {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "queries": str(args.queries.resolve()),
            "run_dir": str(args.run_dir.resolve()),
            "systems": list(system_rows),
            "rate_denominator": "retrievable queries only; unanswerable queries have no gold chunk/source document",
        },
        "summaries": summaries,
    }
    write_json(output_dir / "gold_diagnostic_stratified_summary.json", report)
    cache_configs: dict[str, dict[str, Any]] = {}
    cache_root = Path(str(protocol.get("cache_root") or ""))
    for system, spec in (protocol.get("systems") or {}).items():
        cache_name = str(spec.get("cache") or "")
        config_path = cache_root / cache_name / "run_config.json"
        if not cache_name or cache_name in cache_configs or not config_path.exists():
            continue
        config = load_json(config_path)
        full_docs_path = cache_root / cache_name / "kv_store_full_docs.json"
        chunks_path = cache_root / cache_name / "kv_store_text_chunks.json"
        full_docs = load_json(full_docs_path) if full_docs_path.exists() else {}
        chunks = load_json(chunks_path) if chunks_path.exists() else {}
        cache_configs[cache_name] = {
            "experiment_mode": config.get("experiment_mode"),
            "prompt_profile": config.get("prompt_profile"),
            "effective_domain": config.get("effective_domain"),
            "enable_one_pass_extraction": config.get("enable_one_pass_extraction"),
            "enable_entity_normalization": config.get("enable_entity_normalization"),
            "enable_measurement_instances": config.get("enable_measurement_instances"),
            "enable_efu_repair": config.get("enable_efu_repair"),
            "index_profile": config.get("index_profile"),
            "chunk_size": config.get("chunk_size"),
            "doc_start": config.get("doc_start"),
            "doc_end": config.get("doc_end"),
            "storage_doc_count": len(full_docs) if isinstance(full_docs, dict) else None,
            "storage_chunk_count": len(chunks) if isinstance(chunks, dict) else None,
        }
    limitations = []
    if bool((cache_configs.get("hyper_base") or {}).get("enable_one_pass_extraction")):
        limitations.append({
            "id": "hyper_base_one_pass_enabled",
            "severity": "material_protocol_limitation",
            "statement": (
                "The existing hyper_base cache reports enable_one_pass_extraction=true. "
                "It must not be described as a strict upstream/no-one-pass build baseline. "
                "A strict baseline would require a separately named cache and must not overwrite this cache."
            ),
        })
    write_json(
        output_dir / "experiment_limitations.json",
        {
            "metadata": {
                "created_at": datetime.now(timezone.utc).isoformat(),
                "source_protocol": str(protocol_path.resolve()),
                "cache_read_only": True,
            },
            "cache_run_config_summary": cache_configs,
            "limitations": limitations,
        },
    )
    print(json.dumps(report["metadata"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
