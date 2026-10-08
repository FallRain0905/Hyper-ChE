"""Read-only adapter for the original Hyper-RAG ``hyper_query`` retrieval path.

The adapter deliberately performs no retrieval fusion, graph expansion, or
post-hoc reranking. It only loads the cache storages, calls
``hyperrag.operate.hyper_query`` and maps the returned text-unit contents back
to the frozen chunk IDs required by the formal retrieval evaluator.
"""
from __future__ import annotations

import asyncio
import base64
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

import numpy as np

from hyperrag.base import QueryParam
from hyperrag.operate import hyper_query
from hyperrag.storage import HypergraphStorage, JsonKVStorage, NanoVectorDBStorage
from hyperrag.utils import EmbeddingFunc
from hyperche.retrieval.query_normalization import normalize_query, query_variants


def normalize_whitespace(value: str) -> str:
    """Normalize formatting-only whitespace without changing lexical content."""

    return " ".join(str(value or "").split())


class TextUnitChunkMapper:
    """Map upstream text units back to chunk IDs without changing their order."""

    def __init__(self, chunks: dict[str, dict[str, Any]]) -> None:
        self.chunks = chunks
        self._exact: dict[str, list[str]] = defaultdict(list)
        self._normalized: dict[str, list[str]] = defaultdict(list)
        for chunk_id, chunk in chunks.items():
            content = str(chunk.get("content") or "")
            self._exact[content].append(str(chunk_id))
            self._normalized[normalize_whitespace(content)].append(str(chunk_id))

    def map_text_units(
        self,
        text_units: list[dict[str, Any]],
        *,
        top_k: int,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        mapped: list[dict[str, Any]] = []
        seen_chunk_ids: set[str] = set()
        unmatched: list[dict[str, Any]] = []
        ambiguous: list[dict[str, Any]] = []
        duplicate_text_units = 0

        for text_unit_index, text_unit in enumerate(text_units):
            content = str(text_unit.get("content") or "")
            method = "exact"
            candidates = self._exact.get(content, [])
            if not candidates:
                method = "whitespace_normalized"
                candidates = self._normalized.get(normalize_whitespace(content), [])

            if not candidates:
                unmatched.append(
                    {
                        "text_unit_index": text_unit_index,
                        "content_preview": content[:240],
                    }
                )
                continue
            if len(candidates) != 1:
                ambiguous.append(
                    {
                        "text_unit_index": text_unit_index,
                        "mapping_method": method,
                        "candidate_chunk_ids": list(candidates),
                        "content_preview": content[:240],
                    }
                )
                continue

            chunk_id = candidates[0]
            if chunk_id in seen_chunk_ids:
                duplicate_text_units += 1
                continue
            seen_chunk_ids.add(chunk_id)
            mapped.append(
                {
                    "chunk_id": chunk_id,
                    "chunk": self.chunks[chunk_id],
                    "mapping_method": method,
                    "text_unit_index": text_unit_index,
                }
            )

        returned = mapped[:top_k]
        audit = {
            "text_unit_count": len(text_units),
            "mapped_chunk_count": len(mapped),
            "returned_chunk_count": len(returned),
            "duplicate_text_unit_count": duplicate_text_units,
            "unmatched_text_units": unmatched,
            "ambiguous_text_units": ambiguous,
        }
        return returned, audit


def balanced_branch_merge(
    entity_items: list[dict[str, Any]],
    relation_items: list[dict[str, Any]],
    *,
    top_k: int,
    entity_quota: int,
    relation_quota: int,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Interleave upstream branches without inventing a new retrieval score.

    Each branch keeps the order returned by ``hyper_query``. Cross-branch
    duplicate chunks are removed, and spare capacity is filled from the other
    branch when one side cannot satisfy its quota.
    """

    if top_k <= 0:
        raise ValueError("top_k must be positive")
    if entity_quota < 0 or relation_quota < 0:
        raise ValueError("branch quotas cannot be negative")

    selected: dict[str, list[dict[str, Any]]] = {"entity": [], "relation": []}
    leftovers: dict[str, list[dict[str, Any]]] = {"entity": [], "relation": []}
    seen: set[str] = set()
    cross_branch_duplicates = 0

    for branch, items, quota in (
        ("entity", entity_items, entity_quota),
        ("relation", relation_items, relation_quota),
    ):
        for raw_item in items:
            chunk_id = str(raw_item["chunk_id"])
            if chunk_id in seen:
                cross_branch_duplicates += 1
                continue
            item = {**raw_item, "retrieval_branch": branch}
            if len(selected[branch]) < quota:
                selected[branch].append(item)
                seen.add(chunk_id)
            else:
                leftovers[branch].append(item)

    merged: list[dict[str, Any]] = []
    max_selected = max(len(selected["entity"]), len(selected["relation"]))
    for index in range(max_selected):
        for branch in ("entity", "relation"):
            if index < len(selected[branch]):
                merged.append(selected[branch][index])
                if len(merged) == top_k:
                    break
        if len(merged) == top_k:
            break

    max_leftovers = max(len(leftovers["entity"]), len(leftovers["relation"]))
    for index in range(max_leftovers):
        if len(merged) == top_k:
            break
        for branch in ("entity", "relation"):
            if index >= len(leftovers[branch]):
                continue
            item = leftovers[branch][index]
            chunk_id = str(item["chunk_id"])
            if chunk_id in seen:
                cross_branch_duplicates += 1
                continue
            seen.add(chunk_id)
            merged.append(item)
            if len(merged) == top_k:
                break

    return merged, {
        "returned_entity_count": sum(item["retrieval_branch"] == "entity" for item in merged),
        "returned_relation_count": sum(item["retrieval_branch"] == "relation" for item in merged),
        "cross_branch_duplicate_count": cross_branch_duplicates,
    }


class UpstreamHyperQueryRetriever:
    """Thin, read-only wrapper around ``hyperrag.operate.hyper_query``."""

    REQUIRED_FILES = (
        "kv_store_text_chunks.json",
        "hypergraph_chunk_entity_relation.hgdb",
        "vdb_entities.json",
        "vdb_relationships.json",
    )

    def __init__(
        self,
        cache_dir: Path,
        *,
        llm_json_func: Callable[[str], dict[str, Any]],
        embedding_func: Callable[[str], np.ndarray],
        embedding_dim: int = 2560,
        embedding_batch_num: int = 16,
        graph_top_k: int = 60,
        cosine_threshold: float = 0.2,
        query_domain: str = "default",
        entity_quota: int = 10,
        relation_quota: int = 10,
        enable_query_expansion: bool = False,
        max_query_variants: int = 2,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        missing = [name for name in self.REQUIRED_FILES if not (self.cache_dir / name).exists()]
        if missing:
            raise FileNotFoundError(f"Missing upstream Hyper-RAG cache files: {missing}")

        self.llm_json_func = llm_json_func
        self.embedding_func = embedding_func
        self.graph_top_k = int(graph_top_k)
        self.query_domain = str(query_domain or "default")
        self.query_prompt_source = (
            "hyperrag.prompt.PROMPTS[keywords_extraction]"
            if self.query_domain == "default"
            else f"hyperrag/domains/{self.query_domain}/query_keywords.txt"
        )
        self.entity_quota = int(entity_quota)
        self.relation_quota = int(relation_quota)
        self.enable_query_expansion = bool(enable_query_expansion)
        self.max_query_variants = int(max_query_variants)
        if self.max_query_variants <= 0:
            raise ValueError("max_query_variants must be positive")
        if self.entity_quota < 0 or self.relation_quota < 0:
            raise ValueError("entity_quota and relation_quota cannot be negative")
        self.global_config: dict[str, Any] = {
            "working_dir": str(self.cache_dir),
            "embedding_batch_num": int(embedding_batch_num),
            "cosine_better_than_threshold": float(cosine_threshold),
            "domain": self.query_domain,
            "prompt_profile": "default",
            "llm_model_func": self._llm_call,
        }
        self.embedding = EmbeddingFunc(
            embedding_dim=int(embedding_dim),
            max_token_size=8192,
            func=self._embed_batch,
        )
        self.text_db = JsonKVStorage(namespace="text_chunks", global_config=self.global_config)
        self.graph = HypergraphStorage(
            namespace="chunk_entity_relation",
            global_config=self.global_config,
        )
        self.entities_vdb = NanoVectorDBStorage(
            namespace="entities",
            global_config=self.global_config,
            embedding_func=self.embedding,
            meta_fields={"entity_name", "content"},
        )
        self.relationships_vdb = NanoVectorDBStorage(
            namespace="relationships",
            global_config=self.global_config,
            embedding_func=self.embedding,
            meta_fields={"id_set", "content"},
        )
        self.mapper = TextUnitChunkMapper(self.text_db._data)

    async def _retrieve_branch_candidates(
        self, question: str
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
        """Run hyper_query and retain complete mapped branch candidates."""
        variants = query_variants(question, max_variants=self.max_query_variants) if self.enable_query_expansion else [normalize_query(question)]
        branch_items: dict[str, dict[str, dict[str, Any]]] = {"entity": {}, "relation": {}}
        variant_audits: list[dict[str, Any]] = []
        for variant_index, variant in enumerate(variants):
            query_param = QueryParam(
                mode="hyper",
                top_k=self.graph_top_k,
                max_token_for_text_unit=100000,
                max_token_for_entity_context=10000,
                max_token_for_relation_context=10000,
                only_need_context=True,
                return_type="json",
            )
            context = await hyper_query(
                variant,
                self.graph,
                self.entities_vdb,
                self.relationships_vdb,
                self.text_db,
                query_param,
                self.global_config,
            )
            if not isinstance(context, dict):
                raise RuntimeError(
                    f"hyper_query returned {type(context).__name__}, expected dict context"
                )
            entity_text_units = context.get("entity_text_units") or []
            relation_text_units = context.get("relation_text_units") or []
            if not isinstance(entity_text_units, list):
                raise RuntimeError("hyper_query context.entity_text_units is not a list")
            if not isinstance(relation_text_units, list):
                raise RuntimeError("hyper_query context.relation_text_units is not a list")

            mapped_entity_variant, entity_audit = self.mapper.map_text_units(
                entity_text_units, top_k=len(entity_text_units)
            )
            mapped_relation_variant, relation_audit = self.mapper.map_text_units(
                relation_text_units, top_k=len(relation_text_units)
            )
            for branch, items in (("entity", mapped_entity_variant), ("relation", mapped_relation_variant)):
                for rank, item in enumerate(items, start=1):
                    chunk_id = str(item["chunk_id"])
                    current = branch_items[branch].get(chunk_id)
                    candidate = {
                        **item,
                        "query_variant": variant,
                        "query_variant_index": variant_index,
                        "variant_branch_rank": rank,
                    }
                    if current is None or rank < int(current.get("variant_branch_rank", 10**9)):
                        branch_items[branch][chunk_id] = candidate
            variant_audits.append(
                {
                    "query": variant,
                    "query_variant_index": variant_index,
                    "entity_text_unit_count": len(entity_text_units),
                    "relation_text_unit_count": len(relation_text_units),
                    "mapped_entity_count": len(mapped_entity_variant),
                    "mapped_relation_count": len(mapped_relation_variant),
                    "entity_mapping_audit": entity_audit,
                    "relation_mapping_audit": relation_audit,
                    "entity_keywords": context.get("entity_keywords") or "",
                    "relation_keywords": context.get("relation_keywords") or "",
                }
            )

        mapped_entity = sorted(branch_items["entity"].values(), key=lambda item: (int(item.get("variant_branch_rank", 10**9)), str(item["chunk_id"])))
        mapped_relation = sorted(branch_items["relation"].values(), key=lambda item: (int(item.get("variant_branch_rank", 10**9)), str(item["chunk_id"])))
        branch_rank_by_chunk = {
            "entity": {
                str(item["chunk_id"]): index
                for index, item in enumerate(mapped_entity, start=1)
            },
            "relation": {
                str(item["chunk_id"]): index
                for index, item in enumerate(mapped_relation, start=1)
            },
        }
        audit = {
            "normalized_query": normalize_query(question),
            "query_variants": variants,
            "query_expansion_enabled": self.enable_query_expansion,
            "query_variant_count": len(variants),
            "variant_audits": variant_audits,
            "entity_keywords": variant_audits[0].get("entity_keywords", "") if variant_audits else "",
            "relation_keywords": variant_audits[0].get("relation_keywords", "") if variant_audits else "",
            "entity_text_unit_count": sum(item["entity_text_unit_count"] for item in variant_audits),
            "relation_text_unit_count": sum(item["relation_text_unit_count"] for item in variant_audits),
            "mapped_entity_count": len(mapped_entity),
            "mapped_relation_count": len(mapped_relation),
            "branch_rank_by_chunk": branch_rank_by_chunk,
            "duplicate_text_unit_count": (
                entity_audit["duplicate_text_unit_count"]
                + relation_audit["duplicate_text_unit_count"]
            ),
            "unmatched_text_units": [
                {**item, "branch": branch}
                for branch, branch_audit in (
                    ("entity", entity_audit),
                    ("relation", relation_audit),
                )
                for item in branch_audit["unmatched_text_units"]
            ],
            "ambiguous_text_units": [
                {**item, "branch": branch}
                for branch, branch_audit in (
                    ("entity", entity_audit),
                    ("relation", relation_audit),
                )
                for item in branch_audit["ambiguous_text_units"]
            ],
        }
        return mapped_entity, mapped_relation, audit

    async def _llm_call(self, prompt: str, **_: Any) -> str:
        payload = await asyncio.to_thread(self.llm_json_func, prompt)
        return json.dumps(payload, ensure_ascii=False)

    async def _embed_batch(self, texts: list[str]) -> np.ndarray:
        vectors = await asyncio.gather(
            *[asyncio.to_thread(self.embedding_func, str(text)) for text in texts]
        )
        return np.asarray(vectors, dtype=np.float32)

    async def _asearch(self, question: str, *, top_k: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        mapped_entity, mapped_relation, branch_audit = (
            await self._retrieve_branch_candidates(question)
        )
        mapped, merge_audit = balanced_branch_merge(
            mapped_entity,
            mapped_relation,
            top_k=top_k,
            entity_quota=self.entity_quota,
            relation_quota=self.relation_quota,
        )
        audit = {
            "merge_strategy": "interleaved_entity_relation_quota",
            "query_domain": self.query_domain,
            "query_prompt_source": self.query_prompt_source,
            "entity_quota": self.entity_quota,
            "relation_quota": self.relation_quota,
            "query_expansion_enabled": self.enable_query_expansion,
            "max_query_variants": self.max_query_variants,
            **branch_audit,
            "candidate_union_count": len(candidate_union(mapped_entity, mapped_relation)),
            "returned_chunk_count": len(mapped),
            "balanced_selected_chunk_ids": [str(item["chunk_id"]) for item in mapped],
            **merge_audit,
        }
        audit["retrieval_function"] = "hyperrag.operate.hyper_query"
        audit["graph_top_k"] = self.graph_top_k
        return mapped, audit

    def search(
        self, question: str, top_k: int
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        if top_k <= 0:
            raise ValueError("top_k must be positive")
        return asyncio.run(self._asearch(str(question), top_k=int(top_k)))


def candidate_union(
    entity_items: list[dict[str, Any]],
    relation_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return both upstream branches without imposing a branch quota."""

    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for branch, items in (("entity", entity_items), ("relation", relation_items)):
        for item in items:
            chunk_id = str(item["chunk_id"])
            if chunk_id in seen:
                continue
            seen.add(chunk_id)
            merged.append({**item, "retrieval_branch": branch})
    return merged

class ChunkRerankedUpstreamHyperQueryRetriever(UpstreamHyperQueryRetriever):
    """Independent ablation: upstream candidates plus chunk dense ranking."""

    REQUIRED_FILES = UpstreamHyperQueryRetriever.REQUIRED_FILES + ("vdb_chunks.json",)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        payload = json.loads(
            (self.cache_dir / "vdb_chunks.json").read_text(encoding="utf-8-sig")
        )
        rows = list(payload.get("data") or [])
        dimension = int(payload.get("embedding_dim") or 0)
        encoded = payload.get("matrix")
        if not rows or dimension <= 0 or not isinstance(encoded, str):
            raise ValueError("invalid vdb_chunks.json payload")
        matrix = np.frombuffer(base64.b64decode(encoded), dtype=np.float32)
        expected = len(rows) * dimension
        if matrix.size != expected:
            raise ValueError(f"chunk vector matrix size {matrix.size} != {expected}")
        matrix = matrix.reshape(len(rows), dimension)
        if dimension != self.embedding.embedding_dim:
            raise ValueError(
                f"chunk vector dimension {dimension} != embedding dimension "
                f"{self.embedding.embedding_dim}"
            )
        norms = np.linalg.norm(matrix, axis=1)
        if not np.isfinite(matrix).all() or np.any(norms <= 0.0):
            raise ValueError("chunk vector matrix contains zero or invalid rows")
        self.chunk_vector_ids = [str(row.get("__id__") or "") for row in rows]
        if len(set(self.chunk_vector_ids)) != len(self.chunk_vector_ids):
            raise ValueError("vdb_chunks.json contains duplicate chunk IDs")
        missing = [
            chunk_id
            for chunk_id in self.chunk_vector_ids
            if chunk_id not in self.text_db._data
        ]
        if missing:
            raise ValueError(f"chunk vectors missing from text store: {missing[:5]}")
        self.chunk_matrix = matrix / norms[:, None]
        self.chunk_vector_index = {
            chunk_id: index for index, chunk_id in enumerate(self.chunk_vector_ids)
        }

    async def _rerank_candidates(
        self,
        question: str,
        *,
        top_k: int,
        mapped_entity: list[dict[str, Any]],
        mapped_relation: list[dict[str, Any]],
        branch_audit: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        pool = candidate_union(mapped_entity, mapped_relation)
        balanced_selected, balanced_audit = balanced_branch_merge(
            mapped_entity,
            mapped_relation,
            top_k=top_k,
            entity_quota=self.entity_quota,
            relation_quota=self.relation_quota,
        )
        query_vector = np.asarray(
            await asyncio.to_thread(self.embedding_func, question), dtype=np.float32
        ).reshape(-1)
        if query_vector.shape != (self.embedding.embedding_dim,):
            raise ValueError(
                f"query embedding shape {query_vector.shape} != "
                f"({self.embedding.embedding_dim},)"
            )
        query_norm = float(np.linalg.norm(query_vector))
        if not np.isfinite(query_norm) or query_norm <= 0.0:
            raise ValueError("query embedding has zero or invalid norm")
        query_vector /= query_norm

        branch_ranks = branch_audit["branch_rank_by_chunk"]
        scored: list[dict[str, Any]] = []
        missing_chunk_vectors: list[str] = []
        for pool_rank, item in enumerate(pool, start=1):
            chunk_id = str(item["chunk_id"])
            vector_index = self.chunk_vector_index.get(chunk_id)
            if vector_index is None:
                missing_chunk_vectors.append(chunk_id)
                continue
            score = float(self.chunk_matrix[vector_index] @ query_vector)
            ranks = {
                branch: int(branch_ranks[branch][chunk_id])
                for branch in ("entity", "relation")
                if chunk_id in branch_ranks[branch]
            }
            scored.append(
                {
                    **item,
                    "retrieval_score": score,
                    "chunk_dense_score": score,
                    "candidate_pool_rank": pool_rank,
                    "branch_ranks": ranks,
                    "best_branch_rank": min(ranks.values()) if ranks else None,
                }
            )

        scored.sort(
            key=lambda item: (
                -float(item["chunk_dense_score"]),
                int(item["best_branch_rank"] or 10**9),
                str(item["chunk_id"]),
            )
        )
        selected = scored[:top_k]
        for rank, item in enumerate(selected, start=1):
            item["rerank_rank"] = rank

        audit = {
            "merge_strategy": "upstream_candidate_union_then_chunk_dense",
            "query_domain": self.query_domain,
            "query_prompt_source": self.query_prompt_source,
            **branch_audit,
            "candidate_union_count": len(pool),
            "balanced_selected_chunk_ids": [
                str(item["chunk_id"]) for item in balanced_selected
            ],
            "balanced_merge_audit": balanced_audit,
            "rerank_input_count": len(scored),
            "missing_chunk_vectors": missing_chunk_vectors,
            "returned_chunk_count": len(selected),
            "rerank_selected_chunk_ids": [str(item["chunk_id"]) for item in selected],
            "rerank_rank_by_chunk": {
                str(item["chunk_id"]): int(item["rerank_rank"])
                for item in selected
            },
            "retrieval_function": "hyperrag.operate.hyper_query",
            "graph_top_k": self.graph_top_k,
            "posthoc_reranking": "chunk_dense_cosine_only",
        }
        return selected, audit

    async def _asearch(
        self, question: str, *, top_k: int
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        mapped_entity, mapped_relation, branch_audit = (
            await self._retrieve_branch_candidates(question)
        )
        return await self._rerank_candidates(
            question,
            top_k=top_k,
            mapped_entity=mapped_entity,
            mapped_relation=mapped_relation,
            branch_audit=branch_audit,
        )

    def rerank_from_upstream_audit(
        self,
        question: str,
        upstream_audit: dict[str, Any],
        *,
        top_k: int,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Rerank the exact branch pool saved by the paired baseline call."""

        branch_ranks = upstream_audit.get("branch_rank_by_chunk") or {}

        def rebuild(branch: str) -> list[dict[str, Any]]:
            ranks = branch_ranks.get(branch) or {}
            ordered = sorted(ranks.items(), key=lambda item: (int(item[1]), item[0]))
            return [
                {
                    "chunk_id": str(chunk_id),
                    "chunk": self.text_db._data[str(chunk_id)],
                    "mapping_method": "shared_upstream_audit",
                    "text_unit_index": int(rank) - 1,
                }
                for chunk_id, rank in ordered
                if str(chunk_id) in self.text_db._data
            ]

        mapped_entity = rebuild("entity")
        mapped_relation = rebuild("relation")
        shared_audit = {
            key: value
            for key, value in upstream_audit.items()
            if key
            not in {
                "gold_diagnostics",
                "balanced_selected_chunk_ids",
                "returned_chunk_count",
                "returned_entity_count",
                "returned_relation_count",
                "merge_strategy",
            }
        }
        shared_audit["shared_candidate_source"] = "chem_prompt_hypergraph"
        return asyncio.run(
            self._rerank_candidates(
                str(question),
                top_k=int(top_k),
                mapped_entity=mapped_entity,
                mapped_relation=mapped_relation,
                branch_audit=shared_audit,
            )
        )
