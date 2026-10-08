"""Offline unit tests for post-hoc normalization primitives."""
from __future__ import annotations

import asyncio
import json
import os
import pickle
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np

from hyperche.normalization import posthoc_cache as p
from scripts import normalize_cache_posthoc as cli


class PosthocNormalizationTests(unittest.TestCase):
    def test_cli_uses_kimi_with_conservative_default_concurrency(self):
        with mock.patch.dict("os.environ", {"LLM_MODEL": ""}, clear=False):
            del os.environ["LLM_MODEL"]
            parser = cli._parser()
            args = parser.parse_args([
                "--source-cache", "source",
                "--target-cache", "target",
            ])
        self.assertEqual(args.llm_model, "Pro/moonshotai/Kimi-K2.6")
        self.assertEqual(args.llm_max_async, 5)
        self.assertEqual(args.llm_attempts_per_pair, 2)

    def test_latest_records_does_not_let_failure_overwrite_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "decisions.jsonl"
            p.write_jsonl(path, [
                {"judgement_key": "same-key", "status": "ok", "decision": "ALIAS"},
                {"judgement_key": "same-key", "status": "api_error", "decision": "UNCERTAIN"},
            ])
            selected = p._latest_records(
                path,
                "judgement_key",
                successful_statuses={"ok", "rule_blocked"},
            )
            self.assertEqual(selected["same-key"]["status"], "ok")
            self.assertEqual(selected["same-key"]["decision"], "ALIAS")

    def test_decision_by_pair_prefers_success_and_blocks_success_conflicts(self):
        pair_id = p._pair_id("a", "b")
        selected = p._decision_by_pair([
            {"pair_id": pair_id, "status": "ok", "decision": "ALIAS", "confidence": 0.97, "model": "m1"},
            {"pair_id": pair_id, "status": "api_error", "decision": "UNCERTAIN", "confidence": 0.0, "model": "m1"},
        ])
        self.assertEqual(selected[pair_id]["status"], "ok")
        self.assertEqual(selected[pair_id]["decision"], "ALIAS")

        conflicted = p._decision_by_pair([
            {"pair_id": pair_id, "status": "ok", "decision": "ALIAS", "confidence": 0.97, "model": "m1"},
            {"pair_id": pair_id, "status": "ok", "decision": "DIFFERENT", "confidence": 0.99, "model": "m2"},
        ])
        self.assertEqual(conflicted[pair_id]["status"], "conflict")
        self.assertEqual(conflicted[pair_id]["decision"], "UNCERTAIN")
        self.assertEqual(conflicted[pair_id]["confidence"], 0.0)

    def test_context_is_deterministic_for_unordered_graph_data(self):
        left = p.extract_features("a", {
            "entity_name": "VRFB", "entity_type": "SYSTEM",
            "source_chunk_id": ["RFB_002_CHK_001", "RFB_001_CHK_001"],
        }).to_dict()
        right = p.extract_features("b", {
            "entity_name": "vanadium redox flow battery", "entity_type": "SYSTEM",
            "source_chunk_id": ["RFB_001_CHK_001"],
        }).to_dict()
        pair = {
            "pair_id": p._pair_id("a", "b"), "left_id": "a", "right_id": "b",
            "left_features": left, "right_features": right,
        }
        chunks = {
            "RFB_001_CHK_001": {"content": "VRFB means vanadium redox flow battery."},
            "RFB_002_CHK_001": {"content": "A second VRFB paper."},
        }
        edge = frozenset({"a", "neighbor-z", "neighbor-c"})
        graph_a = {
            "v_inci": {"a": {edge}, "b": set()},
            "e_data": {edge: {"z": {"second", "first"}, "a": 1}},
        }
        graph_b = {
            "v_inci": {"a": {frozenset(reversed(tuple(edge)))}, "b": set()},
            "e_data": {frozenset(reversed(tuple(edge))): {"a": 1, "z": {"first", "second"}}},
        }
        prompt_a, supplied_a = p._context_for_pair(pair, graph_a, chunks, {})
        prompt_b, supplied_b = p._context_for_pair(pair, graph_b, chunks, {})
        self.assertEqual(prompt_a, prompt_b)
        self.assertEqual(supplied_a, supplied_b)
        self.assertEqual(p.json_hash(prompt_a), p.json_hash(prompt_b))

    def test_json_parser_selects_complete_judgement_object_from_reasoning(self):
        parsed = p._parse_json_response(
            'Reasoning used {an invalid fragment}. Final: '
            '{"decision":"DIFFERENT","confidence":0.98,"reason":"distinct",'
            '"canonical_name":null,"preferred_name_source":"NONE","evidence_chunk_ids":[]}'
        )
        self.assertEqual(parsed["decision"], "DIFFERENT")

    def test_preferred_name_source_accepts_safe_llm_variants_only(self):
        base = {
            "decision": "DIFFERENT",
            "confidence": 0.99,
            "reason": "distinct entities",
            "evidence_chunk_ids": [],
        }
        for raw, expected in (
            ("A", "A"),
            ("ENTITY A", "A"),
            ("entity_a", "A"),
            ("B", "B"),
            ("ENTITY B", "B"),
            ("entity-b", "B"),
            ("NEW ENTITY", "NEW"),
            ("N/A", "NONE"),
            ("null", "NONE"),
        ):
            parsed = dict(base, preferred_name_source=raw)
            self.assertEqual(p._validate_pair_response(parsed, [] )["preferred_name_source"], expected)

        with self.assertRaisesRegex(ValueError, "invalid preferred_name_source"):
            p._validate_pair_response(dict(base, preferred_name_source="RFB_039"), [])

    def test_protected_signals_are_preserved(self):
        nafion = p.extract_features("v1", {"entity_name": "Nafion 117", "entity_type": "MEMBRANE"})
        vanadium = p.extract_features("v2", {"entity_name": "V(IV)", "entity_type": "CHEMICAL"})
        self.assertIn("nafion117", nafion.models)
        self.assertTrue(any("IV" in value for value in vanadium.oxidation_states))

        charged = p.extract_features(
            "v3",
            {"entity_name": "VO2+ at 25 °C, 1.0 mol/L, 100 cycles", "entity_type": "CHEMICAL"},
        )
        self.assertTrue(charged.charges)
        self.assertTrue(charged.numeric_signals)

    def test_risk_filter_blocks_model_and_oxidation_conflicts(self):
        left = p.extract_features("a", {"entity_name": "Nafion 117", "entity_type": "MEMBRANE"})
        right = p.extract_features("b", {"entity_name": "Nafion 212", "entity_type": "MEMBRANE"})
        decision, reason = p.risk_filter(left, right)
        self.assertEqual(decision, "VARIANT")
        self.assertIn("conflict", reason)

        left = p.extract_features("c", {"entity_name": "V(IV)", "entity_type": "CHEMICAL"})
        right = p.extract_features("d", {"entity_name": "V(V)", "entity_type": "CHEMICAL"})
        decision, reason = p.risk_filter(left, right)
        self.assertEqual(decision, "VARIANT")
        self.assertIn("oxidation", reason)

    def test_non_transitive_conflict_does_not_merge_clusters(self):
        features = {
            key: p.extract_features(key, {"entity_name": name, "entity_type": "MATERIAL"})
            for key, name in (("a", "alpha"), ("b", "alpha material"), ("c", "gamma"))
        }
        decisions = [
            {"pair_id": p._pair_id("a", "b"), "left_id": "a", "right_id": "b", "decision": "ALIAS", "confidence": 0.99, "status": "ok", "reason": "alias"},
            {"pair_id": p._pair_id("b", "c"), "left_id": "b", "right_id": "c", "decision": "SAME_ENTITY", "confidence": 0.98, "status": "ok", "reason": "same"},
            {"pair_id": p._pair_id("a", "c"), "left_id": "a", "right_id": "c", "decision": "DIFFERENT", "confidence": 0.99, "status": "ok", "reason": "different"},
        ]
        clusters, accepted, rejected = p.conservative_clusters(features, decisions)
        self.assertIn(sorted(["a", "b"]), clusters)
        self.assertIn(["c"], clusters)
        self.assertEqual(len(accepted), 1)
        self.assertEqual(len(rejected), 1)

    def test_relationship_vector_id_is_set_based(self):
        import importlib.util
        import types
        utils_path = Path(__file__).resolve().parents[1] / "hyperrag" / "utils.py"
        spec = importlib.util.spec_from_file_location("posthoc_test_hyperrag_utils", utils_path)
        assert spec and spec.loader
        utils = importlib.util.module_from_spec(spec)
        inserted_tiktoken_stub = "tiktoken" not in sys.modules
        if inserted_tiktoken_stub:
            sys.modules["tiktoken"] = types.ModuleType("tiktoken")
        try:
            spec.loader.exec_module(utils)
        finally:
            if inserted_tiktoken_stub:
                sys.modules.pop("tiktoken", None)
        relationship_vector_id = utils.relationship_vector_id

        self.assertEqual(relationship_vector_id(["z", "a"]), relationship_vector_id(["a", "z"]))
        self.assertNotEqual(relationship_vector_id(["a", "b"]), relationship_vector_id(["a", "b"], surface=True))

    def test_graph_rewrite_preserves_sources_and_merges_duplicate_edges(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            work = root / "work"
            source.mkdir()
            work.mkdir()
            docs = {"RFB_001": {"content": "paper"}}
            chunks = {
                "RFB_001_CHK_001": {"content": "alpha evidence", "full_doc_id": "RFB_001"},
                "RFB_001_CHK_002": {"content": "beta evidence", "full_doc_id": "RFB_001"},
            }
            (source / "kv_store_full_docs.json").write_text(json.dumps(docs), encoding="utf-8")
            (source / "kv_store_text_chunks.json").write_text(json.dumps(chunks), encoding="utf-8")
            graph = {
                "v_data": {
                    "old-a": {"entity_name": "Alpha", "entity_type": "MATERIAL", "source_chunk_id": "RFB_001_CHK_001"},
                    "old-b": {"entity_name": "Alpha material", "entity_type": "MATERIAL", "source_chunk_id": "RFB_001_CHK_002"},
                    "old-c": {"entity_name": "Gamma", "entity_type": "MATERIAL", "source_chunk_id": "RFB_001_CHK_002"},
                },
                "v_inci": {},
                "e_data": {
                    ("old-a", "old-c"): {"relation_type": "supports", "source_chunk_id": "RFB_001_CHK_001"},
                    ("old-b", "old-c"): {"relation_type": "supports", "source_chunk_id": "RFB_001_CHK_002"},
                },
            }
            (source / p.GRAPH_FILE).write_bytes(pickle.dumps(graph))
            canonical_map = {
                "entities": {
                    "old-a": {"canonical_id": "material:alpha", "canonical_name": "Alpha", "members": ["old-a", "old-b"], "aliases": ["Alpha", "Alpha material"], "merge_confidence": 0.99, "merge_reasons": ["alias"]},
                    "old-b": {"canonical_id": "material:alpha", "canonical_name": "Alpha", "members": ["old-a", "old-b"], "aliases": ["Alpha", "Alpha material"], "merge_confidence": 0.99, "merge_reasons": ["alias"]},
                    "old-c": {"canonical_id": "material:gamma", "canonical_name": "Gamma", "members": ["old-c"], "aliases": ["Gamma"], "merge_confidence": 1.0, "merge_reasons": []},
                },
                "clusters": [
                    {"canonical_id": "material:alpha", "canonical_name": "Alpha", "members": ["old-a", "old-b"], "aliases": ["Alpha", "Alpha material"], "merge_confidence": 0.99, "merge_reasons": ["alias"]},
                    {"canonical_id": "material:gamma", "canonical_name": "Gamma", "members": ["old-c"], "aliases": ["Gamma"], "merge_confidence": 1.0, "merge_reasons": []},
                ],
            }
            result = p.rewrite_graph(source, work, canonical_map)
            self.assertEqual(result["canonical_vertices"], 2)
            self.assertEqual(result["duplicate_hyperedges_merged"], 1)
            rewritten = p.load_graph(work)
            self.assertEqual(set(rewritten["v_data"]), {"material:alpha", "material:gamma"})
            self.assertEqual(len(rewritten["e_data"]), 1)
            edge_data = next(iter(rewritten["e_data"].values()))
            self.assertIn("RFB_001_CHK_001", json.dumps(edge_data))
            self.assertIn("RFB_001_CHK_002", json.dumps(edge_data))


    def test_formula_detection_rejects_acronyms_and_roman_numerals(self):
        for value in ("CV", "CF", "SOC", "III", "IV", "SPr", "NPr"):
            self.assertEqual(p._extract_formula_keys(value), [], value)
        for value in ("H2SO4", "FeCl2", "NaCl", "V2O5", "CO"):
            self.assertTrue(p._extract_formula_keys(value), value)
        self.assertEqual(p._extract_formula_keys("K4Fe(CN)6"), ["k4fe(cn)6"])

    def test_simhash_codes_match_direct_bit_encoding(self):
        norms = np.asarray([[1.0, 0.0], [0.0, 1.0], [-1.0, -1.0]], dtype=np.float32)
        projection = np.asarray([[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]], dtype=np.float32)
        codes = p._simhash_codes(norms, projection)
        expected = []
        for row in norms:
            bits = (row @ projection.T) >= 0
            expected.append(sum(int(bit) << bit_index for bit_index, bit in enumerate(bits)))
        self.assertEqual(codes.tolist(), expected)

    def test_free_description_does_not_create_identity_conflicts(self):
        feature = p.extract_features(
            "node",
            {
                "entity_name": "Nafion membrane",
                "entity_type": "MEMBRANE",
                "description": "CV testing at 80 °C for 100 cycles used carbon felt electrodes.",
            },
        )
        self.assertEqual(feature.formulas, [])
        self.assertEqual(feature.models, [])
        self.assertEqual(feature.numeric_signals, [])
        self.assertEqual(p.extract_features("n117", {"entity_name": "Nafion 117", "entity_type": "MEMBRANE"}).models, ["nafion117"])
        self.assertEqual(p.extract_features("sptpc", {"entity_name": "SPTPC-2.59", "entity_type": "MEMBRANE"}).models, ["sptpc259"])

    def test_abbreviation_match_enters_candidate_pool(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            graph = {
                "v_data": {
                    "vrfb": {"entity_name": "VRFB", "entity_type": "SYSTEM"},
                    "full": {"entity_name": "vanadium redox flow battery", "entity_type": "SYSTEM"},
                    "pfsa": {"entity_name": "PFSA", "entity_type": "POLYMER"},
                    "pfsa-full": {"entity_name": "perfluorosulfonic acid", "entity_type": "POLYMER"},
                },
                "v_inci": {},
                "e_data": {},
            }
            (cache / p.GRAPH_FILE).write_bytes(pickle.dumps(graph))
            (cache / "kv_store_text_chunks.json").write_text("{}", encoding="utf-8")
            rows = p.generate_candidates(cache, top_k=8)
            reasons = {
                frozenset((row["left_id"], row["right_id"])): set(row["candidate_reasons"])
                for row in rows
            }
            self.assertIn("abbreviation_match", reasons[frozenset(("vrfb", "full"))])
            self.assertIn("abbreviation_match", reasons[frozenset(("pfsa", "pfsa-full"))])

    def test_candidate_top_k_limits_abbreviations_but_not_exact_matches(self):
        store = {}
        for index, right_id in enumerate(("b", "c", "d"), start=1):
            pair_id = p._pair_id("a", right_id)
            store[pair_id] = {
                "pair_id": pair_id,
                "left_id": "a",
                "right_id": right_id,
                "candidate_reasons": ["abbreviation_match"],
                "scores": {"wratio": 100 - index},
            }
        for right_id in ("x", "y", "z"):
            pair_id = p._pair_id("exact", right_id)
            store[pair_id] = {
                "pair_id": pair_id,
                "left_id": "exact",
                "right_id": right_id,
                "candidate_reasons": ["normalized_exact"],
                "scores": {},
            }

        selected = p._truncate_candidates(store, top_k=1)
        abbreviation_rows = [row for row in selected if "abbreviation_match" in row["candidate_reasons"]]
        exact_rows = [row for row in selected if "normalized_exact" in row["candidate_reasons"]]
        self.assertEqual(len(abbreviation_rows), 1)
        self.assertEqual(len(exact_rows), 3)

    def test_candidate_version_change_rebuilds_and_invalidates_downstream_stages(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            work = root / "target.work"
            source.mkdir()
            work.mkdir()
            p.write_jsonl(work / "normalization_candidates.jsonl", [{"pair_id": "old"}])
            p.write_json(
                work / "normalization_state.json",
                {
                    "source_cache": str(source),
                    "stages": {
                        "candidates": {
                            "status": "completed",
                            "details": {"candidate_top_k": 8, "candidate_version": "old-version"},
                        },
                        "judge": {"status": "completed"},
                        "rewrite": {"status": "completed"},
                        "embed": {"status": "completed"},
                        "validate": {"status": "completed"},
                        "publish": {"status": "completed"},
                    },
                },
            )
            args = SimpleNamespace(resume=True, candidate_top_k=8)
            generated = [{"pair_id": "new", "left_id": "a", "right_id": "b"}]
            original = p.generate_candidates
            try:
                p.generate_candidates = lambda *args, **kwargs: generated
                result = cli._candidate_stage(source, work, args, [], [])
            finally:
                p.generate_candidates = original

            state = p._load_json_dict(work / "normalization_state.json")
            self.assertEqual(result["candidate_version"], p.CANDIDATE_VERSION)
            self.assertEqual(p.read_jsonl(work / "normalization_candidates.jsonl"), generated)
            self.assertEqual(set(state["stages"]), {"candidates"})
            self.assertEqual(
                state["stages"]["candidates"]["details"]["candidate_version"],
                p.CANDIDATE_VERSION,
            )

    def test_cli_judge_stage_reenters_core_after_completed_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            p.write_json(
                work / "normalization_state.json",
                {"stages": {"judge": {"status": "completed", "details": {"api_errors": 1}}}},
            )
            args = SimpleNamespace(
                llm_model="test-model",
                llm_base_url="https://example.invalid/v1",
                llm_max_async=1,
                llm_timeout=1,
                resume=True,
            )
            original_keys = cli._keys
            original_judge = p.judge_candidates
            calls = []

            async def fake_judge(*args, **kwargs):
                calls.append(kwargs)
                return {"candidates": 1, "pending_calls": 1, "completed_calls": 1, "api_errors": 0}

            try:
                cli._keys = lambda kind: ["unused"]
                p.judge_candidates = fake_judge
                result = asyncio.run(cli._judge_stage(work, args))
            finally:
                cli._keys = original_keys
                p.judge_candidates = original_judge

            self.assertEqual(result["completed_calls"], 1)
            self.assertEqual(len(calls), 1)
            self.assertTrue(calls[0]["resume"])

    def test_key_pool_is_strict_round_robin(self):
        async def collect():
            pool = p.AsyncKeyPool(["k1", "k2", "k3"], name="test")
            return [await pool.next() for _ in range(8)]

        self.assertEqual(asyncio.run(collect()), ["k1", "k2", "k3", "k1", "k2", "k3", "k1", "k2"])

    def test_canonical_ids_are_stable_and_collision_safe(self):
        features = {
            "a": p.extract_features("a", {"entity_name": "Alpha", "entity_type": "MATERIAL"}),
            "b": p.extract_features("b", {"entity_name": "Beta", "entity_type": "MATERIAL"}),
        }
        previous = {
            "entities": {
                "a": {"canonical_id": "material:legacy-cluster"},
                "b": {"canonical_id": "material:legacy-cluster"},
            }
        }
        payload = p._build_map_payload(
            features,
            [["a"], ["b"]],
            [],
            p.AliasRegistry(),
            merge_confidence=0.90,
            previous=previous,
        )
        output_ids = {
            payload["entities"]["a"]["canonical_id"],
            payload["entities"]["b"]["canonical_id"],
        }
        self.assertEqual(len(output_ids), 2)
        self.assertIn("material:legacy-cluster", output_ids)

    def test_api_error_is_retried_on_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            work = root / "work"
            source.mkdir()
            work.mkdir()
            chunks = {"RFB_001_CHK_001": {"content": "VRFB means vanadium redox flow battery.", "full_doc_id": "RFB_001"}}
            docs = {"RFB_001": {"content": "A VRFB paper"}}
            graph = {
                "v_data": {
                    "vrfb": {"entity_name": "VRFB", "entity_type": "SYSTEM", "source_chunk_id": "RFB_001_CHK_001"},
                    "full": {"entity_name": "vanadium redox flow battery", "entity_type": "SYSTEM", "source_chunk_id": "RFB_001_CHK_001"},
                },
                "v_inci": {},
                "e_data": {},
            }
            (source / p.GRAPH_FILE).write_bytes(pickle.dumps(graph))
            (source / "kv_store_text_chunks.json").write_text(json.dumps(chunks), encoding="utf-8")
            (source / "kv_store_full_docs.json").write_text(json.dumps(docs), encoding="utf-8")
            left = p.extract_features("vrfb", graph["v_data"]["vrfb"]).to_dict()
            right = p.extract_features("full", graph["v_data"]["full"]).to_dict()
            pair = {
                "pair_id": p._pair_id("vrfb", "full"),
                "left_id": "vrfb",
                "right_id": "full",
                "candidate_reasons": ["abbreviation_match"],
                "scores": {},
                "left_features": left,
                "right_features": right,
                "rule_decision": None,
                "rule_reasons": [],
            }
            p.write_jsonl(work / "normalization_candidates.jsonl", [pair])
            p.write_json(work / "normalization_state.json", {"source_cache": str(source)})
            prompt, _ = p._context_for_pair(pair, graph, chunks, docs)
            context_hash = p.json_hash({"pair": pair["pair_id"], "prompt": prompt})
            judgement_key = ":".join((pair["pair_id"], p.PROMPT_VERSION, "test-model", context_hash))
            p.write_jsonl(work / "normalization_decisions.jsonl", [{
                "pair_id": pair["pair_id"], "judgement_key": judgement_key, "left_id": "vrfb", "right_id": "full",
                "status": "api_error", "decision": "UNCERTAIN", "confidence": 0.0,
            }])

            original = p._call_llm_judgement
            calls = []

            async def fake_call(candidate, *args, **kwargs):
                calls.append(candidate["pair_id"])
                return {
                    "pair_id": candidate["pair_id"], "prompt_version": p.PROMPT_VERSION, "model": "test-model",
                    "context_hash": context_hash, "status": "ok", "api_attempts": 1, "decision": "ALIAS",
                    "canonical_name": "vanadium redox flow battery", "preferred_name_source": "B", "confidence": 0.99,
                    "reason": "The acronym and expanded form denote the same battery system.",
                    "evidence_chunk_ids": ["RFB_001_CHK_001"],
                }

            try:
                p._call_llm_judgement = fake_call
                result = asyncio.run(p.judge_candidates(
                    work, llm_model="test-model", llm_base_url="https://example.invalid/v1",
                    llm_keys=["unused"], max_async=1, timeout=1, resume=True,
                ))
            finally:
                p._call_llm_judgement = original
            self.assertEqual(result["pending_calls"], 1)
            self.assertEqual(calls, [pair["pair_id"]])

if __name__ == "__main__":
    unittest.main()
