from __future__ import annotations

from pathlib import Path
import unittest

from hyperche.normalization import (
    AliasRegistry,
    EntityNormalizer,
    HyperedgeRewriter,
    NegativeRules,
    UnitParser,
    normalize_entities_for_extraction,
    normalize_text,
    normalize_text_for_match,
)
from hyperche.normalization.pipeline import normalize_entities_for_extraction_async


CONFIG_ROOT = Path(__file__).resolve().parents[1] / "configs" / "normalization"
REGISTRY_PATH = CONFIG_ROOT / "alias_registry.yaml"
NEGATIVE_PATHS = [
    CONFIG_ROOT / "negative_pairs.yaml",
    CONFIG_ROOT / "high_risk_rules.yaml",
    CONFIG_ROOT / "generic_terms.yaml",
]


class NormalizationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = AliasRegistry.from_yaml_files([REGISTRY_PATH])
        self.rules = NegativeRules(self.registry, NEGATIVE_PATHS)
        self.normalizer = EntityNormalizer(self.registry, negative_rules=self.rules)

    def test_text_normalization_for_match(self) -> None:
        self.assertEqual(normalize_text("  ≥100 mA cm−2 "), ">=100 ma/cm2")
        self.assertEqual(normalize_text_for_match("OH radical"), "ohradical")
        self.assertEqual(normalize_text_for_match("hydroxyl radical"), "ohradical")
        self.assertEqual(normalize_text_for_match("BaTiO₃"), "batio3")
        self.assertNotEqual(normalize_text_for_match("VO²⁺"), normalize_text_for_match("VO₂⁺"))
        self.assertNotEqual(normalize_text_for_match("V(IV)"), normalize_text_for_match("V(V)"))

    def test_unit_parser_range_and_comparison(self) -> None:
        parser = UnitParser()
        parsed = parser.parse_dict("≥100 mA cm−2", hint="current density")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["operator"], ">=")
        self.assertEqual(parsed["value"], 100.0)
        self.assertEqual(parsed["unit"], "mA/cm2")

        parsed_range = parser.parse_dict("40–68 kHz", hint="ultrasound frequency")
        self.assertIsNotNone(parsed_range)
        self.assertEqual(parsed_range["operator"], "range")
        self.assertEqual(parsed_range["min_value"], 40.0)
        self.assertEqual(parsed_range["max_value"], 68.0)

    def test_required_exact_merges(self) -> None:
        samples = [
            ("PFOA", "PFAS_TARGET", "pfas:pfoa"),
            ("perfluorooctanoic acid", "PFAS_TARGET", "pfas:pfoa"),
            ("C8", "PFAS_TARGET", "pfas:pfoa"),
            ("PFOS", "PFAS_TARGET", "pfas:pfos"),
            ("C8S", "PFAS_TARGET", "pfas:pfos"),
            ("BaTiO₃", "CATALYST_MATERIAL", "catalyst:batio3"),
            ("BTO", "CATALYST_MATERIAL", "catalyst:batio3"),
            ("·OH", "ACTIVE_SPECIES", "active_species:oh_radical"),
            ("hydroxyl radical", "ACTIVE_SPECIES", "active_species:oh_radical"),
        ]
        for name, entity_type, canonical_id in samples:
            with self.subTest(name=name):
                result = self.normalizer.normalize_entity({"name": name, "type": entity_type})
                self.assertEqual(result.decision, "MERGE")
                self.assertEqual(result.canonical_id, canonical_id)

    def test_negative_rules_keep_high_risk_entities_distinct(self) -> None:
        cases = [
            ("PFOA", "PFAS_TARGET", "pfas:pfos"),
            ("PFOS", "PFAS_TARGET", "pfas:pfoa"),
            ("Nafion 117", "MEMBRANE", "membrane:nafion_212"),
            ("V(IV)", "ACTIVE_SPECIES", "active_species:v_v"),
            ("Pt/BTO/BO", "CATALYST_MATERIAL", "catalyst:batio3"),
        ]
        for mention, entity_type, candidate_id in cases:
            with self.subTest(mention=mention):
                blocked, _ = self.rules.violates_negative_rule(mention, candidate_id)
                self.assertTrue(blocked)

    def test_specific_variants_do_not_collapse(self) -> None:
        pt_bto = self.normalizer.normalize_entity({"name": "Pt/BTO/BO", "type": "CATALYST_MATERIAL"})
        self.assertEqual(pt_bto.canonical_id, "catalyst:pt_bto_bo")
        self.assertNotEqual(pt_bto.canonical_id, "catalyst:batio3")

        nafion117 = self.normalizer.normalize_entity({"name": "Nafion 117", "type": "MEMBRANE"})
        nafion212 = self.normalizer.normalize_entity({"name": "Nafion 212", "type": "MEMBRANE"})
        self.assertNotEqual(nafion117.canonical_id, nafion212.canonical_id)

        v4 = self.normalizer.normalize_entity({"name": "V(IV)", "type": "ACTIVE_SPECIES"})
        v5 = self.normalizer.normalize_entity({"name": "V(V)", "type": "ACTIVE_SPECIES"})
        self.assertNotEqual(v4.canonical_id, v5.canonical_id)

        snpbi = self.normalizer.normalize_entity({"name": "SNPBI-1.42", "type": "MEMBRANE"})
        self.assertNotEqual(snpbi.canonical_id, "membrane:pbi")

    def test_false_merge_regression_list(self) -> None:
        cases = [
            ("area resistance", "METRIC", "metric:ce"),
            ("ohmic resistance", "METRIC", "metric:ce"),
            ("charge-transfer resistance", "METRIC", "metric:ce"),
            ("surface roughness", "METRIC", "metric:ce"),
            ("vanadium concentration", "CONDITION", "metric:ce"),
            ("electrode", "ELECTRODE", "electrode:c_c"),
        ]
        for mention, entity_type, forbidden_id in cases:
            with self.subTest(mention=mention):
                result = self.normalizer.normalize_entity({"name": mention, "type": entity_type})
                self.assertNotEqual(result.canonical_id, forbidden_id)
                if result.method == "fuzzy_auto_match":
                    self.assertNotEqual(result.canonical_id, forbidden_id)

    def test_numeric_metric_and_condition_instances_are_preserved(self) -> None:
        metric = self.normalizer.normalize_entity({"name": "EE 74.8%", "type": "METRIC"})
        self.assertEqual(metric.canonical_id, "metric:ee")
        self.assertEqual(metric.node_id, "measurement:ee_74_8_percent")
        self.assertEqual(metric.value, 74.8)

        iec = self.normalizer.normalize_entity({"name": "IEC 1.42 mmol/g", "type": "METRIC"})
        self.assertEqual(iec.canonical_id, "metric:ion_exchange_capacity")
        self.assertEqual(iec.node_id, "measurement:ion_exchange_capacity_1_42_mmol_g")
        self.assertEqual(iec.value, 1.42)

        angle = self.normalizer.normalize_entity({"name": "contact angle 92.8?", "type": "METRIC"})
        self.assertEqual(angle.canonical_id, "metric:contact_angle")
        self.assertEqual(angle.node_id, "measurement:contact_angle_92_8_degree")
        self.assertEqual(angle.value, 92.8)

        condition = self.normalizer.normalize_entity({"name": "120 mA cm?2", "type": "CONDITION"})
        self.assertEqual(condition.canonical_id, "condition:current_density")
        self.assertEqual(condition.node_id, "condition:current_density_120_ma_cm2")
        self.assertEqual(condition.value, 120.0)

    def test_duplicate_metric_mentions_keep_distinct_instances(self) -> None:
        entities, _ = normalize_entities_for_extraction(
            [
                {"name": "EE", "type": "METRIC", "value": 79.2, "unit": "%"},
                {"name": "EE", "type": "METRIC", "value": 74.8, "unit": "%"},
            ],
            domain="flow_battery",
        )
        names = {item["name"] for item in entities}
        self.assertIn("measurement:ee_79_2_percent", names)
        self.assertIn("measurement:ee_74_8_percent", names)

    def test_contact_angle_multi_value_expands_measurements(self) -> None:
        entities, _ = normalize_entities_for_extraction(
            [
                {
                    "name": "contact angle",
                    "type": "METRIC",
                    "description": "contact angle 92.8?/102?/130.4? after activation",
                }
            ],
            domain="flow_battery",
        )
        names = {item["name"] for item in entities}
        self.assertIn("measurement:contact_angle_92_8_degree", names)
        self.assertIn("measurement:contact_angle_102_degree", names)
        self.assertIn("measurement:contact_angle_130_4_degree", names)

    def test_canonical_id_snake_case_for_new_entities(self) -> None:
        energy_density = self.normalizer.normalize_entity({"name": "energy density", "type": "METRIC"})
        self.assertEqual(energy_density.canonical_id, "metric:energy_density")

        electrode_polarization = self.normalizer.normalize_entity({"name": "electrode polarization", "type": "DEGRADATION"})
        self.assertEqual(electrode_polarization.canonical_id, "degradation:electrode_polarization")

        active_pair = self.normalizer.normalize_entity({"name": "V(IV)/V(V)", "type": "SPECIES"})
        self.assertEqual(active_pair.canonical_id, "active_species:v_iv_v_v")

    def test_hyperedge_rewrite_marks_review_entities(self) -> None:
        mention_map = {
            "N117": {"canonical_id": "membrane:nafion_117", "need_review": False},
            "Nafion 212": {"canonical_id": "membrane:nafion_212", "need_review": False},
            "unclear material": {"canonical_id": "unresolved:unclearmaterial", "need_review": True},
        }
        result = HyperedgeRewriter(mention_map).rewrite_hyperedges([
            {"vertices": ["N117", "unclear material"], "relation_type": "OPERATION", "source_id": "chunk-1"}
        ])
        self.assertEqual(result["normalized_hyperedge_count"], 1)
        self.assertEqual(result["unresolved_hyperedge_count"], 1)
        self.assertIn("unresolved:unclearmaterial", result["hyperedges"][0]["canonical_vertices"])

    def test_online_extraction_normalization_preserves_mentions(self) -> None:
        entities, report = normalize_entities_for_extraction(
            [
                {"name": "N117", "type": "MEMBRANE", "description": "membrane used in the test"},
                {"name": "CE", "type": "METRIC", "value": 97, "unit": "%"},
            ],
            domain="flow_battery",
        )
        names = {item["name"] for item in entities}
        self.assertIn("Nafion 117", names)
        self.assertIn("measurement:ce_97_0_percent", names)
        nafion = next(item for item in entities if item["name"] == "Nafion 117")
        self.assertEqual(nafion["raw_name"], "N117")
        self.assertIn("N117", nafion["mentions"])
        ce_instance = next(item for item in entities if item["name"] == "measurement:ce_97_0_percent")
        self.assertEqual(ce_instance["canonical_id"], "metric:ce")
        self.assertEqual(ce_instance["canonical_name"], "coulombic efficiency")
        self.assertEqual(ce_instance["value"], 97.0)
        self.assertGreaterEqual(report["alias_match_count"], 1)

    def test_measurement_condition_parser_priorities(self) -> None:
        current = self.normalizer.normalize_entity({"name": "120 mA/cm2", "type": "METRIC", "description": "current density"})
        self.assertEqual(current.canonical_id, "condition:current_density")
        self.assertEqual(current.node_id, "condition:current_density_120_ma_cm2")

        cycles = self.normalizer.normalize_entity({"name": "200 cycles", "type": "METRIC", "description": "capacity retention test duration"})
        self.assertEqual(cycles.canonical_id, "condition:cycle_number")
        self.assertEqual(cycles.node_id, "condition:cycle_number_200_cycle")

        voltage = self.normalizer.normalize_entity({"name": "polarization voltage 0.14 V", "type": "METRIC"})
        self.assertEqual(voltage.canonical_id, "metric:polarization_voltage")
        self.assertEqual(voltage.node_id, "measurement:polarization_voltage_delta_0_14_v")

        ph = self.normalizer.normalize_entity({"name": "pH 14", "type": "CONDITION"})
        self.assertEqual(ph.canonical_id, "condition:ph")
        self.assertEqual(ph.node_id, "condition:ph_14")


class LLMNormalizationTests(unittest.IsolatedAsyncioTestCase):
    async def test_medium_confidence_candidate_calls_llm(self) -> None:
        calls = []

        async def fake_llm(prompt: str, **kwargs):
            calls.append(prompt)
            return (
                '{"decision":"MERGE","target_canonical_id":"pfas:pfoa",'
                '"relationship":"same_as","canonical_name":"PFOA","confidence":0.92,'
                '"reason":"Typographical variant of perfluorooctanoic acid.",'
                '"aliases_to_add":[],"need_review":false}'
            )

        entities, report = await normalize_entities_for_extraction_async(
            [{"name": "perfluorooctan acid", "type": "PFAS_TARGET"}],
            domain="pfas_piezocatalysis",
            use_llm=True,
            llm_func=fake_llm,
            local_context="PFOA degradation was measured.",
            chunk_key="test-llm",
        )

        self.assertEqual(len(calls), 1)
        self.assertEqual(entities[0]["canonical_id"], "pfas:pfoa")
        self.assertEqual(entities[0]["normalization_method"], "llm_judged")
        self.assertEqual(report["llm_judged_count"], 1)


if __name__ == "__main__":
    unittest.main()
