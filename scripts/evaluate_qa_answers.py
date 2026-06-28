"""Evaluate generated QA answers for Hyper-ChE experiments."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import statistics
from typing import Any

try:
    import yaml
except Exception:  # pragma: no cover
    yaml = None


REPO_ROOT = Path(__file__).resolve().parents[1]
DIMENSIONS = [
    "factual_correctness",
    "condition_completeness",
    "numerical_accuracy",
    "mechanistic_support",
    "comparative_clarity",
    "source_grounding",
    "readability",
]
JUDGE_ALIASES = {
    "kimi": {"api_key_env": "KIMI_API_KEY", "base_url_env": "KIMI_BASE_URL", "model_env": "KIMI_MODEL", "base_url": "https://api.moonshot.cn/v1", "model": "moonshot-v1-8k"},
    "deepseek": {"api_key_env": "DEEPSEEK_API_KEY", "base_url_env": "DEEPSEEK_BASE_URL", "model_env": "DEEPSEEK_MODEL", "base_url": "https://api.deepseek.com", "model": "deepseek-v4-flash"},
    "qwen": {"api_key_env": "QWEN_API_KEY", "base_url_env": "QWEN_BASE_URL", "model_env": "QWEN_MODEL", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen-plus"},
}


def read_yaml_or_json(path: Path) -> Any:
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() in {".yaml", ".yml"} and yaml:
        return yaml.safe_load(text) or {}
    return json.loads(text)


def load_answer_map(path: Path) -> dict[str, Path]:
    data = read_yaml_or_json(path)
    mapping = data.get("answers", data)
    return {str(mode): Path(answer_path) for mode, answer_path in mapping.items()}


def load_answers(path: Path) -> list[dict[str, Any]]:
    data = read_yaml_or_json(path)
    if isinstance(data, list):
        return data
    if "answers" in data and isinstance(data["answers"], list):
        return data["answers"]
    rows = []
    for question_id, value in data.items():
        if isinstance(value, dict):
            rows.append({"question_id": question_id, **value})
        else:
            rows.append({"question_id": question_id, "answer": str(value)})
    return rows


def resolve_judges(names: list[str], errors: list[dict[str, Any]]) -> list[dict[str, str]]:
    judges = []
    for name in names:
        alias = JUDGE_ALIASES.get(name)
        if not alias:
            errors.append({"type": "judge_config", "judge": name, "message": "Unknown judge alias."})
            continue
        api_key = os.getenv(alias["api_key_env"])
        if not api_key:
            errors.append({"type": "judge_config", "judge": name, "message": f"Missing {alias['api_key_env']}; skipped."})
            continue
        judges.append({"name": name, "api_key": api_key, "base_url": os.getenv(alias["base_url_env"], alias["base_url"]), "model": os.getenv(alias["model_env"], alias["model"])})
    return judges


def judge_with_llm(item: dict[str, Any], judge: dict[str, str]) -> dict[str, Any]:
    from openai import OpenAI

    prompt = f"""Evaluate this chemical literature QA answer.

Question:
{item.get('question') or item.get('query') or item.get('question_id')}

Answer:
{item.get('answer') or item.get('response') or ''}

Optional retrieved context/evidence:
{json.dumps(item.get('context') or item.get('evidence') or item.get('sources') or [], ensure_ascii=False, indent=2)}

