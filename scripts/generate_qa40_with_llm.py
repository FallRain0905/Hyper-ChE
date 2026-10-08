"""Generate a 40-question QA set with an LLM, separated from QA answering.

The script uses existing benchmark annotations as grounding material, then asks
the LLM to rewrite each selected question into a clean researcher-style query.
Reference answers and required key points are preserved from the benchmark so
answer evaluation remains anchored.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from scripts.run_qa_smoke_llm import (  # noqa: E402
    LLMClientPool,
    build_full_qa_set,
    load_json,
)


def validate_question(value: dict[str, Any]) -> tuple[bool, str]:
    if not isinstance(value, dict):
        return False, "not an object"
    question = value.get("question")
    if not isinstance(question, str) or len(question.strip()) < 12:
        return False, "question is missing or too short"
    return True, ""


def generate_question(pool: LLMClientPool, qa: dict[str, Any], *, max_retries: int) -> dict[str, Any]:
    prompt = f"""Rewrite this chemical literature QA question for an evaluation benchmark.

Requirements:
- Keep the exact same answer target and difficulty.
- Do not include the reference answer in the question.
- Do not copy long phrases from the reference answer.
- Keep all necessary constraints such as material, condition, metric, and system.
- Return JSON only.

Original question:
{qa.get('question')}

Question type:
{qa.get('question_type') or qa.get('category')}

Answerable:
{qa.get('answerable')}

Reference answer for your understanding only:
{qa.get('reference_answer')}

Required key points for your understanding only:
{json.dumps(qa.get('required_key_points') or [], ensure_ascii=False)}

Return:
{{
  "question": "...",
  "rewrite_rationale": "..."
}}
"""
    errors: list[str] = []
    for attempt in range(max_retries):
        value = pool.complete_json(prompt, temperature=0.2, top_p=1.0, max_tokens=1500, max_retries=1)
        ok, reason = validate_question(value)
        if ok:
            output = dict(qa)
            output["original_question"] = qa.get("question")
            output["question"] = value["question"].strip()
            output["question_generation_model"] = pool.model
            output["question_generation_provider"] = pool.provider_name
            output["question_generation_method"] = "llm_rewrite_from_grounded_benchmark_qa"
            output["question_generation_rationale"] = value.get("rewrite_rationale", "")
            return output
        errors.append(f"attempt={attempt + 1}: {reason}; output={json.dumps(value, ensure_ascii=False)[:400]}")
    raise RuntimeError("question generation failed: " + " || ".join(errors))


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate 40 QA questions using an LLM.")
    parser.add_argument("--benchmark-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--settings", type=Path, default=REPO_ROOT / "web-ui" / "backend" / "settings.json")
    parser.add_argument("--provider", default="deepseek_env")
    parser.add_argument("--model")
    parser.add_argument("--base-url")
    parser.add_argument("--max-retries", type=int, default=8)
    args = parser.parse_args()

    qa_all = load_json(args.benchmark_dir / "qa_questions.json").get("qa_questions", [])
    seed_questions = build_full_qa_set(qa_all)
    pool = LLMClientPool(args.settings, args.provider, model_override=args.model, base_url_override=args.base_url)

    generated: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    args.output.parent.mkdir(parents=True, exist_ok=True)
    progress_path = args.output.with_suffix(".progress.jsonl")
    completed = set()
    if args.output.exists():
        try:
            existing = json.loads(args.output.read_text(encoding="utf-8"))
            generated = existing.get("qa_questions", [])
            completed = {str(item.get("question_id")) for item in generated}
        except Exception:
            generated = []
            completed = set()

    for index, qa in enumerate(seed_questions, start=1):
        qid = str(qa.get("question_id"))
        if qid in completed:
            print(f"[QAQuestionGen] {index}/{len(seed_questions)} skip {qid}", flush=True)
            continue
        print(f"[QAQuestionGen] {index}/{len(seed_questions)} generate {qid}", flush=True)
        try:
            item = generate_question(pool, qa, max_retries=args.max_retries)
            generated.append(item)
            completed.add(qid)
            with progress_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"status": "ok", "question_id": qid}, ensure_ascii=False) + "\n")
        except Exception as exc:  # noqa: BLE001
            errors.append({"question_id": qid, "error": str(exc)})
            with progress_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"status": "error", "question_id": qid, "error": str(exc)}, ensure_ascii=False) + "\n")
        payload = {
            "metadata": {
                "question_count": len(generated),
                "target_question_count": len(seed_questions),
                "provider": pool.provider_name,
                "model": pool.model,
                "base_url": pool.base_url,
                "api_key_count": len(pool.entries),
                "errors": errors,
            },
            "qa_questions": generated,
        }
        args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    if errors:
        raise SystemExit(f"Question generation completed with {len(errors)} errors; see {progress_path}")
    print(json.dumps({"output": str(args.output), "questions": len(generated), "errors": len(errors)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
