"""Rejudge QA hallucination with retrieved evidence blocks.

This script does not regenerate answers. It reads existing QA records and asks an
LLM judge to evaluate whether each generated answer is grounded in its evidence.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.run_qa_smoke_llm import LLMClientPool  # noqa: E402


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def evidence_context_from_record(record: dict[str, Any], max_chars: int = 12000) -> str:
    blocks = []
    for evidence in record.get("evidence") or []:
        block = evidence.get("formatted_evidence_block") or evidence.get("readable_evidence") or ""
        if block:
            blocks.append(block)
    text = "\n\n".join(blocks)
    return text[:max_chars]


def strict_hallucination_prompt(record: dict[str, Any]) -> str:
    evidence_context = evidence_context_from_record(record)
    payload = {
        "question_id": record.get("question_id"),
        "group": record.get("group"),
        "question": record.get("question"),
        "answerable": record.get("answerable"),
        "reference_answer": record.get("reference_answer"),
        "required_key_points": record.get("required_key_points") or [],
        "generated_answer": record.get("generated_answer") or "",
        "citations": record.get("citations") or [],
        "original_abstained": bool(record.get("abstained")),
        "retrieved_evidence_blocks": evidence_context,
    }
    return f"""You are auditing hallucination in a chemical literature QA benchmark.

Evaluate whether the generated answer is grounded in the retrieved evidence.

Important definition:
- A hallucination is any concrete claim in the generated answer that is not supported by the retrieved evidence, conflicts with the reference answer, uses the wrong material/entity/condition/metric binding, gives the wrong numeric value or unit, or overgeneralizes beyond the evidence.
- Treat the reference answer as the gold standard. If the generated answer conflicts with the reference answer, mark hallucinated=true even when a retrieved evidence block appears to support the generated answer. Retrieved evidence can be wrong, noisy, or incorrectly verbalized.
- If retrieved evidence and the reference answer conflict, trust the reference answer for hallucination judgment and mention this conflict in wrong_bindings or unsupported_claims_found.
- Do NOT count an empty answer or a cautious abstention as hallucination unless it also makes unsupported concrete claims.
- Missing information, low key-point coverage, or refusal to answer should be judged as poor coverage, not hallucination.
- For chemical QA, be strict about entity binding, condition binding, metric type, value, and unit.
- If the answer cites evidence that does not support the claim, count that as an unsupported claim.

Input:
{json.dumps(payload, ensure_ascii=False, indent=2)}

