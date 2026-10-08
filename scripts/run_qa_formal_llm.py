"""Run the frozen 40-question QA Gold benchmark across formal systems.

This runner is read-only with respect to all Hyper-RAG caches. It provides a
strict readiness gate, a standard text Hybrid RAG baseline (BM25 + dense + RRF),
resumable LLM generation/judging, and formal aggregate/stratified metrics.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import hashlib
import json
import math
import os
import pickle
import re
import statistics
import sys
import threading
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np
from openai import OpenAI

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import run_qa_smoke_llm as core  # noqa: E402
from scripts.structured_graph_retrieval import (  # noqa: E402
    StructuredGraphIndex,
    StructuredGraphRetriever,
    StructuredRetrievalConfig,
    decode_matrix,
)


FORMAL_GROUPS: dict[str, dict[str, Any]] = {
    "original_hypergraph": {
        "label": "Original Hyper-RAG",
        "cache": "hyper_base",
        "view": "hyper",
        'retriever': 'structured_graph_hybrid_v1',
        "rerank": False,
    },
    "chem_prompt_graph": {
        "label": "Chem-Prompt Binary Graph",
        "cache": "hyper_chem_prompt",
        "view": "graph",
        'retriever': 'structured_graph_hybrid_v1',
        "rerank": False,
    },
    "chem_prompt_hypergraph": {
        "label": "Chem-Prompt Hypergraph",
        "cache": "hyper_chem_prompt",
        "view": "hyper",
        'retriever': 'structured_graph_hybrid_v1',
        "rerank": False,
    },
    "hybrid_rag_baseline": {
        "label": "Hybrid Text RAG (BM25 + Dense + RRF)",
        "cache": "hyper_chem_prompt",
        "view": "text",
        "retriever": "bm25_dense_rrf",
        "rerank": False,
    },
}

# Optional systems are deliberately excluded from ``--groups all`` so an
# existing four-group QA v3 output can continue resuming under its frozen
# protocol. Select these groups explicitly and use a separate output folder.
OPTIONAL_GROUPS: dict[str, dict[str, Any]] = {
    "normalized_final": {
        "label": "Normalized Final (EFU repair disabled)",
        "cache": "hyper_final_posthoc_v1",
        "view": "hyper",
        "retriever": "normalized_final_hybrid_rerank_v1",
        "rerank": True,
    },
    "naive_dense_rag": {
        "label": "Original Naive RAG (Chunk Dense Only)",
        "cache": "hyper_chem_prompt",
        "view": "text",
        "retriever": "naive_chunk_dense",
        "rerank": False,
    },
}

FORMAL_PROTOCOL_VERSION = 'qa-formal-v3-structured-retrieval-four-groups'
TOKEN_RE = re.compile(r"[A-Za-zΑ-Ωα-ω][A-Za-z0-9Α-Ωα-ω_+./%−–-]*|\d+(?:\.\d+)?")
CITATION_RE = re.compile(r"(?:evidence|证据)\s*#?\s*(\d+)", flags=re.IGNORECASE)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def split_keys(value: Any) -> list[str]:
    return core.split_keys(value)


def tokenize(value: str) -> list[str]:
    return [match.group(0).casefold() for match in TOKEN_RE.finditer(str(value or ""))]


def is_kimi_k2_model(model_name: str) -> bool:
    normalized = str(model_name or "").strip().casefold()
    return "kimi-k2.6" in normalized or "kimi-k2.5" in normalized


def response_content_or_raise(response: Any) -> str:
    choices = getattr(response, "choices", None) or []
    if not choices:
        raise RuntimeError("LLM returned no choices")
    choice = choices[0]
    message = getattr(choice, "message", None)
    content = str(getattr(message, "content", None) or "")
    if content.strip():
        return content

    reasoning = str(getattr(message, "reasoning_content", None) or "")
    usage = getattr(response, "usage", None)
    completion_tokens = getattr(usage, "completion_tokens", None)
    total_tokens = getattr(usage, "total_tokens", None)
    raise RuntimeError(
        "LLM returned empty content: "
        f"finish_reason={getattr(choice, 'finish_reason', None)!r}, "
        f"reasoning_chars={len(reasoning)}, "
        f"completion_tokens={completion_tokens!r}, total_tokens={total_tokens!r}"
    )


class FormalLLMClientPool(core.LLMClientPool):
    def __init__(self, *args: Any, timeout: float = 600.0, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.timeout = float(timeout)

    def complete_json(
        self,
        prompt: str,
        *,
        temperature: float = 0.0,
        top_p: float = 1.0,
        max_tokens: int = 512,
        max_retries: int = 5,
        extra_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        errors: list[str] = []
        for attempt in range(max_retries):
            entry = self._next_entry()
            model_name = str(entry.get("model") or "")
            is_kimi = is_kimi_k2_model(model_name)
            use_json_mode = not any(marker in model_name for marker in ("GLM-4.5", "Qwen/Qwen3.5", "deepseek-v4-flash"))
            client = OpenAI(api_key=entry["api_key"], base_url=entry["base_url"], timeout=self.timeout, max_retries=0)
            kwargs: dict[str, Any] = {
                "model": entry["model"],
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "timeout": self.timeout,
            }
            if is_kimi:
                # Kimi K2.5/K2.6 enables thinking by default. Strict JSON QA
                # needs the final answer instead of a reasoning trace that can
                # consume the complete output-token budget.
                kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
            else:
                kwargs["temperature"] = temperature
                kwargs["top_p"] = top_p
                if extra_body:
                    kwargs["extra_body"] = dict(extra_body)
            if use_json_mode:
                kwargs["response_format"] = {"type": "json_object"}
            try:
                response = client.chat.completions.create(**kwargs)
                return self._parse_json_content(response_content_or_raise(response))
            except Exception as exc:  # noqa: BLE001
                message = str(exc)
                if use_json_mode and ("Json mode is not supported" in message or "response_format" in message):
                    kwargs.pop("response_format", None)
                    try:
                        response = client.chat.completions.create(**kwargs)
                        return self._parse_json_content(response_content_or_raise(response))
                    except Exception as fallback_exc:  # noqa: BLE001
                        errors.append(f"{entry['provider']}:{type(fallback_exc).__name__}:{str(fallback_exc)[:400]}")
                else:
                    errors.append(f"{entry['provider']}:{type(exc).__name__}:{message[:400]}")
                time.sleep(min(2.0**attempt, 30.0))
        raise RuntimeError("LLM call failed after retries: " + " || ".join(errors))


class EmbeddingClientPool:
    def __init__(self, *, timeout: float = 600.0, max_retries: int = 5) -> None:
        keys = split_keys(os.getenv("EMB_API_KEY") or os.getenv("SILICONFLOW_API_KEY"))
        self.base_url = str(os.getenv("EMB_BASE_URL") or os.getenv("SILICONFLOW_BASE_URL") or "https://api.siliconflow.cn/v1").rstrip("/")
        if self.base_url.endswith("/embeddings"):
            self.base_url = self.base_url[: -len("/embeddings")]
        self.model = str(os.getenv("EMB_MODEL") or "Qwen/Qwen3-Embedding-4B")
        self.dimension = int(os.getenv("EMB_DIM") or "2560")
        self.timeout = float(timeout)
        self.max_retries = max(1, int(max_retries))
        self.entries = [OpenAI(api_key=key, base_url=self.base_url, timeout=self.timeout, max_retries=0) for key in keys]
        if not self.entries:
            raise RuntimeError("Hybrid baseline requires EMB_API_KEY or SILICONFLOW_API_KEY.")
        self._cursor = 0
        self._lock = threading.Lock()
        self._cache: dict[str, np.ndarray] = {}
        self._inflight: dict[str, threading.Event] = {}

    def embed(self, text: str) -> np.ndarray:
        cache_key = str(text)
        with self._lock:
            cached = self._cache.get(cache_key)
            if cached is not None:
                return cached.copy()
            event = self._inflight.get(cache_key)
            owner = event is None
            if owner:
                event = threading.Event()
                self._inflight[cache_key] = event
        if not owner:
            assert event is not None
            event.wait()
            with self._lock:
                cached = self._cache.get(cache_key)
            if cached is None:
                raise RuntimeError('Concurrent embedding request failed; retry the query')
            return cached.copy()

        errors: list[str] = []
        attempts = max(self.max_retries, len(self.entries))
        try:
            for _ in range(attempts):
                with self._lock:
                    client = self.entries[self._cursor % len(self.entries)]
                    self._cursor += 1
                try:
                    response = client.embeddings.create(model=self.model, input=[text], timeout=self.timeout)
                    vector = np.asarray(response.data[0].embedding, dtype=np.float32)
                    if vector.shape != (self.dimension,):
                        raise ValueError(f'embedding dimension {vector.shape} != ({self.dimension},)')
                    with self._lock:
                        self._cache[cache_key] = vector
                    return vector.copy()
                except Exception as exc:  # noqa: BLE001
                    errors.append(f'{type(exc).__name__}: {str(exc)[:300]}')
                    time.sleep(0.5)
            raise RuntimeError('Embedding call failed: ' + ' || '.join(errors))
        finally:
            with self._lock:
                completed_event = self._inflight.pop(cache_key, None)
                if completed_event is not None:
                    completed_event.set()


class HybridTextRetriever:
    """Standard text baseline: BM25 + dense cosine retrieval fused with weighted RRF."""

    def __init__(
        self,
        cache_dir: Path,
        embedding_pool: EmbeddingClientPool,
        *,
        candidate_depth: int = 50,
        rrf_k: int = 60,
        dense_weight: float = 1.0,
        bm25_weight: float = 1.0,
    ) -> None:
        self.cache_dir = cache_dir
        self.embedding_pool = embedding_pool
        self.candidate_depth = max(10, int(candidate_depth))
        self.rrf_k = max(1, int(rrf_k))
        self.dense_weight = float(dense_weight)
        self.bm25_weight = float(bm25_weight)
        self.chunks = load_json(cache_dir / "kv_store_text_chunks.json")
        self.evidence = core.evidence_from_chunks(self.chunks)
        self.evidence_by_id = {str(item.get("id")): item for item in self.evidence}
        self.ids = list(self.chunks)
        self.doc_tokens: dict[str, list[str]] = {}
        self.term_frequencies: dict[str, Counter[str]] = {}
        self.document_frequency: Counter[str] = Counter()
        total_length = 0
        for chunk_id, chunk in self.chunks.items():
            tokens = tokenize(str(chunk.get("content") or ""))
            self.doc_tokens[chunk_id] = tokens
            counts = Counter(tokens)
            self.term_frequencies[chunk_id] = counts
            self.document_frequency.update(counts.keys())
            total_length += len(tokens)
        self.avg_doc_length = total_length / max(1, len(self.ids))
        chunk_payload = load_json(cache_dir / 'vdb_chunks.json')
        self.chunk_vector_rows = list(chunk_payload.get('data') or [])
        self.chunk_matrix = decode_matrix(chunk_payload)
        if self.chunk_matrix.shape[1] != embedding_pool.dimension:
            raise ValueError(
                'chunk embedding dimension {} != configured dimension {}'.format(
                    self.chunk_matrix.shape[1], embedding_pool.dimension
                )
            )
        self.chunk_vector_ids = [str(row.get('__id__') or '') for row in self.chunk_vector_rows]
        missing_vector_chunks = [chunk_id for chunk_id in self.chunk_vector_ids if chunk_id not in self.chunks]
        if missing_vector_chunks:
            raise ValueError('chunk vectors do not map to stored chunks: {}'.format(missing_vector_chunks[:5]))

    def _bm25(self, query: str) -> list[str]:
        terms = tokenize(query)
        if not terms:
            return []
        n_docs = len(self.ids)
        k1 = 1.5
        b = 0.75
        scored: list[tuple[float, str]] = []
        for chunk_id in self.ids:
            counts = self.term_frequencies[chunk_id]
            doc_len = len(self.doc_tokens[chunk_id])
            score = 0.0
            for term in terms:
                tf = counts.get(term, 0)
                if not tf:
                    continue
                df = self.document_frequency.get(term, 0)
                idf = math.log(1.0 + (n_docs - df + 0.5) / (df + 0.5))
                denom = tf + k1 * (1.0 - b + b * doc_len / max(1.0, self.avg_doc_length))
                score += idf * tf * (k1 + 1.0) / denom
            if score > 0:
                scored.append((score, chunk_id))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [chunk_id for _, chunk_id in scored[: self.candidate_depth]]

    def _dense(self, query: str) -> list[str]:
        vector = self.embedding_pool.embed(query)
        query_vector = np.asarray(vector, dtype=np.float32).reshape(-1)
        norm = float(np.linalg.norm(query_vector))
        if not math.isfinite(norm) or norm <= 0.0:
            raise ValueError('query embedding has zero or invalid norm')
        scores = self.chunk_matrix @ (query_vector / norm)
        limit = min(self.candidate_depth, scores.size)
        indices = np.argpartition(-scores, limit - 1)[:limit]
        ordered = sorted(
            (int(index) for index in indices if math.isfinite(float(scores[index]))),
            key=lambda index: (-float(scores[index]), self.chunk_vector_ids[index]),
        )
        return [self.chunk_vector_ids[index] for index in ordered]

    def search(self, query: str, top_k: int) -> list[dict[str, Any]]:
        dense_ids = self._dense(query)
        bm25_ids = self._bm25(query)
        scores: defaultdict[str, float] = defaultdict(float)
        dense_rank = {chunk_id: rank for rank, chunk_id in enumerate(dense_ids, 1)}
        bm25_rank = {chunk_id: rank for rank, chunk_id in enumerate(bm25_ids, 1)}
        for chunk_id, rank in dense_rank.items():
            scores[chunk_id] += self.dense_weight / (self.rrf_k + rank)
        for chunk_id, rank in bm25_rank.items():
            scores[chunk_id] += self.bm25_weight / (self.rrf_k + rank)
        ordered = sorted(scores, key=lambda chunk_id: (-scores[chunk_id], chunk_id))[:top_k]
        output: list[dict[str, Any]] = []
        for chunk_id in ordered:
            item = dict(self.evidence_by_id.get(chunk_id) or {"id": chunk_id, "text": self.chunks[chunk_id].get("content", "")})
            item["retrieval_score"] = round(scores[chunk_id], 8)
            item["dense_rank"] = dense_rank.get(chunk_id)
            item["bm25_rank"] = bm25_rank.get(chunk_id)
            item["retrieval_method"] = "bm25_dense_rrf"
            output.append(item)
        return output


class NaiveDenseRetriever:
    """Original Hyper-RAG naive retrieval: chunk dense cosine Top-K only.

    This intentionally does not construct a BM25 index and does not load the
    entity vectors, relationship vectors, or hypergraph. It mirrors upstream
    `naive_query` retrieval while returning the evidence shape expected by
    the formal runners.
    """

    def __init__(
        self,
        cache_dir: Path,
        embedding_pool: EmbeddingClientPool,
        *,
        cosine_threshold: float = 0.2,
    ) -> None:
        self.cache_dir = cache_dir
        self.embedding_pool = embedding_pool
        self.cosine_threshold = float(cosine_threshold)
        self.chunks = load_json(cache_dir / "kv_store_text_chunks.json")
        chunk_payload = load_json(cache_dir / "vdb_chunks.json")
        self.chunk_vector_rows = list(chunk_payload.get("data") or [])
        matrix = decode_matrix(chunk_payload)
        if matrix.shape[1] != embedding_pool.dimension:
            raise ValueError(
                "chunk embedding dimension {} != configured dimension {}".format(
                    matrix.shape[1], embedding_pool.dimension
                )
            )
        self.chunk_vector_ids = [str(row.get("__id__") or "") for row in self.chunk_vector_rows]
        if len(set(self.chunk_vector_ids)) != len(self.chunk_vector_ids):
            raise ValueError("vdb_chunks.json contains duplicate chunk vector IDs")
        missing = [chunk_id for chunk_id in self.chunk_vector_ids if chunk_id not in self.chunks]
        if missing:
            raise ValueError("chunk vectors do not map to stored chunks: {}".format(missing[:5]))
        row_norms = np.linalg.norm(matrix, axis=1)
        if not np.isfinite(row_norms).all() or np.any(row_norms <= 0.0):
            raise ValueError("chunk vector matrix contains zero or invalid row norms")
        self.chunk_matrix = matrix / row_norms[:, None]

    def search(self, query: str, top_k: int) -> list[dict[str, Any]]:
        limit = min(max(0, int(top_k)), len(self.chunk_vector_ids))
        if limit == 0:
            return []
        query_vector = np.asarray(self.embedding_pool.embed(query), dtype=np.float32).reshape(-1)
        norm = float(np.linalg.norm(query_vector))
        if not math.isfinite(norm) or norm <= 0.0:
            raise ValueError("query embedding has zero or invalid norm")
        scores = self.chunk_matrix @ (query_vector / norm)
        eligible = [
            index
            for index, score in enumerate(scores)
            if math.isfinite(float(score)) and float(score) >= self.cosine_threshold
        ]
        ordered = sorted(
            eligible,
            key=lambda index: (-float(scores[index]), self.chunk_vector_ids[index]),
        )[:limit]
        output: list[dict[str, Any]] = []
        for rank, index in enumerate(ordered, 1):
            chunk_id = self.chunk_vector_ids[index]
            chunk = self.chunks[chunk_id]
            text = str(chunk.get("content") or "")
            output.append(
                {
                    "id": chunk_id,
                    "source_chunk_id": chunk_id,
                    "source_id": chunk_id,
                    "text": text,
                    "readable_evidence": text,
                    "vertices": [],
                    "canonical_vertices": [],
                    "relation_type": "TEXT_CHUNK",
                    "arity": 1,
                    "kind": "naive",
                    "retrieval_score": round(float(scores[index]), 8),
                    "dense_rank": rank,
                    "bm25_rank": None,
                    "retrieval_method": "naive_chunk_dense",
                    "retrieval_channels": ["chunk_dense"],
                }
            )
        return output


def load_gold(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    payload = load_json(path)
    questions = payload.get("qa_questions", payload.get("questions", payload if isinstance(payload, list) else []))
    if not isinstance(questions, list):
        questions = []
    return payload if isinstance(payload, dict) else {}, questions


def selected_groups(value: str) -> dict[str, dict[str, Any]]:
    names = [part.strip() for part in str(value or "all").split(",") if part.strip()]
    if names == ["all"]:
        return dict(FORMAL_GROUPS)
    available = {**FORMAL_GROUPS, **OPTIONAL_GROUPS}
    unknown = [name for name in names if name not in available]
    if unknown:
        raise ValueError(f"Unknown groups: {unknown}; available={list(available)}")
    return {name: available[name] for name in names}


def protocol_version_for_groups(groups: dict[str, dict[str, Any]]) -> str:
    if "normalized_final" in groups:
        return "qa-formal-v3-normalized-final-extension-v1"
    if list(groups) == list(FORMAL_GROUPS):
        return FORMAL_PROTOCOL_VERSION
    if list(groups) == ["naive_dense_rag"]:
        return "qa-formal-v3-naive-dense-optional-v1"
    return "qa-formal-v3-structured-retrieval-with-naive-dense-v1"


def cache_snapshot(cache_dir: Path, *, require_graph: bool = True, index_profile: str = "canonical_only") -> dict[str, Any]:
    docs_path = cache_dir / "kv_store_full_docs.json"
    chunks_path = cache_dir / "kv_store_text_chunks.json"
    graph_path = cache_dir / "hypergraph_chunk_entity_relation.hgdb"
    run_config_path = cache_dir / "run_config.json"
    vector_paths = {"chunks": cache_dir / "vdb_chunks.json"}
    if require_graph:
        vector_paths.update(
            {
                "entities": cache_dir / "vdb_entities.json",
                "relationships": cache_dir / "vdb_relationships.json",
            }
        )
    required_paths = [docs_path, chunks_path, run_config_path, *vector_paths.values()]
    if require_graph:
        required_paths.append(graph_path)
    result: dict[str, Any] = {
        "cache_dir": str(cache_dir),
        "exists": cache_dir.is_dir(),
        "required_files": {},
        "errors": [],
        "warnings": [],
    }
    for path in required_paths:
        result["required_files"][path.name] = path.exists()
        if not path.exists():
            result["errors"].append(f"missing {path.name}")
    if result["errors"]:
        result["status"] = "FAIL"
        return result
    try:
        docs = load_json(docs_path)
        chunks = load_json(chunks_path)
        graph = pickle.loads(graph_path.read_bytes()) if require_graph else None
        run_config = load_json(run_config_path)
        expected_docs = {f"RFB_{index:03d}" for index in range(1, 61)}
        graph_vertices = len(graph.get("v_data") or {}) if graph is not None else None
        graph_edges = len(graph.get("e_data") or {}) if graph is not None else None
        vector_stats: dict[str, Any] = {}
        for namespace, path in vector_paths.items():
            payload = load_json(path)
            dimension = int(payload.get("embedding_dim") or 0)
            rows = len(payload.get("data") or [])
            vector_stats[namespace] = {"embedding_dimension": dimension, "rows": rows}
            if dimension != 2560:
                result["errors"].append(f"{path.name} embedding dimension is {dimension}, expected 2560")
            if rows <= 0:
                result["errors"].append(f"{path.name} has no vector rows")
        result.update(
            {
                "documents": len(docs),
                "chunks": len(chunks),
                "document_ids_exact": set(docs) == expected_docs,
                "graph_vertices": graph_vertices,
                "graph_edges": graph_edges,
                "vectors": vector_stats,
                "run_config": {
                    "index_profile": run_config.get("index_profile"),
                    "enable_entity_normalization": run_config.get("enable_entity_normalization"),
                    "normalization_mode": run_config.get("normalization_mode"),
                    "embedding_model": run_config.get("embedding_model"),
                    "embedding_dim": run_config.get("embedding_dim"),
                },
            }
        )
        if set(docs) != expected_docs:
            result["errors"].append("document IDs are not exactly RFB_001-RFB_060")
        if len(chunks) != 1328:
            result["errors"].append(f"expected 1328 chunks, found {len(chunks)}")
        if vector_stats["chunks"]["rows"] != len(chunks):
            result["errors"].append("chunk vector row count differs from chunk count")
        if require_graph and (not graph_vertices or not graph_edges):
            result["errors"].append("graph contains no vertices or hyperedges")
        if str(run_config.get("index_profile") or "") != index_profile:
            result["errors"].append(f"run_config.index_profile is not {index_profile}")
        if index_profile == "dual_concat":
            validation_path = cache_dir / "final_validation.json"
            if not validation_path.exists() or not load_json(validation_path).get("validation_passed"):
                result["errors"].append("final cache has no successful validation")
            if run_config.get("enable_efu_repair") is not False or run_config.get("enable_measurement_instances") is not True:
                result["errors"].append("final method flags differ from agreed plan")
            if run_config.get("embedding_model") != "Qwen/Qwen3-Embedding-4B":
                result["errors"].append("final embedding model differs from frozen baseline")
    except Exception as exc:  # noqa: BLE001
        result["errors"].append(f"storage parse failure: {type(exc).__name__}: {exc}")
    result["status"] = "PASS" if not result["errors"] else "FAIL"
    return result

def build_readiness_report(
    question_file: Path,
    payload: dict[str, Any],
    questions: list[dict[str, Any]],
    cache_root: Path,
    groups: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def add(name: str, passed: bool, observed: Any, expected: Any, *, severity: str = "fail") -> None:
        checks.append({"name": name, "status": "PASS" if passed else severity.upper(), "observed": observed, "expected": expected})

    answerable_count = sum(bool(question.get("answerable")) for question in questions)
    unanswerable_count = len(questions) - answerable_count
    question_ids = [str(question.get("question_id") or "") for question in questions]
    gold_chunk_ids = {
        str(chunk_id)
        for question in questions
        for chunk_id in (question.get("gold_chunk_ids") or [])
        if str(chunk_id)
    }
    add("question_file_exists", question_file.exists(), str(question_file), "existing file")
    add("benchmark_status_final_gold", payload.get("status") == "final_gold", payload.get("status"), "final_gold")
    add("benchmark_human_confirmed", payload.get("human_confirmed") is True, payload.get("human_confirmed"), True)
    add("question_count", len(questions) == 40, len(questions), 40)
    add("question_ids_nonempty_unique", all(question_ids) and len(set(question_ids)) == len(question_ids), len(set(question_ids)), len(questions))
    add("answerability_split", (answerable_count, unanswerable_count) == (35, 5), [answerable_count, unanswerable_count], [35, 5])
    final_gold_count = sum(question.get("review_status") == "final_gold" and question.get("human_decision") == "ACCEPT" for question in questions)
    add("all_questions_final_gold", final_gold_count == 40, final_gold_count, 40)
    confirmed_count = sum(question.get("human_confirmed") is True for question in questions)
    add("all_questions_human_confirmed", confirmed_count == 40, confirmed_count, 40)
    add("all_rubrics_present", all(question.get("required_key_points") for question in questions), sum(bool(question.get("required_key_points")) for question in questions), 40)
    unanswerable_final = sum(
        (not bool(question.get("answerable")))
        and question.get("human_confirmed") is True
        and question.get("gold_label") == "unanswerable"
        for question in questions
    )
    add("unanswerable_absence_confirmed", unanswerable_final == 5, unanswerable_final, 5)

    cache_reports: dict[str, Any] = {}
    selected_cache_names = sorted({str(spec["cache"]) for spec in groups.values()})
    for cache_name in selected_cache_names:
        cache_dir = cache_root / cache_name
        require_graph = any(
            str(spec.get("cache")) == cache_name
            and spec.get("retriever") in {"structured_graph_hybrid_v1", "normalized_final_hybrid_rerank_v1"}
            for spec in groups.values()
        )
        final_cache = any(spec.get("cache") == cache_name and spec.get("retriever") == "normalized_final_hybrid_rerank_v1" for spec in groups.values())
        cache_reports[cache_name] = cache_snapshot(cache_dir, require_graph=require_graph, index_profile="dual_concat" if final_cache else "canonical_only")
        add(f"cache_{cache_name}", cache_reports[cache_name]["status"] == "PASS", cache_reports[cache_name], "complete 60-doc cache")
        lock_path = cache_root / f".{cache_name}.lock"
        add(f"cache_{cache_name}_not_locked", not lock_path.exists(), str(lock_path) if lock_path.exists() else None, "no active writer lock")
        chunks_path = cache_dir / "kv_store_text_chunks.json"
        if chunks_path.exists():
            chunk_ids = set(load_json(chunks_path))
            missing_gold = sorted(gold_chunk_ids - chunk_ids)
            add(f"cache_{cache_name}_gold_chunk_compatibility", not missing_gold, missing_gold[:20], "all answerable gold chunk IDs exist")

    base_chunks_path = cache_root / "hyper_base" / "kv_store_text_chunks.json"
    chem_chunks_path = cache_root / "hyper_chem_prompt" / "kv_store_text_chunks.json"
    if base_chunks_path.exists() and chem_chunks_path.exists():
        base_chunks = load_json(base_chunks_path)
        chem_chunks = load_json(chem_chunks_path)
        add("base_chem_chunk_id_alignment", set(base_chunks) == set(chem_chunks), len(set(base_chunks) ^ set(chem_chunks)), 0)
        mismatch_count = sum(
            1
            for chunk_id in set(base_chunks) & set(chem_chunks)
            if base_chunks[chunk_id].get("content") != chem_chunks[chunk_id].get("content")
        )
        add("base_chem_text_difference_policy", mismatch_count == 0, mismatch_count, "accepted non-blocking experiment variable", severity="warn")

    fail_count = sum(check["status"] == "FAIL" for check in checks)
    warn_count = sum(check["status"] == "WARN" for check in checks)
    return {
        "protocol_version": protocol_version_for_groups(groups),
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "status": "PASS" if fail_count == 0 else "FAIL",
        "fail_count": fail_count,
        "warn_count": warn_count,
        "question_file": str(question_file),
        "question_file_sha256": sha256_file(question_file) if question_file.exists() else None,
        "cache_root": str(cache_root),
        "groups": groups,
        "checks": checks,
        "cache_reports": cache_reports,
    }

def citation_metrics(citations: list[Any], evidence_count: int, abstained: bool) -> dict[str, Any]:
    if not citations:
        return {
            "citation_reference_validity": None if abstained else 0.0,
            "citation_present": False,
            "valid_citation_count": 0,
            "citation_count": 0,
            "resolved_evidence_ranks": [],
        }
    ranks: list[int] = []
    for citation in citations:
        match = CITATION_RE.search(str(citation))
        if match:
            ranks.append(int(match.group(1)))
    valid = [rank for rank in ranks if 1 <= rank <= evidence_count]
    return {
        "citation_reference_validity": len(valid) / max(1, len(citations)),
        "citation_present": True,
        "valid_citation_count": len(valid),
        "citation_count": len(citations),
        "resolved_evidence_ranks": valid,
    }



def formal_judge_prompt(qa: dict[str, Any], answer_record: dict[str, Any], evidence_context: str) -> str:
    prompt = core.judge_prompt(qa, answer_record, evidence_context)
    prompt = prompt.replace('"citation_stability_experimental": 0.0', '"citation_support_score": 0.0')
    return prompt + """

