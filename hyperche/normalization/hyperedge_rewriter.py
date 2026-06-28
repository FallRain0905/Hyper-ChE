"""Rewrite hyperedge vertices with normalization mappings."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class RewrittenHyperedge:
    original: dict[str, Any]
    canonical_vertices: list[str]
    unresolved_vertices: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = dict(self.original)
        data["canonical_vertices"] = self.canonical_vertices
        if self.unresolved_vertices:
            data["unresolved_vertices"] = self.unresolved_vertices
            data["normalization_status"] = "unresolved"
        else:
            data["normalization_status"] = "resolved"
        return data


class HyperedgeRewriter:
    def __init__(self, mention_to_canonical_map: dict[str, dict[str, Any]]):
        self.mention_to_canonical_map = mention_to_canonical_map

    def rewrite_hyperedges(self, hyperedges: list[dict[str, Any]]) -> dict[str, Any]:
        rewritten = []
        unresolved_count = 0
        for edge in hyperedges:
            vertices = self._vertices(edge)
            canonical_vertices = []
            unresolved_vertices = []
            for vertex in vertices:
                mapped = self.mention_to_canonical_map.get(str(vertex))
                if mapped:
                    node_id = mapped.get("node_id") or mapped.get("instance_id") or mapped["canonical_id"]
                    canonical_vertices.append(node_id)
                    if mapped.get("need_review"):
                        unresolved_vertices.append(str(vertex))
                else:
                    canonical_vertices.append(str(vertex))
                    unresolved_vertices.append(str(vertex))
            if unresolved_vertices:
                unresolved_count += 1
            item = RewrittenHyperedge(
                original=edge,
                canonical_vertices=list(dict.fromkeys(canonical_vertices)),
                unresolved_vertices=unresolved_vertices,
            )
            rewritten.append(item.to_dict())
        return {
            "raw_hyperedge_count": len(hyperedges),
            "normalized_hyperedge_count": len(rewritten),
            "unresolved_hyperedge_count": unresolved_count,
            "hyperedges": rewritten,
        }

    @staticmethod
    def _vertices(edge: dict[str, Any]) -> list[Any]:
        for key in ("vertices", "entityN", "entities_set", "id_set"):
            if key in edge and edge[key] is not None:
                value = edge[key]
                return list(value) if isinstance(value, (list, tuple, set)) else [value]
        source = edge.get("source")
        target = edge.get("target")
        if source is not None or target is not None:
            return [item for item in (source, target) if item is not None]
        return []


def rewrite_hyperedges(hyperedges: list[dict[str, Any]], mention_to_canonical_map: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return HyperedgeRewriter(mention_to_canonical_map).rewrite_hyperedges(hyperedges)
