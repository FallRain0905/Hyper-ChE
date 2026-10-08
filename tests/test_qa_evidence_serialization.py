import unittest

from scripts import run_qa_smoke_llm as runner


class LosslessEvidenceSerializationTests(unittest.TestCase):
    def test_lossless_format_preserves_binding_and_source_span(self):
        item = {
            "id": "efu-1",
            "source_chunk_id": "RFB_001_CHK_002",
            "relation_type": "ATOMIC_MEASUREMENT",
            "canonical_vertices": ["membrane:nafion_117", "measurement:area_resistance"],
            "atomic_entity": "Nafion 117",
            "atomic_metric": "area resistance",
            "atomic_value": "1.65",
            "atomic_unit": "ohm cm2",
            "atomic_condition": "25 C",
            "source_span": "Nafion 117; area resistance = 1.65 ohm cm2; 25 C",
            "readable_evidence": "Nafion 117 area resistance = 1.65 ohm cm2 at 25 C",
        }
        block = runner.format_lossless_evidence_block(1, item, "area resistance of Nafion 117")
        self.assertIn("Source chunk: RFB_001_CHK_002", block)
        self.assertIn("subject=Nafion 117; metric=area resistance; value=1.65; unit=ohm cm2; condition=25 C", block)
        self.assertIn("Nafion 117; area resistance = 1.65 ohm cm2; 25 C", block)

    def test_context_format_switch_keeps_ids_and_budget(self):
        item = {"id": "e1", "relation_type": "TEXT_CHUNK", "readable_evidence": "metric = 1.0 at 25 C"}
        runner.EVIDENCE_BUDGET_CHARS = 500
        legacy = runner.format_evidence_context("metric at 25 C", [item], evidence_format="legacy")
        lossless = runner.format_evidence_context("metric at 25 C", [item], evidence_format="lossless")
        self.assertIn("Evidence 1", legacy)
        self.assertIn("Evidence 1", lossless)
        self.assertIn("Source spans:", lossless)


if __name__ == "__main__":
    unittest.main()
