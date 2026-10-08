"""F0/F1 pairing using the existing structured hybrid retrieval components."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .structured import (
    StructuredGraphIndex, StructuredRetrievalConfig, load_json, source_chunk_ids, tokenize,
)


@dataclass(frozen=True)
class FinalRetrievalConfig(StructuredRetrievalConfig):
    enable_rerank: bool = True


class FinalGraphIndex(StructuredGraphIndex):
    def __init__(self, cache_dir: Path):
        validation = load_json(cache_dir / "final_validation.json")
        config = load_json(cache_dir / "run_config.json")
        if not validation.get("validation_passed") or config.get("index_profile") != "dual_concat":
            raise ValueError("final retrieval requires an accepted dual_concat cache")
        if config.get("enable_efu_repair") or not config.get("enable_measurement_instances"):
            raise ValueError("final method flags differ from the experiment plan")
        super().__init__(cache_dir)

    def _rank_and_reconstruct(self, query, view, top_k, config, edge_states):
        # Both groups freeze the same RRF pool before applying the existing
        # lexical/structural bonuses. Rerank never changes candidate selection.
        pool = sorted(edge_states.items(), key=lambda row: (-row[1]["rrf"], tuple(row[0])))
        pool = pool[:max(top_k, config.rerank_candidate_depth)]
        pool_ids = ["|".join(key) for key, _ in pool]
        query_terms = set(tokenize(query))
        ranked = []
        for key, state in pool:
            edge = self.edges[key]
            vertices = self.edge_vertices(key)
            terms = set(tokenize(self.relationship_document({"id_set": vertices}, edge)))
            coverage = len(query_terms & terms) / max(1, len(query_terms))
            matched_seeds = len(set(vertices) & set(state["seed_entities"]))
            structure_bonus = min(.003, .0015 * max(0, matched_seeds - 1))
            score = float(state["rrf"])
            if config.enable_rerank:
                score += .004 * coverage + structure_bonus
            ranked.append((score, key, state))
        ranked.sort(key=lambda row: (-row[0], tuple(row[1])))
        chunk_states = {}
        for edge_rank, (edge_score, key, state) in enumerate(ranked, 1):
            edge = self.edges[key]
            for chunk in source_chunk_ids(edge, self.chunks):
                # Select source-local descriptions/spans; aggregated descriptions
                # can contain other studies with the same metric/value tuple.
                instances = [i for i in edge.get("evidence_instances", []) if chunk in source_chunk_ids(i, self.chunks)]
                descriptions = list(dict.fromkeys(str(i.get("description") or "") for i in instances))
                spans = list(dict.fromkeys(str(i.get("source_span") or i.get("evidence_span") or "") for i in instances))
                relation = {"edge_id": "|".join(key), "vertices": list(key), "arity": len(key),
                            "relation_type": str(edge.get("relation_type") or "RELATION"),
                            "description": "<SEP>".join(descriptions), "source_spans": spans,
                            "keywords": str(edge.get("keywords") or ""),
                            "edge_rank": edge_rank, "edge_score": edge_score,
                            "retrieval_channels": state["channels"], "expanded_from_entities": sorted(state["expanded_from"])}
                cs = chunk_states.setdefault(chunk, {"score": 0., "max_edge_score": 0., "relations": []})
                cs["score"] += 1. / (config.rrf_k + edge_rank)
                cs["max_edge_score"] = max(cs["max_edge_score"], edge_score)
                cs["relations"].append(relation)
        ordered = sorted(chunk_states.items(), key=lambda row: (-row[1]["score"], -row[1]["max_edge_score"], row[0]))
        evidence = []
        for chunk, state in ordered[:min(top_k, config.chunk_candidate_depth)]:
            row = self._chunk_evidence(chunk, state, view)
            row["retrieval_method"] = "normalized_final_hybrid_rerank_v1" if config.enable_rerank else "normalized_final_hybrid_rrf_v1"
            row["rerank_enabled"] = config.enable_rerank
            row["candidate_edge_ids"] = pool_ids
            row["candidate_chunk_ids"] = sorted(chunk_states)
            evidence.append(row)
        return evidence


class FinalGraphRetriever:
    def __init__(self, index, embedding_pool, *, config=None):
        self.index = index
        self.embedding_pool = embedding_pool
        self.config = config or FinalRetrievalConfig()

    def search(self, query, top_k):
        return self.index.search(query, self.embedding_pool.embed(query), view="hyper", top_k=top_k, config=self.config)
