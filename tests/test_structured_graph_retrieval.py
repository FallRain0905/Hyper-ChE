import base64
import json
import pickle
import tempfile
import unittest
from pathlib import Path

import numpy as np

from scripts.structured_graph_retrieval import (
    StructuredGraphIndex,
    StructuredGraphRetriever,
    StructuredRetrievalConfig,
    decode_matrix,
    source_chunk_ids,
    tokenize,
)


def vector_payload(rows, matrix):
    array = np.asarray(matrix, dtype=np.float32)
    return {
        'embedding_dim': int(array.shape[1]),
        'data': rows,
        'matrix': base64.b64encode(array.tobytes()).decode('ascii'),
    }


class FakeEmbeddingPool:
    def __init__(self, vector):
        self.vector = np.asarray(vector, dtype=np.float32)
        self.calls = 0

    def embed(self, text):
        self.calls += 1
        return self.vector.copy()


class StructuredGraphRetrievalTests(unittest.TestCase):
    def test_tokenize_preserves_unicode_chemical_terms(self):
        self.assertEqual(
            tokenize('α-V2O5 at 25.0 °C and 100 mA·cm−2'),
            ['α-v2o5', 'at', '25.0', 'c', 'and', '100', 'ma', 'cm−2'],
        )

    def make_cache(self, root):
        chunks = {
            'RFB_001_CHK_001': {
                'content': 'Nafion membrane controls vanadium crossover in a flow battery.',
                'source_doc_id': 'RFB_001',
            },
            'RFB_001_CHK_002': {
                'content': 'Temperature and current density jointly affect energy efficiency.',
                'source_doc_id': 'RFB_001',
            },
        }
        binary = ('NAFION MEMBRANE', 'VANADIUM CROSSOVER')
        high_order = ('CURRENT DENSITY', 'ENERGY EFFICIENCY', 'TEMPERATURE')
        graph = {
            'v_data': {
                name: {'description': name, 'entity_type': 'CONCEPT'}
                for name in set(binary + high_order)
            },
            'v_inci': {
                'NAFION MEMBRANE': {binary},
                'VANADIUM CROSSOVER': {binary},
                'CURRENT DENSITY': {high_order},
                'ENERGY EFFICIENCY': {high_order},
                'TEMPERATURE': {high_order},
            },
            'e_data': {
                binary: {
                    'relation_type': 'BARRIER_EFFECT',
                    'description': 'The membrane limits vanadium crossover.',
                    'source_chunk_id': 'RFB_001_CHK_001',
                },
                high_order: {
                    'relation_type': 'CONDITION_PERFORMANCE',
                    'description': 'Temperature and current density jointly affect energy efficiency.',
                    'source_chunk_ids': ['RFB_001_CHK_002'],
                },
            },
        }
        relationship_rows = [
            {
                '__id__': 'rel-binary',
                'id_set': ['NAFION MEMBRANE', 'NAFION MEMBRANE', 'VANADIUM CROSSOVER'],
                'relation_type': 'BARRIER_EFFECT',
                'content': 'Nafion membrane vanadium crossover',
            },
            {
                '__id__': 'rel-high',
                'id_set': list(high_order),
                'relation_type': 'CONDITION_PERFORMANCE',
                'content': 'temperature current density energy efficiency',
            },
        ]
        entity_rows = [
            {
                '__id__': 'ent-{}'.format(index),
                'entity_name': name,
                'entity_type': 'CONCEPT',
                'content': name,
            }
            for index, name in enumerate(graph['v_data'])
        ]
        relationship_matrix = [[1.0, 0.0], [0.0, 1.0]]
        entity_matrix = []
        for row in entity_rows:
            if row['entity_name'] in high_order:
                entity_matrix.append([0.0, 1.0])
            else:
                entity_matrix.append([1.0, 0.0])

        (root / 'kv_store_text_chunks.json').write_text(json.dumps(chunks), encoding='utf-8')
        (root / 'hypergraph_chunk_entity_relation.hgdb').write_bytes(pickle.dumps(graph))
        (root / 'vdb_relationships.json').write_text(
            json.dumps(vector_payload(relationship_rows, relationship_matrix)), encoding='utf-8'
        )
        (root / 'vdb_entities.json').write_text(
            json.dumps(vector_payload(entity_rows, entity_matrix)), encoding='utf-8'
        )

    def test_decode_matrix_rejects_wrong_size(self):
        payload = vector_payload([{'__id__': 'a'}], [[1.0, 0.0]])
        payload['embedding_dim'] = 3
        with self.assertRaises(ValueError):
            decode_matrix(payload)

    def test_duplicate_relationship_vertices_map_to_set_edge(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_cache(root)
            index = StructuredGraphIndex(root)
            self.assertEqual(index.relationship_edge_keys[0], ('NAFION MEMBRANE', 'VANADIUM CROSSOVER'))
            self.assertEqual(index.mapping_audit['mapped_relationship_vector_rows'], 2)
            self.assertEqual(index.mapping_audit['graph_edges_without_relationship_vectors'], 0)

    def test_graph_filters_high_order_and_hypergraph_keeps_it(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_cache(root)
            index = StructuredGraphIndex(root)
            config = StructuredRetrievalConfig(
                relationship_candidate_depth=2,
                entity_candidate_depth=5,
                bm25_candidate_depth=2,
                max_expanded_edges=10,
            )
            query = 'How do temperature and current density affect energy efficiency?'
            graph_rows = index.search(query, np.array([0.0, 1.0]), view='graph', top_k=5, config=config)
            hyper_rows = index.search(query, np.array([0.0, 1.0]), view='hyper', top_k=5, config=config)
            self.assertTrue(all(arity == 2 for row in graph_rows for arity in row['supporting_arities']))
            self.assertTrue(any(3 in row['supporting_arities'] for row in hyper_rows))
            high_order_row = next(row for row in hyper_rows if 3 in row['supporting_arities'])
            self.assertEqual(high_order_row['source_chunk_id'], 'RFB_001_CHK_002')
            self.assertIn('Full source chunk:', high_order_row['readable_evidence'])
            self.assertIn('relationship_dense', high_order_row['retrieval_channels'])
            self.assertIn('entity_expansion', high_order_row['retrieval_channels'])

    def test_retriever_embeds_query_once(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_cache(root)
            index = StructuredGraphIndex(root)
            pool = FakeEmbeddingPool([1.0, 0.0])
            retriever = StructuredGraphRetriever(index, pool, view='hyper')
            rows = retriever.search('Nafion crossover', 5)
            self.assertEqual(pool.calls, 1)
            self.assertTrue(rows)

    def test_two_hop_entity_expansion_reaches_neighbor_edge(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_cache(root)
            chunks = json.loads((root / 'kv_store_text_chunks.json').read_text(encoding='utf-8'))
            chunks['RFB_001_CHK_003'] = {
                'content': 'Vanadium crossover changes capacity retention.',
                'source_doc_id': 'RFB_001',
            }
            (root / 'kv_store_text_chunks.json').write_text(json.dumps(chunks), encoding='utf-8')
            graph_path = root / 'hypergraph_chunk_entity_relation.hgdb'
            graph = pickle.loads(graph_path.read_bytes())
            neighbor_edge = ('CAPACITY RETENTION', 'VANADIUM CROSSOVER')
            graph['v_data']['CAPACITY RETENTION'] = {
                'description': 'CAPACITY RETENTION',
                'entity_type': 'CONCEPT',
            }
            graph['v_inci']['CAPACITY RETENTION'] = {neighbor_edge}
            graph['v_inci']['VANADIUM CROSSOVER'].add(neighbor_edge)
            graph['e_data'][neighbor_edge] = {
                'relation_type': 'PERFORMANCE_EFFECT',
                'description': 'Vanadium crossover changes capacity retention.',
                'source_chunk_id': 'RFB_001_CHK_003',
            }
            graph_path.write_bytes(pickle.dumps(graph))
            index = StructuredGraphIndex(root)
            nafion_index = index.entity_names.index('NAFION MEMBRANE')
            rows = index._fuse_and_expand(
                'Nafion transport pathway',
                'hyper',
                5,
                StructuredRetrievalConfig(
                    entity_candidate_depth=1,
                    expansion_hops=2,
                    max_expanded_edges=10,
                ),
                [],
                [],
                [(nafion_index, 1.0)],
                [],
            )
            self.assertTrue(any(row['source_chunk_id'] == 'RFB_001_CHK_003' for row in rows))
            self.assertTrue(all('entity_expansion' in row['retrieval_channels'] for row in rows))

    def test_source_chunk_ids_reads_evidence_instances(self):
        chunks = {'RFB_001_CHK_001': {}, 'RFB_001_CHK_002': {}}
        edge = {'evidence_instances': [{'source_id': 'RFB_001_CHK_002'}]}
        self.assertEqual(source_chunk_ids(edge, chunks), ['RFB_001_CHK_002'])


if __name__ == '__main__':
    unittest.main()
