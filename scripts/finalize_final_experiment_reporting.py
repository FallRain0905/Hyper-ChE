"""Finalize offline reporting for the old-embedding HyperChE experiment.

This script deliberately does not invent Composite Fact Recall labels.  It
builds an auditable atomic-fact review pack from the frozen retrieval queries
and records CFR as pending until entity/metric/value/unit/condition bindings
have been reviewed.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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


def rows(value: Any, keys: tuple[str, ...]) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        for key in keys:
            item = value.get(key)
            if isinstance(item, list):
                return [row for row in item if isinstance(row, dict)]
    raise ValueError(f"No row list found under {keys}")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def source_level_metrics(
    union_rows: list[dict[str, Any]], ranked_rows: list[dict[str, str]], *, k: int = 5
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    sources = {
        (str(row.get("query_id")), str(row.get("chunk_id"))): [
            str(item) for item in (row.get("source_doc_ids") or []) if str(item)
        ]
        for row in union_rows
    }
    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in ranked_rows:
        try:
            rank = int(row.get("rank") or 0)
        except ValueError:
            rank = 0
        if rank <= k:
            grouped[(str(row.get("system")), str(row.get("query_id")))].append(row)

    query_rows: list[dict[str, Any]] = []
    for (system, query_id), items in sorted(grouped.items()):
        items.sort(key=lambda row: int(row.get("rank") or 0))
        unique_sources: set[str] = set()
        row_source_count = 0
        for item in items:
            chunk_sources = sources.get((query_id, str(item.get("chunk_id"))), [])
            unique_sources.update(chunk_sources)
            row_source_count += len(chunk_sources)
        duplicate_ratio = 1.0 - len(unique_sources) / row_source_count if row_source_count else 0.0
        for threshold in (2, 3):
            relevant = [item for item in items if int(item.get("qrel_grade") or 0) >= threshold]
            relevant_sources: set[str] = set()
            for item in relevant:
                relevant_sources.update(sources.get((query_id, str(item.get("chunk_id"))), []))
            query_rows.append(
                {
                    "system": system,
                    "query_id": query_id,
                    "threshold": f"grade>={threshold}",
                    "top_k": len(items),
                    "chunk_hit": bool(relevant),
                    "source_level_hit": bool(relevant_sources),
                    "unique_sources_top_k": len(unique_sources),
                    "relevant_sources_top_k": len(relevant_sources),
                    "source_duplicate_ratio_top_k": round(duplicate_ratio, 6),
                }
            )

    summary: list[dict[str, Any]] = []
    by_system: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in query_rows:
        by_system[(row["system"], row["threshold"])].append(row)
    for (system, threshold), items in sorted(by_system.items()):
        summary.append(
            {
                "system": system,
                "threshold": threshold,
                "queries": len(items),
                "Source-level Hit@5": round(sum(bool(x["source_level_hit"]) for x in items) / len(items), 6),
                "chunk Hit@5 (same qrel policy)": round(sum(bool(x["chunk_hit"]) for x in items) / len(items), 6),
                "mean unique sources@5": round(sum(x["unique_sources_top_k"] for x in items) / len(items), 6),
                "mean source duplicate ratio@5": round(sum(x["source_duplicate_ratio_top_k"] for x in items) / len(items), 6),
                "source_policy": "A query is a source hit when a top-5 retrieved chunk from that source has qrel at or above the threshold.",
                "interpretation": "chunk-derived source diagnostic; because relevance is currently judged at (query_id, chunk_id), this binary value is expected to equal chunk Hit@5 until source-level qrels are audited.",
            }
        )
    return summary, query_rows


def build_atomic_review_pack(query_rows: list[dict[str, Any]]) -> dict[str, Any]:
    pack: list[dict[str, Any]] = []
    for query in query_rows:
        required = query.get("required_elements") or {}
        atoms: list[dict[str, Any]] = []
        for category, values in required.items():
            if not isinstance(values, list):
                values = [values]
            for index, value in enumerate(values, start=1):
                atoms.append(
                    {
                        "provisional_atom_id": f"{query.get('query_id')}|{category}:{index}",
                        "category": category,
                        "text": str(value),
                        "status": "requires_human_binding_review",
                        "note": "Category membership alone is not a gold atomic fact; review entity/metric/value/unit/condition/relation binding against evidence spans.",
                    }
                )
        pack.append(
            {
                "query_id": query.get("query_id"),
                "question": query.get("question"),
                "retrievable": bool(query.get("retrievable")),
                "source_doc_id": query.get("source_doc_id"),
                "gold_chunk_ids": query.get("gold_chunk_ids") or [],
                "reference_answer": query.get("reference_answer"),
                "gold_claim": query.get("gold_claim"),
                "required_elements": required,
                "evidence_spans": query.get("original_evidence_spans") or query.get("evidence_spans") or [],
                "provisional_atoms": atoms,
                "status": "pending_manual_atomic_gold",
            }
        )
    return {
        "version": "composite-fact-gold-review-pack-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "pending_manual_atomic_gold",
        "definition": "Composite Fact Recall counts reviewed atomic entity/metric/value/unit/condition/relation facts supported by the retrieved evidence.",
        "prohibition": "Do not report CFR from provisional category strings or token overlap.",
        "queries": pack,
    }


def qrels_audit(pool_dir: Path, qrels_dir: Path) -> dict[str, Any]:
    pool = load_json(pool_dir / "candidate_union.json")
    qrels = load_json(qrels_dir / "shared_qrels.json")
    pool_rows = rows(pool, ("candidate_union",))
    qrel_rows = rows(qrels, ("qrels",))
    pool_keys = {(str(x.get("query_id")), str(x.get("chunk_id"))) for x in pool_rows}
    qrel_keys = [(str(x.get("query_id")), str(x.get("chunk_id"))) for x in qrel_rows]
    counts = Counter(qrel_keys)
    invalid = [x for x in qrel_rows if x.get("relevance_grade") not in {0, 1, 2, 3}]
    duplicates = [key for key, count in counts.items() if count > 1]
    audit_records = []
    audit_path = qrels_dir / "shared_qrels_audit.jsonl"
    if audit_path.exists():
        for line in audit_path.read_text(encoding="utf-8-sig").splitlines():
            if line.strip():
                try:
                    audit_records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    successful_keys = []
    for record in audit_records:
        if record.get("status") == "success":
            judgment = record.get("judgment") or {}
            successful_keys.append((str(judgment.get("query_id")), str(judgment.get("chunk_id"))))
    audit_duplicates = sum(count - 1 for count in Counter(successful_keys).values() if count > 1)
    metadata = dict(qrels.get("metadata") or {})
    return {
        "version": "shared-qrels-final-audit-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "needs_manual_final_audit",
        "pool_pairs": len(pool_keys),
        "qrel_rows": len(qrel_rows),
        "unique_qrel_keys": len(set(qrel_keys)),
        "missing_pool_pairs": len(pool_keys - set(qrel_keys)),
        "extra_qrel_pairs": len(set(qrel_keys) - pool_keys),
        "invalid_grade_rows": len(invalid),
        "duplicate_qrel_keys": len(duplicates),
        "annotation_status": metadata.get("gold_status"),
        "seeded_judgments": metadata.get("seeded_judgments_preserved"),
        "incremental_llm_judgments": metadata.get("incremental_llm_judgments"),
        "audit_attempt_records": len(audit_records),
        "audit_duplicate_success_records": audit_duplicates,
        "grade_distribution": metadata.get("grade_distribution") or {},
        "manual_review_reason": "The 3,875 seeded grades remain provisional and the 321 added grades are LLM judgments; completeness is verified, but this file is not human-gold certification.",
    }


def qa_comparison(root: Path, output: Path) -> list[dict[str, Any]]:
    historical = root / "outputs/qa_eval/real_flow_60_qa_formal_v3_structured_four_groups_kimi_moonshot_fixed/qa_formal_v3_summary.csv"
    final = output / "qa/qa_final_summary.csv"
    rows_out: list[dict[str, Any]] = []
    for row in read_csv(historical):
        rows_out.append({**row, "qa_provider": "Moonshot", "comparison_status": "historical_four_group"})
    for row in read_csv(final):
        rows_out.append({**row, "qa_provider": "Aliyun DashScope", "comparison_status": "new_normalized_final", "provider_comparability": "limited"})
    return rows_out


def attribution_report(output: Path, source_summary: list[dict[str, Any]], qa_rows: list[dict[str, Any]]) -> str:
    metrics = load_json(output / "retrieval_metrics/shared_retrieval_summary.json")["summary"]
    grade2 = {row["system"]: row for row in metrics if row["relevance_threshold"] == "grade>=2"}
    src2 = {row["system"]: row for row in source_summary if row["threshold"] == "grade>=2"}
    def delta(a: str, b: str, key: str) -> str:
        if a not in grade2 or b not in grade2:
            return "NA"
        return f"{grade2[a][key] - grade2[b][key]:+.6f}"
    lines = [
        "# HyperChE final experiment attribution report",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Retrieval findings",
        "",
        "- F0 is `normalized_final_no_rerank`; F1 is `normalized_final`.",
        f"- F1 minus F0: Hit@5 {delta('normalized_final', 'normalized_final_no_rerank', 'Hit@5')}, MRR {delta('normalized_final', 'normalized_final_no_rerank', 'MRR')}, gNDCG@5 {delta('normalized_final', 'normalized_final_no_rerank', 'gNDCG@5')}.",
        f"- F1 grade>=2 Source-level Hit@5: {src2.get('normalized_final', {}).get('Source-level Hit@5', 'NA')}; F0: {src2.get('normalized_final_no_rerank', {}).get('Source-level Hit@5', 'NA')}.",
        f"- F1 minus chem-prompt hypergraph: Hit@5 {delta('normalized_final', 'chem_prompt_hypergraph', 'Hit@5')}, MRR {delta('normalized_final', 'chem_prompt_hypergraph', 'MRR')}, gNDCG@5 {delta('normalized_final', 'chem_prompt_hypergraph', 'gNDCG@5')}.",
        f"- F1 minus chunk-rerank baseline: Hit@5 {delta('normalized_final', 'chem_prompt_hypergraph_chunk_rerank', 'Hit@5')}, MRR {delta('normalized_final', 'chem_prompt_hypergraph_chunk_rerank', 'MRR')}, gNDCG@5 {delta('normalized_final', 'chem_prompt_hypergraph_chunk_rerank', 'gNDCG@5')}.",
        "",
        "These paired differences do not isolate normalization alone: B2 and F0 use different retrieval indexes. F0/F1 share the same frozen hybrid candidate pool and differ only by the deterministic rerank switch.",
        "The current source-level table is a chunk-derived diagnostic. Since qrels are keyed by (query_id, chunk_id), binary source Hit@5 is expected to equal chunk Hit@5 until source-level relevance is audited separately.",
        "",
        "## QA findings",
        "",
        "The five-group QA table combines four historical Moonshot runs with the new Aliyun DashScope normalized-final run. The model name is the same (`kimi-k2.6`), but the serving provider differs, so this is a disclosed extension and not a fully controlled provider comparison.",
        "",
        "## Coverage and audit limits",
        "",
        "- Shared qrels are complete for all 4,196 pooled query/chunk pairs, but remain provisional/LLM judged pending final manual audit.",
        "- Composite Fact Recall is not reported yet. The review pack records provisional categories, but entity/metric/value/unit/condition/relation bindings require manual gold review.",
        "- The benchmark accepts 259 same-ID chunk text differences between the historical base and chemistry caches as a documented non-blocking variable.",
        "",
        "## Required next action",
        "",
        "Review `composite_fact_gold_review_pack.json` and certify atomic facts before computing CFR. Review `shared_qrels_final_audit.json` before calling qrels human gold.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--cache-root", type=Path, required=True)
    args = parser.parse_args()
    repo = args.repo.resolve()
    cache_root = args.cache_root.resolve()
    output = repo / "outputs/final_experiment_v1_old_embedding"
    queries = rows(load_json(repo / "outputs/retrieval_benchmark/query_benchmark_curated_v2/retrieval_queries.json"), ("queries", "retrieval_queries"))
    union = rows(load_json(output / "shared_pool/candidate_union.json"), ("candidate_union",))
    ranked = read_csv(output / "retrieval_metrics/shared_retrieval_ranked_topk.csv")
    source_summary, source_query = source_level_metrics(union, ranked)
    write_csv(output / "retrieval_metrics/source_level_hit_summary.csv", source_summary)
    write_csv(output / "retrieval_metrics/source_level_hit_per_query.csv", source_query)
    write_json(output / "composite_fact_gold_review_pack.json", build_atomic_review_pack(queries))
    write_json(output / "shared_qrels/shared_qrels_final_audit.json", qrels_audit(output / "shared_pool", output / "shared_qrels"))
    qa_rows = qa_comparison(repo, output)
    write_csv(output / "qa/qa_five_group_comparison.csv", qa_rows)
    (output / "attribution_report.md").write_text(attribution_report(output, source_summary, qa_rows), encoding="utf-8")
    state_path = cache_root / "hyper_final_experiment_v1_state.json"
    state = load_json(state_path)
    state["stages"] = dict(state.get("stages") or {})
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for name in ("source_level", "qrels_final_audit", "qa_comparison", "attribution"):
        state["stages"][name] = {"status": "completed", "updated_at": now, "details": {"output": str(output.resolve())}}
    state["stages"]["composite_fact_recall"] = {
        "status": "needs_manual_atomic_gold",
        "updated_at": now,
        "details": {"review_pack": str((output / "composite_fact_gold_review_pack.json").resolve())},
    }
    state["reporting_pending"] = True
    write_json(state_path, state)
    print(json.dumps({
        "source_level": str((output / "retrieval_metrics/source_level_hit_summary.csv").resolve()),
        "qrels_audit": str((output / "shared_qrels/shared_qrels_final_audit.json").resolve()),
        "qa_comparison": str((output / "qa/qa_five_group_comparison.csv").resolve()),
        "attribution": str((output / "attribution_report.md").resolve()),
        "composite_fact_recall": "pending_manual_atomic_gold",
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
