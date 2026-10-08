"""Read-only, shared final-cache registry and Web evidence projection.

This module does not instantiate HyperRAG, write cache metadata, or call a model.
Only trusted server-built cache directories may be registered.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import threading
from collections import Counter
from pathlib import Path, PureWindowsPath
from typing import Any, Awaitable, Callable

import numpy as np

from .evidence import answer_system_prompt, format_context
from .final import FinalGraphIndex, FinalRetrievalConfig
from .structured import load_json, source_chunk_ids

FINAL_MODEL = "Qwen/Qwen3-Embedding-4B"
FINAL_DIMENSION = 2560
FINAL_VERSION = "final-posthoc-v1"
FINAL_FILES = (
    "run_config.json", "final_validation.json", "hypergraph_chunk_entity_relation.hgdb",
    "kv_store_text_chunks.json", "vdb_entities.json", "vdb_relationships.json",
)
LFS_HEADER = b"version https://git-lfs.github.com/spec/v1"


class CacheCompatibilityError(ValueError):
    """A requested final cache or embedding configuration is incompatible."""


def inspect_final_cache(directory: Path) -> dict[str, Any]:
    """Inspect small metadata only; readiness never depends on model API calls."""
    directory = Path(directory)
    missing, pointers, failures = [], [], []
    for name in FINAL_FILES:
        path = directory / name
        if not path.is_file():
            missing.append(name)
        else:
            with path.open("rb") as handle:
                if handle.read(len(LFS_HEADER)) == LFS_HEADER:
                    pointers.append(name)
    config, validation = {}, {}
    if not missing and not pointers:
        try:
            config = load_json(directory / "run_config.json")
            validation = load_json(directory / "final_validation.json")
            required = {"normalization_version": FINAL_VERSION, "index_profile": "dual_concat",
                        "enable_entity_normalization": True, "enable_measurement_instances": True,
                        "enable_efu_repair": False, "embedding_model": FINAL_MODEL,
                        "embedding_dim": FINAL_DIMENSION}
            for key, expected in required.items():
                if config.get(key) != expected:
                    failures.append(f"incompatible {key}")
            if validation.get("validation_passed") is not True or validation.get("validation_failures"):
                failures.append("final validation has not passed")
            if validation.get("embedding_model") != FINAL_MODEL or validation.get("embedding_dim") != FINAL_DIMENSION:
                failures.append("validation embedding signature differs")
        except (ValueError, TypeError, OSError) as exc:
            failures.append(f"invalid final metadata ({type(exc).__name__})")
    return {"cache_ready": not missing and not pointers and not failures,
            "missing_files": missing, "lfs_pointer_files": pointers, "validation_failures": failures,
            "embedding_model": FINAL_MODEL, "embedding_dim": FINAL_DIMENSION,
            "normalization_version": FINAL_VERSION, "read_only": True,
            "counts": {name: validation.get(name, 0) for name in ("documents", "chunks", "entities", "relationships")}}


def _stat_signature(directory: Path) -> tuple:
    return tuple((name, (directory / name).stat().st_size, (directory / name).stat().st_mtime_ns)
                 for name in FINAL_FILES)


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set)):
        return [json_safe(item) for item in value]
    if isinstance(value, np.generic):
        return value.item()
    return value


def vertex_record(node_id: str, data: dict) -> dict:
    # Avoid interpreting a chemistry category as a G6 renderer's `type`.
    result = {key: json_safe(value) for key, value in data.items()
              if key not in {"type", "source_file", "file_path", "cache_dir"}}
    result.update(id=node_id, entity_name=node_id,
                  display_name=str(data.get("canonical_name") or data.get("entity_name") or node_id),
                  entity_type=str(data.get("entity_type") or "UNKNOWN"))
    return result


class FinalCacheRegistry:
    """Reuse one verified immutable index per path/version within the worker."""
    def __init__(self):
        self._entries: dict[Path, tuple[tuple, FinalGraphIndex, str]] = {}
        self._lock = threading.Lock()

    def get(self, directory: Path) -> tuple[FinalGraphIndex, str]:
        directory = Path(directory).resolve()
        with self._lock:
            status = inspect_final_cache(directory)
            if not status["cache_ready"]:
                raise CacheCompatibilityError("Final cache is unavailable or incompatible: " +
                                              "; ".join(status["missing_files"] + status["lfs_pointer_files"] + status["validation_failures"]))
            stamp = _stat_signature(directory)
            cached = self._entries.get(directory)
            if cached and cached[0] == stamp:
                return cached[1], cached[2]
            index = FinalGraphIndex(directory)
            self._validate_index(index, status["counts"])
            hashes = {name: _file_hash(directory / name) for name in FINAL_FILES}
            if _stat_signature(directory) != stamp:
                raise CacheCompatibilityError("Final cache changed while loading; retry after publication")
            signature = _json_hash(hashes)
            self._entries[directory] = (stamp, index, signature)
            return index, signature

    @staticmethod
    def _validate_index(index: FinalGraphIndex, counts: dict) -> None:
        if index.dimension != FINAL_DIMENSION:
            raise CacheCompatibilityError("Final vectors must have 2560 dimensions")
        actual = {"chunks": len(index.chunks), "entities": len(index.vertices), "relationships": len(index.edges)}
        if any(actual[key] != counts.get(key) for key in actual):
            raise CacheCompatibilityError("Final validation counts do not match the cache")
        if index.mapping_audit["graph_edges_without_relationship_vectors"] or index.mapping_audit["duplicate_vector_rows"]:
            raise CacheCompatibilityError("Final relationship-vector mapping is incomplete")
        for rows, matrix in ((index.entity_rows, index.entity_matrix),
                             (index.relationship_rows, index.relationship_matrix)):
            if np.any(np.linalg.norm(matrix, axis=1) <= 0):
                raise CacheCompatibilityError("Final cache contains zero vectors")
            for row in rows:
                content = row.get("content") or ""
                if (row.get("embedding_model") != FINAL_MODEL or row.get("embedding_dim") != FINAL_DIMENSION or
                        row.get("index_view") != "dual_concat" or "[Canonical]" not in content or "[Surface]" not in content or
                        row.get("content_hash") != _json_hash(content)):
                    raise CacheCompatibilityError("Final vector model/content signature is invalid")
        for key, edge in index.edges.items():
            if any(node not in index.vertices for node in key) or not source_chunk_ids(edge, index.chunks):
                raise CacheCompatibilityError("Final edge has missing endpoints or source chunks")
            for instance in edge.get("evidence_instances") or []:
                if instance.get("repair_applied") or set(instance.get("canonical_vertices") or []) != set(key):
                    raise CacheCompatibilityError("Final evidence has invalid endpoint bindings")

    def forget(self, directory: Path) -> None:
        with self._lock:
            self._entries.pop(Path(directory).resolve(), None)


final_cache_registry = FinalCacheRegistry()


def project_evidence(index: FinalGraphIndex, evidence: list[dict]) -> dict:
    """Return exactly the source-local relations attached to retrieved chunks."""
    nodes, edges, units = {}, {}, []
    for rank, item in enumerate(evidence, 1):
        chunk_id = str(item["id"])
        units.append({"id": chunk_id, "rank": rank, "source_chunk_id": chunk_id,
                      "included_in_context": True,
                      "source_doc_id": item.get("source_doc_id"),
                      "source_file": PureWindowsPath(str(item.get("source_file") or "")).name,
                      "content": item.get("chunk_content", ""),
                      "retrieval_score": item.get("retrieval_score"),
                      "supporting_relations": json_safe(item.get("supporting_relations") or [])})
        for relation in item.get("supporting_relations") or []:
            members = list(relation["vertices"])
            edge_id = str(relation["edge_id"])
            for node_id in members:
                nodes[node_id] = vertex_record(node_id, index.vertices[node_id])
            edge = edges.setdefault(edge_id, {
                "id": edge_id, "entity_set": members, "vertices": members,
                "arity": len(members), "relation_type": relation.get("relation_type"),
                "keywords": relation.get("keywords", ""), "weight": relation.get("edge_score", 1),
                "description": "", "source_chunk_ids": [], "source_spans": [], "evidence_instances": [],
                "retrieval_channels": [], "rank": relation.get("edge_rank"),
            })
            if chunk_id not in edge["source_chunk_ids"]:
                edge["source_chunk_ids"].append(chunk_id)
                edge["evidence_instances"].append({"source_chunk_id": chunk_id,
                    "source_doc_id": item.get("source_doc_id"), "vertices": members,
                    "description": relation.get("description", ""),
                    "source_spans": list(relation.get("source_spans") or [])})
            edge["source_spans"] = list(dict.fromkeys(edge["source_spans"] + list(relation.get("source_spans") or [])))
            edge["description"] = "<SEP>".join(dict.fromkeys(i["description"] for i in edge["evidence_instances"] if i["description"]))
            edge["retrieval_channels"] = sorted(set(edge["retrieval_channels"]) | set(relation.get("retrieval_channels") or {}))
    return {"entities": list(nodes.values()), "hyperedges": list(edges.values()), "text_units": units}


async def retrieve_final(query: str, directory: Path, embed: Callable[..., Awaitable[np.ndarray]], *,
                         evidence_top_k: int = 5, enable_rerank: bool = True) -> dict:
    index, signature = await asyncio.to_thread(final_cache_registry.get, directory)
    vector = np.asarray(await embed([query], dimensions=FINAL_DIMENSION, expected_model=FINAL_MODEL), dtype=np.float32)
    if vector.shape != (1, FINAL_DIMENSION) or not np.isfinite(vector).all() or np.linalg.norm(vector[0]) <= 0:
        raise CacheCompatibilityError("Query embedding does not match the final cache (expected 1 × 2560)")
    config = FinalRetrievalConfig(enable_rerank=enable_rerank)
    evidence = await asyncio.to_thread(index.search, query, vector[0], view="hyper", top_k=evidence_top_k, config=config)
    context, used_ids = format_context(query, evidence, budget=1500)
    # The answer-linked graph contains only sources actually sent to generation.
    # Keep the raw top-k result and its IDs separately for retrieval audits.
    result = project_evidence(index, [item for item in evidence if str(item["id"]) in used_ids])
    result.update(response=context, context=context, evidence=evidence,
                  answer_prompt=query, answer_system_prompt=answer_system_prompt(context),
                  has_context=bool(context), retrieval_meta={
        "profile": "f1" if enable_rerank else "f0", "method": "normalized_final_hybrid_rerank_v1" if enable_rerank else "normalized_final_hybrid_rrf_v1",
        "cache_signature": signature, "read_only": True, "embedding_model": FINAL_MODEL,
        "embedding_dim": FINAL_DIMENSION, "query_expansion": False, "rerank_enabled": enable_rerank,
        "candidate_edge_ids": evidence[0]["candidate_edge_ids"] if evidence else [],
        "candidate_chunk_ids": evidence[0]["candidate_chunk_ids"] if evidence else [],
        "candidate_pool_depth": config.rerank_candidate_depth, "evidence_top_k": evidence_top_k,
        "evidence_format": "legacy", "evidence_budget": 1500, "budget_unit": "whitespace_tokens",
        "generation_evidence_ids": used_ids, "qa_protocol": "web-cited-markdown-v1",
        "retrieved_evidence_ids": [str(item["id"]) for item in evidence],
        "generation_matches_paper_protocol": False,
    })
    return result


def graph_snapshot(index: FinalGraphIndex, *, edge_limit: int = 12, vertex_id: str | None = None,
                   members: list[str] | None = None) -> dict:
    if vertex_id is not None:
        keys = sorted(index.vertex_incidence.get(vertex_id) or [])
    elif members:
        keys = sorted(set().union(*(index.vertex_incidence.get(node) or set() for node in members)))
    else:
        keys = sorted(index.edges)
    selected = keys[:edge_limit]
    ids = list(dict.fromkeys(node for key in selected for node in key))
    if vertex_id in index.vertices and vertex_id not in ids:
        ids.append(vertex_id)
    return {"vertices": {node: vertex_record(node, index.vertices[node]) for node in ids},
            "edges": {"|#|".join(key): json_safe(index.edges[key]) for key in selected},
            "read_only": True, "sampled": len(keys) > len(selected),
            "total_vertices": len(index.vertices), "total_edges": len(index.edges)}


def graph_page(index: FinalGraphIndex, *, kind: str, page: int | None = None, page_size: int | None = None) -> Any:
    if kind == "vertices":
        counts = Counter(node for key in index.edges for node in key)
        rows = sorted((node for node, count in counts.items() if count >= 2), key=lambda node: (-counts[node], node))
    else:
        rows = [{"id": "|*|".join(key), "vertices": list(key), "keywords": edge.get("keywords", ""),
                 "description": edge.get("description", ""), "summary": edge.get("summary", "")}
                for key, edge in sorted(index.edges.items())]
    if page is None or page_size is None:
        return rows
    size = min(100, max(1, page_size))
    number = max(1, page)
    return {"data": rows[(number - 1) * size:number * size], "total": len(rows),
            "page": number, "page_size": size, "total_pages": (len(rows) + size - 1) // size}
