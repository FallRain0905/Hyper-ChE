"""Incrementally LLM-label unjudged pairs in a pooled retrieval qrels template.

Existing seeded judgments are preserved verbatim.  Only rows whose
``relevance_grade`` is null are sent to the judge.  Progress is appended to a
JSONL audit file so interrupted runs can resume without repeating completed
API calls.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import sys
import threading
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.run_qa_formal_llm import FormalLLMClientPool


LABELS = {0: "IRRELEVANT", 1: "BACKGROUND", 2: "STRONG_SUPPORT", 3: "DIRECT"}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def rows(value: Any, keys: tuple[str, ...]) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        for key in keys:
            candidate = value.get(key)
            if isinstance(candidate, list):
                return [item for item in candidate if isinstance(item, dict)]
    return []


def required_elements_text(query: dict[str, Any]) -> str:
    required = query.get("required_elements") or {}
    if not isinstance(required, dict):
        return str(required)
    parts = []
    for key, values in required.items():
        if isinstance(values, list) and values:
            parts.append(f"{key}: {', '.join(map(str, values))}")
    return "\n".join(parts) or "(none specified)"


def judge_prompt(query: dict[str, Any], candidate: dict[str, Any]) -> str:
    return f"""You are judging chunk-level retrieval relevance for a chemical-engineering benchmark.

Judge whether the candidate chunk supports the information need in the question. Do not use document IDs, retrieval rank, or the fact that a system retrieved the chunk as evidence. Judge only the semantic content shown below.

Grade schema:
3 DIRECT: the chunk alone directly answers the question or states the decisive requested fact(s).
2 STRONG_SUPPORT: the chunk provides a substantial, necessary part of the answer, but another chunk is needed for full completion.
1 BACKGROUND: the chunk supplies a concrete requested subfact, entity property, condition, mechanism, or comparison context that is genuinely useful, but does not support the requested claim strongly enough for grade 2.
0 IRRELEVANT: unrelated, merely bibliographic, too generic to help, or contradictory without useful support. Sharing only the broad domain (for example, discussing flow batteries in general) is grade 0 when none of the requested entities or specific subfacts is present.

For multi-condition or multi-metric questions, do not award grade 3 unless the relevant entities, conditions, measurements, and their binding are actually present. A chunk can still receive grade 2 when it strongly supports one necessary part of an adjacent-chunk or cross-section answer.

Question:
{query.get('question', '')}

Gold claim used only to define the information need:
{query.get('gold_claim', '')}

Reference answer used only to define the information need:
{query.get('reference_answer', '')}

Required elements:
{required_elements_text(query)}

Candidate chunk ID: {candidate.get('chunk_id', '')}
Candidate chunk text:
---
{candidate.get('content', '')}
---

