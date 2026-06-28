"""Normalization report helpers."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any


def build_merge_report(
    *,
    raw_entities: list[dict[str, Any]],
    canonical_entities: list[dict[str, Any]],
    mention_to_canonical_map: dict[str, dict[str, Any]],
    unit_parse_count: int = 0,
    raw_hyperedge_count: int | None = None,
    normalized_hyperedge_count: int | None = None,
) -> dict[str, Any]:
    raw_count = len(raw_entities)
    canonical_count = len(canonical_entities)
    merged_count = max(0, raw_count - canonical_count)
    methods = Counter(item.get("normalization_method", "unknown") for item in mention_to_canonical_map.values())
    merge_by_type: dict[str, int] = defaultdict(int)
    for entity in canonical_entities:
        mentions = entity.get("mentions") or []
        if len(mentions) > 1:
            merge_by_type[entity.get("type", "UNKNOWN")] += len(mentions) - 1

    alias_merges = []
    for entity in canonical_entities:
        mentions = entity.get("mentions") or []
        if len(mentions) > 1:
            alias_merges.append(
                {
                    "canonical_id": entity.get("canonical_id"),
                    "canonical_name": entity.get("canonical_name"),
                    "type": entity.get("type"),
                    "mentions": mentions[:20],
                    "merge_count": len(mentions) - 1,
                }
            )
    alias_merges.sort(key=lambda item: item["merge_count"], reverse=True)

    report = {
        "raw_entity_count": raw_count,
        "canonical_entity_count": canonical_count,
        "merged_count": merged_count,
        "merge_ratio": round(merged_count / raw_count, 4) if raw_count else 0.0,
        "merge_by_type": dict(sorted(merge_by_type.items())),
        "normalization_methods": dict(methods),
        "unit_parse_count": unit_parse_count,
        "unit_parse_success_rate": round(unit_parse_count / raw_count, 4) if raw_count else 0.0,
        "top_alias_merges": alias_merges[:30],
    }
    if raw_hyperedge_count is not None:
        report["raw_hyperedge_count"] = raw_hyperedge_count
    if normalized_hyperedge_count is not None:
        report["normalized_hyperedge_count"] = normalized_hyperedge_count
        report["hyperedge_deduplicated_count"] = max(0, (raw_hyperedge_count or 0) - normalized_hyperedge_count)
    return report
