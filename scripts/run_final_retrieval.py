"""Run frozen 58-query F0/F1 retrieval; retain shared candidates and source audits."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hyperche.normalization import posthoc_cache as core
from scripts.final_graph_retrieval import FinalGraphIndex, FinalGraphRetriever, FinalRetrievalConfig
from scripts.run_qa_formal_llm import EmbeddingClientPool
from scripts.run_retrieval_formal_four_groups import query_rows, structured_retrieve

QUERY_SHA = "7232fbf58ad48070f90f201b17d512ecb54ec32d9f6e27572724c224177904be"
GROUPS = {"normalized_final_no_rerank": False, "normalized_final": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--queries", type=Path, required=True)
    parser.add_argument("--embedding-endpoints-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if core.file_sha256(args.queries) != QUERY_SHA:
        raise ValueError("retrieval query file differs from frozen protocol")
    config = FinalRetrievalConfig()
    validation = core._load_json_dict(args.cache / "final_validation.json")
    if not validation.get("validation_passed"):
        raise ValueError("final cache has not passed validation")
    protocol = {"protocol_version": "retrieval-final-paired-v1", "query_sha256": QUERY_SHA,
                "cache": str(args.cache.resolve()), "cache_graph_sha256": core.file_sha256(args.cache / core.GRAPH_FILE),
                "query_count": 58, "top_k": 20, "source_doc_filter_used": False, "config": config.as_dict(),
                "groups": GROUPS, "candidate_policy": "same hybrid RRF top-50 edge pool before rerank",
                "rerank": "existing 0.004 lexical coverage + min(0.003, 0.0015 * additional matched seeds)",
                "qa_and_shared_qrels_evaluation": "separate subsequent stages"}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    path = args.output_dir / "run_protocol.json"
    if path.exists() and core._load_json_dict(path) != protocol:
        raise ValueError("output directory has a different protocol")
    core.write_json(path, protocol)
    endpoints = [line.split("|", 1) for line in args.embedding_endpoints_file.read_text(encoding="utf-8-sig").splitlines() if "|" in line]
    if any(url.strip() != "https://api.siliconflow.cn/v1" for url, _ in endpoints):
        raise ValueError("unexpected query embedding endpoint")
    os.environ["EMB_API_KEY"] = ";".join(key.strip() for _, key in endpoints)
    os.environ["EMB_MODEL"] = "Qwen/Qwen3-Embedding-4B"
    os.environ["EMB_DIM"] = "2560"
    os.environ["EMB_BASE_URL"] = "https://api.siliconflow.cn/v1"
    pool = EmbeddingClientPool(timeout=120, max_retries=5)
    index = FinalGraphIndex(args.cache)
    queries = query_rows(core._load_json_dict(args.queries))
    if len(queries) != 58:
        raise ValueError("expected 58 frozen queries")
    completed = {group: {r["query_id"]: r for r in core.read_jsonl(args.output_dir / group / "retrieval_query_results.jsonl") if r.get("status") == "success"} for group in GROUPS}
    started = time.monotonic()
    try:
        for query in queries:
            qid = str(query["query_id"])
            audits = {}
            for group, rerank in GROUPS.items():
                if qid in completed[group]:
                    audits[group] = completed[group][qid]["retrieval_audit"]
                    continue
                retriever = FinalGraphRetriever(index, pool, config=replace(config, enable_rerank=rerank))
                raw = retriever.search(str(query.get("question") or ""), 20)
                audit = {"candidate_edge_ids": raw[0]["candidate_edge_ids"] if raw else [],
                         "candidate_chunk_ids": raw[0]["candidate_chunk_ids"] if raw else [],
                         "rerank_enabled": rerank}
                # Reuse the existing export schema without querying twice.
                class Ready:
                    def search(self, *_):
                        return raw
                candidates = structured_retrieve(query=query, system=group, retriever=Ready(), top_k=20)
                row = {"query_id": qid, "system": group, "question": query.get("question"), "status": "success",
                       "candidate_count": len(candidates), "retrieval_audit": audit, "candidates": candidates}
                core.append_jsonl(args.output_dir / group / "retrieval_query_results.jsonl", row)
                completed[group][qid] = row
                audits[group] = audit
            if audits["normalized_final"]["candidate_edge_ids"] != audits["normalized_final_no_rerank"]["candidate_edge_ids"]:
                raise ValueError(f"F0/F1 candidate edge pools differ: {qid}")
            if audits["normalized_final"]["candidate_chunk_ids"] != audits["normalized_final_no_rerank"]["candidate_chunk_ids"]:
                raise ValueError(f"F0/F1 candidate chunk pools differ: {qid}")
            core.write_json(args.output_dir / "progress.json", {"completed": {g: len(r) for g, r in completed.items()},
                            "expected": 58, "elapsed_seconds": round(time.monotonic() - started, 1)})
            print(f"F0/F1 {qid} completed", flush=True)
        for group in GROUPS:
            results = [completed[group][str(q["query_id"])] for q in queries]
            metadata = {"protocol_version": protocol["protocol_version"], "system": group,
                        "top_k": 20, "query_count_expected": 58, "query_count_completed": len(results), "failure_count": 0}
            core.write_json(args.output_dir / group / "candidate_evidence.json", {"metadata": metadata,
                            "candidate_evidence": [c for r in results for c in r["candidates"]]})
            core.write_json(args.output_dir / group / "retrieval_results.json", {"metadata": metadata, "results": results, "errors": []})
        core.write_json(args.output_dir / "run_summary.json", {"complete": True, "groups": {g: len(r) for g, r in completed.items()},
                        "shared_qrels_evaluation_pending": True})
    finally:
        for client in pool.entries:
            client.close()


if __name__ == "__main__":
    main()
