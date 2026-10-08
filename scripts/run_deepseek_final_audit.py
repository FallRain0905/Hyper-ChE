"""Run a resumable DeepSeek audit of final retrieval qrels and atomic facts.

The provider output is kept separate from the frozen evaluation files.  It is
an LLM audit until a human accepts the spot-check; this script never silently
labels provider output as human gold.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import threading
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI


LABELS = {0: "IRRELEVANT", 1: "BACKGROUND", 2: "STRONG_SUPPORT", 3: "DIRECT"}
TRANSIENT_STATUS = {408, 409, 429, 500, 502, 503, 504}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def rows(value: Any, names: tuple[str, ...]) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        for name in names:
            item = value.get(name)
            if isinstance(item, list):
                return [row for row in item if isinstance(row, dict)]
    raise ValueError(f"missing rows under {names}")


def parse_json_text(text: str) -> dict[str, Any]:
    value = str(text or "").strip()
    value = re.sub(r"^```(?:json)?\s*", "", value, flags=re.I)
    value = re.sub(r"\s*```$", "", value)
    try:
        result = json.loads(value)
    except json.JSONDecodeError:
        start = value.find("{")
        end = value.rfind("}")
        if start < 0 or end <= start:
            raise
        result = json.loads(value[start : end + 1])
    if not isinstance(result, dict):
        raise ValueError("model output must be a JSON object")
    return result


def endpoint_rows(path: Path) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if "|" not in line:
            continue
        base_url, key = line.split("|", 1)
        base_url = base_url.strip().rstrip("/")
        key = key.strip()
        if not key:
            continue
        if "nikoapi.xyz" in base_url:
            label = "niko"
        elif "18m.wtf" in base_url:
            label = "18m"
        elif "treeapi.online" in base_url:
            label = "treeapi"
        else:
            continue
        output.append({"label": label, "base_url": base_url, "api_key": key})
    if len(output) != 30:
        raise ValueError(f"expected 30 18m/Niko/treeapi endpoints, found {len(output)}")
    return output


class DeepSeekPool:
    def __init__(self, entries: list[dict[str, str]], *, model: str, timeout: float, min_interval: float, max_retries: int):
        self.entries = entries
        self.model = model
        self.timeout = timeout
        self.min_interval = max(0.0, min_interval)
        self.max_retries = max(1, max_retries)
        self.index = 0
        self.lock = threading.Lock()
        self.pace_lock = threading.Lock()
        self.last_request = 0.0
        self.cooldown_until = 0.0

    def next_entry(self) -> dict[str, str]:
        with self.lock:
            entry = self.entries[self.index % len(self.entries)]
            self.index += 1
            return entry

    def pace(self) -> None:
        with self.pace_lock:
            now = time.monotonic()
            wait_until = max(self.last_request + self.min_interval, self.cooldown_until)
            if wait_until > now:
                time.sleep(wait_until - now)
            self.last_request = time.monotonic()

    @staticmethod
    def transient(exc: Exception) -> bool:
        if isinstance(exc, (APIConnectionError, APITimeoutError, TimeoutError, ConnectionError)):
            return True
        if isinstance(exc, APIStatusError):
            return int(getattr(exc, "status_code", 0) or 0) in TRANSIENT_STATUS
        message = str(exc).lower()
        return any(token in message for token in ("timeout", "timed out", "connection reset", "429", "rate limit", "temporarily unavailable"))

    def complete_json(self, prompt: str, *, max_tokens: int) -> tuple[dict[str, Any], dict[str, Any]]:
        errors: list[str] = []
        json_retry_used = False
        use_response_format = True
        for attempt in range(self.max_retries + 1):
            entry = self.next_entry()
            self.pace()
            client = OpenAI(api_key=entry["api_key"], base_url=entry["base_url"], timeout=self.timeout, max_retries=0)
            current_tokens = max_tokens * 2 if json_retry_used else max_tokens
            kwargs: dict[str, Any] = {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
                "top_p": 1,
                "max_tokens": current_tokens,
                "timeout": self.timeout,
            }
            if use_response_format:
                kwargs["response_format"] = {"type": "json_object"}
            try:
                response = client.chat.completions.create(**kwargs)
                content = str(getattr(getattr((getattr(response, "choices", None) or [None])[0], "message", None), "content", None) or "")
                try:
                    return parse_json_text(content), {"endpoint": entry["label"], "attempt": attempt + 1, "max_tokens": current_tokens}
                except Exception as exc:
                    if json_retry_used:
                        raise
                    json_retry_used = True
                    use_response_format = False
                    errors.append(f"json_parse:{type(exc).__name__}")
                    continue
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{type(exc).__name__}:{str(exc)[:240]}")
                if use_response_format and "response_format" in str(exc).lower():
                    use_response_format = False
                    continue
                if not self.transient(exc) or attempt >= self.max_retries:
                    raise RuntimeError("DeepSeek request failed: " + " || ".join(errors)) from exc
                if isinstance(exc, APIStatusError) and int(getattr(exc, "status_code", 0) or 0) == 429:
                    with self.pace_lock:
                        self.cooldown_until = max(self.cooldown_until, time.monotonic() + 30.0)
                time.sleep(min(2.0 ** attempt, 20.0))
        raise RuntimeError("DeepSeek request failed: " + " || ".join(errors))


def append_record(path: Path, record: dict[str, Any], lock: threading.Lock) -> None:
    with lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def completed_keys(path: Path, key_fields: tuple[str, ...]) -> set[tuple[str, ...]]:
    done: set[tuple[str, ...]] = set()
    if not path.exists():
        return done
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if item.get("status") != "success":
            continue
        payload = item.get("result") or {}
        key = tuple(str(payload.get(field) or "") for field in key_fields)
        if all(key):
            done.add(key)
    return done


def qrel_prompt(query: dict[str, Any], candidate: dict[str, Any], current: Any) -> str:
    return f"""You are an independent audit reviewer for a chemical-engineering retrieval benchmark.