Score each dimension from 1 to 5, where 5 is best. Return strict JSON only:
{{
  "factual_correctness": 1,
  "condition_completeness": 1,
  "numerical_accuracy": 1,
  "mechanistic_support": 1,
  "comparative_clarity": 1,
  "source_grounding": 1,
  "readability": 1,
  "overall_score": 1,
  "strengths": [],
  "weaknesses": [],
  "reason": "..."
}}
"""
    client = OpenAI(api_key=judge["api_key"], base_url=judge.get("base_url")) if judge.get("base_url") else OpenAI(api_key=judge["api_key"])
    response = client.chat.completions.create(model=judge["model"], messages=[{"role": "user", "content": prompt}], temperature=0, response_format={"type": "json_object"})
    raw = response.choices[0].message.content or "{}"
    data = json.loads(raw)
    result = {dim: float(data.get(dim, 0.0)) for dim in DIMENSIONS}
    result["overall_score"] = float(data.get("overall_score", statistics.mean(result.values()) if result else 0.0))
    result["strengths"] = data.get("strengths", [])
    result["weaknesses"] = data.get("weaknesses", [])
    result["reason"] = str(data.get("reason", ""))
    result["_raw_response"] = raw
    result["judge_name"] = judge["name"]
    result["judge_model"] = judge["model"]
    return result


def aggregate(judgments: list[dict[str, Any]]) -> dict[str, Any]:
    if not judgments:
        return {**{dim: 0.0 for dim in DIMENSIONS}, "overall_score": 0.0, "judge_count": 0}
    output = {dim: round(statistics.mean(float(j.get(dim, 0.0)) for j in judgments), 4) for dim in DIMENSIONS}
    output["overall_score"] = round(statistics.mean(float(j.get("overall_score", 0.0)) for j in judgments), 4)
    output["std_overall_score"] = round(statistics.pstdev(float(j.get("overall_score", 0.0)) for j in judgments), 4) if len(judgments) > 1 else 0.0
    output["judge_count"] = len(judgments)
    output["per_model_judgments"] = judgments
    return output


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def make_paths(output_dir: Path | None) -> dict[str, Path]:
    if output_dir is None:
        run_id = datetime.now(timezone.utc).strftime("run_%Y%m%d_%H%M%S")
        output_dir = REPO_ROOT / "outputs" / "qa_eval" / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    return {
        "dir": output_dir,
        "run_config": output_dir / "run_config.json",
        "summary_csv": output_dir / "qa_score_summary.csv",
        "summary_json": output_dir / "qa_score_summary.json",
        "full": output_dir / "qa_full_judgments.json",
        "llm": output_dir / "qa_llm_judgments.jsonl",
        "raw": output_dir / "model_raw_outputs.jsonl",
        "errors": output_dir / "errors.jsonl",
        "log": output_dir / "run.log",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate Hyper-ChE QA answers with seven-dimension LLM scoring.")
    parser.add_argument("--answer-map", required=True, type=Path)
    parser.add_argument("--modes", nargs="+", required=True)
    parser.add_argument("--judge-model", choices=list(JUDGE_ALIASES))
    parser.add_argument("--judge-models", nargs="+", choices=list(JUDGE_ALIASES))
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    paths = make_paths(args.output_dir)
    answer_map = load_answer_map(args.answer_map)
    errors: list[dict[str, Any]] = []
    judges = resolve_judges(args.judge_models or ([args.judge_model] if args.judge_model else ["deepseek"]), errors)
    full_records = []
    llm_records = []
    raw_records = []
    summary_rows = []

    for mode in args.modes:
        answer_path = answer_map.get(mode)
        if not answer_path:
            errors.append({"type": "answer_map", "mode": mode, "message": "No answer file configured; skipped."})
            continue
        answers = load_answers(answer_path)
        mode_scores = []
        for index, answer in enumerate(answers, start=1):
            qid = answer.get("question_id") or answer.get("id") or f"q-{index}"
            per_model = []
            for judge in judges:
                try:
                    judged = judge_with_llm(answer, judge)
                    per_model.append(judged)
                    llm_records.append({**judged, "mode": mode, "question_id": qid})
                    raw_records.append({"mode": mode, "question_id": qid, "judge": judge["name"], "model": judge["model"], "raw_response": judged.get("_raw_response")})
                except Exception as exc:
                    errors.append({"type": "qa_llm_judge", "mode": mode, "question_id": qid, "judge": judge.get("name"), "error": str(exc)})
            aggregated = aggregate(per_model)
            aggregated.update({"mode": mode, "question_id": qid, "question": answer.get("question") or answer.get("query")})
            full_records.append(aggregated)
            if per_model:
                mode_scores.append(aggregated)
            if args.verbose:
                print(f"[QAEval] mode={mode} {index}/{len(answers)} {qid} overall={aggregated['overall_score']}", flush=True)
        if mode_scores:
            row = {"mode": mode, "question_count": len(mode_scores)}
            for dim in DIMENSIONS + ["overall_score"]:
                row[dim] = round(statistics.mean(float(item.get(dim, 0.0)) for item in mode_scores), 4)
            summary_rows.append(row)

    paths["run_config"].write_text(json.dumps({"answer_map": str(args.answer_map), "modes": args.modes, "judge_models": [{"name": j["name"], "model": j["model"], "base_url": j.get("base_url")} for j in judges], "output_dir": str(paths["dir"])}, ensure_ascii=False, indent=2), encoding="utf-8")
    paths["summary_json"].write_text(json.dumps(summary_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    with paths["summary_csv"].open("w", encoding="utf-8", newline="") as f:
        fieldnames = ["mode", "question_count"] + DIMENSIONS + ["overall_score"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(summary_rows)
    paths["full"].write_text(json.dumps(full_records, ensure_ascii=False, indent=2), encoding="utf-8")
    write_jsonl(paths["llm"], llm_records)
    write_jsonl(paths["raw"], raw_records)
    write_jsonl(paths["errors"], errors)
    paths["log"].write_text("QA evaluation completed.\n", encoding="utf-8")
    print(json.dumps({"output_dir": str(paths["dir"]), "summary_json_path": str(paths["summary_json"]), "summary_csv_path": str(paths["summary_csv"]), "full_judgment_path": str(paths["full"]), "llm_archive_path": str(paths["llm"]), "errors_path": str(paths["errors"]), "mode_count": len(summary_rows)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
