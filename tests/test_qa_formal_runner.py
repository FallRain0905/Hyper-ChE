import base64
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from scripts import run_qa_formal_llm as runner


class QAFormalRunnerProtocolTests(unittest.TestCase):
    @staticmethod
    def _client_pool_for(model):
        pool = object.__new__(runner.FormalLLMClientPool)
        pool.timeout = 600.0
        pool._next_entry = lambda: {
            "provider": "test",
            "api_key": "test-key",
            "base_url": "https://example.invalid/v1",
            "model": model,
        }
        return pool

    @staticmethod
    def _response(content, *, reasoning_content=None, finish_reason="stop"):
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=content, reasoning_content=reasoning_content),
                    finish_reason=finish_reason,
                )
            ],
            usage=SimpleNamespace(completion_tokens=12, total_tokens=34),
        )

    def test_all_selects_exactly_the_four_active_systems(self):
        groups = runner.selected_groups("all")
        self.assertEqual(
            list(groups),
            [
                "original_hypergraph",
                "chem_prompt_graph",
                "chem_prompt_hypergraph",
                "hybrid_rag_baseline",
            ],
        )
        self.assertNotIn("chem_norm_hypergraph", groups)
        self.assertNotIn("naive_dense_rag", groups)

    def test_naive_dense_group_requires_explicit_selection(self):
        groups = runner.selected_groups("naive_dense_rag")
        self.assertEqual(list(groups), ["naive_dense_rag"])
        self.assertEqual(groups["naive_dense_rag"]["retriever"], "naive_chunk_dense")
        self.assertEqual(
            runner.protocol_version_for_groups(groups),
            "qa-formal-v3-naive-dense-optional-v1",
        )

    def test_protocol_version_marks_four_group_design(self):
        self.assertEqual(
            runner.FORMAL_PROTOCOL_VERSION,
            'qa-formal-v3-structured-retrieval-four-groups',
        )

    def test_graph_groups_use_structured_retrieval(self):
        groups = runner.selected_groups('all')
        for name in ('original_hypergraph', 'chem_prompt_graph', 'chem_prompt_hypergraph'):
            self.assertEqual(groups[name]['retriever'], 'structured_graph_hybrid_v1')

    def test_naive_dense_retriever_uses_only_chunk_cosine_with_stable_order(self):
        class FakeEmbeddingPool:
            dimension = 2

            @staticmethod
            def embed(_text):
                return np.asarray([1.0, 0.0], dtype=np.float32)

        with tempfile.TemporaryDirectory() as temp_dir:
            cache_dir = Path(temp_dir)
            chunks = {
                "RFB_001_CHK_002": {"content": "second"},
                "RFB_001_CHK_001": {"content": "first"},
                "RFB_001_CHK_003": {"content": "below threshold"},
            }
            (cache_dir / "kv_store_text_chunks.json").write_text(json.dumps(chunks), encoding="utf-8")
            matrix = np.asarray([[1.0, 0.0], [1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
            payload = {
                "embedding_dim": 2,
                "data": [
                    {"__id__": "RFB_001_CHK_002"},
                    {"__id__": "RFB_001_CHK_001"},
                    {"__id__": "RFB_001_CHK_003"},
                ],
                "matrix": base64.b64encode(matrix.tobytes()).decode("ascii"),
            }
            (cache_dir / "vdb_chunks.json").write_text(json.dumps(payload), encoding="utf-8")

            retriever = runner.NaiveDenseRetriever(cache_dir, FakeEmbeddingPool(), cosine_threshold=0.2)
            results = retriever.search("query", 5)

        self.assertEqual([row["id"] for row in results], ["RFB_001_CHK_001", "RFB_001_CHK_002"])
        self.assertTrue(all(row["retrieval_channels"] == ["chunk_dense"] for row in results))
        self.assertTrue(all(row["bm25_rank"] is None for row in results))
        self.assertFalse(hasattr(retriever, "document_frequency"))
        self.assertFalse(hasattr(retriever, "term_frequencies"))

    def test_kimi_disables_thinking_and_uses_json_mode_without_sampling_overrides(self):
        calls = []
        response = self._response('{"answer": "ok"}')

        class FakeOpenAI:
            def __init__(self, **_kwargs):
                self.chat = SimpleNamespace(
                    completions=SimpleNamespace(create=lambda **kwargs: calls.append(kwargs) or response)
                )

        pool = self._client_pool_for("kimi-k2.6")
        with patch.object(runner, "OpenAI", FakeOpenAI):
            result = pool.complete_json("prompt", temperature=1.0, top_p=0.95, max_retries=1)

        self.assertEqual(result, {"answer": "ok"})
        self.assertEqual(calls[0]["extra_body"], {"thinking": {"type": "disabled"}})
        self.assertEqual(calls[0]["response_format"], {"type": "json_object"})
        self.assertNotIn("temperature", calls[0])
        self.assertNotIn("top_p", calls[0])

    def test_non_kimi_keeps_sampling_parameters(self):
        calls = []
        response = self._response('{"answer": "ok"}')

        class FakeOpenAI:
            def __init__(self, **_kwargs):
                self.chat = SimpleNamespace(
                    completions=SimpleNamespace(create=lambda **kwargs: calls.append(kwargs) or response)
                )

        pool = self._client_pool_for("some-json-model")
        with patch.object(runner, "OpenAI", FakeOpenAI):
            pool.complete_json("prompt", temperature=0.2, top_p=0.8, max_retries=1)

        self.assertEqual(calls[0]["temperature"], 0.2)
        self.assertEqual(calls[0]["top_p"], 0.8)
        self.assertNotIn("extra_body", calls[0])

    def test_formal_judge_abstained_echo_is_normalized_to_generator_state(self):
        value = {
            "quality_label": "GOOD",
            "good": True,
            "satisfactory_or_better": True,
            "key_point_coverage": 1.0,
            "covered_key_points": ["point"],
            "missing_key_points": [],
            "hallucinated": False,
            "abstained": False,
            "citation_support_score": 1.0,
            "unsupported_claims_found": [],
            "rationale": "The answer correctly abstains.",
        }

        valid, reason = runner.validate_formal_judgment(value, ["point"], True)

        self.assertTrue(valid, reason)
        self.assertTrue(value["abstained"])

    def test_empty_content_is_reported_instead_of_becoming_empty_json(self):
        response = self._response("", reasoning_content="long reasoning", finish_reason="length")

        class FakeOpenAI:
            def __init__(self, **_kwargs):
                self.chat = SimpleNamespace(
                    completions=SimpleNamespace(create=lambda **_kwargs: response)
                )

        pool = self._client_pool_for("kimi-k2.6")
        with patch.object(runner, "OpenAI", FakeOpenAI):
            with self.assertRaisesRegex(RuntimeError, "LLM call failed after retries") as raised:
                pool.complete_json("prompt", max_retries=1)

        self.assertIn("LLM returned empty content", str(raised.exception))
        self.assertIn("finish_reason='length'", str(raised.exception))
        self.assertIn("reasoning_chars=14", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
