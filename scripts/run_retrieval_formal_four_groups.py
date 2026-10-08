"""Run the frozen Retrieval Gold benchmark across four read-only systems.

The runner reads existing Hyper-RAG caches only. Graph/hypergraph evidence is
ranked first, then its source relations are aggregated back to chunk-level
Top-k results so all systems can share chunk-level qrels.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import csv
import hashlib
import json
import os
import re
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import run_qa_formal_llm as qa_formal  # noqa: E402
from scripts.structured_graph_retrieval import (  # noqa: E402
    StructuredGraphIndex,
    StructuredGraphRetriever,
    StructuredRetrievalConfig,
)
from scripts.upstream_hyper_query_retrieval import (  # noqa: E402
    ChunkRerankedUpstreamHyperQueryRetriever,
    UpstreamHyperQueryRetriever,
)

PROTOCOL_VERSION = 'retrieval-formal-v4-chem-domain-balanced-hyper-query'
GROUPS = {name: dict(spec) for name, spec in qa_formal.FORMAL_GROUPS.items()}
for _hyper_system in ('original_hypergraph', 'chem_prompt_hypergraph'):
    GROUPS[_hyper_system]['retriever'] = 'upstream_hyper_query'
GROUPS['original_hypergraph']['query_domain'] = 'default'
GROUPS['chem_prompt_hypergraph']['query_domain'] = 'flow_battery'
IMPROVED_GROUPS = {
    "chem_prompt_hypergraph_chunk_rerank": {
        "label": "Chem-Prompt Hypergraph + Chunk Dense Rerank",
        "cache": "hyper_chem_prompt",
        "view": "hyper",
        "retriever": "upstream_hyper_query_chunk_dense_rerank",
        "rerank": True,
        "query_domain": "flow_battery",
    }
}
OPTIONAL_GROUPS = {**qa_formal.OPTIONAL_GROUPS, **IMPROVED_GROUPS}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def configure_embedding_from_settings(settings_path: Path) -> None:
    """Use UI embedding settings only when explicit environment values are absent."""
    if os.getenv("EMB_API_KEY") or os.getenv("SILICONFLOW_API_KEY"):
        return
    settings = load_json(settings_path)
    keys = qa_formal.split_keys(settings.get("embeddingApiKey"))
    if keys:
        os.environ["EMB_API_KEY"] = ";".join(keys)
    if settings.get("embeddingBaseUrl"):
        os.environ.setdefault("EMB_BASE_URL", str(settings["embeddingBaseUrl"]))
    if settings.get("embeddingModel"):
        os.environ.setdefault("EMB_MODEL", str(settings["embeddingModel"]))
    if settings.get("embeddingDim"):
        os.environ.setdefault("EMB_DIM", str(settings["embeddingDim"]))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def selected_systems(value: str) -> dict[str, dict[str, Any]]:
    if value.strip().lower() == "all":
        return dict(GROUPS)
    if value.strip().lower() == "all_plus_chunk_rerank":
        return {**GROUPS, **IMPROVED_GROUPS}
    names = [item.strip() for item in value.split(",") if item.strip()]
    available = {**GROUPS, **OPTIONAL_GROUPS}
    unknown = [name for name in names if name not in available]
    if unknown:
        raise ValueError(f"Unknown systems: {unknown}; available={list(available)}")
    return {name: available[name] for name in names}


def protocol_version_for_systems(systems: dict[str, dict[str, Any]]) -> str:
    if list(systems) == list(GROUPS):
        return PROTOCOL_VERSION
    if list(systems) == ["naive_dense_rag"]:
        return "retrieval-formal-v2-naive-dense-optional-v1"
    if list(systems) == list({**GROUPS, **IMPROVED_GROUPS}):
        return "retrieval-formal-v5-upstream-hyper-query-chunk-rerank-ablation"
    if any(
        spec.get("retriever") == "upstream_hyper_query_chunk_dense_rerank"
        for spec in systems.values()
    ):
        return "retrieval-formal-v5-upstream-hyper-query-chunk-rerank-selected"
    if any(
        spec.get("retriever") == "upstream_hyper_query"
        for spec in systems.values()
    ):
        return "retrieval-formal-v4-chem-domain-balanced-hyper-query-selected"
    return "retrieval-formal-v2-structured-with-naive-dense-v1"


def complete_upstream_query_json(
    pool: qa_formal.FormalLLMClientPool,
    prompt: str,
    *,
    primary_max_tokens: int,
    length_fallback_max_tokens: int,
    max_retries: int,
) -> dict[str, Any]:
    """Call the query-keyword LLM with a length-only token fallback.

    A primary call is attempted once per retry slot. If the provider returns an
    empty final answer specifically because the completion budget was exhausted,
    retry immediately with the larger budget instead of wasting the remaining
    primary attempts on the same deterministic failure. Other failures retain
    the configured retry count and key-pool rotation.
    """

    errors: list[str] = []
    for _ in range(max(1, int(max_retries))):
        try:
            return pool.complete_json(
                prompt,
                max_tokens=int(primary_max_tokens),
                max_retries=1,
            )
        except RuntimeError as exc:
            message = str(exc)
            is_length_exhaustion = (
                "LLM returned empty content" in message
                and "finish_reason='length'" in message
            )
            if is_length_exhaustion and int(length_fallback_max_tokens) > int(primary_max_tokens):
                return pool.complete_json(
                    prompt,
                    max_tokens=int(length_fallback_max_tokens),
                    max_retries=max(1, int(max_retries)),
                )
            errors.append(message)
    raise RuntimeError("LLM call failed after retries: " + " || ".join(errors))


def query_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        rows = payload.get("queries") or payload.get("retrieval_queries")
        if isinstance(rows, list):
            return [item for item in rows if isinstance(item, dict)]
    raise ValueError("Query file must contain queries or retrieval_queries")


def source_doc_id(chunk_id: str, chunk: dict[str, Any]) -> str:
    value = str(chunk.get("source_doc_id") or chunk.get("doc_id") or "").strip()
    if value:
        return value
    match = re.match(r"(RFB_\d+)_CHK_\d+", chunk_id, flags=re.IGNORECASE)
    return match.group(1).upper() if match else ""


def hybrid_retrieve(
    *, query: dict[str, Any], system: str, retriever: qa_formal.HybridTextRetriever, top_k: int
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for rank, item in enumerate(retriever.search(str(query.get("question") or ""), top_k), start=1):
        cid = str(item.get("id") or item.get("source_chunk_id") or "")
        chunk = retriever.chunks.get(cid, {})
        rows.append(
            {
                "query_id": str(query["query_id"]),
                "system": system,
                "candidate_group": system,
                "candidate_id": f"{system}:{cid}",
                "chunk_id": cid,
                "retrieval_rank": rank,
                "retrieval_score": float(item.get("retrieval_score") or 0.0),
                "dense_rank": item.get("dense_rank"),
                "bm25_rank": item.get("bm25_rank"),
                "source_doc_ids": [source_doc_id(cid, chunk)],
                "source_file": chunk.get("source_file"),
                "content": chunk.get("content", item.get("text", "")),
                "retrieval_channels": ["dense", "bm25", "weighted_rrf"],
            }
        )
    return rows


def naive_retrieve(
    *, query: dict[str, Any], system: str, retriever: qa_formal.NaiveDenseRetriever, top_k: int
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for rank, item in enumerate(retriever.search(str(query.get("question") or ""), top_k), start=1):
        cid = str(item.get("id") or item.get("source_chunk_id") or "")
        chunk = retriever.chunks.get(cid, {})
        rows.append(
            {
                "query_id": str(query["query_id"]),
                "system": system,
                "candidate_group": system,
                "candidate_id": f"{system}:{cid}",
                "chunk_id": cid,
                "retrieval_rank": rank,
                "retrieval_score": float(item.get("retrieval_score") or 0.0),
                "dense_rank": item.get("dense_rank"),
                "bm25_rank": None,
                "source_doc_ids": [source_doc_id(cid, chunk)],
                "source_file": chunk.get("source_file"),
                "content": chunk.get("content", item.get("text", "")),
                "retrieval_method": "naive_chunk_dense",
                "retrieval_channels": ["chunk_dense"],
                "supporting_edge_ids": [],
                "supporting_arities": [],
                "supporting_relation_types": [],
            }
        )
    return rows


def structured_retrieve(
    *, query: dict[str, Any], system: str, retriever: StructuredGraphRetriever, top_k: int
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for rank, item in enumerate(retriever.search(str(query.get('question') or ''), top_k), start=1):
        chunk_id = str(item.get('source_chunk_id') or item.get('id') or '')
        rows.append(
            {
                'query_id': str(query['query_id']),
                'system': system,
                'candidate_group': system,
                'candidate_id': '{}:{}'.format(system, chunk_id),
                'chunk_id': chunk_id,
                'retrieval_rank': rank,
                'retrieval_score': float(item.get('retrieval_score') or 0.0),
                'max_supporting_edge_score': float(item.get('max_supporting_edge_score') or 0.0),
                'source_doc_ids': item.get('source_doc_ids') or [],
                'source_file': item.get('source_file'),
                'content': item.get('chunk_content') or '',
                'readable_evidence': item.get('readable_evidence') or '',
                'retrieval_method': item.get('retrieval_method'),
                'retrieval_channels': item.get('retrieval_channels') or [],
                'supporting_edge_ids': item.get('supporting_edge_ids') or [],
                'supporting_arities': item.get('supporting_arities') or [],
                'supporting_relation_types': item.get('supporting_relation_types') or [],
                'supporting_relations': item.get('supporting_relations') or [],
            }
        )
    return rows


def upstream_retrieve(
    *,
    query: dict[str, Any],
    system: str,
    retriever: UpstreamHyperQueryRetriever,
    top_k: int,
    precomputed: tuple[list[dict[str, Any]], dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    mapped, audit = (
        precomputed
        if precomputed is not None
        else retriever.search(str(query.get("question") or ""), top_k)
    )
    rows: list[dict[str, Any]] = []
    for rank, item in enumerate(mapped, start=1):
        chunk_id = str(item["chunk_id"])
        chunk = item["chunk"]
        reranked = item.get("chunk_dense_score") is not None
        rows.append(
            {
                "query_id": str(query["query_id"]),
                "system": system,
                "candidate_group": system,
                "candidate_id": f"{system}:{chunk_id}",
                "chunk_id": chunk_id,
                "retrieval_rank": rank,
                "retrieval_score": float(item.get("retrieval_score") or 0.0),
                "source_doc_ids": [source_doc_id(chunk_id, chunk)],
                "source_file": chunk.get("source_file"),
                "content": chunk.get("content", ""),
                "retrieval_method": (
                    "upstream_hyper_query_chunk_dense_rerank"
                    if reranked
                    else "upstream_hyper_query"
                ),
                "retrieval_channels": [
                    f"hyper_query_{item.get('retrieval_branch', 'unknown')}_text_units"
                ],
                "retrieval_branch": item.get("retrieval_branch"),
                "mapping_method": item.get("mapping_method"),
                "upstream_text_unit_index": item.get("text_unit_index"),
                "upstream_branch_ranks": item.get("branch_ranks") or {},
                "candidate_pool_rank": item.get("candidate_pool_rank"),
                "chunk_dense_score": item.get("chunk_dense_score"),
                "rerank_rank": item.get("rerank_rank"),
                "supporting_edge_ids": [],
                "supporting_arities": [],
                "supporting_relation_types": [],
            }
        )
    return rows, audit


def add_gold_diagnostics(
    query: dict[str, Any],
    audit: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    """Attach stage-level gold diagnostics without influencing retrieval."""

    gold_ids = [str(value) for value in (query.get("gold_chunk_ids") or []) if str(value)]
    gold_set = set(gold_ids)
    source_doc = str(query.get("source_doc_id") or "")
    branch_ranks = audit.get("branch_rank_by_chunk") or {}
    entity_ranks = branch_ranks.get("entity") or {}
    relation_ranks = branch_ranks.get("relation") or {}
    has_full_branch_pool = bool(branch_ranks)
    balanced_ids = {
        str(value) for value in (audit.get("balanced_selected_chunk_ids") or [])
    }
    final_rank_by_chunk = {
        str(item.get("chunk_id") or ""): int(item.get("retrieval_rank") or index)
        for index, item in enumerate(candidates, start=1)
    }
    final_ids = set(final_rank_by_chunk)
    union_ids = (
        set(entity_ranks) | set(relation_ranks)
        if has_full_branch_pool
        else set(final_ids)
    )
    if not balanced_ids and not has_full_branch_pool:
        balanced_ids = set(final_ids)
    candidate_source_docs = {
        str(doc_id)
        for item in candidates
        for doc_id in (item.get("source_doc_ids") or [])
        if str(doc_id)
    }

    candidate_hit = bool(gold_set & union_ids)
    final_hit = bool(gold_set & final_ids)
    balanced_hit = bool(gold_set & balanced_ids)
    reranked = audit.get("posthoc_reranking") == "chunk_dense_cosine_only"
    if not bool(query.get("retrievable")):
        loss_stage = "not_applicable_unretrievable"
    elif final_hit:
        loss_stage = "retrieved"
    elif not candidate_hit:
        loss_stage = "candidate_generation_or_mapping"
    elif reranked:
        loss_stage = "chunk_dense_rerank_or_topk"
    else:
        loss_stage = "balanced_branch_quota_or_topk"

    audit["gold_diagnostics"] = {
        "retrievable": bool(query.get("retrievable")),
        "candidate_diagnostics_scope": (
            "complete_upstream_branch_union"
            if has_full_branch_pool
            else "final_topk_only"
        ),
        "gold_chunk_ids": gold_ids,
        "gold_source_doc_id": source_doc,
        "entity_branch_hit": bool(gold_set & set(entity_ranks)),
        "relation_branch_hit": bool(gold_set & set(relation_ranks)),
        "candidate_union_hit": candidate_hit,
        "balanced_topk_hit": balanced_hit,
        "final_topk_hit": final_hit,
        "source_document_hit": bool(source_doc and source_doc in candidate_source_docs),
        "dropped_by_balanced_quota_or_topk": candidate_hit and not balanced_hit,
        "dropped_by_chunk_rerank_or_topk": reranked and candidate_hit and not final_hit,
        "loss_stage": loss_stage,
        "per_gold_chunk": [
            {
                "chunk_id": chunk_id,
                "entity_branch_rank": entity_ranks.get(chunk_id),
                "relation_branch_rank": relation_ranks.get(chunk_id),
                "in_candidate_union": chunk_id in union_ids,
                "in_balanced_topk": chunk_id in balanced_ids,
                "final_rank": final_rank_by_chunk.get(chunk_id),
            }
            for chunk_id in gold_ids
        ],
    }
    return audit


def gold_diagnostic_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [
        result.get("retrieval_audit", {}).get("gold_diagnostics", {})
        for result in results
    ]
    retrievable = [row for row in rows if row.get("retrievable")]
    unanswerable = [row for row in rows if not row.get("retrievable")]

    def rate(key: str) -> float:
        return (
            sum(bool(row.get(key)) for row in retrievable) / len(retrievable)
            if retrievable
            else 0.0
        )

    loss_counts: dict[str, int] = {}
    for row in retrievable:
        stage = str(row.get("loss_stage") or "unknown")
        loss_counts[stage] = loss_counts.get(stage, 0) + 1
    return {
        "query_count": len(rows),
        "retrievable_query_count": len(retrievable),
        "unretrievable_query_count": len(unanswerable),
        "entity_branch_gold_hit_rate": rate("entity_branch_hit"),
        "relation_branch_gold_hit_rate": rate("relation_branch_hit"),
        "candidate_union_gold_recall": rate("candidate_union_hit"),
        "balanced_topk_exact_gold_hit_rate": rate("balanced_topk_hit"),
        "final_topk_exact_gold_hit_rate": rate("final_topk_hit"),
        "final_topk_source_document_hit_rate": rate("source_document_hit"),
        "balanced_quota_or_topk_loss_count": sum(
            bool(row.get("dropped_by_balanced_quota_or_topk")) for row in retrievable
        ),
        "chunk_rerank_or_topk_loss_count": sum(
            bool(row.get("dropped_by_chunk_rerank_or_topk")) for row in retrievable
        ),
        "loss_stage_counts": dict(sorted(loss_counts.items())),
    }


def diagnostic_export_rows(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for result in results:
        audit = result.get("retrieval_audit") or {}
        gold = audit.get("gold_diagnostics") or {}
        rows.append(
            {
                "query_id": result.get("query_id"),
                "retrievable": result.get("retrievable"),
                "entity_keywords": audit.get("entity_keywords"),
                "relation_keywords": audit.get("relation_keywords"),
                "query_domain": audit.get("query_domain"),
                "query_prompt_source": audit.get("query_prompt_source"),
                "mapped_entity_count": audit.get("mapped_entity_count"),
                "mapped_relation_count": audit.get("mapped_relation_count"),
                "candidate_union_count": audit.get("candidate_union_count"),
                "returned_chunk_count": audit.get("returned_chunk_count"),
                "gold_chunk_ids": json.dumps(gold.get("gold_chunk_ids") or []),
                "candidate_diagnostics_scope": gold.get("candidate_diagnostics_scope"),
                "entity_branch_gold_hit": gold.get("entity_branch_hit"),
                "relation_branch_gold_hit": gold.get("relation_branch_hit"),
                "candidate_union_gold_hit": gold.get("candidate_union_hit"),
                "balanced_topk_gold_hit": gold.get("balanced_topk_hit"),
                "final_topk_gold_hit": gold.get("final_topk_hit"),
                "source_document_hit": gold.get("source_document_hit"),
                "loss_stage": gold.get("loss_stage"),
                "per_gold_chunk": json.dumps(gold.get("per_gold_chunk") or []),
                "unmatched_text_unit_count": len(audit.get("unmatched_text_units") or []),
                "ambiguous_text_unit_count": len(audit.get("ambiguous_text_units") or []),
            }
        )
    return rows

def retrieval_diagnostics(results: list[dict[str, Any]]) -> dict[str, Any]:
    channel_candidates: dict[str, int] = {}
    channel_queries: dict[str, set[str]] = {}
    arity_candidates: dict[int, int] = {}
    high_order_candidates = 0
    high_order_queries: set[str] = set()
    reconstructed_chunks = 0
    candidate_count = 0
    supporting_edge_count = 0
    for result in results:
        query_id = str(result.get('query_id') or '')
        for candidate in result.get('candidates') or []:
            candidate_count += 1
            reconstructed_chunks += int(bool(str(candidate.get('content') or '').strip()))
            supporting_edge_count += len(candidate.get('supporting_edge_ids') or [])
            channels = {str(value) for value in (candidate.get('retrieval_channels') or []) if str(value)}
            for channel in channels:
                channel_candidates[channel] = channel_candidates.get(channel, 0) + 1
                channel_queries.setdefault(channel, set()).add(query_id)
            arities = {int(value) for value in (candidate.get('supporting_arities') or [])}
            for arity in arities:
                arity_candidates[arity] = arity_candidates.get(arity, 0) + 1
            if any(arity > 2 for arity in arities):
                high_order_candidates += 1
                high_order_queries.add(query_id)
    query_count = len({str(result.get('query_id') or '') for result in results})
    return {
        'candidate_count': candidate_count,
        'full_chunk_reconstruction_rate': reconstructed_chunks / candidate_count if candidate_count else 0.0,
        'avg_supporting_edges_per_candidate': supporting_edge_count / candidate_count if candidate_count else 0.0,
        'channel_candidate_counts': dict(sorted(channel_candidates.items())),
        'channel_query_counts': {key: len(value) for key, value in sorted(channel_queries.items())},
        'arity_candidate_counts': {str(key): value for key, value in sorted(arity_candidates.items())},
        'high_order_candidate_count': high_order_candidates,
        'high_order_candidate_rate': high_order_candidates / candidate_count if candidate_count else 0.0,
        'queries_with_high_order_evidence': len(high_order_queries),
        'queries_with_high_order_evidence_rate': len(high_order_queries) / query_count if query_count else 0.0,
    }


def readiness(queries_path: Path, cache_root: Path, systems: dict[str, dict[str, Any]]) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    payload = load_json(queries_path)
    rows = query_rows(payload)
    metadata = payload.get("metadata", {}) if isinstance(payload, dict) else {}
    checks.append({"name": "gold_status", "pass": metadata.get("status") == "final_gold" and metadata.get("human_confirmed") is True, "value": {"status": metadata.get("status"), "human_confirmed": metadata.get("human_confirmed")}})
    checks.append({"name": "query_count", "pass": len(rows) == 58, "value": len(rows)})
    checks.append({"name": "unique_query_ids", "pass": len({str(row.get('query_id')) for row in rows}) == len(rows), "value": len({str(row.get('query_id')) for row in rows})})
    for cache_name in sorted({spec["cache"] for spec in systems.values()}):
        cache = cache_root / cache_name
        required = [cache / 'kv_store_full_docs.json', cache / 'kv_store_text_chunks.json', cache / 'vdb_chunks.json']
        if any(spec['cache'] == cache_name and spec['view'] != 'text' for spec in systems.values()):
            required.extend(
                [
                    cache / 'hypergraph_chunk_entity_relation.hgdb',
                    cache / 'vdb_entities.json',
                    cache / 'vdb_relationships.json',
                ]
            )
        checks.append({"name": f"cache_files:{cache_name}", "pass": all(path.exists() for path in required), "missing": [str(path) for path in required if not path.exists()]})
        if (cache / "kv_store_full_docs.json").exists() and (cache / "kv_store_text_chunks.json").exists():
            docs = load_json(cache / "kv_store_full_docs.json")
            chunks = load_json(cache / "kv_store_text_chunks.json")
            checks.append({"name": f"cache_counts:{cache_name}", "pass": len(docs) == 60 and len(chunks) == 1328, "docs": len(docs), "chunks": len(chunks)})
    failures = [item for item in checks if not item.get("pass")]
    return {"status": "PASS" if not failures else "FAIL", "checks": checks, "fail_count": len(failures), "query_file_sha256": sha256_file(queries_path)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queries", required=True, type=Path)
    parser.add_argument("--cache-root", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--settings", type=Path, default=REPO_ROOT / "web-ui" / "backend" / "settings.json")
    parser.add_argument("--provider", default="siliconflow")
    parser.add_argument("--model")
    parser.add_argument("--base-url")
    parser.add_argument("--llm-timeout", type=float, default=600.0)
    parser.add_argument(
        "--systems",
        default="all",
        help=(
            "Comma-separated systems. 'all' intentionally keeps the frozen original four systems; "
            "optional systems such as naive_dense_rag must be selected explicitly."
        ),
    )
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--hybrid-candidate-depth", type=int, default=50)
    parser.add_argument("--rrf-k", type=int, default=60)
    parser.add_argument("--dense-weight", type=float, default=1.0)
    parser.add_argument("--bm25-weight", type=float, default=1.0)
    parser.add_argument("--naive-cosine-threshold", type=float, default=0.2)
    parser.add_argument('--relationship-candidate-depth', type=int, default=50)
    parser.add_argument('--entity-candidate-depth', type=int, default=30)
    parser.add_argument('--graph-bm25-candidate-depth', type=int, default=50)
    parser.add_argument('--structured-rrf-k', type=int, default=60)
    parser.add_argument('--graph-expansion-hops', type=int, default=1)
    parser.add_argument('--graph-max-expanded-edges', type=int, default=100)
    parser.add_argument('--graph-rerank-candidate-depth', type=int, default=50)
    parser.add_argument('--graph-chunk-candidate-depth', type=int, default=30)
    parser.add_argument('--relationship-dense-weight', type=float, default=1.0)
    parser.add_argument('--relationship-bm25-weight', type=float, default=1.0)
    parser.add_argument('--entity-dense-weight', type=float, default=0.8)
    parser.add_argument('--entity-bm25-weight', type=float, default=0.8)
    parser.add_argument('--graph-expansion-weight', type=float, default=0.9)
    parser.add_argument("--parallel-workers", type=int, default=5)
    parser.add_argument("--embedding-timeout", type=float, default=600.0)
    parser.add_argument("--embedding-max-retries", type=int, default=5)
    parser.add_argument("--llm-max-retries", type=int, default=5)
    parser.add_argument("--upstream-llm-max-tokens", type=int, default=4096)
    parser.add_argument("--upstream-llm-length-fallback-max-tokens", type=int, default=16384)
    parser.add_argument("--upstream-graph-top-k", type=int, default=60)
    parser.add_argument("--upstream-entity-quota", type=int, default=10)
    parser.add_argument("--upstream-relation-quota", type=int, default=10)
    parser.add_argument("--upstream-query-expansion", action="store_true", help="Use deterministic normalized and abbreviation query variants.")
    parser.add_argument("--upstream-max-query-variants", type=int, default=2)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--readiness-only", action="store_true")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    if not args.readiness_only and not args.run_id.strip():
        parser.error("--run-id is required for a formal run")
    if (
        args.top_k <= 0
        or args.parallel_workers <= 0
        or args.upstream_llm_max_tokens <= 0
        or args.upstream_llm_length_fallback_max_tokens <= 0
    ):
        parser.error("--top-k and --parallel-workers must be positive")
    if args.upstream_entity_quota < 0 or args.upstream_relation_quota < 0:
        parser.error("--upstream-entity-quota and --upstream-relation-quota cannot be negative")
    if args.upstream_entity_quota + args.upstream_relation_quota == 0:
        parser.error("at least one upstream branch quota must be positive")
    if args.upstream_max_query_variants <= 0:
        parser.error("--upstream-max-query-variants must be positive")

    systems = selected_systems(args.systems)
    protocol_version = protocol_version_for_systems(systems)
    report = readiness(args.queries, args.cache_root, systems)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.output_dir / "readiness_report.json", report)
    print(json.dumps({"readiness": report["status"], "fail_count": report["fail_count"]}, ensure_ascii=False), flush=True)
    if args.readiness_only:
        raise SystemExit(0 if report["status"] == "PASS" else 2)
    if report["status"] != "PASS":
        raise RuntimeError("Retrieval readiness failed; see readiness_report.json")

    payload = load_json(args.queries)
    queries = query_rows(payload)
    if args.limit:
        queries = queries[: args.limit]
    configure_embedding_from_settings(args.settings)
    embedding_pool = qa_formal.EmbeddingClientPool(
        timeout=args.embedding_timeout,
        max_retries=args.embedding_max_retries,
    )
    upstream_llm_pool: qa_formal.FormalLLMClientPool | None = None
    if any(
        spec["retriever"] in {
            "upstream_hyper_query",
            "upstream_hyper_query_chunk_dense_rerank",
        }
        for spec in systems.values()
    ):
        upstream_llm_pool = qa_formal.FormalLLMClientPool(
            args.settings,
            args.provider,
            model_override=args.model,
            base_url_override=args.base_url,
            timeout=args.llm_timeout,
        )
    structured_config = StructuredRetrievalConfig(
        relationship_candidate_depth=args.relationship_candidate_depth,
        entity_candidate_depth=args.entity_candidate_depth,
        bm25_candidate_depth=args.graph_bm25_candidate_depth,
        rrf_k=args.structured_rrf_k,
        relationship_dense_weight=args.relationship_dense_weight,
        relationship_bm25_weight=args.relationship_bm25_weight,
        entity_dense_weight=args.entity_dense_weight,
        entity_bm25_weight=args.entity_bm25_weight,
        expansion_weight=args.graph_expansion_weight,
        expansion_hops=args.graph_expansion_hops,
        max_expanded_edges=args.graph_max_expanded_edges,
        rerank_candidate_depth=args.graph_rerank_candidate_depth,
        chunk_candidate_depth=args.graph_chunk_candidate_depth,
    )
    structured_indexes: dict[str, StructuredGraphIndex] = {}
    for spec in systems.values():
        if spec['retriever'] == 'structured_graph_hybrid_v1':
            cache_name = str(spec['cache'])
            if cache_name not in structured_indexes:
                structured_indexes[cache_name] = StructuredGraphIndex(args.cache_root / cache_name)
    protocol = {
        "protocol_version": protocol_version,
        "run_id": args.run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "queries": str(args.queries.resolve()),
        "query_sha256": report["query_file_sha256"],
        "cache_root": str(args.cache_root.resolve()),
        "systems": systems,
        "query_count": len(queries),
        "top_k": args.top_k,
        "source_doc_filter_used": False,
        "upstream_hyper_query_method": {
            "method": "direct hyperrag.operate.hyper_query call",
            "adapter": "maps entity/relation text units to frozen chunk IDs; preserves each upstream branch order",
            "merge_strategy": "interleaved_entity_relation_quota",
            "query_domains": {
                name: spec.get("query_domain", "default")
                for name, spec in systems.items()
                if spec.get("retriever")
                in {"upstream_hyper_query", "upstream_hyper_query_chunk_dense_rerank"}
            },
            "query_prompt_policy": "selected by query_domain in operate._get_query_keywords_prompt",
            "query_prompt_sources": {
                name: (
                    "hyperrag.prompt.PROMPTS[keywords_extraction]"
                    if spec.get("query_domain", "default") == "default"
                    else f"hyperrag/domains/{spec.get('query_domain')}/query_keywords.txt"
                )
                for name, spec in systems.items()
                if spec.get("retriever")
                in {"upstream_hyper_query", "upstream_hyper_query_chunk_dense_rerank"}
            },
            "llm_primary_max_tokens": args.upstream_llm_max_tokens,
            "llm_length_fallback_max_tokens": args.upstream_llm_length_fallback_max_tokens,
            "llm_length_fallback_condition": "empty content with finish_reason=length",
            "graph_top_k": args.upstream_graph_top_k,
            "entity_quota": args.upstream_entity_quota,
            "relation_quota": args.upstream_relation_quota,
            "query_expansion_enabled": args.upstream_query_expansion,
            "max_query_variants": args.upstream_max_query_variants,
            "fusion": False,
            "posthoc_reranking": False,
        },
        "chunk_rerank_ablation": {
            "system": "chem_prompt_hypergraph_chunk_rerank",
            "candidate_source": "complete mapped entity/relation text-unit union from hyperrag.operate.hyper_query",
            "score": "cosine(query embedding, existing vdb_chunks.json vector)",
            "lexical_fusion": False,
            "extra_graph_expansion": False,
            "paired_candidate_reuse": "reuses chem_prompt_hypergraph branch_rank_by_chunk when both systems run together",
            "replaces_baseline": False,
        },
        'structured_graph_method': 'relationship dense + relationship BM25 + entity dense + entity BM25 + weighted RRF + incident-edge expansion + deterministic structural rerank + full source-chunk reconstruction',
        'structured_graph_config': structured_config.as_dict(),
        'structured_cache_mapping_audits': {
            name: index.mapping_audit for name, index in structured_indexes.items()
        },
        "hybrid_method": "BM25 + Qwen dense cosine + weighted RRF",
        "hybrid_candidate_depth": args.hybrid_candidate_depth,
        "rrf_k": args.rrf_k,
        "dense_weight": args.dense_weight,
        "bm25_weight": args.bm25_weight,
        "parallel_workers": args.parallel_workers,
        "cache_read_only": True,
    }
    if 'naive_dense_rag' in systems:
        protocol['naive_dense_method'] = {
            'method': 'upstream Hyper-RAG naive mode: Qwen chunk dense cosine Top-K only',
            'cosine_threshold': args.naive_cosine_threshold,
            'bm25': False,
            'graph_access': False,
            'reranker': False,
        }
    protocol_path = args.output_dir / "run_protocol.json"
    if protocol_path.exists():
        old = load_json(protocol_path)
        comparable = {key: value for key, value in protocol.items() if key != "created_at"}
        old_comparable = {key: value for key, value in old.items() if key != "created_at"}
        if old_comparable != comparable:
            raise RuntimeError("Output directory has a different protocol; use another --output-dir")
    else:
        write_json(protocol_path, protocol)

    summaries: list[dict[str, Any]] = []
    completed_by_system: dict[str, dict[str, dict[str, Any]]] = {}
    for system, spec in systems.items():
        started = time.perf_counter()
        system_dir = args.output_dir / system
        system_dir.mkdir(parents=True, exist_ok=True)
        progress_path = system_dir / "retrieval_query_results.jsonl"
        completed: dict[str, dict[str, Any]] = {}
        if args.resume and progress_path.exists():
            for line in progress_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = json.loads(line)
                    if row.get("status") == "success":
                        completed[str(row["query_id"])] = row
        hybrid: qa_formal.HybridTextRetriever | None = None
        naive: qa_formal.NaiveDenseRetriever | None = None
        structured: StructuredGraphRetriever | None = None
        upstream: UpstreamHyperQueryRetriever | None = None
        upstream_reranked: ChunkRerankedUpstreamHyperQueryRetriever | None = None
        if spec["retriever"] == "bm25_dense_rrf":
            hybrid = qa_formal.HybridTextRetriever(args.cache_root / spec["cache"], embedding_pool, candidate_depth=args.hybrid_candidate_depth, rrf_k=args.rrf_k, dense_weight=args.dense_weight, bm25_weight=args.bm25_weight)
        elif spec["retriever"] == "naive_chunk_dense":
            naive = qa_formal.NaiveDenseRetriever(
                args.cache_root / spec["cache"],
                embedding_pool,
                cosine_threshold=args.naive_cosine_threshold,
            )
        elif spec["retriever"] == "upstream_hyper_query":
            assert upstream_llm_pool is not None
            upstream = UpstreamHyperQueryRetriever(
                args.cache_root / spec["cache"],
                llm_json_func=lambda prompt: complete_upstream_query_json(
                    upstream_llm_pool,
                    prompt,
                    primary_max_tokens=args.upstream_llm_max_tokens,
                    length_fallback_max_tokens=args.upstream_llm_length_fallback_max_tokens,
                    max_retries=args.llm_max_retries,
                ),
                embedding_func=embedding_pool.embed,
                embedding_dim=embedding_pool.dimension,
                graph_top_k=args.upstream_graph_top_k,
                cosine_threshold=args.naive_cosine_threshold,
                query_domain=spec.get("query_domain", "default"),
                entity_quota=args.upstream_entity_quota,
                relation_quota=args.upstream_relation_quota,
                enable_query_expansion=args.upstream_query_expansion,
                max_query_variants=args.upstream_max_query_variants,
            )
        elif spec["retriever"] == "upstream_hyper_query_chunk_dense_rerank":
            assert upstream_llm_pool is not None
            upstream_reranked = ChunkRerankedUpstreamHyperQueryRetriever(
                args.cache_root / spec["cache"],
                llm_json_func=lambda prompt: complete_upstream_query_json(
                    upstream_llm_pool,
                    prompt,
                    primary_max_tokens=args.upstream_llm_max_tokens,
                    length_fallback_max_tokens=args.upstream_llm_length_fallback_max_tokens,
                    max_retries=args.llm_max_retries,
                ),
                embedding_func=embedding_pool.embed,
                embedding_dim=embedding_pool.dimension,
                graph_top_k=args.upstream_graph_top_k,
                cosine_threshold=args.naive_cosine_threshold,
                query_domain=spec.get("query_domain", "default"),
                entity_quota=args.upstream_entity_quota,
                relation_quota=args.upstream_relation_quota,
                enable_query_expansion=args.upstream_query_expansion,
                max_query_variants=args.upstream_max_query_variants,
            )
        elif spec["retriever"] == "structured_graph_hybrid_v1":
            structured = StructuredGraphRetriever(
                structured_indexes[str(spec['cache'])],
                embedding_pool,
                view=str(spec['view']),
                config=structured_config,
            )
        else:
            raise ValueError(f"Unknown retriever for {system}: {spec['retriever']}")

        pending = [query for query in queries if str(query["query_id"]) not in completed]
        write_lock = threading.Lock()

        def run_one(query: dict[str, Any]) -> dict[str, Any]:
            qid = str(query["query_id"])
            t0 = time.perf_counter()
            retrieval_audit: dict[str, Any] = {}
            if hybrid is not None:
                candidates = hybrid_retrieve(query=query, system=system, retriever=hybrid, top_k=args.top_k)
            elif naive is not None:
                candidates = naive_retrieve(query=query, system=system, retriever=naive, top_k=args.top_k)
            elif upstream is not None:
                candidates, retrieval_audit = upstream_retrieve(
                    query=query,
                    system=system,
                    retriever=upstream,
                    top_k=args.top_k,
                )
            elif upstream_reranked is not None:
                paired = completed_by_system.get("chem_prompt_hypergraph", {}).get(qid)
                precomputed = None
                if paired is not None:
                    precomputed = upstream_reranked.rerank_from_upstream_audit(
                        str(query.get("question") or ""),
                        paired.get("retrieval_audit") or {},
                        top_k=args.top_k,
                    )
                candidates, retrieval_audit = upstream_retrieve(
                    query=query,
                    system=system,
                    retriever=upstream_reranked,
                    top_k=args.top_k,
                    precomputed=precomputed,
                )
            else:
                assert structured is not None
                candidates = structured_retrieve(query=query, system=system, retriever=structured, top_k=args.top_k)
            add_gold_diagnostics(query, retrieval_audit, candidates)
            return {
                "status": "success", "query_id": qid,
                "retrievable": bool(query.get("retrievable")),
                "candidate_count": len(candidates),
                "elapsed_seconds": round(time.perf_counter() - t0, 3),
                "retrieval_audit": retrieval_audit, "candidates": candidates,
            }

        errors: list[dict[str, Any]] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.parallel_workers) as executor:
            future_map = {executor.submit(run_one, query): query for query in pending}
            for future in concurrent.futures.as_completed(future_map):
                query = future_map[future]
                qid = str(query["query_id"])
                try:
                    row = future.result()
                    completed[qid] = row
                    with write_lock, progress_path.open("a", encoding="utf-8") as handle:
                        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                    print(f"[RetrievalFormal] done {system} {qid} candidates={row['candidate_count']} ({len(completed)}/{len(queries)})", flush=True)
                except Exception as exc:  # noqa: BLE001
                    errors.append({"query_id": qid, "system": system, "error": f"{type(exc).__name__}: {exc}"})
                    print(f"[RetrievalFormal] error {system} {qid}: {type(exc).__name__}: {exc}", flush=True)

        ordered_results = [completed[str(query["query_id"])] for query in queries if str(query["query_id"]) in completed]
        completed_by_system[system] = dict(completed)
        candidates = [candidate for result in ordered_results for candidate in result["candidates"]]
        diagnostics = retrieval_diagnostics(ordered_results)
        gold_diagnostics = gold_diagnostic_summary(ordered_results)
        metadata = {
            "protocol_version": protocol_version,
            "run_id": args.run_id,
            "system": system,
            "system_spec": spec,
            "query_count_expected": len(queries),
            "query_count_completed": len(ordered_results),
            "candidate_count": len(candidates),
            "top_k": args.top_k,
            "failure_count": len(errors),
            "source_doc_filter_used": False,
            "cache_read_only": True,
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            'retrieval_diagnostics': diagnostics,
            'gold_retrieval_diagnostics': gold_diagnostics,
        }
        write_json(system_dir / "candidate_evidence.json", {"metadata": metadata, "candidate_evidence": candidates})
        write_json(system_dir / "retrieval_results.json", {"metadata": metadata, "results": ordered_results, "errors": errors})
        write_json(
            system_dir / "retrieval_loss_diagnostics.json",
            {
                "metadata": metadata,
                "per_query": diagnostic_export_rows(ordered_results),
            },
        )
        write_csv(
            system_dir / "retrieval_loss_diagnostics.csv",
            diagnostic_export_rows(ordered_results),
        )
        write_json(system_dir / "run_summary.json", {**metadata, "errors": errors})
        summaries.append(metadata)

    final = {"protocol_version": protocol_version, "run_id": args.run_id, "systems": summaries, "complete": all(item["query_count_completed"] == len(queries) and item["failure_count"] == 0 for item in summaries)}
    write_json(args.output_dir / "run_summary.json", final)
    print(json.dumps(final, ensure_ascii=False, indent=2), flush=True)
    if not final["complete"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
