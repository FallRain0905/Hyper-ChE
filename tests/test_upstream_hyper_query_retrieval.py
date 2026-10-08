import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import numpy as np

from hyperrag import operate
from hyperrag.base import QueryParam
from scripts.upstream_hyper_query_retrieval import (
    ChunkRerankedUpstreamHyperQueryRetriever,
    TextUnitChunkMapper,
    balanced_branch_merge,
    candidate_union,
)


class TextUnitChunkMapperTests(unittest.TestCase):
    def setUp(self):
        self.mapper = TextUnitChunkMapper(
            {
                "RFB_001_CHK_001": {"content": "alpha beta", "source_doc_id": "RFB_001"},
                "RFB_001_CHK_002": {"content": "gamma\n delta", "source_doc_id": "RFB_001"},
                "RFB_002_CHK_001": {"content": "same content", "source_doc_id": "RFB_002"},
                "RFB_003_CHK_001": {"content": "same content", "source_doc_id": "RFB_003"},
            }
        )

    def test_exact_and_whitespace_mapping_preserve_order(self):
        mapped, audit = self.mapper.map_text_units(
            [
                {"content": "gamma delta"},
                {"content": "alpha beta"},
                {"content": "alpha beta"},
            ],
            top_k=20,
        )
        self.assertEqual(
            [item["chunk_id"] for item in mapped],
            ["RFB_001_CHK_002", "RFB_001_CHK_001"],
        )
        self.assertEqual(mapped[0]["mapping_method"], "whitespace_normalized")
        self.assertEqual(audit["duplicate_text_unit_count"], 1)

    def test_unmatched_and_ambiguous_are_audited_not_guessed(self):
        mapped, audit = self.mapper.map_text_units(
            [{"content": "missing"}, {"content": "same content"}],
            top_k=20,
        )
        self.assertEqual(mapped, [])
        self.assertEqual(len(audit["unmatched_text_units"]), 1)
        self.assertEqual(len(audit["ambiguous_text_units"]), 1)
        self.assertEqual(
            audit["ambiguous_text_units"][0]["candidate_chunk_ids"],
            ["RFB_002_CHK_001", "RFB_003_CHK_001"],
        )

    def test_top_k_truncates_after_mapping_without_reordering(self):
        mapped, audit = self.mapper.map_text_units(
            [{"content": "alpha beta"}, {"content": "gamma\n delta"}],
            top_k=1,
        )
        self.assertEqual([item["chunk_id"] for item in mapped], ["RFB_001_CHK_001"])
        self.assertEqual(audit["mapped_chunk_count"], 2)
        self.assertEqual(audit["returned_chunk_count"], 1)

    def test_balanced_merge_interleaves_branches_and_preserves_branch_order(self):
        entity = [
            {"chunk_id": "E1"},
            {"chunk_id": "E2"},
        ]
        relation = [
            {"chunk_id": "R1"},
            {"chunk_id": "R2"},
        ]
        merged, audit = balanced_branch_merge(
            entity,
            relation,
            top_k=4,
            entity_quota=2,
            relation_quota=2,
        )
        self.assertEqual(
            [item["chunk_id"] for item in merged],
            ["E1", "R1", "E2", "R2"],
        )
        self.assertEqual(
            [item["chunk_id"] for item in merged if item["retrieval_branch"] == "entity"],
            ["E1", "E2"],
        )
        self.assertEqual(
            [item["chunk_id"] for item in merged if item["retrieval_branch"] == "relation"],
            ["R1", "R2"],
        )
        self.assertEqual(audit["returned_entity_count"], 2)
        self.assertEqual(audit["returned_relation_count"], 2)

    def test_balanced_merge_deduplicates_and_fills_from_available_branch(self):
        entity = [{"chunk_id": value} for value in ("E1", "E2", "E3", "E4")]
        relation = [{"chunk_id": value} for value in ("E1", "R1")]
        merged, audit = balanced_branch_merge(
            entity,
            relation,
            top_k=4,
            entity_quota=1,
            relation_quota=2,
        )
        self.assertEqual(
            [item["chunk_id"] for item in merged],
            ["E1", "R1", "E2", "E3"],
        )
        self.assertEqual(len({item["chunk_id"] for item in merged}), 4)
        self.assertEqual(audit["returned_entity_count"], 3)
        self.assertEqual(audit["returned_relation_count"], 1)
        self.assertEqual(audit["cross_branch_duplicate_count"], 1)

    def test_candidate_union_keeps_all_unique_chunks_without_quota(self):
        merged = candidate_union(
            [{"chunk_id": "A"}, {"chunk_id": "B"}],
            [{"chunk_id": "B"}, {"chunk_id": "C"}],
        )
        self.assertEqual([item["chunk_id"] for item in merged], ["A", "B", "C"])
        self.assertEqual([item["retrieval_branch"] for item in merged], ["entity", "entity", "relation"])


