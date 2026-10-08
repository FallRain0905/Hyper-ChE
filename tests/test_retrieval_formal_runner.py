import unittest

from scripts import run_retrieval_formal_four_groups as runner


class RetrievalFormalRunnerTests(unittest.TestCase):
    def test_upstream_llm_uses_length_only_token_fallback(self):
        class FakePool:
            def __init__(self):
                self.calls = []

            def complete_json(self, _prompt, *, max_tokens, max_retries):
                self.calls.append((max_tokens, max_retries))
                if max_tokens == 4096:
                    raise RuntimeError(
                        "LLM call failed after retries: legacy:RuntimeError:"
                        "LLM returned empty content: finish_reason='length'"
                    )
                return {"high_level_keywords": ["battery"]}

        pool = FakePool()
        result = runner.complete_upstream_query_json(
            pool,
            "prompt",
            primary_max_tokens=4096,
            length_fallback_max_tokens=16384,
            max_retries=5,
        )
        self.assertEqual(result, {"high_level_keywords": ["battery"]})
        self.assertEqual(pool.calls, [(4096, 1), (16384, 5)])

    def test_upstream_llm_does_not_raise_budget_for_connection_errors(self):
        class FakePool:
            def __init__(self):
                self.calls = []

            def complete_json(self, _prompt, *, max_tokens, max_retries):
                self.calls.append((max_tokens, max_retries))
                if len(self.calls) < 3:
                    raise RuntimeError("LLM call failed after retries: APIConnectionError")
                return {"low_level_keywords": ["electrolyte"]}

        pool = FakePool()
        result = runner.complete_upstream_query_json(
            pool,
            "prompt",
            primary_max_tokens=4096,
            length_fallback_max_tokens=16384,
            max_retries=5,
        )
        self.assertEqual(result, {"low_level_keywords": ["electrolyte"]})
        self.assertEqual(pool.calls, [(4096, 1), (4096, 1), (4096, 1)])

    def test_protocol_marks_upstream_hyper_query_retrieval(self):
        self.assertEqual(
            runner.PROTOCOL_VERSION,
            'retrieval-formal-v4-chem-domain-balanced-hyper-query',
        )

    def test_hypergraph_systems_use_upstream_hyper_query(self):
        systems = runner.selected_systems('all')
        for name in ('original_hypergraph', 'chem_prompt_hypergraph'):
            self.assertEqual(systems[name]['retriever'], 'upstream_hyper_query')
        self.assertEqual(systems['original_hypergraph']['query_domain'], 'default')
        self.assertEqual(systems['chem_prompt_hypergraph']['query_domain'], 'flow_battery')
        self.assertEqual(systems['chem_prompt_graph']['retriever'], 'structured_graph_hybrid_v1')

    def test_all_excludes_optional_naive_dense_system(self):
        self.assertNotIn("naive_dense_rag", runner.selected_systems("all"))
        self.assertNotIn(
            "chem_prompt_hypergraph_chunk_rerank", runner.selected_systems("all")
        )

    def test_all_plus_chunk_rerank_preserves_baselines_and_adds_ablation(self):
        systems = runner.selected_systems("all_plus_chunk_rerank")
        self.assertEqual(list(systems)[:4], list(runner.GROUPS))
        self.assertEqual(
            systems["chem_prompt_hypergraph_chunk_rerank"]["retriever"],
            "upstream_hyper_query_chunk_dense_rerank",
        )
        self.assertEqual(
            runner.protocol_version_for_systems(systems),
            "retrieval-formal-v5-upstream-hyper-query-chunk-rerank-ablation",
        )

    def test_naive_dense_system_requires_explicit_selection(self):
        systems = runner.selected_systems("naive_dense_rag")
        self.assertEqual(list(systems), ["naive_dense_rag"])
        self.assertEqual(
            runner.protocol_version_for_systems(systems),
            "retrieval-formal-v2-naive-dense-optional-v1",
        )

    def test_naive_retrieve_emits_shared_pool_compatible_rows(self):
        class FakeRetriever:
            chunks = {
                "RFB_001_CHK_001": {
                    "content": "full chunk",
                    "source_doc_id": "RFB_001",
                    "source_file": "001_full.md",
                }
            }

            @staticmethod
            def search(_query, _top_k):
                return [
                    {
                        "id": "RFB_001_CHK_001",
                        "retrieval_score": 0.75,
                        "dense_rank": 1,
                    }
                ]

        rows = runner.naive_retrieve(
            query={"query_id": "Q1", "question": "question"},
            system="naive_dense_rag",
            retriever=FakeRetriever(),
            top_k=20,
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["candidate_id"], "naive_dense_rag:RFB_001_CHK_001")
        self.assertEqual(rows[0]["retrieval_method"], "naive_chunk_dense")
        self.assertEqual(rows[0]["retrieval_channels"], ["chunk_dense"])
        self.assertEqual(rows[0]["supporting_edge_ids"], [])

    def test_retrieval_diagnostics_tracks_channels_arities_and_chunks(self):
        diagnostics = runner.retrieval_diagnostics(
            [
                {
                    'query_id': 'Q1',
                    'candidates': [
                        {
                            'content': 'full chunk',
                            'retrieval_channels': ['relationship_dense', 'entity_expansion'],
                            'supporting_edge_ids': ['A|B|C'],
                            'supporting_arities': [3],
                        },
                        {
                            'content': 'another chunk',
                            'retrieval_channels': ['relationship_bm25'],
                            'supporting_edge_ids': ['A|B'],
                            'supporting_arities': [2],
                        },
                    ],
                }
            ]
        )
        self.assertEqual(diagnostics['candidate_count'], 2)
        self.assertEqual(diagnostics['full_chunk_reconstruction_rate'], 1.0)
        self.assertEqual(diagnostics['channel_query_counts']['relationship_dense'], 1)
        self.assertEqual(diagnostics['arity_candidate_counts'], {'2': 1, '3': 1})
        self.assertEqual(diagnostics['high_order_candidate_count'], 1)
        self.assertEqual(diagnostics['queries_with_high_order_evidence'], 1)

    def test_gold_diagnostics_distinguish_candidate_and_topk_loss(self):
        audit = {
            "branch_rank_by_chunk": {
                "entity": {"RFB_001_CHK_001": 12},
                "relation": {},
            },
            "balanced_selected_chunk_ids": ["RFB_002_CHK_001"],
            "posthoc_reranking": "chunk_dense_cosine_only",
        }
        runner.add_gold_diagnostics(
            {
                "retrievable": True,
                "source_doc_id": "RFB_001",
                "gold_chunk_ids": ["RFB_001_CHK_001"],
            },
            audit,
            [
                {
                    "chunk_id": "RFB_001_CHK_002",
                    "retrieval_rank": 1,
                    "source_doc_ids": ["RFB_001"],
                }
            ],
        )
        gold = audit["gold_diagnostics"]
        self.assertTrue(gold["candidate_union_hit"])
        self.assertFalse(gold["balanced_topk_hit"])
        self.assertFalse(gold["final_topk_hit"])
        self.assertTrue(gold["source_document_hit"])
        self.assertEqual(gold["loss_stage"], "chunk_dense_rerank_or_topk")


if __name__ == '__main__':
    unittest.main()
