"""Offline regression gates for the Web final retrieval integration."""
import asyncio
import base64
import hashlib
import json
import pickle
import importlib.util
import sys
from contextlib import asynccontextmanager
from types import SimpleNamespace
from pathlib import Path

import numpy as np
import pytest

from hyperche.retrieval.evidence import format_context
from hyperche.retrieval.final import FinalGraphIndex, FinalRetrievalConfig
from hyperche.retrieval.runtime import (
    FINAL_DIMENSION, FINAL_MODEL, CacheCompatibilityError, FinalCacheRegistry,
    graph_snapshot, inspect_final_cache, project_evidence, retrieve_final,
)
from hyperche.retrieval.structured import source_chunk_ids


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def content_hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


@pytest.fixture
def final_cache(tmp_path):
    chunks = {"RFB_001_CHK_001": {"content": "energy efficiency 80% at 25 C", "source_doc_id": "RFB_001"},
              "RFB_002_CHK_001": {"content": "energy efficiency 60% at 10 C", "source_doc_id": "RFB_002"}}
    keys = [("a", "b"), ("c", "d")]
    edges = {}
    vertices = {name: {"entity_type": "CONCEPT", "canonical_name": name} for name in "abcd"}
    for key, chunk in zip(keys, chunks):
        edges[key] = {"description": chunks[chunk]["content"], "keywords": "energy efficiency",
                      "source_chunk_ids": [chunk], "relation_type": "MEASUREMENT",
                      "evidence_instances": [{"canonical_vertices": list(key), "vertices": list(key),
                        "source_chunk_id": chunk, "description": chunks[chunk]["content"],
                        "source_span": chunks[chunk]["content"]}]}
    graph = {"v_data": vertices, "e_data": edges,
             "v_inci": {name: {key} for key in keys for name in key}}
    (tmp_path / "hypergraph_chunk_entity_relation.hgdb").write_bytes(pickle.dumps(graph))
    dump(tmp_path / "kv_store_text_chunks.json", chunks)
    dump(tmp_path / "run_config.json", {"normalization_version": "final-posthoc-v1", "index_profile": "dual_concat",
        "enable_entity_normalization": True, "enable_measurement_instances": True, "enable_efu_repair": False,
        "embedding_model": FINAL_MODEL, "embedding_dim": FINAL_DIMENSION})
    dump(tmp_path / "final_validation.json", {"validation_passed": True, "validation_failures": [],
        "documents": 2, "chunks": 2, "entities": 4, "relationships": 2,
        "embedding_model": FINAL_MODEL, "embedding_dim": FINAL_DIMENSION})
    for kind, ids in (("entities", list(vertices)), ("relationships", keys)):
        rows = []
        for rank, name in enumerate(ids):
            content = "[Canonical] " + str(name) + " [Surface] energy efficiency"
            row = {"__id__": str(rank), "content": content, "embedding_model": FINAL_MODEL,
                   "embedding_dim": FINAL_DIMENSION, "index_view": "dual_concat", "content_hash": content_hash(content)}
            row.update({"entity_name": name} if kind == "entities" else {"id_set": list(name)})
            rows.append(row)
        matrix = np.zeros((len(rows), FINAL_DIMENSION), dtype=np.float32)
        matrix[:, 0] = 1
        dump(tmp_path / f"vdb_{kind}.json", {"embedding_dim": FINAL_DIMENSION, "data": rows,
             "matrix": base64.b64encode(matrix.tobytes()).decode()})
    return tmp_path


def test_registry_verifies_reuses_and_keeps_cache_read_only(final_cache):
    before = {path.name: path.read_bytes() for path in final_cache.iterdir()}
    registry = FinalCacheRegistry()
    index, signature = registry.get(final_cache)
    again, signature_again = registry.get(final_cache)
    assert index is again and signature == signature_again
    assert inspect_final_cache(final_cache)["cache_ready"]
    assert {path.name: path.read_bytes() for path in final_cache.iterdir()} == before
    snapshot = graph_snapshot(index, edge_limit=1)
    assert snapshot["sampled"] and len(snapshot["edges"]) == 1


def test_stale_content_signature_blocks_load(final_cache):
    payload = json.loads((final_cache / "vdb_entities.json").read_text())
    payload["data"][0]["content"] += " modified"
    dump(final_cache / "vdb_entities.json", payload)
    with pytest.raises(CacheCompatibilityError, match="signature"):
        FinalCacheRegistry().get(final_cache)


