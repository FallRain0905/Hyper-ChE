"""Run retrieval benchmark metrics from qrels and candidate evidence.

This script is intentionally independent from Fact Coverage / QA evaluation.
It follows the IR-style evaluation used by the Hyper-RAG paper: graded qrels
are fixed, retrieval/reranking produces an ordered list, and metrics are
computed without LLM judging.
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
import json
import math
import re
import sys
from pathlib import Path
from typing import Any


STOPWORDS = {
    "the",
    "and",
    "or",
    "of",
    "to",
    "in",
    "at",
    "for",
    "with",
    "which",
    "what",
    "was",
    "were",
    "is",
    "are",
    "that",
    "this",
    "evidence",
    "supports",
    "involving",
}


GROUP_LABELS = {
    "text_segments": "Text",
    "text_bm25": "BM25 Text",
    "text_hybrid": "Hybrid Text",
    "original_hypergraph": "Original Hyper-RAG",
    "chem_prompt_graph": "C-Graph",
    "chem_prompt_hypergraph": "C-HG",
}

TOKEN_CACHE: dict[tuple[str, str], list[str]] = {}
QUERY_TOKEN_CACHE: dict[str, list[str]] = {}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def normalize(text: Any) -> str:
    value = str(text or "").lower()
    value = value.replace("cm−2", "cm2").replace("cm-2", "cm2").replace("cm^2", "cm2")
    value = value.replace("cm²", "cm2").replace("ω", "ohm").replace("·", " ")
    value = re.sub(r"m\s*a\s*(?:/|\s+)\s*cm\s*-?\s*2", "ma/cm2", value)
    value = re.sub(r"ohm\s*cm\s*2", "ohm cm2", value)
    value = re.sub(r"mol\s*(?:/|\s+)\s*l(?:-1)?", "mol/l", value)
    value = re.sub(r"[^a-z0-9.%/+:-]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def tokenize(text: Any) -> list[str]:
    return [tok for tok in normalize(text).split() if tok and tok not in STOPWORDS]


def candidate_text(item: dict[str, Any], *, view: str = "all") -> str:
    if view == "canonical":
        fields = [
            item.get("relation_type"),
            " ".join(map(str, item.get("canonical_vertices") or [])),
            " ".join(map(str, item.get("readable_labels") or [])),
        ]
    elif view == "surface":
        spans = []
        for inst in item.get("evidence_instances") or []:
            if isinstance(inst, dict):
                spans.extend(
                    str(inst.get(key) or "")
                    for key in ("evidence_span", "source_span", "sentence", "description")
                )
        fields = [
            item.get("readable_evidence"),
            item.get("source_sentence"),
            item.get("previous_sentence"),
            item.get("next_sentence"),
            " ".join(spans),
        ]
    else:
        fields = [
            item.get("relation_type"),
            item.get("readable_evidence"),
            item.get("source_sentence"),
            item.get("previous_sentence"),
            item.get("next_sentence"),
            " ".join(map(str, item.get("canonical_vertices") or [])),
            " ".join(map(str, item.get("readable_labels") or [])),
        ]
    return "\n".join(str(field) for field in fields if field)


def query_text(query: dict[str, Any]) -> str:
    fields = [
        query.get("question"),
        " ".join(map(str, query.get("required_entities") or [])),
        " ".join(str(x.get("canonical_id") or x) for x in query.get("required_conditions") or []),
        " ".join(str(x.get("canonical_id") or x) for x in query.get("required_metrics") or []),
        " ".join(map(str, query.get("required_mechanisms") or [])),
    ]
    return "\n".join(str(field) for field in fields if field)


def bm25_scores_from_tokens(query_id: str, query: str, doc_keys: list[tuple[str, str]], docs: list[str]) -> list[float]:
    if query_id not in QUERY_TOKEN_CACHE:
        QUERY_TOKEN_CACHE[query_id] = tokenize(query)
    q_terms = QUERY_TOKEN_CACHE[query_id]
    doc_terms = []
    for key, doc in zip(doc_keys, docs):
        if key not in TOKEN_CACHE:
            TOKEN_CACHE[key] = tokenize(doc)
        doc_terms.append(TOKEN_CACHE[key])
    if not docs:
        return []
    avgdl = sum(len(doc) for doc in doc_terms) / max(1, len(doc_terms))
    df = Counter()
    for doc in doc_terms:
        for term in set(doc):
            df[term] += 1
    n_docs = len(doc_terms)
    k1 = 1.5
    b = 0.75
    scores = []
    for doc in doc_terms:
        tf = Counter(doc)
        dl = len(doc)
        score = 0.0
        for term in q_terms:
            if not tf[term]:
                continue
            idf = math.log(1 + (n_docs - df[term] + 0.5) / (df[term] + 0.5))
            denom = tf[term] + k1 * (1 - b + b * dl / max(avgdl, 1e-9))
            score += idf * (tf[term] * (k1 + 1)) / denom
        scores.append(score)
    return scores


def minmax(values: list[float]) -> list[float]:
    if not values:
        return []
    lo = min(values)
    hi = max(values)
    if hi <= lo:
        return [0.0 for _ in values]
    return [(v - lo) / (hi - lo) for v in values]


def rank_to_score(rank: Any) -> float:
    try:
        r = int(rank)
    except Exception:
        r = 999
    return 1.0 / max(1, r)


def overlap_score(query: dict[str, Any], item: dict[str, Any]) -> float:
    text = normalize(candidate_text(item))
    required: list[str] = []
    required.extend(map(str, query.get("required_entities") or []))
    required.extend(str(x.get("canonical_id") or "") for x in query.get("required_conditions") or [])
    required.extend(str(x.get("canonical_id") or "") for x in query.get("required_metrics") or [])
    required.extend(map(str, query.get("required_mechanisms") or []))
    if not required:
        q_terms = set(tokenize(query_text(query)))
        d_terms = set(tokenize(text))
        return len(q_terms & d_terms) / max(1, len(q_terms))
    hits = 0
    for item_id in required:
        compact_id = normalize(item_id.replace("_", " ").replace(":", " "))
        if compact_id and compact_id in text:
            hits += 1
            continue
        tail = normalize(item_id.split(":", 1)[-1].replace("_", " "))
        if tail and tail in text:
            hits += 1
    return hits / max(1, len(required))


def relation_bonus(query: dict[str, Any], item: dict[str, Any]) -> float:
    relation = normalize(item.get("relation_type"))
    q = normalize(query.get("question") or query.get("gold_claim"))
    fact_type = normalize(query.get("fact_type"))
    if "comparison" in fact_type or any(x in q for x in ["compare", "while", "than"]):
        return 1.0 if "compar" in relation else 0.0
    if "degradation" in fact_type or any(x in q for x in ["degradation", "fade", "crossover", "mechanism"]):
        return 1.0 if any(x in relation for x in ["degradation", "mechanism"]) else 0.0
    if any(x in q for x in ["achieved", "current density", "efficiency", "retention"]):
        return 1.0 if any(x in relation for x in ["operation", "performance"]) else 0.0
    return 0.0


def order_candidates(group: str, query: dict[str, Any], items: list[dict[str, Any]], method: str) -> list[dict[str, Any]]:
    if not items:
        return []
    q = query_text(query)
    original = [rank_to_score(item.get("retrieval_rank")) for item in items]
    query_id = str(query.get("query_id") or query.get("id") or "")
    ids = [str(item.get("candidate_id") or item.get("id") or index) for index, item in enumerate(items)]
    norm_original = minmax(original)
    norm_bm25 = [0.0 for _ in items]
    norm_canonical = [0.0 for _ in items]
    norm_surface = [0.0 for _ in items]
    overlaps = [0.0 for _ in items]
    bonuses = [0.0 for _ in items]
    if method in {"bm25", "hybrid_text", "reranker"}:
        bm25_all = bm25_scores_from_tokens(query_id + "|all", q, [(cid, "all") for cid in ids], [candidate_text(item) for item in items])
        norm_bm25 = minmax(bm25_all)
    if method in {"dual_index", "reranker"}:
        bm25_canonical = bm25_scores_from_tokens(query_id + "|canonical", q, [(cid, "canonical") for cid in ids], [candidate_text(item, view="canonical") for item in items])
        bm25_surface = bm25_scores_from_tokens(query_id + "|surface", q, [(cid, "surface") for cid in ids], [candidate_text(item, view="surface") for item in items])
        norm_canonical = minmax(bm25_canonical)
        norm_surface = minmax(bm25_surface)
    if method == "reranker":
        overlaps = [overlap_score(query, item) for item in items]
        bonuses = [relation_bonus(query, item) for item in items]

    scored = []
    for idx, item in enumerate(items):
        if method == "current_order":
            score = original[idx]
        elif method == "bm25":
            score = norm_bm25[idx]
        elif method == "hybrid_text":
            score = 0.9 * norm_bm25[idx] + 0.1 * norm_original[idx]
        elif method == "dual_index":
            score = 0.40 * norm_canonical[idx] + 0.40 * norm_surface[idx] + 0.20 * norm_original[idx]
        elif method == "reranker":
            score = (
                0.25 * norm_original[idx]
                + 0.25 * max(norm_canonical[idx], norm_surface[idx])
                + 0.30 * overlaps[idx]
                + 0.10 * bonuses[idx]
                + 0.10 * min(float(item.get("top_n_pool") or 20), 20.0) / 20.0
            )
        else:
            raise ValueError(f"Unknown method: {method}")
        out = dict(item)
        out["benchmark_score"] = round(float(score), 6)
        out["benchmark_method"] = method
        scored.append((score, -int(item.get("retrieval_rank") or 999), out))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [item for _, _, item in scored]


def dcg(grades: list[int], k: int) -> float:
    return sum((2**grade - 1) / math.log2(i + 2) for i, grade in enumerate(grades[:k]))


def metrics_for_ranked(grades: list[int], *, threshold: int, k: int) -> dict[str, float]:
    binary = [1 if grade >= threshold else 0 for grade in grades]
    first = next((idx + 1 for idx, hit in enumerate(binary) if hit), None)
    ideal = sorted(grades, reverse=True)
    denom = dcg(ideal, k)
    return {
        "P@1": 1.0 if binary[:1] and binary[0] else 0.0,
        f"Hit@{k}": 1.0 if any(binary[:k]) else 0.0,
        "MRR": 1.0 / first if first else 0.0,
        f"gNDCG@{k}": dcg(grades, k) / denom if denom > 0 else 0.0,
    }


def read_inputs(candidate_path: Path, qrels_path: Path, queries_path: Path) -> tuple[list[dict[str, Any]], dict[tuple[str, str], int], dict[str, dict[str, Any]]]:
    candidates_obj = load_json(candidate_path)
    candidates = list(candidates_obj.get("candidate_evidence", candidates_obj if isinstance(candidates_obj, list) else []))
    qrels_obj = load_json(qrels_path)
    qrels = qrels_obj.get("qrels", qrels_obj if isinstance(qrels_obj, list) else [])
    qrel_map = {(str(row["query_id"]), str(row["candidate_id"])): int(row.get("relevance_grade", 0) or 0) for row in qrels}
    queries_obj = load_json(queries_path)
    queries = queries_obj.get("queries") or queries_obj.get("retrieval_queries") or queries_obj
    query_map = {str(row["query_id"]): row for row in queries}
    return candidates, qrel_map, query_map


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    keys = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate IR retrieval metrics from graded qrels.")
    parser.add_argument("--candidates", required=True, type=Path)
    parser.add_argument("--qrels", required=True, type=Path)
    parser.add_argument("--queries", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--thresholds", nargs="+", type=int, default=[1, 2, 3])
    parser.add_argument("--limit", type=int, help="Evaluate only the first N queries for smoke tests.")
    args = parser.parse_args()

    print(
        "[RetrievalBenchmark] WARNING: legacy evaluator uses system-local Top-k IDCG; "
        "use build_shared_retrieval_pool.py + evaluate_shared_retrieval_qrels.py for formal cross-system comparison.",
        file=sys.stderr,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    candidates, qrel_map, query_map = read_inputs(args.candidates, args.qrels, args.queries)
    by_query_group: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in candidates:
        by_query_group[(str(item.get("query_id")), str(item.get("candidate_group")))].append(item)

    systems = [
        ("text_segments", "current_order", "text_segments"),
        ("text_bm25", "bm25", "text_segments"),
        ("text_hybrid", "hybrid_text", "text_segments"),
        ("original_hypergraph", "current_order", "original_hypergraph"),
        ("chem_prompt_graph", "current_order", "chem_prompt_graph"),
        ("chem_prompt_hypergraph", "current_order", "chem_prompt_hypergraph"),
    ]

    summary_rows: list[dict[str, Any]] = []
    per_query_rows: list[dict[str, Any]] = []
    ranked_rows: list[dict[str, Any]] = []
    query_ids = sorted(query_map)
    if args.limit:
        query_ids = query_ids[: args.limit]
    for system_name, method, source_group in systems:
        ranked_cache: dict[str, tuple[list[dict[str, Any]], list[int]]] = {}
        for query_id in query_ids:
            query = query_map[query_id]
            items = by_query_group.get((query_id, source_group), [])
            if not items:
                continue
            ranked = order_candidates(source_group, query, items, method)
            grades = [qrel_map.get((query_id, str(item.get("candidate_id"))), 0) for item in ranked]
            ranked_cache[query_id] = (ranked, grades)
            for rank, item in enumerate(ranked[: args.k], start=1):
                ranked_rows.append(
                    {
                        "system": system_name,
                        "query_id": query_id,
                        "rank": rank,
                        "candidate_id": item.get("candidate_id"),
                        "qrel_grade": qrel_map.get((query_id, str(item.get("candidate_id"))), 0),
                        "benchmark_score": item.get("benchmark_score"),
                        "method": method,
                    }
                )
        for threshold in args.thresholds:
            metric_accumulator: list[dict[str, float]] = []
            evaluated = 0
            for query_id, (_ranked, grades) in ranked_cache.items():
                metrics = metrics_for_ranked(grades, threshold=threshold, k=args.k)
                metric_accumulator.append(metrics)
                evaluated += 1
                per_query_rows.append(
                    {
                        "system": system_name,
                        "label": GROUP_LABELS.get(system_name, system_name),
                        "source_group": source_group,
                        "method": method,
                        "threshold": f"grade>={threshold}",
                        "query_id": query_id,
                        "top1_grade": grades[0] if grades else 0,
                        f"top{args.k}_grades": " ".join(map(str, grades[: args.k])),
                        **{key: round(value, 6) for key, value in metrics.items()},
                    }
                )
            if evaluated:
                avg = {
                    key: sum(row[key] for row in metric_accumulator) / evaluated
                    for key in metric_accumulator[0]
                }
            else:
                avg = {"P@1": 0.0, f"Hit@{args.k}": 0.0, "MRR": 0.0, f"gNDCG@{args.k}": 0.0}
            summary_rows.append(
                {
                    "system": system_name,
                    "label": GROUP_LABELS.get(system_name, system_name),
                    "source_group": source_group,
                    "method": method,
                    "relevance_threshold": f"grade>={threshold}",
                    "queries": evaluated,
                    "P@1": round(avg["P@1"], 4),
                    f"Hit@{args.k}": round(avg[f"Hit@{args.k}"], 4),
                    "MRR": round(avg["MRR"], 4),
                    f"gNDCG@{args.k}": round(avg[f"gNDCG@{args.k}"], 4),
                }
            )

    write_csv(args.output_dir / "retrieval_benchmark_summary.csv", summary_rows)
    write_csv(args.output_dir / "retrieval_benchmark_per_query.csv", per_query_rows)
    write_csv(args.output_dir / "retrieval_benchmark_ranked_topk.csv", ranked_rows)
    report = {
        "evaluation_status": "diagnostic_only_system_local_idcg",
        "warning": "Not valid for formal cross-system gNDCG comparison; use pooled chunk-level qrels and shared IDCG.",
        "candidate_file": str(args.candidates),
        "qrels_file": str(args.qrels),
        "queries_file": str(args.queries),
        "k": args.k,
        "thresholds": args.thresholds,
        "systems": [{"system": s, "method": m, "source_group": g} for s, m, g in systems],
        "outputs": {
            "summary_csv": str(args.output_dir / "retrieval_benchmark_summary.csv"),
            "per_query_csv": str(args.output_dir / "retrieval_benchmark_per_query.csv"),
            "ranked_topk_csv": str(args.output_dir / "retrieval_benchmark_ranked_topk.csv"),
        },
        "summary": summary_rows,
    }
    (args.output_dir / "retrieval_benchmark_summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({"output_dir": str(args.output_dir), "summary_csv": report["outputs"]["summary_csv"], "systems": len(systems), "queries": len(query_ids)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
