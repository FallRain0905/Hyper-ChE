"""Advance accepted final cache through frozen retrieval, qrels and QA stages."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from hyperche.normalization import posthoc_cache as core


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-root", type=Path, required=True)
    parser.add_argument("--wait-for-cache", action="store_true")
    args = parser.parse_args()
    cache_root = args.cache_root.resolve()
    target = cache_root / "hyper_final_posthoc_v1"
    state_path = cache_root / "hyper_final_experiment_v1_state.json"
    output = ROOT / "outputs" / "final_experiment_v1_old_embedding"
    output.mkdir(parents=True, exist_ok=True)
    state = core._load_json_dict(state_path) or {"version": "final-experiment-v1", "stages": {}}
    state["pid"] = os.getpid()
    state["reporting_pending"] = True
    stage = "wait_cache"

    def mark(name, status, details=None):
        state["stages"][name] = {"status": status, "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "details": details or {}}
        core.write_json(state_path, state)
        print(f"stage={name} status={status}", flush=True)

    def run(name, argv, env=None):
        nonlocal stage
        stage = name
        if state["stages"].get(name, {}).get("status") == "completed":
            return
        mark(name, "running")
        with (output / f"{name}.log").open("a", encoding="utf-8") as log:
            result = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "scripts" / argv[0]), *map(str, argv[1:])],
                                    cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
        if result.returncode != 0:
            raise RuntimeError(f"stage {name} failed with exit code {result.returncode}; see {output / (name + '.log')}")
        mark(name, "completed")

    def endpoints(file):
        rows = [line.strip().split("|", 1) for line in (cache_root / file).read_text(encoding="utf-8-sig").splitlines() if "|" in line]
        if len(rows) != 5 or len({url for url, _ in rows}) != 1:
            raise ValueError(f"expected five endpoints with a single provider: {file}")
        return rows[0][0], ";".join(key for _, key in rows)

    with core.TargetCacheLock(cache_root / "hyper_final_experiment_v1"):
        try:
            mark("wait_cache", "running")
            started = time.monotonic()
            while not target.exists():
                work_state = core._load_json_dict(target.with_name(target.name + ".work") / "normalization_state.json")
                if any(s.get("status") == "failed" for s in work_state.get("stages", {}).values()):
                    raise RuntimeError("cache builder failed; inspect final_build.log before continuing")
                if not args.wait_for_cache or time.monotonic() - started > 1800:
                    raise RuntimeError("accepted final cache not available yet")
                time.sleep(5)
            validation = core._load_json_dict(target / "final_validation.json")
            if not validation.get("validation_passed"):
                raise ValueError("final cache validation did not pass")
            mark("wait_cache", "completed", validation)
            queries = ROOT / "outputs/retrieval_benchmark/query_benchmark_curated_v2/retrieval_queries.json"
            retrieval = output / "retrieval"
            run("retrieval", ["run_final_retrieval.py", "--cache", target, "--queries", queries,
                              "--embedding-endpoints-file", cache_root / "siliconflow_endpoints.active.accdb", "--output-dir", retrieval])
            baseline = ROOT / "outputs/retrieval_benchmark/retrieval_formal_v5_chunk_rerank_full58_20260910"
            seed = ROOT / "outputs/retrieval_benchmark/retrieval_formal_v5_chunk_rerank_shared_qrels_qwen35_delta_20260910/shared_qrels.json"
            baseline_protocol = core._load_json_dict(baseline / "run_protocol.json")
            if str(baseline_protocol.get("query_sha256") or "").lower() != core.file_sha256(queries):
                raise ValueError("baseline retrieval query protocol differs")
            systems = ["original_hypergraph", "chem_prompt_graph", "chem_prompt_hypergraph", "hybrid_rag_baseline", "chem_prompt_hypergraph_chunk_rerank"]
            argv = ["build_shared_retrieval_pool.py", "--output-dir", output / "shared_pool", "--top-k", 20, "--seed-qrels", seed]
            for group in systems:
                argv += ["--system", f"{group}={baseline / group / 'candidate_evidence.json'}"]
            for group in ("normalized_final_no_rerank", "normalized_final"):
                argv += ["--system", f"{group}={retrieval / group / 'candidate_evidence.json'}"]
            run("pool", argv)
            url, keys = endpoints("siliconflow_endpoints.active.accdb")
            env = {**os.environ, "SILICONFLOW_API_KEY": keys, "SILICONFLOW_BASE_URL": url,
                   "EMB_API_KEY": keys, "EMB_BASE_URL": url, "EMB_MODEL": "Qwen/Qwen3-Embedding-4B", "EMB_DIM": "2560"}
            run("qrels", ["label_shared_retrieval_qrels_llm.py", "--queries", queries,
                          "--candidate-union", output / "shared_pool/candidate_union.json",
                          "--qrels-template", output / "shared_pool/shared_qrels_template.json",
                          "--output-dir", output / "shared_qrels", "--provider", "siliconflow_env",
                          "--model", "Qwen/Qwen3.5-35B-A3B", "--base-url", url, "--timeout", 120,
                          "--concurrency", 2, "--request-min-interval", 6, "--max-retries", 3, "--disable-thinking"], env)
            if core._load_json_dict(output / "shared_qrels/shared_qrels_protocol.json").get("unjudged_pairs"):
                raise RuntimeError("shared qrels are incomplete; do not compute final conclusions")
            run("retrieval_metrics", ["evaluate_shared_retrieval_qrels.py", "--candidate-union", output / "shared_pool/candidate_union.json",
                                      "--qrels", output / "shared_qrels/shared_qrels.json", "--queries", queries,
                                      "--output-dir", output / "retrieval_metrics", "--k", 5])
            llm_url, llm_keys = endpoints("llm_endpoints.active.accdb")
            env.update(LLM_API_KEY=llm_keys, LLM_BASE_URL=llm_url, LLM_MODEL="kimi-k2.6")
            state["qa_provider_limitation"] = "Historical four-group QA used Moonshot; final QA uses Aliyun with the same kimi-k2.6 model name. Provider difference is disclosed; do not claim a fully controlled model-serving comparison."
            run("qa", ["run_qa_formal_llm.py", "--groups", "normalized_final", "--question-file", ROOT / "outputs/qa_eval/real_flow_60_qa_gold_v1/qa_questions.json",
                       "--cache-root", cache_root, "--output-dir", output / "qa", "--output-prefix", "qa_final",
                       "--provider", "custom_env", "--model", "kimi-k2.6", "--base-url", llm_url,
                       "--top-k", 5, "--evidence-budget-chars", 1500, "--evidence-format", "legacy", "--temperature", 1.0,
                       "--top-p", .95, "--seed", 20260811, "--parallel-workers", 3, "--llm-timeout", 120,
                       "--embedding-timeout", 120, "--llm-max-retries", 2, "--run-id", "qa-final-old-embedding-v1"], env)
            mark("main_evaluation", "completed", {"reporting_pending": True, "qrels_final_audit_pending": True,
                 "next": "Source-level Hit@5, Composite Fact Recall, QA baseline comparison and attribution report"})
        except BaseException as exc:
            mark(stage, "failed", {"error_type": type(exc).__name__, "message": str(exc)})
            raise


if __name__ == "__main__":
    main()