def test_raw_query_one_embedding_frozen_pool_and_source_local_projection(final_cache):
    calls = []
    query = "μ  energy efficiency  "
    async def embed(texts, **options):
        calls.append((texts, options))
        vector = np.zeros((1, FINAL_DIMENSION), dtype=np.float32)
        vector[0, 0] = 1
        return vector
    result = asyncio.run(retrieve_final(query, final_cache, embed))
    assert calls == [([query], {"dimensions": 2560, "expected_model": FINAL_MODEL})]
    assert result["retrieval_meta"]["query_expansion"] is False
    assert result["retrieval_meta"]["budget_unit"] == "whitespace_tokens"
    index = FinalGraphIndex(final_cache)
    vector = np.zeros(FINAL_DIMENSION, dtype=np.float32)
    vector[0] = 1
    f0 = index.search(query, vector, view="hyper", top_k=5, config=FinalRetrievalConfig(enable_rerank=False))
    assert result["evidence"][0]["candidate_edge_ids"] == f0[0]["candidate_edge_ids"]
    assert result["evidence"][0]["candidate_chunk_ids"] == f0[0]["candidate_chunk_ids"]
    for edge in result["hyperedges"]:
        assert edge["evidence_instances"][0]["source_chunk_id"] in edge["source_chunk_ids"]


def test_wrong_dimension_rejected(final_cache):
    async def embed(*args, **kwargs):
        return np.ones((1, 3), dtype=np.float32)
    with pytest.raises(CacheCompatibilityError, match="2560"):
        asyncio.run(retrieve_final("energy", final_cache, embed))


def test_generic_chunk_ids_match_exact_case_and_sep():
    chunks = {"chunk-aBc": {}, "doc2_HASH": {}, "RFB_001_CHK_001": {}}
    edge = {"source_id": "chunk-aBc<SEP>doc2_HASH", "source_chunk_ids": ["rfb_001_chk_001"]}
    assert source_chunk_ids(edge, chunks) == ["RFB_001_CHK_001", "chunk-aBc", "doc2_HASH"]


def test_formatter_exactly_matches_frozen_qa_legacy():
    from scripts import run_qa_smoke_llm as frozen
    items = [{"id": f"e{rank}", "readable_evidence": "Nafion energy efficiency 80% at 25 C",
              "vertices": ["Nafion", "energy efficiency", "25 C"], "relation_type": "MEASUREMENT"} for rank in range(5)]
    previous = frozen.EVIDENCE_BUDGET_CHARS
    try:
        frozen.EVIDENCE_BUDGET_CHARS = 1500
        context, ids = format_context("Nafion energy efficiency", items)
        assert context == frozen.format_evidence_context("Nafion energy efficiency", items, evidence_format="legacy")
        assert ids == [item["id"] for item in items]
    finally:
        frozen.EVIDENCE_BUDGET_CHARS = previous