Return strict JSON only:
{{
  "hallucinated": false,
  "hallucination_severity": "none | minor | major",
  "evidence_groundedness_score": 0.0,
  "unsupported_claims_found": [],
  "wrong_bindings": [],
  "wrong_values_or_units": [],
  "overgeneralizations": [],
  "supported_claims": [],
  "answer_is_empty_or_abstention": false,
  "rationale": "..."
}}
"""


def as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def normalize_judgment(value: dict[str, Any]) -> dict[str, Any]:
    severity = str(value.get("hallucination_severity") or "none").strip().lower()
    if severity not in {"none", "minor", "major"}:
        severity = "major" if value.get("hallucinated") else "none"
    return {
        "hallucinated": bool(value.get("hallucinated")),
        "hallucination_severity": severity,
        "evidence_groundedness_score": max(0.0, min(1.0, as_float(value.get("evidence_groundedness_score"), 0.0))),
        "unsupported_claims_found": value.get("unsupported_claims_found") or [],
        "wrong_bindings": value.get("wrong_bindings") or [],
        "wrong_values_or_units": value.get("wrong_values_or_units") or [],
        "overgeneralizations": value.get("overgeneralizations") or [],
        "supported_claims": value.get("supported_claims") or [],
        "answer_is_empty_or_abstention": bool(value.get("answer_is_empty_or_abstention")),
        "rationale": str(value.get("rationale") or ""),
    }


def aggregate(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_group: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_group[row["group"]].append(row)
    out = []
    for group in sorted(by_group):
        items = by_group[group]
        n = max(1, len(items))
        out.append(
            {
                "group": group,
                "questions": len(items),
                "strict_hallucination_rate": round(sum(1 for item in items if item["hallucinated"]) / n, 4),
                "major_hallucination_rate": round(sum(1 for item in items if item["hallucination_severity"] == "major") / n, 4),
                "minor_hallucination_rate": round(sum(1 for item in items if item["hallucination_severity"] == "minor") / n, 4),
                "avg_evidence_groundedness": round(sum(as_float(item.get("evidence_groundedness_score")) for item in items) / n, 4),
                "empty_or_abstention_rate": round(sum(1 for item in items if item["answer_is_empty_or_abstention"]) / n, 4),
                "old_hallucination_rate": round(sum(1 for item in items if item.get("old_hallucinated")) / n, 4),
            }
        )
    return out


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_markdown(path: Path, summary_rows: list[dict[str, Any]], judgment_rows: list[dict[str, Any]]) -> None:
    lines = [
        "# Evidence-Grounded Hallucination Rejudge",
        "",
        "This audit rejudges existing QA answers without regenerating them.",
        "The judge reads the retrieved evidence blocks and flags unsupported claims, wrong bindings, wrong values/units, and overgeneralizations.",
        "",
        "## Summary",
        "",
        "| group | questions | strict hallucination | major | minor | avg groundedness | empty/abstention | old hallucination |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in summary_rows:
        lines.append(
            f"| {row['group']} | {row['questions']} | {row['strict_hallucination_rate']} | {row['major_hallucination_rate']} | {row['minor_hallucination_rate']} | {row['avg_evidence_groundedness']} | {row['empty_or_abstention_rate']} | {row['old_hallucination_rate']} |"
        )
    lines.extend(["", "## Hallucinated Cases", ""])
    hallucinated = [row for row in judgment_rows if row.get("hallucinated")]
    if not hallucinated:
        lines.append("No hallucinated cases were detected by the evidence-grounded judge.")
    for row in hallucinated[:80]:
        lines.extend(
            [
                f"### {row.get('question_id')} | {row.get('group')}",
                "",
                f"- Severity: {row.get('hallucination_severity')}",
                f"- Groundedness: {row.get('evidence_groundedness_score')}",
                f"- Question: {row.get('question')}",
                f"- Answer: {row.get('generated_answer')}",
                f"- Unsupported claims: {json.dumps(row.get('unsupported_claims_found') or [], ensure_ascii=False)}",
                f"- Wrong bindings: {json.dumps(row.get('wrong_bindings') or [], ensure_ascii=False)}",
                f"- Wrong values/units: {json.dumps(row.get('wrong_values_or_units') or [], ensure_ascii=False)}",
                f"- Overgeneralizations: {json.dumps(row.get('overgeneralizations') or [], ensure_ascii=False)}",
                f"- Rationale: {row.get('rationale')}",
                "",
            ]
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--settings", type=Path, default=REPO_ROOT / "web-ui" / "backend" / "settings.json")
    parser.add_argument("--provider", default="multi_env")
    parser.add_argument("--model")
    parser.add_argument("--base-url")
    parser.add_argument("--parallel-workers", type=int, default=5)
    parser.add_argument("--llm-max-retries", type=int, default=10)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--top-p", type=float, default=1.0)
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    records = load_jsonl(args.records)
    pool = LLMClientPool(args.settings, args.provider, model_override=args.model, base_url_override=args.base_url)

    out_jsonl = args.output_dir / "hallucination_rejudge_records.jsonl"
    errors_path = args.output_dir / "hallucination_rejudge_errors.jsonl"
    done_rows = load_jsonl(out_jsonl) if out_jsonl.exists() else []
    done = {(row.get("question_id"), row.get("group")) for row in done_rows}
    errors = load_jsonl(errors_path) if errors_path.exists() else []
    pending = [record for record in records if (record.get("question_id"), record.get("group")) not in done]

    print(f"[HallucinationRejudge] records={len(records)} done={len(done_rows)} pending={len(pending)} workers={args.parallel_workers}", flush=True)

    def judge_one(record: dict[str, Any]) -> dict[str, Any]:
        response = pool.complete_json(
            strict_hallucination_prompt(record),
            temperature=args.temperature,
            top_p=args.top_p,
            max_tokens=768,
            max_retries=args.llm_max_retries,
        )
        judgment = normalize_judgment(response)
        answer_text = str(record.get("generated_answer") or "").strip().lower()
        deterministic_abstention = (
            not answer_text
            or "i don't know based on the retrieved evidence" in answer_text
            or "cannot answer based on the retrieved evidence" in answer_text
            or bool(record.get("abstained"))
        )
        judgment["answer_is_empty_or_abstention"] = deterministic_abstention
        return {
            "question_id": record.get("question_id"),
            "group": record.get("group"),
            "question": record.get("question"),
            "generated_answer": record.get("generated_answer") or "",
            "old_hallucinated": bool(record.get("hallucinated")),
            "old_unsupported_claims_found": record.get("unsupported_claims_found") or [],
            **judgment,
        }

    def persist() -> None:
        write_jsonl(out_jsonl, done_rows)
        write_jsonl(errors_path, errors)

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.parallel_workers)) as executor:
        future_map = {executor.submit(judge_one, record): record for record in pending}
        for index, future in enumerate(concurrent.futures.as_completed(future_map), start=1):
            record = future_map[future]
            try:
                row = future.result()
                done_rows.append(row)
                errors[:] = [item for item in errors if (item.get("question_id"), item.get("group")) != (record.get("question_id"), record.get("group"))]
                print(f"[HallucinationRejudge] done {index}/{len(pending)} {record.get('group')} {record.get('question_id')}", flush=True)
            except Exception as exc:  # noqa: BLE001
                errors.append({"question_id": record.get("question_id"), "group": record.get("group"), "error": str(exc)})
                print(f"[HallucinationRejudge] error {record.get('group')} {record.get('question_id')}: {exc}", flush=True)
            persist()

    summary_rows = aggregate(done_rows)
    write_csv(args.output_dir / "hallucination_rejudge_summary.csv", summary_rows)
    (args.output_dir / "hallucination_rejudge_summary.json").write_text(
        json.dumps({"summary": summary_rows, "records": len(done_rows), "errors": len(errors)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_markdown(args.output_dir / "hallucination_rejudge_report.md", summary_rows, done_rows)
    print(json.dumps({"output_dir": str(args.output_dir), "summary": summary_rows, "records": len(done_rows), "errors": len(errors)}, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