Return one JSON object only:
{{
  "query_id": "{query.get('query_id', '')}",
  "chunk_id": "{candidate.get('chunk_id', '')}",
  "relevance_grade": 0,
  "supported_elements": [],
  "conflicts": [],
  "rationale": "brief evidence-based explanation"
}}
"""


def validate_judgment(
    result: dict[str, Any],
    *,
    query_id: str,
    chunk_id: str,
) -> dict[str, Any]:
    returned_query_id = str(result.get("query_id") or "")
    returned_chunk_id = str(result.get("chunk_id") or "")
    identifier_corrections = []
    if returned_query_id != query_id:
        identifier_corrections.append({
            "field": "query_id",
            "model_value": returned_query_id,
            "task_value": query_id,
        })
    if returned_chunk_id != chunk_id:
        identifier_corrections.append({
            "field": "chunk_id",
            "model_value": returned_chunk_id,
            "task_value": chunk_id,
        })
    try:
        grade = int(result.get("relevance_grade"))
    except (TypeError, ValueError) as exc:
        raise ValueError("relevance_grade must be an integer") from exc
    if grade not in LABELS:
        raise ValueError(f"relevance_grade must be 0-3, got {grade}")
    rationale = str(result.get("rationale") or "").strip()
    if not rationale:
        raise ValueError("rationale is required")
    return {
        "query_id": query_id,
        "chunk_id": chunk_id,
        "relevance_grade": grade,
        "relevance_label": LABELS[grade],
        "rationale": rationale,
        "supported_elements": [str(item) for item in (result.get("supported_elements") or [])],
        "conflicts": [str(item) for item in (result.get("conflicts") or [])],
        "annotation_status": "llm_judged_pending_final_audit",
        "annotation_method": "incremental_shared_qrels_llm_v1",
        "model_identifier_corrections": identifier_corrections,
    }


def load_completed(path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    completed: dict[tuple[str, str], dict[str, Any]] = {}
    if not path.exists():
        return completed
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if item.get("status") == "success" and isinstance(item.get("judgment"), dict):
            judgment = item["judgment"]
            key = (str(judgment.get("query_id")), str(judgment.get("chunk_id")))
            completed[key] = judgment
    return completed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queries", required=True, type=Path)
    parser.add_argument("--candidate-union", required=True, type=Path)
    parser.add_argument("--qrels-template", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--settings", type=Path, default=Path("web-ui/backend/settings.json"))
    parser.add_argument("--provider", default="siliconflow")
    parser.add_argument("--model", default="Qwen/Qwen3.5-35B-A3B")
    parser.add_argument("--base-url", default=os.getenv("SILICONFLOW_BASE_URL") or "https://api.siliconflow.cn/v1")
    parser.add_argument("--timeout", type=float, default=3600.0)
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--max-retries", type=int, default=5)
    parser.add_argument("--max-tokens", type=int, default=1200)
    parser.add_argument("--request-min-interval", type=float, default=0,
                        help="Minimum seconds between requests across the whole key pool; 429 triggers a shared 60-second cooldown.")
    parser.add_argument(
        "--disable-thinking",
        action="store_true",
        help="Use the same Qwen model in non-thinking mode for low-latency relevance classification.",
    )
    parser.add_argument(
        "--thinking-budget",
        type=int,
        default=0,
        help="Optional bounded thinking budget; ignored when --disable-thinking is set.",
    )
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    if args.concurrency <= 0 or args.timeout <= 0 or args.max_retries <= 0:
        parser.error("--concurrency, --timeout and --max-retries must be positive")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    partial_path = args.output_dir / "shared_qrels_audit.jsonl"
    errors_path = args.output_dir / "shared_qrels_errors.json"
    output_path = args.output_dir / "shared_qrels.json"

    query_items = rows(load_json(args.queries), ("queries",))
    candidate_items = rows(load_json(args.candidate_union), ("candidate_union", "candidates"))
    template_obj = load_json(args.qrels_template)
    qrel_items = rows(template_obj, ("qrels", "retrieval_qrels"))
    query_map = {str(item["query_id"]): item for item in query_items}
    candidate_map = {
        (str(item["query_id"]), str(item["chunk_id"])): item
        for item in candidate_items
    }
    completed = load_completed(partial_path)

    pending = [
        item
        for item in qrel_items
        if item.get("relevance_grade") is None
        and (str(item.get("query_id")), str(item.get("chunk_id"))) not in completed
    ]
    if args.limit is not None:
        pending = pending[: args.limit]

    llm = FormalLLMClientPool(
        args.settings,
        args.provider,
        model_override=args.model,
        base_url_override=args.base_url,
        timeout=args.timeout,
    )
    write_lock = threading.Lock()
    errors: list[dict[str, Any]] = []
    completed_now = 0
    pacing_lock = threading.Lock()
    next_request = 0.0
    cooldown_until = 0.0

    def pace_request() -> None:
        nonlocal next_request
        while True:
            with pacing_lock:
                now = time.monotonic()
                delay = max(next_request, cooldown_until) - now
                if delay <= 0:
                    next_request = now + args.request_min_interval
                    return
            time.sleep(min(delay, 5.0))

    def judge(row: dict[str, Any]) -> dict[str, Any]:
        nonlocal cooldown_until
        qid = str(row.get("query_id"))
        cid = str(row.get("chunk_id"))
        query = query_map.get(qid)
        candidate = candidate_map.get((qid, cid))
        if query is None or candidate is None:
            raise KeyError(f"missing query or candidate for {(qid, cid)!r}")
        prompt = judge_prompt(query, candidate)
        extra_body = ({"enable_thinking": False} if args.disable_thinking
                      else {"enable_thinking": True, "thinking_budget": args.thinking_budget}
                      if args.thinking_budget > 0 else None)
        attempts = args.max_retries if args.request_min_interval > 0 else 1
        for attempt in range(attempts):
            if args.request_min_interval > 0:
                pace_request()
            try:
                result = llm.complete_json(prompt, max_tokens=args.max_tokens,
                                          max_retries=1 if args.request_min_interval > 0 else args.max_retries,
                                          extra_body=extra_body)
                break
            except RuntimeError as exc:
                if args.request_min_interval <= 0 or "429" not in str(exc):
                    raise
                with pacing_lock:
                    cooldown_until = max(cooldown_until, time.monotonic() + 60)
                if attempt + 1 == attempts:
                    raise
        return validate_judgment(result, query_id=qid, chunk_id=cid)

    with partial_path.open("a", encoding="utf-8") as audit_handle:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as executor:
            futures = {executor.submit(judge, row): row for row in pending}
            for future in concurrent.futures.as_completed(futures):
                row = futures[future]
                key = (str(row.get("query_id")), str(row.get("chunk_id")))
                try:
                    judgment = future.result()
                    record = {
                        "status": "success",
                        "created_at": datetime.now(timezone.utc).isoformat(),
                        "judgment": judgment,
                    }
                    with write_lock:
                        completed[key] = judgment
                        completed_now += 1
                except Exception as exc:  # noqa: BLE001
                    error = {
                        "status": "error",
                        "created_at": datetime.now(timezone.utc).isoformat(),
                        "query_id": key[0],
                        "chunk_id": key[1],
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                    record = error
                    with write_lock:
                        errors.append(error)
                with write_lock:
                    audit_handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                    audit_handle.flush()
                    done = completed_now + len(errors)
                    if done % 20 == 0 or done == len(pending):
                        print(
                            f"[SharedQrelsLLM] processed={done}/{len(pending)} "
                            f"success={completed_now} errors={len(errors)}",
                            flush=True,
                        )

    merged: list[dict[str, Any]] = []
    unresolved = 0
    for row in qrel_items:
        key = (str(row.get("query_id")), str(row.get("chunk_id")))
        if row.get("relevance_grade") is not None:
            merged.append(row)
        elif key in completed:
            merged.append(completed[key])
        else:
            merged.append(row)
            unresolved += 1

    grade_counts = Counter(
        int(item["relevance_grade"])
        for item in merged
        if item.get("relevance_grade") is not None
    )
    previous_metadata = dict(template_obj.get("metadata") or {})
    current_attempt = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "provider": args.provider,
        "model": args.model,
        "base_url": args.base_url,
        "key_pool_size": len(llm.entries),
        "requested_pairs": len(pending),
        "successful_pairs": completed_now,
        "failed_pairs": len(errors),
    }
    metadata = {
        **previous_metadata,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "complete_shared_qrels" if unresolved == 0 else "incomplete_shared_qrels",
        "gold_status": "llm_judged_pending_final_audit",
        "prompt_version": "shared-retrieval-qrels-v1-delta-strict-background",
        "seed_prompt_version": "shared-retrieval-qrels-v1",
        # A failed retry must not replace the provenance of judgments that
        # were produced by an earlier successful model run.
        "model": args.model if completed_now else previous_metadata.get("model", args.model),
        "base_url": args.base_url if completed_now else previous_metadata.get("base_url", args.base_url),
        "timeout_ms": int(args.timeout * 1000),
        "concurrency": args.concurrency,
        "request_min_interval_seconds": args.request_min_interval,
        "batch_size": 1,
        "key_pool_size": len(llm.entries) if completed_now else previous_metadata.get("key_pool_size", len(llm.entries)),
        "enable_thinking": not args.disable_thinking,
        "thinking_budget": args.thinking_budget if args.thinking_budget > 0 and not args.disable_thinking else None,
        "qrel_key": ["query_id", "chunk_id"],
        "grade_schema": {str(key): value for key, value in LABELS.items()},
        "pooled_pairs": len(merged),
        "judged_pairs": len(merged) - unresolved,
        "unjudged_pairs": unresolved,
        "grade_distribution": {str(key): grade_counts.get(key, 0) for key in LABELS},
        "seeded_judgments_preserved": sum(item.get("relevance_grade") is not None for item in qrel_items),
        "incremental_llm_judgments": len(completed),
        "run_scope": "limited_smoke" if args.limit is not None else "full_pool",
        "last_llm_attempt": current_attempt,
    }
    write_json(output_path, {"metadata": metadata, "qrels": merged})
    write_json(errors_path, errors)
    write_json(args.output_dir / "shared_qrels_protocol.json", metadata)
    print(json.dumps(metadata, ensure_ascii=False, indent=2), flush=True)
    if errors or (unresolved and args.limit is None):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