@pytest.fixture
def backend(monkeypatch, tmp_path):
    # Isolate authentication/settings writes from the developer's environment.
    import uvicorn  # noqa: F401; keep the backend from replacing pytest's stdout
    root = Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(root / "web-ui/backend"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("HYPERCHE_ADMIN_EMAIL", raising=False)
    monkeypatch.delenv("HYPERCHE_ADMIN_PASSWORD", raising=False)
    monkeypatch.setenv("HYPERCHE_SQLITE_PATH", str(tmp_path / "auth.db"))
    settings = tmp_path / "settings.json"
    dump(settings, {})
    monkeypatch.setenv("HYPERCHE_SETTINGS_FILE", str(settings))
    spec = importlib.util.spec_from_file_location("hyperche_backend_test", root / "web-ui/backend/main.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_public_json_and_stream_share_one_retrieval_and_release_slot(backend, final_cache, monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setenv("HYPERCHE_FINAL_CACHE_DIR", str(final_cache))
    monkeypatch.setenv("HYPERCHE_FINAL_CACHE_DATABASE", "case1")
    monkeypatch.setenv("HYPERCHE_PUBLIC_DEMO_DATABASE", "case1")
    monkeypatch.setattr(backend, "query_model_status", lambda **kwargs: {
        "embedding_ready": True, "answer_ready": True, "models_ready": True})
    calls, releases = [], []
    async def embed(texts, **options):
        calls.append(texts)
        vector = np.zeros((1, FINAL_DIMENSION), dtype=np.float32)
        vector[0, 0] = 1
        return vector
    async def answer(*args, **kwargs):
        return "Supported answer [Evidence 1]"
    async def stream(*args, **kwargs):
        yield "Supported answer [Evidence 1]"
    @asynccontextmanager
    async def slot(request):
        assert request.client
        try:
            yield SimpleNamespace(bind_owner=lambda: None)
        finally:
            releases.append(True)
    monkeypatch.setattr(backend, "get_hyperrag_embedding_func", embed)
    monkeypatch.setattr(backend, "get_hyperrag_llm_func", answer)
    monkeypatch.setattr(backend, "get_hyperrag_llm_stream_func", stream)
    monkeypatch.setattr(backend, "public_query_slot", slot)
    monkeypatch.setattr(backend, "get_or_create_hyperrag", lambda *args: pytest.fail("final cache must stay read-only"))
    client = TestClient(backend.app)
    payload = {"question": "energy efficiency", "top_k": 60}
    response = client.post("/public/demo/query", json=payload)
    assert response.status_code == 200
    assert response.json()["retrieval_meta"]["profile"] == "f1"
    assert response.json()["retrieval_meta"]["evidence_top_k"] == 5
    assert len(calls) == 1 and len(releases) == 1
    streamed = client.post("/public/demo/query/stream", json=payload)
    assert streamed.status_code == 200
    assert streamed.text.index("event: retrieval") < streamed.text.index("event: token") < streamed.text.index("event: done")
    assert '"text_units"' in streamed.text and '"source_chunk_ids"' in streamed.text
    assert len(calls) == 2 and len(releases) == 2
    # Context-only queries perform retrieval but never invoke answer generation.
    async def forbidden_answer(*args, **kwargs):
        pytest.fail("context-only query called generation")
    monkeypatch.setattr(backend, "get_hyperrag_llm_func", forbidden_answer)
    assert client.post("/public/demo/query", json={**payload, "only_need_context": True}).status_code == 200


def test_offline_graph_available_without_models_and_queries_preflight(backend, final_cache, monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setenv("HYPERCHE_FINAL_CACHE_DIR", str(final_cache))
    monkeypatch.setenv("HYPERCHE_FINAL_CACHE_DATABASE", "case1")
    monkeypatch.setenv("HYPERCHE_PUBLIC_DEMO_DATABASE", "case1")
    monkeypatch.setattr(backend, "query_model_status", lambda **kwargs: {
        "embedding_ready": False, "answer_ready": False, "models_ready": False})
    async def forbidden(*args, **kwargs):
        pytest.fail("model API called before channel configuration")
    monkeypatch.setattr(backend, "get_hyperrag_embedding_func", forbidden)
    client = TestClient(backend.app)
    status = client.get("/public/demo/status").json()
    assert status["cache_ready"] and not status["models_ready"] and not status["ready"]
    graph = client.get("/public/demo/graph").json()
    assert graph["offline"] and graph["vertices"] and graph["entities"]
    for route in ("/public/demo/query", "/public/demo/query/stream"):
        assert client.post(route, json={"question": "energy efficiency"}).status_code == 503


def test_budget_cut_keeps_json_and_sse_graph_linked_to_generation(backend, final_cache, monkeypatch):
    from fastapi.testclient import TestClient
    from hyperche.retrieval import runtime
    from hyperche.retrieval.evidence import format_evidence_block, token_count
    original = runtime.format_context
    def one_block_budget(query, items, **kwargs):
        return original(query, items, budget=token_count(format_evidence_block(1, items[0], query)))
    monkeypatch.setattr(runtime, "format_context", one_block_budget)
    monkeypatch.setenv("HYPERCHE_FINAL_CACHE_DIR", str(final_cache))
    monkeypatch.setenv("HYPERCHE_FINAL_CACHE_DATABASE", "case1")
    monkeypatch.setenv("HYPERCHE_PUBLIC_DEMO_DATABASE", "case1")
    monkeypatch.setattr(backend, "query_model_status", lambda **kwargs: {
        "embedding_ready": True, "answer_ready": False, "models_ready": False})
    async def embed(*args, **kwargs):
        vector = np.zeros((1, FINAL_DIMENSION), dtype=np.float32)
        vector[0, 0] = 1
        return vector
    @asynccontextmanager
    async def slot(request):
        yield SimpleNamespace(bind_owner=lambda: None)
    monkeypatch.setattr(backend, "get_hyperrag_embedding_func", embed)
    monkeypatch.setattr(backend, "public_query_slot", slot)
    client = TestClient(backend.app)
    payload = {"question": "energy efficiency", "only_need_context": True}
    result = client.post("/public/demo/query", json=payload).json()
    meta = result["retrieval_meta"]
    assert len(meta["retrieved_evidence_ids"]) == 2 and len(meta["generation_evidence_ids"]) == 1
    assert [unit["id"] for unit in result["text_units"]] == meta["generation_evidence_ids"]
    assert all(unit["included_in_context"] for unit in result["text_units"])
    text = client.post("/public/demo/query/stream", json=payload).text
    frame = next(frame for frame in text.split("\n\n") if frame.startswith("event: retrieval"))
    streamed = json.loads(frame.split("data: ", 1)[1])
    assert streamed["entities"] == result["entities"] and streamed["text_units"] == result["text_units"]


def test_authenticated_final_query_and_graph_are_read_only(backend, final_cache, monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setenv("HYPERCHE_FINAL_CACHE_DIR", str(final_cache))
    monkeypatch.setenv("HYPERCHE_FINAL_CACHE_DATABASE", "case1")
    monkeypatch.setattr(backend, "query_model_status", lambda **kwargs: {
        "embedding_ready": True, "answer_ready": False, "models_ready": False})
    user = {"id": "test-admin", "role": "admin"}
    backend.app.dependency_overrides[backend.require_current_user] = lambda: user
    async def embed(*args, **kwargs):
        vector = np.zeros((1, FINAL_DIMENSION), dtype=np.float32)
        vector[0, 0] = 1
        return vector
    monkeypatch.setattr(backend, "get_hyperrag_embedding_func", embed)
    monkeypatch.setattr(backend, "get_or_create_hyperrag", lambda *args: pytest.fail("mutable final access"))
    before = {path.name: path.read_bytes() for path in final_cache.iterdir()}
    client = TestClient(backend.app)
    payload = {"question": "energy efficiency", "database": "case1", "only_need_context": True}
    published = next(item for item in client.get("/databases").json() if item["name"] == "case1")
    assert published["read_only"] and published["retrieval_profile"] == "f1"
    assert client.post("/hyperrag/query", json=payload).json()["retrieval_meta"]["profile"] == "f1"
    assert "event: retrieval" in client.post("/hyperrag/query/stream", json=payload).text
    assert client.get("/db?database=case1").json()["read_only"]
    assert client.get("/db/vertices/a?database=case1").json()["entity_name"] == "a"
    assert client.get("/db/hyperedges?database=case1&page=1&page_size=1").json()["total"] == 2
    status = client.get("/database/status?database=case1").json()
    assert status["cache_ready"] and status["supports_modes"] == ["hyper"]
    assert client.post("/database/clear?database=case1").status_code == 403
    assert {path.name: path.read_bytes() for path in final_cache.iterdir()} == before


def test_models_status_uses_personal_channels_when_platform_empty(backend, monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setattr(backend, "load_effective_settings", lambda: {})
    monkeypatch.setattr(backend, "resolve_embedding_target", lambda settings, user_id: (
        FINAL_MODEL, "test-key" if user_id else "", "http://test.invalid", "user" if user_id else "platform"))
    monkeypatch.setattr(backend, "configured_embedding_dim", lambda settings, user_id: FINAL_DIMENSION)
    monkeypatch.setattr(backend.providers, "resolve_role_providers", lambda role, current_user_id=None: [
        {"modelName": "personal-model", "baseUrl": "http://test.invalid", "apiKeys": ["test-key"], "scope": "user"}
    ] if current_user_id else [])
    backend.app.dependency_overrides[backend.get_current_user] = lambda: {"id": "personal-user"}
    assert TestClient(backend.app).get("/systems/status").json()["models_ready"]
    assert not backend.query_model_status(final=True, user_id=None)["models_ready"]


@pytest.mark.parametrize("streaming,after_token", [(False, False), (True, False), (True, True)])
def test_provider_cancellation_never_fails_over(backend, monkeypatch, tmp_path, streaming, after_token):
    settings = tmp_path / "cancel-settings.json"
    dump(settings, {"llmMaxRetries": 1})
    monkeypatch.setattr(backend, "SETTINGS_FILE", str(settings))
    candidate = {"provider": {"name": "test", "modelName": "test", "baseUrl": "http://test.invalid",
                 "scope": "platform"}, "key": "test", "key_index": 1, "key_total": 1,
                 "provider_id": "test", "key_id": "test"}
    monkeypatch.setattr(backend, "resolve_llm_candidates", lambda *args: [candidate, candidate])
    monkeypatch.setattr(backend, "consume_platform_quota", lambda *args: None)
    monkeypatch.setattr(backend, "summarize_llm_candidate_pool", lambda *args: {})
    monkeypatch.setattr(backend, "record_llm_provider_result", lambda *args, **kwargs: None)
    calls, released = [], []
    async def acquire(*args):
        return lambda: released.append(True), {"active": 1, "limit": 2}, {"active": 1, "limit": 2}
    monkeypatch.setattr(backend, "acquire_llm_provider_slot", acquire)
    async def cancelled(*args, **kwargs):
        calls.append(True)
        raise asyncio.CancelledError()
    async def cancelled_stream(*args, **kwargs):
        calls.append(True)
        if after_token:
            yield "partial"
        raise asyncio.CancelledError()
    monkeypatch.setattr(backend, "openai_complete_if_cache", cancelled)
    monkeypatch.setattr(backend, "openai_complete_stream_if_cache", cancelled_stream)
    async def run():
        if streaming:
            async for _ in backend.get_hyperrag_llm_stream_func("question"):
                pass
        else:
            await backend.get_hyperrag_llm_func("question")
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run())
    assert len(calls) == 1 and len(released) == 1