Judge the candidate only from the question and candidate text. The current grade is advisory and must not anchor your decision.

Grade: 3 DIRECT (chunk alone directly answers the information need); 2 STRONG_SUPPORT (substantial necessary part); 1 BACKGROUND (useful concrete subfact but insufficient); 0 IRRELEVANT.
For multi-metric or multi-condition questions, check entity/metric/value/condition binding. Do not give 3 merely because a few keywords occur.

Question: {query.get('question','')}
Gold claim: {query.get('gold_claim','')}
Reference answer: {query.get('reference_answer','')}
Required elements: {json.dumps(query.get('required_elements') or {{}}, ensure_ascii=False)}
Candidate chunk ID: {candidate.get('chunk_id','')}
Candidate text:
---
{candidate.get('content','')}
---
Current advisory grade: {current}

Return JSON only:
{{"query_id":"{query.get('query_id','')}","chunk_id":"{candidate.get('chunk_id','')}","audited_grade":0,"supported_elements":[],"conflicts":[],"rationale":"evidence-based reason","confidence":"high|medium|low","needs_human_attention":false}}"""


def atomic_gold_prompt(query: dict[str, Any]) -> str:
    spans = query.get("original_evidence_spans") or query.get("evidence_spans") or []
    return f"""Create an auditable atomic-fact gold record for this frozen retrieval query.
Use only the reference answer, gold claim, and evidence excerpts. Do not invent a value or condition. For an unretrievable query, return an empty atomic_facts list.
Each atomic fact must preserve entity/metric/value/unit/condition/relation binding. Split comparison facts when the value or direction differs.

Query ID: {query.get('query_id','')}
Retrievable: {bool(query.get('retrievable'))}
Question: {query.get('question','')}
Gold claim: {query.get('gold_claim','')}
Reference answer: {query.get('reference_answer','')}
Required elements: {json.dumps(query.get('required_elements') or {{}}, ensure_ascii=False)}
Evidence excerpts: {json.dumps(spans, ensure_ascii=False)}

Return JSON only:
{{"query_id":"{query.get('query_id','')}","atomic_facts":[{{"fact_id":"{query.get('query_id','')}|fact:1","claim":"","entity":"","metric":"","value":"","unit":"","condition":"","relation":"","supporting_chunk_ids":[],"support_span":"","confidence":"high|medium|low"}}],"needs_human_attention":false,"rationale":""}}"""


def support_prompt(query: dict[str, Any], facts: list[dict[str, Any]], system: str, candidates: list[dict[str, Any]]) -> str:
    evidence = [{"rank": i + 1, "chunk_id": c.get("chunk_id"), "content": c.get("content", "")} for i, c in enumerate(candidates)]
    return f"""Audit support for reviewed atomic facts in one retrieval system.
A fact is supported only when the retrieved evidence entails the complete binding. Use partial when some components are present but the value/unit/condition/relation binding is incomplete. Use binding_error when the evidence attaches a value to the wrong entity or condition. Use unsupported when absent.

