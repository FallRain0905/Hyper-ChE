'''Read-only structured hybrid retrieval for Hyper-RAG caches.'''

from __future__ import annotations

import base64
import json
import math
import pickle
import re
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np

TOKEN_RE = re.compile(r'[A-Za-zΑ-Ωα-ω][A-Za-z0-9Α-Ωα-ω_+./%−–-]*|\d+(?:\.\d+)?')
CHUNK_ID_RE = re.compile(r'RFB_\d+_CHK_\d+', re.IGNORECASE)


def tokenize(value: str) -> list[str]:
    return [match.group(0).casefold() for match in TOKEN_RE.finditer(str(value or ''))]


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding='utf-8-sig'))


def decode_matrix(payload: dict[str, Any]) -> np.ndarray:
    rows = payload.get('data') or []
    dimension = int(payload.get('embedding_dim') or 0)
    encoded = payload.get('matrix')
    if not rows or dimension <= 0 or not isinstance(encoded, str):
        raise ValueError('invalid NanoVectorDB payload')
    matrix = np.frombuffer(base64.b64decode(encoded), dtype=np.float32)
    expected = len(rows) * dimension
    if matrix.size != expected:
        raise ValueError(f'vector matrix size {matrix.size} != expected {expected}')
    matrix = matrix.reshape(len(rows), dimension)
    if not np.isfinite(matrix).all():
        raise ValueError('vector matrix contains non-finite values')
    return matrix


def source_doc_id(chunk_id: str, chunk: dict[str, Any]) -> str:
    explicit = str(chunk.get('source_doc_id') or chunk.get('full_doc_id') or chunk.get('doc_id') or '').strip()
    if explicit:
        return explicit
    match = re.match(r'(RFB_\d+)_CHK_\d+', chunk_id, flags=re.IGNORECASE)
    return match.group(1).upper() if match else ''


def source_chunk_ids(edge: dict[str, Any], chunks: dict[str, Any]) -> list[str]:
    values: list[Any] = []
    for key in ('source_chunk_ids', 'source_chunk_id', 'source_id'):
        value = edge.get(key)
        values.extend(value if isinstance(value, list) else [value])
    for instance in edge.get('evidence_instances') or []:
        if isinstance(instance, dict):
            for key in ('source_chunk_ids', 'source_chunk_id', 'source_id'):
                value = instance.get(key)
                values.extend(value if isinstance(value, list) else [value])
    found: list[str] = []
    for value in values:
        for match in CHUNK_ID_RE.findall(str(value or '')):
            chunk_id = match.upper()
            if chunk_id in chunks and chunk_id not in found:
                found.append(chunk_id)
    return found


@dataclass(frozen=True)
class StructuredRetrievalConfig:
    relationship_candidate_depth: int = 50
    entity_candidate_depth: int = 30
    bm25_candidate_depth: int = 50
    rrf_k: int = 60
    relationship_dense_weight: float = 1.0
    relationship_bm25_weight: float = 1.0
    entity_dense_weight: float = 0.8
    entity_bm25_weight: float = 0.8
    expansion_weight: float = 0.9
    expansion_hops: int = 1
    max_expanded_edges: int = 100
    rerank_candidate_depth: int = 50
    chunk_candidate_depth: int = 30

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class BM25Index:
    def __init__(self, documents: list[str]) -> None:
        self.documents = documents
        self.tokens: list[list[str]] = []
        self.term_frequencies: list[Counter[str]] = []
        self.document_frequency: Counter[str] = Counter()
        total_length = 0
        for document in documents:
            tokens = tokenize(document)
            counts = Counter(tokens)
            self.tokens.append(tokens)
            self.term_frequencies.append(counts)
            self.document_frequency.update(counts.keys())
            total_length += len(tokens)
        self.avg_length = total_length / max(1, len(documents))

    def query(self, text: str, top_k: int, *, allowed: np.ndarray | None = None) -> list[tuple[int, float]]:
        terms = tokenize(text)
        if not terms:
            return []
        n_docs = len(self.documents)
        scored: list[tuple[float, int]] = []
        for index, counts in enumerate(self.term_frequencies):
            if allowed is not None and not bool(allowed[index]):
                continue
            score = 0.0
            doc_len = len(self.tokens[index])
            for term in terms:
                tf = counts.get(term, 0)
                if not tf:
                    continue
                df = self.document_frequency.get(term, 0)
                idf = math.log(1.0 + (n_docs - df + 0.5) / (df + 0.5))
                denominator = tf + 1.5 * (0.25 + 0.75 * doc_len / max(1.0, self.avg_length))
                score += idf * tf * 2.5 / denominator
            if score > 0.0:
                scored.append((score, index))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [(index, score) for score, index in scored[:top_k]]


