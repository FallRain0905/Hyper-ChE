"""Hyperedge canonicalization and deduplication."""

from __future__ import annotations

import hashlib
import json
from typing import Any


class HyperedgeNormalizer:
    """Rewrite edge vertices with canonical ids and deduplicate signatures."""

    def __init__(self, mention_to_canonical_map: dict[str, dict[str, Any]]):
        self.mention_to_canonical_map = mention_to_canonical_map

    def normalize_hyperedges(self, hyperedges: list[dict[str, Any]]) -> dict[str, Any]:
        normalized: dict[str, dict[str, Any]] = {}
        raw_count = len(hyperedges)
        for edge in hyperedges:
            vertices = self._vertices(edge)
            canonical_vertices = [
                self.mention_to_canonical_map.get(vertex, {}).get("canonical_id", vertex)
                for vertex in vertices
            ]
            relation_type = str(edge.get("relation_type") or edge.get("type") or "UNKNOWN")
            signature = self.edge_signature(edge, canonical_vertices, relation_type)
            if signature not in normalized:
                item = dict(edge)
                item["raw_vertices"] = vertices
                item["canonical_vertices"] = canonical_vertices
                item["edge_signature"] = signature
                normalized[signature] = item
            else:
                existing = normalized[signature]
                existing_sources = set(self._split_sep(existing.get("source_id")))
                for source_id in self._split_sep(edge.get("source_id")):
                    if source_id not in existing_sources:
                        existing_sources.add(source_id)
                if existing_sources:
                    existing["source_id"] = "<SEP>".join(sorted(existing_sources))
        return {
            "raw_hyperedge_count": raw_count,
            "normalized_hyperedge_count": len(normalized),
            "deduplicated_count": raw_count - len(normalized),
            "hyperedges": list(normalized.values()),
        }

    @staticmethod
    def edge_signature(edge: dict[str, Any], canonical_vertices: list[str], relation_type: str) -> str:
        source_id = edge.get("source_id") or edge.get("source_doc_id") or edge.get("chunk_id") or ""
        conditions = edge.get("normalized_condition_values") or edge.get("conditions") or []
        payload = {
            "relation_type": relation_type,
            "vertices": sorted(str(vertex) for vertex in canonical_vertices),
            "conditions": conditions,
            "source_id": source_id,
        }
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _vertices(edge: dict[str, Any]) -> list[str]:
        raw = edge.get("vertices") or edge.get("entity_set") or edge.get("entities_set") or edge.get("id_set") or []
        if isinstance(raw, str):
            return [item.strip() for item in raw.split("|#|") if item.strip()]
        return [str(item).strip() for item in raw if str(item).strip()]

    @staticmethod
    def _split_sep(value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item) for item in value if str(item)]
        return [item for item in str(value).split("<SEP>") if item]
