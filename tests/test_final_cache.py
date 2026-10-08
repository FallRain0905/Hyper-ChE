import json

from hyperche.normalization.alias_registry import AliasRegistry
from hyperche.normalization.entity_normalizer import EntityNormalizer
from hyperche.normalization.final_cache import cached_payload, local_instance, rewrite_final_graph


def test_description_numbers_do_not_create_or_override_local_value():
    normalizer = EntityNormalizer(AliasRegistry())
    raw = {"name": "energy efficiency", "type": "METRIC", "value": 80, "unit": "%",
           "description": "90% for another electrode at 150 mA/cm2"}
    result, _ = local_instance(raw, normalizer)
    assert result["value"] == 80
    raw["value"] = None
    assert local_instance(raw, normalizer)[0] is None


def test_energy_density_and_ph_slope_are_not_efficiency_or_ph():
    normalizer = EntityNormalizer(AliasRegistry())
    result, _ = local_instance({"name": "energy density", "type": "METRIC", "value": 25, "unit": "Wh/L"}, normalizer)
    assert result["canonical_id"] == "metric:energy_density"
    assert result["unit"] == "Wh/L"
    assert local_instance({"name": "expected pH shift", "type": "METRIC", "value": 118, "unit": "mV/pH"}, normalizer)[0] is None


def test_chunk_local_values_do_not_cross_bind_or_add_edge_vertices():
    chunks = ["RFB_001_CHK_001", "RFB_002_CHK_001"]
    vertices = {n: {"source_chunk_ids": chunks} for n in ("electrode", "energy efficiency")}
    instances = [{"vertices": ["electrode", "energy efficiency"], "source_chunk_id": chunk,
                  "description": f"EE {value}%", "source_span": f"EE {value}%", "relation_type": "PERFORMANCE",
                  "repair_applied": False} for chunk, value in zip(chunks, (80, 90))]
    source = {"v_data": vertices, "e_data": {("electrode", "energy efficiency"): {"evidence_instances": instances}}}
    mapping = {n: {"canonical_id": "canonical:" + n} for n in vertices}
    normalized = {"v_data": {"canonical:" + n: {"canonical_name": n, "source_chunk_ids": chunks, "aliases": [n]} for n in vertices}}
    canonical_map = {"entities": mapping, "clusters": [{"canonical_id": d["canonical_id"], "members": [n]} for n, d in mapping.items()]}
    extracted = {chunk: [{"name": "energy efficiency", "type": "METRIC", "value": value, "unit": "%"},
                         {"name": "current density", "type": "CONDITION", "value": 150, "unit": "mA/cm2"}]
                 for chunk, value in zip(chunks, (80, 90))}
    nodes, edges, occurrences, details = rewrite_final_graph(source, normalized, canonical_map, extracted)
    assert len(edges) == 2
    assert len(occurrences) == 2
    for key, edge in edges.items():
        chunk = edge["source_chunk_ids"][0]
        value = 80 if chunk == chunks[0] else 90
        numeric_nodes = [nodes[n] for n in key if nodes[n].get("instance_id")]
        assert len(key) == 2 and len(numeric_nodes) == 1
        assert numeric_nodes[0]["value"] == value
        assert edge["evidence_instances"][0]["source_span"] == f"EE {value}%"
        assert "current density" not in str(key)
    assert details["summary"]["removed_replaced_numeric_clusters"] == 1


def test_only_json_escaping_is_repaired():
    text = r'{"entities":[{"name":"$\alpha$"}]}'
    assert cached_payload(text)["entities"][0]["name"] == r"$\alpha$"
    assert cached_payload(json.dumps({"entities": []})) == {"entities": []}


def test_ranges_do_not_read_a_formula_digit_as_a_scalar():
    result, _ = local_instance({"name": "H2SO4 electrolyte concentration", "type": "CONDITION",
                               "value_min": 0, "value_max": .04, "unit": "mol/L"}, EntityNormalizer(AliasRegistry()))
    assert result["value"] is None
    assert result["min_value"] == 0 and result["max_value"] == .04
    assert local_instance({"name": "current density", "type": "CONDITION", "value_min": 10,
                           "unit": "mA/cm2"}, EntityNormalizer(AliasRegistry()))[0] is None


def test_final_rerank_uses_the_same_frozen_candidate_pool():
    from scripts.final_graph_retrieval import FinalGraphIndex, FinalRetrievalConfig
    index = FinalGraphIndex.__new__(FinalGraphIndex)
    chunks = ["RFB_001_CHK_001", "RFB_002_CHK_001"]
    index.chunks = {chunk: {} for chunk in chunks}
    index.edges = {("a", "b"): {"source_chunk_ids": [chunks[0]], "description": "unrelated", "evidence_instances": []},
                   ("c", "d"): {"source_chunk_ids": [chunks[1]], "description": "energy efficiency", "evidence_instances": []}}
    states = {key: {"rrf": .05 - rank * .001, "seed_entities": set(), "expanded_from": set(), "channels": {}}
              for rank, key in enumerate(index.edges)}
    index._chunk_evidence = lambda chunk, state, view: {"source_chunk_id": chunk}
    f0 = index._rank_and_reconstruct("energy efficiency", "hyper", 1, FinalRetrievalConfig(enable_rerank=False), states)
    f1 = index._rank_and_reconstruct("energy efficiency", "hyper", 1, FinalRetrievalConfig(enable_rerank=True), states)
    assert f0[0]["candidate_edge_ids"] == f1[0]["candidate_edge_ids"]
    assert f0[0]["candidate_chunk_ids"] == f1[0]["candidate_chunk_ids"]
    assert f0[0]["source_chunk_id"] == chunks[0]
    assert f1[0]["source_chunk_id"] == chunks[1]