Query ID: {query.get('query_id','')}
System: {system}
Question: {query.get('question','')}
Atomic facts: {json.dumps(facts, ensure_ascii=False)}
Top-5 retrieved evidence: {json.dumps(evidence, ensure_ascii=False)}

Return JSON only:
{{"query_id":"{query.get('query_id','')}","system":"{system}","fact_support":[{{"fact_id":"","status":"supported|partial|binding_error|unsupported","evidence_chunk_ids":[],"rationale":""}}],"needs_human_attention":false}}"""


def run_phase(name: str, tasks: list[tuple[tuple[str, ...], str, dict[str, Any]]], path: Path, pool: DeepSeekPool, max_tokens: int, key_fields: tuple[str, ...], concurrency: int) -> dict[str, int]:
    done = completed_keys(path, key_fields)
    pending = [task for task in tasks if task[0] not in done]
    lock = threading.Lock()
    counts = Counter(done=0, success=0, errors=0)
    counts["done"] = len(done)
    def work(task: tuple[tuple[str, ...], str, dict[str, Any]]) -> dict[str, Any]:
        key, prompt, meta = task
        try:
            result, request = pool.complete_json(prompt, max_tokens=max_tokens)
            result.setdefault("_audit_key", list(key))
            return {"status": "success", "created_at": datetime.now(timezone.utc).isoformat(), "phase": name, "request": request, "result": result, "meta": meta}
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "created_at": datetime.now(timezone.utc).isoformat(), "phase": name, "error": f"{type(exc).__name__}: {exc}", "meta": meta}
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = {executor.submit(work, task): task for task in pending}
        for future in concurrent.futures.as_completed(futures):
            record = future.result()
            append_record(path, record, lock)
            counts[record["status"]] += 1
            if (counts["success"] + counts["errors"]) % 20 == 0 or counts["success"] + counts["errors"] == len(pending):
                print(f"[{name}] processed={counts['success'] + counts['errors']}/{len(pending)} success={counts['success']} errors={counts['errors']}", flush=True)
    return dict(counts)


def read_success(path: Path) -> list[dict[str, Any]]:
    output = []
    if not path.exists():
        return output
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if item.get("status") == "success":
            output.append(item)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--endpoint-file", type=Path, required=True)
    parser.add_argument("--phase", choices=("probe", "qrels", "atomic", "support", "all"), default="all")
    parser.add_argument("--model", default="deepseek-v4.1-flash")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--request-min-interval", type=float, default=0.05)
    args = parser.parse_args()
    repo = args.repo.resolve()
    output = args.output.resolve()
    entries = endpoint_rows(args.endpoint_file.resolve())
    pool = DeepSeekPool(entries, model=args.model, timeout=args.timeout, min_interval=args.request_min_interval, max_retries=args.max_retries)
    output.mkdir(parents=True, exist_ok=True)
    if args.phase == "probe":
        tasks = [(tuple([str(i)]), 'Return JSON only: {"ok":true}', {"endpoint_index": i}) for i in range(len(entries))]
        # Probe tasks use a fresh one-entry rotation so every configured key is tested exactly once.
        probe_path = output / "endpoint_probe.jsonl"
        lock = threading.Lock()
        def probe(task):
            index = int(task[2]["endpoint_index"])
            entry = entries[index]
            client = OpenAI(api_key=entry["api_key"], base_url=entry["base_url"], timeout=args.timeout, max_retries=0)
            try:
                response = client.chat.completions.create(model=args.model, messages=[{"role":"user","content":'Return JSON only: {"ok":true}'}], temperature=0, max_tokens=128, timeout=args.timeout)
                content = str(getattr(getattr((getattr(response, "choices", None) or [None])[0], "message", None), "content", None) or "")
                parse_json_text(content)
                return {"status":"success","endpoint":entry["label"],"base_url":entry["base_url"],"endpoint_index":index}
            except Exception as exc:  # noqa: BLE001
                return {"status":"error","endpoint":entry["label"],"base_url":entry["base_url"],"endpoint_index":index,"error":f"{type(exc).__name__}: {str(exc)[:240]}"}
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as executor:
            futures=[executor.submit(probe,t) for t in tasks]
            for future in concurrent.futures.as_completed(futures):
                append_record(probe_path,future.result(),lock)
        success=sum(1 for line in probe_path.read_text(encoding="utf-8-sig").splitlines() if line.strip() and json.loads(line).get("status") == "success") if probe_path.exists() else 0
        print(json.dumps({"endpoint_count":len(entries),"probe_success":success,"probe_errors":len(entries)-success,"output":str(probe_path)},ensure_ascii=False,indent=2))
        return

    query_rows = rows(load_json(repo / "outputs/retrieval_benchmark/query_benchmark_curated_v2/retrieval_queries.json"), ("queries", "retrieval_queries"))
    query_map = {str(row["query_id"]): row for row in query_rows}
    union_rows = rows(load_json(repo / "outputs/final_experiment_v1_old_embedding/shared_pool/candidate_union.json"), ("candidate_union",))
    union_map = {(str(row["query_id"]), str(row["chunk_id"])): row for row in union_rows}
    qrels_rows = rows(load_json(repo / "outputs/final_experiment_v1_old_embedding/shared_qrels/shared_qrels.json"), ("qrels",))
    ranked_path = repo / "outputs/final_experiment_v1_old_embedding/retrieval_metrics/shared_retrieval_ranked_topk.csv"
    import csv
    with ranked_path.open("r", encoding="utf-8-sig", newline="") as handle:
        ranked_rows = list(csv.DictReader(handle))
    systems = sorted({str(row.get("system")) for row in ranked_rows})
    top5: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in ranked_rows:
        if int(row.get("rank") or 0) <= 5:
            top5.setdefault((str(row.get("system")), str(row.get("query_id"))), []).append(union_map[(str(row["query_id"]), str(row["chunk_id"]))])

    if args.phase in ("qrels", "all"):
        tasks=[]
        qpath=output/"qrels_review.jsonl"
        for row in qrels_rows:
            qid,cid=str(row["query_id"]),str(row["chunk_id"])
            tasks.append(((qid,cid),qrel_prompt(query_map[qid],union_map[(qid,cid)],row.get("relevance_grade")),{"query_id":qid,"chunk_id":cid,"current_grade":row.get("relevance_grade")}))
        run_phase("qrels",tasks,qpath,pool,900,("query_id","chunk_id"),args.concurrency)

    if args.phase in ("atomic", "all"):
        tasks=[((str(q["query_id"]),),atomic_gold_prompt(q),{"query_id":str(q["query_id"])}) for q in query_rows]
        # Atomic fact records can contain several fully bound facts and evidence
        # spans; keep enough headroom to avoid truncating otherwise valid JSON.
        run_phase("atomic",tasks,output/"atomic_gold.jsonl",pool,4096,("query_id",),args.concurrency)

    atomic_success=read_success(output/"atomic_gold.jsonl")
    atomic_by_query={str(item["result"].get("query_id")):item["result"] for item in atomic_success}
    if args.phase in ("support", "all"):
        tasks=[]
        for qid,q in query_map.items():
            facts=atomic_by_query.get(qid,{}).get("atomic_facts") or []
            for system in systems:
                key=(qid,system)
                tasks.append((key,support_prompt(q,facts,system,top5.get((system,qid),[])),{"query_id":qid,"system":system}))
        run_phase("support",tasks,output/"support_review.jsonl",pool,1800,("query_id","system"),args.concurrency)

    summary={"version":"deepseek-final-audit-v1","created_at":datetime.now(timezone.utc).isoformat(),"model":args.model,"endpoint_count":len(entries),"endpoint_labels":dict(Counter(entry["label"] for entry in entries)),"concurrency":args.concurrency,"status":"llm_audit_pending_user_spot_check"}
    qsuccess=read_success(output/"qrels_review.jsonl")
    if qsuccess:
        disagreements=sum(1 for item in qsuccess if int(item["meta"].get("current_grade")) != int(item["result"].get("audited_grade")))
        summary["qrels_review"]={"completed":len(qsuccess),"expected":len(qrels_rows),"disagreements":disagreements,"agreement_rate":round((len(qsuccess)-disagreements)/len(qsuccess),6)}
    asuccess=read_success(output/"atomic_gold.jsonl")
    summary["atomic_gold"]={"completed":len(asuccess),"expected":len(query_rows),"facts":sum(len(item["result"].get("atomic_facts") or []) for item in asuccess)}
    ssuccess=read_success(output/"support_review.jsonl")
    summary["support_review"]={"completed":len(ssuccess),"expected":len(query_rows)*len(systems)}
    write_json(output/"deepseek_audit_summary.json",summary)
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__ == "__main__":
    main()