class StructuredGraphIndex:
    '''Shared read-only index; graph and hypergraph views differ only by arity.'''

    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = Path(cache_dir)
        self.chunks: dict[str, dict[str, Any]] = load_json(self.cache_dir / 'kv_store_text_chunks.json')
        self.graph: dict[str, Any] = pickle.loads((self.cache_dir / 'hypergraph_chunk_entity_relation.hgdb').read_bytes())
        self.vertices: dict[str, dict[str, Any]] = self.graph.get('v_data') or {}
        self.edges: dict[Any, dict[str, Any]] = self.graph.get('e_data') or {}
        self.vertex_incidence: dict[str, set[Any]] = self.graph.get('v_inci') or {}

        relationship_payload = load_json(self.cache_dir / 'vdb_relationships.json')
        entity_payload = load_json(self.cache_dir / 'vdb_entities.json')
        self.dimension = int(relationship_payload.get('embedding_dim') or 0)
        if int(entity_payload.get('embedding_dim') or 0) != self.dimension:
            raise ValueError('entity and relationship embedding dimensions differ')
        self.relationship_rows = list(relationship_payload.get('data') or [])
        self.entity_rows = list(entity_payload.get('data') or [])
        self.relationship_matrix = decode_matrix(relationship_payload)
        self.entity_matrix = decode_matrix(entity_payload)

        edge_by_vertices = {
            self.stable_vertex_set(key if isinstance(key, tuple) else [key]): key
            for key in self.edges
        }
        self.relationship_edge_keys: list[Any] = []
        mapping_counts: Counter[Any] = Counter()
        for row in self.relationship_rows:
            # Historical caches can contain duplicate names in a relationship
            # vector id_set even though the graph store represents an edge as a
            # set.  De-duplicate only for the mapping key; keep every vector row
            # as an independent dense/BM25 seed and retain its vector id in the
            # retrieval provenance.
            vertices = self.stable_vertex_set(row.get('id_set') or [])
            if vertices not in edge_by_vertices:
                raise ValueError('relationship vector does not map to graph edge: {}'.format(row.get('__id__')))
            edge_key = edge_by_vertices[vertices]
            self.relationship_edge_keys.append(edge_key)
            mapping_counts[edge_key] += 1

        self.mapping_audit = {
            'relationship_vector_rows': len(self.relationship_rows),
            'graph_edges': len(self.edges),
            'mapped_relationship_vector_rows': len(self.relationship_edge_keys),
            'unique_mapped_graph_edges': len(mapping_counts),
            'duplicate_vector_rows': sum(count - 1 for count in mapping_counts.values() if count > 1),
            'graph_edges_without_relationship_vectors': len(set(self.edges) - set(mapping_counts)),
        }

        self.entity_names: list[str] = []
        for row in self.entity_rows:
            candidates = (row.get('entity_name'), row.get('canonical_id'), row.get('canonical_name'), row.get('raw_name'))
            name = next((str(value) for value in candidates if value is not None and str(value) in self.vertices), '')
            if not name:
                raise ValueError('entity vector does not map to graph vertex: {}'.format(row.get('__id__')))
            self.entity_names.append(name)

        relation_docs = [
            self.relationship_document(row, self.edges[self.relationship_edge_keys[index]])
            for index, row in enumerate(self.relationship_rows)
        ]
        entity_docs = [self.entity_document(row, self.vertices[name]) for row, name in zip(self.entity_rows, self.entity_names)]
        self.relationship_bm25 = BM25Index(relation_docs)
        self.entity_bm25 = BM25Index(entity_docs)
        self.relationship_allowed = {
            'graph': np.asarray([self.edge_arity(key) == 2 for key in self.relationship_edge_keys], dtype=bool),
            'hyper': np.ones(len(self.relationship_rows), dtype=bool),
        }

    @staticmethod
    def stable_vertex_set(values: Iterable[Any]) -> tuple[str, ...]:
        return tuple(sorted({str(item) for item in values if str(item)}))

    @staticmethod
    def edge_vertices(edge_key: Any) -> list[str]:
        values = edge_key if isinstance(edge_key, tuple) else [edge_key]
        return list(StructuredGraphIndex.stable_vertex_set(values))

    @staticmethod
    def edge_arity(edge_key: Any) -> int:
        return len(StructuredGraphIndex.edge_vertices(edge_key))

    @staticmethod
    def relationship_document(row: dict[str, Any], edge: dict[str, Any]) -> str:
        values = (
            row.get('content'), row.get('relation_type'), ' '.join(str(item) for item in (row.get('id_set') or [])),
            edge.get('description'), edge.get('keywords'), edge.get('evidence_span'),
        )
        return '\n'.join(str(value or '') for value in values)

    @staticmethod
    def entity_document(row: dict[str, Any], vertex: dict[str, Any]) -> str:
        values = (
            row.get('content'), row.get('entity_name'), row.get('canonical_name'), row.get('entity_type'),
            vertex.get('description'), vertex.get('additional_properties'),
        )
        return '\n'.join(str(value or '') for value in values)

    @staticmethod
    def dense(matrix: np.ndarray, query_vector: np.ndarray, top_k: int, allowed: np.ndarray | None = None) -> list[tuple[int, float]]:
        vector = np.asarray(query_vector, dtype=np.float32).reshape(-1)
        if matrix.shape[1] != vector.shape[0]:
            raise ValueError(f'query embedding dimension {vector.shape[0]} != cache dimension {matrix.shape[1]}')
        norm = float(np.linalg.norm(vector))
        if not math.isfinite(norm) or norm <= 0.0:
            raise ValueError('query embedding has zero or invalid norm')
        scores = matrix @ (vector / norm)
        if allowed is not None:
            scores = np.where(allowed, scores, -np.inf)
        limit = min(max(1, int(top_k)), scores.size)
        indices = np.argpartition(-scores, limit - 1)[:limit]
        ordered = sorted(
            (int(index) for index in indices if math.isfinite(float(scores[index]))),
            key=lambda index: (-float(scores[index]), index),
        )
        return [(index, float(scores[index])) for index in ordered]

    def search(self, query: str, query_vector: np.ndarray, *, view: str, top_k: int, config: StructuredRetrievalConfig) -> list[dict[str, Any]]:
        if view not in {'graph', 'hyper'}:
            raise ValueError(f'unsupported graph view: {view}')
        allowed = self.relationship_allowed[view]
        relation_dense = self.dense(self.relationship_matrix, query_vector, config.relationship_candidate_depth, allowed)
        relation_bm25 = self.relationship_bm25.query(query, config.bm25_candidate_depth, allowed=allowed)
        entity_dense = self.dense(self.entity_matrix, query_vector, config.entity_candidate_depth)
        entity_bm25 = self.entity_bm25.query(query, config.entity_candidate_depth)
        return self._fuse_and_expand(query, view, top_k, config, relation_dense, relation_bm25, entity_dense, entity_bm25)

    def _fuse_and_expand(
        self,
        query: str,
        view: str,
        top_k: int,
        config: StructuredRetrievalConfig,
        relation_dense: Iterable[tuple[int, float]],
        relation_bm25: Iterable[tuple[int, float]],
        entity_dense: Iterable[tuple[int, float]],
        entity_bm25: Iterable[tuple[int, float]],
    ) -> list[dict[str, Any]]:
        edge_states: dict[Any, dict[str, Any]] = {}
        entity_states: dict[str, dict[str, Any]] = {}

        def add_edges(results: Iterable[tuple[int, float]], channel: str, weight: float) -> None:
            for rank, (index, raw_score) in enumerate(results, 1):
                edge_key = self.relationship_edge_keys[index]
                state = edge_states.setdefault(edge_key, {'rrf': 0.0, 'channels': {}, 'seed_entities': set(), 'expanded_from': set()})
                state['rrf'] += weight / (config.rrf_k + rank)
                state['channels'][channel] = {'rank': rank, 'score': raw_score, 'vector_id': self.relationship_rows[index].get('__id__')}

        def add_entities(results: Iterable[tuple[int, float]], channel: str, weight: float) -> None:
            for rank, (index, raw_score) in enumerate(results, 1):
                name = self.entity_names[index]
                state = entity_states.setdefault(name, {'rrf': 0.0, 'channels': {}})
                state['rrf'] += weight / (config.rrf_k + rank)
                state['channels'][channel] = {'rank': rank, 'score': raw_score, 'vector_id': self.entity_rows[index].get('__id__')}

        add_edges(relation_dense, 'relationship_dense', config.relationship_dense_weight)
        add_edges(relation_bm25, 'relationship_bm25', config.relationship_bm25_weight)
        add_entities(entity_dense, 'entity_dense', config.entity_dense_weight)
        add_entities(entity_bm25, 'entity_bm25', config.entity_bm25_weight)

        ranked_entities = sorted(entity_states.items(), key=lambda item: (-item[1]['rrf'], item[0]))[: config.entity_candidate_depth]
        frontier = [(name, state['rrf'], 0, name, state['channels']) for name, state in ranked_entities]
        seen_vertices = {name for name, _, _, _, _ in frontier}
        expanded_edges: set[Any] = set()
        while frontier and len(expanded_edges) < config.max_expanded_edges:
            entity_name, entity_score, hop, seed_entity, entity_channels = frontier.pop(0)
            if hop >= max(1, config.expansion_hops):
                continue
            incident = sorted(self.vertex_incidence.get(entity_name) or [], key=self.stable_vertex_set)
            for edge_key in incident:
                vertices = self.edge_vertices(edge_key)
                if view == 'graph' and len(vertices) != 2:
                    continue
                state = edge_states.setdefault(edge_key, {'rrf': 0.0, 'channels': {}, 'seed_entities': set(), 'expanded_from': set()})
                contribution = config.expansion_weight * entity_score / (hop + 1)
                state['rrf'] += contribution
                if hop == 0:
                    state['seed_entities'].add(entity_name)
                state['expanded_from'].add(entity_name)
                channel = state['channels'].setdefault('entity_expansion', {'rank': None, 'score': 0.0, 'entities': []})
                channel['score'] += contribution
                if entity_name not in channel['entities']:
                    channel['entities'].append(entity_name)
                for seed_channel, seed_detail in entity_channels.items():
                    provenance = state['channels'].setdefault(
                        seed_channel,
                        {
                            'rank': seed_detail['rank'],
                            'score': seed_detail['score'],
                            'vector_id': seed_detail['vector_id'],
                            'entities': [],
                        },
                    )
                    provenance['rank'] = min(int(provenance['rank']), int(seed_detail['rank']))
                    provenance['score'] = max(float(provenance['score']), float(seed_detail['score']))
                    if seed_entity not in provenance['entities']:
                        provenance['entities'].append(seed_entity)
                expanded_edges.add(edge_key)
                if len(expanded_edges) >= config.max_expanded_edges:
                    break
                if hop + 1 < config.expansion_hops:
                    for neighbor in vertices:
                        if neighbor not in seen_vertices:
                            seen_vertices.add(neighbor)
                            frontier.append((neighbor, entity_score * 0.5, hop + 1, seed_entity, entity_channels))

        return self._rank_and_reconstruct(query, view, top_k, config, edge_states)

    def _rank_and_reconstruct(self, query, view, top_k, config, edge_states):
        query_terms = set(tokenize(query))
        ranked_edges = []
        for edge_key, state in edge_states.items():
            edge = self.edges.get(edge_key)
            if edge is None:
                continue
            vertices = self.edge_vertices(edge_key)
            terms = set(tokenize(self.relationship_document({'id_set': vertices}, edge)))
            lexical_coverage = len(query_terms & terms) / max(1, len(query_terms))
            matched_seeds = len(set(vertices) & set(state['seed_entities']))
            # Reward evidence that jointly connects multiple independently
            # retrieved entities. Do not reward raw arity itself: graph and
            # hypergraph must differ only in which relation orders are allowed,
            # not through an artificial high-order score bonus.
            structure_bonus = min(0.003, 0.0015 * max(0, matched_seeds - 1))
            state['lexical_coverage'] = lexical_coverage
            state['structure_bonus'] = structure_bonus
            state['score'] = float(state['rrf']) + 0.004 * lexical_coverage + structure_bonus
            ranked_edges.append((state['score'], edge_key, state))
        ranked_edges.sort(key=lambda item: (-item[0], tuple(str(value) for value in item[1])))
        ranked_edges = ranked_edges[: max(top_k, config.rerank_candidate_depth)]

        chunk_states = {}
        for edge_rank, (edge_score, edge_key, state) in enumerate(ranked_edges, 1):
            edge = self.edges[edge_key]
            vertices = self.edge_vertices(edge_key)
            relation = {
                'edge_id': '|'.join(sorted(vertices)),
                'vertices': vertices,
                'arity': len(vertices),
                'relation_type': str(edge.get('relation_type') or 'RELATION'),
                'description': str(edge.get('description') or ''),
                'keywords': str(edge.get('keywords') or ''),
                'edge_rank': edge_rank,
                'edge_score': edge_score,
                'retrieval_channels': state['channels'],
                'expanded_from_entities': sorted(state['expanded_from']),
            }
            for chunk_id in source_chunk_ids(edge, self.chunks):
                chunk_state = chunk_states.setdefault(chunk_id, {'score': 0.0, 'max_edge_score': 0.0, 'relations': []})
                chunk_state['score'] += 1.0 / (config.rrf_k + edge_rank)
                chunk_state['max_edge_score'] = max(float(chunk_state['max_edge_score']), edge_score)
                chunk_state['relations'].append(relation)

        ordered = sorted(
            chunk_states.items(),
            key=lambda item: (-float(item[1]['score']), -float(item[1]['max_edge_score']), item[0]),
        )[: min(top_k, config.chunk_candidate_depth)]
        return [self._chunk_evidence(chunk_id, state, view) for chunk_id, state in ordered]

    def _chunk_evidence(self, chunk_id, state, view):
        chunk = self.chunks[chunk_id]
        relations = sorted(state['relations'], key=lambda item: (item['edge_rank'], item['edge_id']))
        relation_lines = []
        vertices = []
        channels = set()
        for relation in relations[:8]:
            relation_lines.append('[{}; arity={}] {}: {}'.format(
                relation['relation_type'], relation['arity'], ', '.join(relation['vertices']), relation['description']
            ))
            vertices.extend(relation['vertices'])
            channels.update(relation['retrieval_channels'])
        content = str(chunk.get('content') or '')
        readable = 'Structured relations:\n' + '\n'.join(relation_lines) + '\n\nFull source chunk:\n' + content
        doc_id = source_doc_id(chunk_id, chunk)
        return self._evidence_record(chunk_id, chunk, doc_id, readable, vertices, channels, relations, state, view)

    @staticmethod
    def _evidence_record(chunk_id, chunk, doc_id, readable, vertices, channels, relations, state, view):
        return {
            'id': chunk_id,
            'source_id': chunk_id,
            'source_chunk_id': chunk_id,
            'source_chunk_ids': [chunk_id],
            'source_doc_id': doc_id,
            'source_doc_ids': [doc_id] if doc_id else [],
            'source_file': chunk.get('source_file'),
            'text': readable,
            'readable_evidence': readable,
            'chunk_content': str(chunk.get('content') or ''),
            'kind': view,
            'relation_type': 'STRUCTURED_HYPERGRAPH_CONTEXT' if view == 'hyper' else 'STRUCTURED_BINARY_GRAPH_CONTEXT',
            'vertices': list(dict.fromkeys(vertices)),
            'canonical_vertices': list(dict.fromkeys(vertices)),
            'readable_labels': list(dict.fromkeys(vertices)),
            'arity': max((int(item['arity']) for item in relations), default=1),
            'retrieval_score': round(float(state['score']), 10),
            'max_supporting_edge_score': round(float(state['max_edge_score']), 10),
            'retrieval_method': 'structured_graph_hybrid_v1',
            'retrieval_channels': sorted(channels),
            'supporting_relations': relations,
            'supporting_edge_ids': [item['edge_id'] for item in relations],
            'supporting_arities': sorted({int(item['arity']) for item in relations}),
            'supporting_relation_types': sorted({str(item['relation_type']) for item in relations}),
        }


class StructuredGraphRetriever:
    def __init__(self, index, embedding_pool, *, view, config=None):
        self.index = index
        self.embedding_pool = embedding_pool
        self.view = view
        self.config = config or StructuredRetrievalConfig()

    def search(self, query: str, top_k: int) -> list[dict[str, Any]]:
        query_vector = self.embedding_pool.embed(query)
        return self.index.search(query, query_vector, view=self.view, top_k=top_k, config=self.config)