Additional formal scoring rules:
- citation_support_score must be in [0, 1]. It measures whether the cited evidence blocks actually support the answer's concrete claims, not merely whether citation labels are well formed.
- covered_key_points and missing_key_points must copy the benchmark's required key-point strings exactly; together they must partition the full required-key-point list with no duplicates.
- abstained must match whether the generated answer actually abstained.
"""


def validate_formal_judgment(
    value: dict[str, Any],
    required_key_points: list[str],
    expected_abstained: bool,
) -> tuple[bool, str]:
    valid, reason = core.validate_judgment(value)
    if not valid:
        return valid, reason
    required = [str(item) for item in required_key_points]
    covered = [str(item) for item in value.get("covered_key_points") or []]
    missing = [str(item) for item in value.get("missing_key_points") or []]
    if len(set(covered)) != len(covered) or len(set(missing)) != len(missing):
        return False, "covered/missing key points contain duplicates"
    if set(covered) & set(missing):
        return False, "covered and missing key points overlap"
    if set(covered) | set(missing) != set(required):
        return False, "covered and missing key points must exactly partition required_key_points"
    # Rounded model output (for example 0.3333 for 1/3) is not a hard
    # validation failure. The covered/missing partition is the source of truth
    # and run_one recomputes KPC deterministically.
    # Whether the generator abstained is determined once from the generated
    # answer and is not a subjective judge score. Normalize the judge echo to
    # that source of truth instead of retrying a contradictory model flag.
    value["abstained"] = bool(expected_abstained)
    try:
        citation_support = float(value.get("citation_support_score"))
    except Exception:
        return False, "citation_support_score must be numeric"
    if not 0.0 <= citation_support <= 1.0:
        return False, "citation_support_score must be in [0, 1]"
    return True, ""

def aggregate(items: list[dict[str, Any]], group: str, field: str | None = None, value: Any = None) -> dict[str, Any]:
    n = len(items)
    answerable = [item for item in items if item.get("answerable")]
    unanswerable = [item for item in items if not item.get("answerable")]
    required_total = sum(len(item.get("required_key_points") or []) for item in items)
    covered_total = sum(min(len(item.get("covered_key_points") or []), len(item.get("required_key_points") or [])) for item in items)
    citation_values = [float(item["citation_reference_validity"]) for item in items if item.get("citation_reference_validity") is not None]
    row: dict[str, Any] = {"group": group}
    if field is not None:
        row[field] = value
    row.update(
        {
            "questions": n,
            "Good Rate": round(sum(bool(item.get("good")) for item in items) / max(1, n), 4),
            "Satisfactory-or-Better Rate": round(sum(bool(item.get("satisfactory_or_better")) for item in items) / max(1, n), 4),
            "Macro KPC": round(statistics.mean(float(item.get("key_point_coverage", 0.0)) for item in items), 4) if items else 0.0,
            "Micro KPC": round(covered_total / max(1, required_total), 4),
            "Hallucination Rate": round(sum(bool(item.get("hallucinated")) for item in items) / max(1, n), 4),
            "False Abstention Rate": round(sum(bool(item.get("abstained")) for item in answerable) / max(1, len(answerable)), 4),
            "False Answer Rate": round(sum(not bool(item.get("abstained")) for item in unanswerable) / max(1, len(unanswerable)), 4),
            "Unanswerable Abstention Accuracy": round(sum(bool(item.get("abstained")) for item in unanswerable) / max(1, len(unanswerable)), 4),
            "Citation Reference Validity": round(statistics.mean(citation_values), 4) if citation_values else None,
            "Citation Presence Rate": round(sum(bool(item.get("citation_present")) for item in items) / max(1, n), 4),
            "Citation Support Score (LLM)": round(statistics.mean(float(item.get("citation_support_score", 0.0)) for item in items), 4) if items else 0.0,
        }
    )
    return row


def aggregate_summary(records: list[dict[str, Any]], groups: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return [aggregate([item for item in records if item.get("group") == group], group) for group in groups]


def aggregate_by_field(records: list[dict[str, Any]], groups: dict[str, dict[str, Any]], field: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for group in groups:
        group_items = [item for item in records if item.get("group") == group]
        values = sorted({str(item.get(field)) for item in group_items})
        for value in values:
            rows.append(aggregate([item for item in group_items if str(item.get(field)) == value], group, field, value))
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
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


def pairwise(records: list[dict[str, Any]], groups: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    by_key = {(str(item.get("question_id")), str(item.get("group"))): item for item in records}
    output: list[dict[str, Any]] = []
    names = list(groups)
    for i, group_a in enumerate(names):
        for group_b in names[i + 1 :]:
            pairs = [(by_key[(qid, group_a)], by_key[(qid, group_b)]) for qid in sorted({key[0] for key in by_key}) if (qid, group_a) in by_key and (qid, group_b) in by_key]
            output.append(
                {
                    "group_a": group_a,
                    "group_b": group_b,
                    "paired_questions": len(pairs),
                    "a_good_b_not": sum(bool(a.get("good")) and not bool(b.get("good")) for a, b in pairs),
                    "b_good_a_not": sum(bool(b.get("good")) and not bool(a.get("good")) for a, b in pairs),
                    "macro_kpc_delta_a_minus_b": round(statistics.mean(float(a.get("key_point_coverage", 0.0)) - float(b.get("key_point_coverage", 0.0)) for a, b in pairs), 4) if pairs else 0.0,
                    "hallucination_delta_a_minus_b": round(statistics.mean(float(bool(a.get("hallucinated"))) - float(bool(b.get("hallucinated"))) for a, b in pairs), 4) if pairs else 0.0,
                }
            )
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--question-file", type=Path, default=REPO_ROOT / "outputs" / "qa_eval" / "real_flow_60_qa_gold_v1" / "qa_questions.json")
    parser.add_argument("--cache-root", type=Path, default=REPO_ROOT.parent / "real_flow_80_chunk1000_v3")
    parser.add_argument('--output-dir', type=Path, default=REPO_ROOT / 'outputs' / 'qa_eval' / 'real_flow_60_qa_formal_v3_structured_four_groups')
    parser.add_argument('--output-prefix', default='qa_formal_v3')
    parser.add_argument(
        "--groups",
        default="all",
        help=(
            "Comma-separated groups. 'all' intentionally keeps the frozen original four groups; "
            "optional groups such as naive_dense_rag must be selected explicitly."
        ),
    )
    parser.add_argument("--readiness-only", action="store_true")
    parser.add_argument("--settings", type=Path, default=REPO_ROOT / "web-ui" / "backend" / "settings.json")
    parser.add_argument("--provider", default="siliconflow")
    parser.add_argument("--model")
    parser.add_argument("--base-url")
    parser.add_argument("--judge-provider")
    parser.add_argument("--judge-model")
    parser.add_argument("--judge-base-url")
    parser.add_argument("--answer-model-label", default="")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--evidence-budget-chars", type=int, default=1500)
    parser.add_argument("--evidence-format", choices=["legacy", "lossless"], default="legacy")
    parser.add_argument("--hybrid-candidate-depth", type=int, default=50)
    parser.add_argument("--rrf-k", type=int, default=60)
    parser.add_argument("--dense-weight", type=float, default=1.0)
    parser.add_argument("--bm25-weight", type=float, default=1.0)
    parser.add_argument("--naive-cosine-threshold", type=float, default=0.2)
    parser.add_argument('--relationship-candidate-depth', type=int, default=50)
    parser.add_argument('--entity-candidate-depth', type=int, default=30)
    parser.add_argument('--graph-bm25-candidate-depth', type=int, default=50)
    parser.add_argument('--graph-rrf-k', type=int, default=60)
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
    parser.add_argument("--llm-max-retries", type=int, default=5)
    parser.add_argument("--llm-timeout", type=float, default=600.0)
    parser.add_argument("--embedding-timeout", type=float, default=600.0)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--top-p", type=float, default=1.0)
    parser.add_argument("--seed", type=int, default=20260811)
    parser.add_argument("--run-id", default="", help="Required for a formal run; prevents mixing records from different protocols.")
    args = parser.parse_args()
    if not args.readiness_only and not str(args.run_id).strip():
        parser.error("--run-id is required for a formal run so outputs cannot overwrite or mix experiments")
    if args.dense_weight <= 0 or args.bm25_weight <= 0:
        parser.error("--dense-weight and --bm25-weight must both be positive")
    np.random.seed(int(args.seed))

    groups = selected_groups(args.groups)
    core.GROUPS = groups
    core.EVIDENCE_BUDGET_CHARS = int(args.evidence_budget_chars)
    core.EVIDENCE_FORMAT = args.evidence_format
    args.output_dir.mkdir(parents=True, exist_ok=True)
    payload, questions = load_gold(args.question_file)
    readiness = build_readiness_report(args.question_file, payload, questions, args.cache_root, groups)
    write_json(args.output_dir / f"{args.output_prefix}_readiness_report.json", readiness)
    print(json.dumps({"readiness": readiness["status"], "fail_count": readiness["fail_count"], "warn_count": readiness["warn_count"]}, ensure_ascii=False), flush=True)
    if args.readiness_only:
        raise SystemExit(0 if readiness["status"] == "PASS" else 2)
    if readiness["status"] != "PASS":
        raise RuntimeError(f"Formal readiness gate failed with {readiness['fail_count']} hard failures. See readiness report.")

    generator_pool = FormalLLMClientPool(args.settings, args.provider, model_override=args.model, base_url_override=args.base_url, timeout=args.llm_timeout)
    judge_pool = FormalLLMClientPool(args.settings, args.judge_provider or args.provider, model_override=args.judge_model or args.model, base_url_override=args.judge_base_url or args.base_url, timeout=args.llm_timeout)
    embedding_pool = EmbeddingClientPool(timeout=args.embedding_timeout, max_retries=args.llm_max_retries)
    structured_config = StructuredRetrievalConfig(
        relationship_candidate_depth=args.relationship_candidate_depth,
        entity_candidate_depth=args.entity_candidate_depth,
        bm25_candidate_depth=args.graph_bm25_candidate_depth,
        rrf_k=args.graph_rrf_k,
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
    structured_retrievers: dict[str, StructuredGraphRetriever] = {}
    for group, spec in groups.items():
        if spec['retriever'] == 'normalized_final_hybrid_rerank_v1':
            from scripts.final_graph_retrieval import FinalGraphIndex, FinalGraphRetriever, FinalRetrievalConfig
            cache_name = str(spec['cache'])
            structured_indexes[cache_name] = FinalGraphIndex(args.cache_root / cache_name)
            structured_retrievers[group] = FinalGraphRetriever(
                structured_indexes[cache_name], embedding_pool,
                config=FinalRetrievalConfig(**structured_config.as_dict(), enable_rerank=True),
            )
            continue
        if spec['retriever'] != 'structured_graph_hybrid_v1':
            continue
        cache_name = str(spec['cache'])
        if cache_name not in structured_indexes:
            structured_indexes[cache_name] = StructuredGraphIndex(args.cache_root / cache_name)
        structured_retrievers[group] = StructuredGraphRetriever(
            structured_indexes[cache_name],
            embedding_pool,
            view=str(spec['view']),
            config=structured_config,
        )

    hybrid_retriever: HybridTextRetriever | None = None
    if 'hybrid_rag_baseline' in groups:
        hybrid_retriever = HybridTextRetriever(
            args.cache_root / groups['hybrid_rag_baseline']['cache'],
            embedding_pool,
            candidate_depth=args.hybrid_candidate_depth,
            rrf_k=args.rrf_k,
            dense_weight=args.dense_weight,
            bm25_weight=args.bm25_weight,
        )

    naive_retriever: NaiveDenseRetriever | None = None
    if 'naive_dense_rag' in groups:
        naive_retriever = NaiveDenseRetriever(
            args.cache_root / groups['naive_dense_rag']['cache'],
            embedding_pool,
            cosine_threshold=args.naive_cosine_threshold,
        )

    protocol = {
        "protocol_version": protocol_version_for_groups(groups),
        "run_id": str(args.run_id),
        "question_file": str(args.question_file.resolve()),
        "question_file_sha256": readiness.get("question_file_sha256"),
        "cache_root": str(args.cache_root.resolve()),
        "groups": groups,
        "top_k": args.top_k,
        "evidence_budget_chars": args.evidence_budget_chars,
        "evidence_format": args.evidence_format,
        'structured_graph_retrieval': {
            'method': 'relationship dense + relationship BM25 + entity dense + entity BM25 + weighted RRF + one-hop incident-edge expansion + deterministic structural rerank + full source-chunk reconstruction',
            'config': structured_config.as_dict(),
            'cache_mapping_audits': {name: index.mapping_audit for name, index in structured_indexes.items()},
            'graph_hypergraph_difference': 'identical retrieval pipeline and parameters; graph permits only arity=2 while hypergraph permits all arities',
        },
        "hybrid_baseline": {"method": "BM25 + Qwen/Qwen3-Embedding-4B dense cosine + weighted RRF", "candidate_depth": args.hybrid_candidate_depth, "rrf_k": args.rrf_k, "dense_weight": args.dense_weight, "bm25_weight": args.bm25_weight},
        "generator": {"provider": generator_pool.provider_name, "base_url": generator_pool.base_url, "model": generator_pool.model, "key_count": len(generator_pool.entries)},
        "judge": {"provider": judge_pool.provider_name, "base_url": judge_pool.base_url, "model": judge_pool.model, "key_count": len(judge_pool.entries)},
        "temperature": args.temperature,
        "top_p": args.top_p,
        "parallel_workers": args.parallel_workers,
        "llm_timeout": args.llm_timeout,
        "embedding_timeout": args.embedding_timeout,
        "seed": args.seed,
        "gold_source_doc_filtering": False,
        "base_chem_text_difference_policy": "accepted non-blocking experiment variable",
    }
    if 'normalized_final' in groups:
        if readiness.get('question_file_sha256') != 'a01fd36a1795e651fe8a08d9fb8482f61dcbce1197839064c072c3fe515014c0':
            raise ValueError('final QA requires the frozen 40-question file')
        if (args.top_k, args.evidence_budget_chars, args.temperature, args.top_p, args.seed) != (5, 1500, 1.0, .95, 20260811):
            raise ValueError('final QA requires frozen top-k=5, budget=1500, temperature=1.0, top-p=0.95, seed=20260811')
        if generator_pool.model != 'kimi-k2.6' or judge_pool.model != 'kimi-k2.6':
            raise ValueError('final QA requires the frozen kimi-k2.6 generator and judge')
        protocol['normalized_final_retrieval'] = {
            'method': 'hybrid RRF candidate pool frozen before existing lexical/structural rerank',
            'config': FinalRetrievalConfig(**structured_config.as_dict(), enable_rerank=True).as_dict(),
            'cache_validation': load_json(args.cache_root / groups['normalized_final']['cache'] / 'final_validation.json'),
        }
    if 'naive_dense_rag' in groups:
        protocol['naive_dense_baseline'] = {
            'enabled': True,
            'method': 'upstream Hyper-RAG naive mode: Qwen chunk dense cosine Top-K only',
            'cosine_threshold': args.naive_cosine_threshold,
            'bm25': False,
            'graph_access': False,
            'reranker': False,
        }
    protocol_path = args.output_dir / f"{args.output_prefix}_protocol.json"
    records_path = args.output_dir / f"{args.output_prefix}_records.jsonl"
    if protocol_path.exists() and records_path.exists():
        existing_protocol = load_json(protocol_path)
        if existing_protocol != protocol:
            raise RuntimeError("Output directory already contains records from a different formal protocol; use a new --output-dir or matching --run-id/configuration")
    write_json(protocol_path, protocol)
    write_json(args.output_dir / "qa_questions.json", {"benchmark_id": payload.get("benchmark_id"), "status": payload.get("status"), "qa_questions": questions})

    raw_path = args.output_dir / f"{args.output_prefix}_raw.json"
    errors_path = args.output_dir / f"{args.output_prefix}_errors.json"
    records: list[dict[str, Any]] = []
    if records_path.exists():
        for line in records_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                records.append(json.loads(line))
    raw_records = load_json(raw_path) if raw_path.exists() else []
    errors = load_json(errors_path) if errors_path.exists() else []
    completed = {(str(item.get("question_id")), str(item.get("group"))) for item in records}
    persisted = set(completed)

    def persist() -> None:
        with records_path.open("a", encoding="utf-8") as handle:
            for item in records:
                key = (str(item.get("question_id")), str(item.get("group")))
                if key not in persisted:
                    handle.write(json.dumps(item, ensure_ascii=False) + "\n")
                    persisted.add(key)
        write_json(raw_path, raw_records)
        write_json(errors_path, errors)

    total = len(questions) * len(groups)

    def run_one(index: int, qa: dict[str, Any], group: str) -> dict[str, Any]:
        print(f"[QAFormal] {index}/{total} generation+judge {group} {qa['question_id']}", flush=True)
        if group == "hybrid_rag_baseline":
            assert hybrid_retriever is not None
            evidence = hybrid_retriever.search(qa["question"], args.top_k)
        elif group == "naive_dense_rag":
            assert naive_retriever is not None
            evidence = naive_retriever.search(qa["question"], args.top_k)
        else:
            evidence = structured_retrievers[group].search(qa["question"], args.top_k)
        evidence_context = core.format_evidence_context(qa["question"], evidence, evidence_format=args.evidence_format)
        generated = core.complete_valid_json(generator_pool, core.generation_prompt(qa, evidence_context), core.validate_generation, temperature=args.temperature, top_p=args.top_p, max_tokens=800, max_retries=args.llm_max_retries, label="generation")
        answer_text = str(generated.get("answer") or "")
        answer_record = {"answer": answer_text, "citations": generated.get("citations") or [], "abstained": bool(generated.get("abstained")) or "don't know based on the retrieved evidence" in answer_text.lower()}
        judge_validator = lambda value: validate_formal_judgment(value, qa.get("required_key_points") or [], answer_record["abstained"])
        judged = core.complete_valid_json(judge_pool, formal_judge_prompt(qa, answer_record, evidence_context), judge_validator, temperature=args.temperature, top_p=args.top_p, max_tokens=1400, max_retries=args.llm_max_retries, label="judge")
        covered_key_points = [str(item) for item in judged.get('covered_key_points') or []]
        required_key_points = [str(item) for item in qa.get('required_key_points') or []]
        judged['key_point_coverage'] = len(covered_key_points) / max(1, len(required_key_points))
        citation = citation_metrics(answer_record["citations"], len(evidence), answer_record["abstained"])
        quality_label = str(judged.get("quality_label") or "POOR")
        record = {
            "question_id": qa["question_id"],
            "group": group,
            "group_label": groups[group]["label"],
            "question": qa["question"],
            "answerable": bool(qa["answerable"]),
            "question_type": qa.get("question_type"),
            "difficulty": qa.get("difficulty"),
            "support_mode": qa.get("support_mode"),
            "fact_arity": qa.get("fact_arity"),
            "reference_answer": qa.get("reference_answer"),
            "required_key_points": qa.get("required_key_points") or [],
            "generated_answer": answer_text,
            "citations": answer_record["citations"],
            "quality_label": quality_label,
            "good": quality_label == "GOOD",
            "satisfactory_or_better": quality_label in {"GOOD", "SATISFACTORY"},
            "key_point_coverage": float(judged.get("key_point_coverage", 0.0) or 0.0),
            "covered_key_points": judged.get("covered_key_points") or [],
            "missing_key_points": judged.get("missing_key_points") or [],
            "hallucinated": bool(judged.get("hallucinated")),
            "unsupported_claims_found": judged.get("unsupported_claims_found") or [],
            "abstained": answer_record["abstained"],
            "false_abstention": bool(qa["answerable"] and answer_record["abstained"]),
            "false_answer": bool((not qa["answerable"]) and (not answer_record["abstained"])),
            "abstention_correct": (not answer_record["abstained"]) if qa["answerable"] else answer_record["abstained"],
            "citation_support_score": float(judged.get("citation_support_score", 0.0) or 0.0),
            **citation,
            "rationale": judged.get("rationale", ""),
            "generator_model": generator_pool.model,
            "judge_model": judge_pool.model,
            "evidence": [{"rank": rank, "evidence_id": item.get("id"), "retrieval_score": item.get("retrieval_score"), "dense_rank": item.get("dense_rank"), "bm25_rank": item.get("bm25_rank"), "relation_type": item.get("relation_type"), 'retrieval_method': item.get('retrieval_method'), 'retrieval_channels': item.get('retrieval_channels'), 'supporting_edge_ids': item.get('supporting_edge_ids'), 'supporting_arities': item.get('supporting_arities'), 'supporting_relation_types': item.get('supporting_relation_types'), "readable_evidence": core.evidence_text(item)[:1200], "formatted_evidence_block": core.format_evidence_block(rank, item, qa["question"])[:1600]} for rank, item in enumerate(evidence, 1)],
        }
        return {"record": record, "raw": {"question_id": qa["question_id"], "group": group, "generated": generated, "judged": judged}}

    pending: list[tuple[int, dict[str, Any], str]] = []
    index = 0
    for qa in questions:
        for group in groups:
            index += 1
            if (str(qa["question_id"]), group) not in completed:
                pending.append((index, qa, group))
    workers = max(1, int(args.parallel_workers))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {executor.submit(run_one, index, qa, group): (qa, group) for index, qa, group in pending}
        for future in concurrent.futures.as_completed(future_map):
            qa, group = future_map[future]
            try:
                result = future.result()
                records.append(result["record"])
                raw_records.append(result["raw"])
                errors = [item for item in errors if (item.get("question_id"), item.get("group")) != (qa["question_id"], group)]
                print(f"[QAFormal] done {group} {qa['question_id']} ({len(records)}/{total})", flush=True)
            except Exception as exc:  # noqa: BLE001
                errors.append({"question_id": qa["question_id"], "group": group, "error": f"{type(exc).__name__}: {exc}"})
                print(f"[QAFormal] error {group} {qa['question_id']}: {type(exc).__name__}: {exc}", flush=True)
            persist()

    summary = aggregate_summary(records, groups)
    write_csv(args.output_dir / f"{args.output_prefix}_summary.csv", summary)
    strata: dict[str, list[dict[str, Any]]] = {}
    for field in ("answerable", "question_type", "difficulty", "support_mode", "fact_arity"):
        rows = aggregate_by_field(records, groups, field)
        strata[field] = rows
        write_csv(args.output_dir / f"{args.output_prefix}_by_{field}.csv", rows)
    pairwise_rows = pairwise(records, groups)
    write_csv(args.output_dir / f"{args.output_prefix}_pairwise.csv", pairwise_rows)
    core.write_failure_debug(args.output_dir / f"{args.output_prefix}_debug_failures.md", records)
    write_json(
        args.output_dir / f"{args.output_prefix}_summary.json",
        {
            "protocol": protocol,
            "readiness": readiness,
            "record_count": len(records),
            "expected_record_count": total,
            "complete": len(records) == total and not errors,
            "summary": summary,
            "strata": strata,
            "pairwise": pairwise_rows,
            "errors": errors,
        },
    )
    print(json.dumps({"output_dir": str(args.output_dir), "records": len(records), "expected": total, "errors": len(errors), "summary": summary}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
