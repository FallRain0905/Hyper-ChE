import unittest

from hyperrag.utils import relationship_vector_id


class RelationshipVectorIdTests(unittest.TestCase):
    def test_order_independent(self):
        self.assertEqual(
            relationship_vector_id(["ææ–™", "ä½“ç³»", "ç‰©ç§"]),
            relationship_vector_id(["ç‰©ç§", "ææ–™", "ä½“ç³»"]),
        )

    def test_relation_metadata_does_not_change_id(self):
        self.assertEqual(relationship_vector_id(["a", "b"]), relationship_vector_id(["a", "b"]))

    def test_distinct_vertex_sets_and_surface_namespace(self):
        self.assertNotEqual(relationship_vector_id(["a", "b"]), relationship_vector_id(["a", "c"]))
        self.assertNotEqual(relationship_vector_id(["a", "b"]), relationship_vector_id(["a", "b"], surface=True))


if __name__ == "__main__":
    unittest.main()
