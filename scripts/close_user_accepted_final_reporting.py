"""Finalize report/state after explicit user acceptance of the audit."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--cache-root", type=Path, required=True)
    args = parser.parse_args()
    repo = args.repo.resolve()
    cache_root = args.cache_root.resolve()
    output = repo / "outputs/final_experiment_v1_old_embedding"
    now = datetime.now(timezone.utc).isoformat()

    state_path = cache_root / "hyper_final_experiment_v1_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8-sig"))
    state["pid"] = None
    state["reporting_pending"] = False
    stages = state.setdefault("stages", {})
    stages["deepseek_audit"] = {
        "status": "completed",
        "updated_at": now,
        "details": {
            "model": "deepseek-v4.1-flash",
            "endpoint_count": 30,
            "concurrency": 30,
            "status": "user_accepted_audit_gold",
            "accepted_by": "user",
            "accepted_at": now,
            "output": str((output / "deepseek_audit").resolve()),
            "acceptance_manifest": str((output / "deepseek_audit_user_acceptance.json").resolve()),
        },
    }
    stages["qrels_final_audit"] = {
        "status": "completed",
        "updated_at": now,
        "details": {
            "status": "user_accepted_audit_gold",
            "output": str((output / "shared_qrels/shared_qrels_final_audit.json").resolve()),
            "accepted_qrels": str((output / "shared_qrels/shared_qrels.json").resolve()),
        },
    }
    cfr_path = output / "composite_fact_recall_user_accepted.json"
    cfr = json.loads(cfr_path.read_text(encoding="utf-8-sig"))
    stages["composite_fact_recall"] = {
        "status": "completed",
        "updated_at": now,
        "details": {
            "status": "completed_user_accepted_audit",
            "output": str(cfr_path.resolve()),
            "accepted_gold": str((output / "composite_fact_gold_user_accepted.json").resolve()),
            "facts": len(cfr.get("per_fact") or []),
            "method": "accepted_atomic_gold_exact_chunk_binding",
        },
    }
    write = lambda p, x: p.write_text(json.dumps(x, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write(state_path, state)

    audit_path = output / "shared_qrels/shared_qrels_final_audit.json"
    audit = json.loads(audit_path.read_text(encoding="utf-8-sig"))
    audit.update({
        "status": "completed_user_accepted_audit",
        "annotation_status": "user_accepted_audit_gold",
        "accepted_at": now,
        "accepted_by": "user",
        "manual_review_reason": "User spot-checked the DeepSeek audit and confirmed no anomalies; provider successes were accepted and provider failures retained the existing frozen qrel grade.",
    })
    write(audit_path, audit)

    report_path = output / "attribution_report.md"
    report = report_path.read_text(encoding="utf-8")
    report = report.replace(
        "Shared qrels are complete for all 4,196 pooled query/chunk pairs, but remain provisional/LLM judged pending final manual audit.",
        "Shared qrels are complete for all 4,196 pooled query/chunk pairs and were accepted by the user after spot-checking the DeepSeek audit. Provider-failure rows retain their existing frozen grade."
    )
    report = report.replace(
        "Composite Fact Recall is not reported yet. The review pack records provisional categories, but entity/metric/value/unit/condition/relation bindings require manual gold review.",
        "Composite Fact Recall is reported in `composite_fact_recall_user_accepted.json` using 150 accepted atomic facts and exact supporting-chunk binding at Top-5. The five provider-failure queries use explicitly marked user-accepted manual fallback facts."
    )
    report = report.replace(
        "Review `composite_fact_gold_review_pack.json` and certify atomic facts before computing CFR. Review `shared_qrels_final_audit.json` before calling qrels human gold.",
        "User audit acceptance is recorded in `deepseek_audit_user_acceptance.json`; no further provider calls are required."
    )
    report += f"\n## User-accepted audit closure\n\n- Accepted at: {now}\n- qrels: 4,196 pooled pairs; 4,175 provider grades accepted and 21 existing grades retained after provider failure.\n- Atomic gold: 58 queries and 150 accepted facts.\n- CFR: [composite_fact_recall_user_accepted.json]({(output / 'composite_fact_recall_user_accepted.json').resolve()})\n- EFU repair remains disabled in the final cache.\n"
    report_path.write_text(report, encoding="utf-8")

    print(json.dumps({"status": "completed", "reporting_pending": False, "cfr": str(cfr_path.resolve()), "report": str(report_path.resolve())}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
