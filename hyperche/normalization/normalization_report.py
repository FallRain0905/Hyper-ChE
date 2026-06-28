"""Normalization report helpers."""

from __future__ import annotations

from collections import Counter
from typing import Any


def build_normalization_report(
    normalization_results: list[dict[str, Any]],
    *,
    raw_hyperedge_count: int = 0,
    normalized_hyperedge_count: int = 0,
    unresolved_hyperedge_count: int = 0,
) -> dict[str, Any]:
    methods = Counter(item.get("method", "unknown") for item in normalization_results)
    decisions = Counter(item.get("decision", "unknown") for item in normalization_results)
    blocked = [item for item in normalization_results if item.get("blocked_reason")]
    review = [item for item in normalization_results if item.get("need_review")]
    created = [item for item in normalization_results if item.get("decision") == "CREATE_NEW"]
    merged_count = decisions.get("MERGE", 0)
    raw_count = len(normalization_results)
    return {
        "raw_entity_count": raw_count,
        "exact_match_count": methods.get("exact_alias_match", 0),
        "fuzzy_auto_match_count": methods.get("fuzzy_auto_match", 0),
        "llm_judged_count": methods.get("llm_judged", 0),
        "created_new_count": len(created),
        "need_review_count": len(review),
        "canonical_entity_count": len({item.get("canonical_id") for item in normalization_results if item.get("canonical_id")}),
        "merge_ratio": round(merged_count / raw_count, 4) if raw_count else 0.0,
        "decision_counts": dict(decisions),
        "method_counts": dict(methods),
        "top_unresolved_entities": [
            {
                "original_name": item.get("original_name"),
                "entity_type": item.get("entity_type"),
                "candidates": item.get("candidates", [])[:5],
                "reason": item.get("reason"),
            }
            for item in review[:20]
        ],
        "top_added_aliases": [],
        "high_risk_blocked_merges": [
            {
                "original_name": item.get("original_name"),
                "entity_type": item.get("entity_type"),
                "candidate": (item.get("candidates") or [None])[0],
                "reason": item.get("blocked_reason"),
            }
            for item in blocked[:20]
        ],
        "raw_hyperedge_count": raw_hyperedge_count,
        "normalized_hyperedge_count": normalized_hyperedge_count,
        "unresolved_hyperedge_count": unresolved_hyperedge_count,
    }
