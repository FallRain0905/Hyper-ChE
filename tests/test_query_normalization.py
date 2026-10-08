import unittest

from hyperche.retrieval.query_normalization import (
    classify_query,
    normalize_query,
    query_variants,
)


class QueryNormalizationTests(unittest.TestCase):
    def test_normalize_query_keeps_chemistry_content_and_standardizes_units(self):
        value = "Compare Nafion 117 at 25°C, 100 mA / cm², and 3.9 × 10⁻⁷ cm²/s"
        normalized = normalize_query(value)
        self.assertIn("25 C", normalized)
        self.assertIn("100 mA/cm2", normalized)
        self.assertIn("3.9 x 10-7 cm2/s", normalized)
        self.assertIn("Nafion 117", normalized)

    def test_variants_are_deterministic_and_bounded(self):
        variants = query_variants("What is the coulombic efficiency of a VRFB?", max_variants=2)
        self.assertEqual(len(variants), 2)
        self.assertEqual(variants[0], "What is the coulombic efficiency of a VRFB?")
        self.assertIn("CE", variants[1])
        self.assertEqual(variants, query_variants("What is the coulombic efficiency of a VRFB?", max_variants=2))

    def test_query_type_is_routing_only(self):
        self.assertEqual(classify_query("Compare Nafion 117 versus Nafion 212"), "comparison")
        self.assertEqual(classify_query("Why does crossover increase?"), "mechanism explanation")
        self.assertEqual(classify_query("What is CE at 25 C?"), "condition-constrained retrieval")


if __name__ == "__main__":
    unittest.main()