class HyperQueryBranchContextTests(unittest.IsolatedAsyncioTestCase):
    async def test_json_context_exposes_entity_and_relation_text_units(self):
        entity_context = {
            "context": None,
            "entities": [],
            "hyperedges": [],
            "text_units": [{"content": "entity evidence"}],
        }
        relation_context = {
            "context": None,
            "entities": [],
            "hyperedges": [],
            "text_units": [{"content": "relation evidence"}],
        }
        llm = AsyncMock(return_value="{}")
        with (
            patch.object(operate, "_parse_query_keywords", return_value=("entity", "relation")),
            patch.object(
                operate,
                "_build_entity_query_context",
                AsyncMock(return_value=entity_context),
            ),
            patch.object(
                operate,
                "_build_relation_query_context",
                AsyncMock(return_value=relation_context),
            ),
        ):
            context = await operate.hyper_query(
                "question",
                None,
                None,
                None,
                None,
                QueryParam(only_need_context=True, return_type="json"),
                {"domain": "default", "llm_model_func": llm},
            )

        self.assertEqual(context["entity_text_units"], entity_context["text_units"])
        self.assertEqual(context["relation_text_units"], relation_context["text_units"])
        self.assertEqual(context["entity_keywords"], "entity")
        self.assertEqual(context["relation_keywords"], "relation")
        self.assertEqual(
            [item["content"] for item in context["text_units"]],
            ["entity evidence", "relation evidence"],
        )


class ChunkRerankTests(unittest.IsolatedAsyncioTestCase):
    async def test_dense_rerank_uses_complete_branch_union(self):
        retriever = object.__new__(ChunkRerankedUpstreamHyperQueryRetriever)
        retriever.embedding = SimpleNamespace(embedding_dim=2)
        retriever.embedding_func = lambda _text: np.asarray([1.0, 0.0], dtype=np.float32)
        retriever.chunk_vector_ids = ["A", "B", "C"]
        retriever.chunk_vector_index = {"A": 0, "B": 1, "C": 2}
        retriever.chunk_matrix = np.asarray(
            [[0.1, 0.995], [0.8, 0.6], [1.0, 0.0]], dtype=np.float32
        )
        retriever.graph_top_k = 60
        retriever.query_domain = "flow_battery"
        retriever.query_prompt_source = "hyperrag/domains/flow_battery/query_keywords.txt"
        retriever.entity_quota = 1
        retriever.relation_quota = 1
        retriever._retrieve_branch_candidates = AsyncMock(
            return_value=(
                [
                    {"chunk_id": "A", "chunk": {"content": "a"}, "text_unit_index": 0},
                    {"chunk_id": "C", "chunk": {"content": "c"}, "text_unit_index": 1},
                ],
                [{"chunk_id": "B", "chunk": {"content": "b"}, "text_unit_index": 0}],
                {
                    "entity_keywords": "C",
                    "relation_keywords": "performance",
                    "branch_rank_by_chunk": {
                        "entity": {"A": 1, "C": 2},
                        "relation": {"B": 1},
                    },
                    "mapped_entity_count": 2,
                    "mapped_relation_count": 1,
                },
            )
        )

        selected, audit = await retriever._asearch("question", top_k=2)

        self.assertEqual([item["chunk_id"] for item in selected], ["C", "B"])
        self.assertEqual(audit["candidate_union_count"], 3)
        self.assertEqual(audit["posthoc_reranking"], "chunk_dense_cosine_only")
        self.assertEqual(audit["balanced_selected_chunk_ids"], ["A", "B"])


if __name__ == "__main__":
    unittest.main()
