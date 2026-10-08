"""Recompute the frozen five-system paper results without model/API calls."""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.evaluate_shared_retrieval_qrels import dcg, metrics

SYSTEMS = (
    'original_hypergraph', 'chem_prompt_graph', 'chem_prompt_hypergraph',
    'normalized_final_no_rerank', 'normalized_final',
)


def load_json(path: Path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def load_csv(path: Path):
    with path.open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def close(actual: float, expected: float, label: str):
    if not math.isclose(actual, expected, rel_tol=0, abs_tol=1e-6):
        raise ValueError(f'{label}: recomputed={actual:.9f}, archived={expected:.9f}')


def reproduce(data: Path) -> dict:
    pool = load_json(data / 'benchmark/candidate_rankings.json')['candidate_union']
    qrels = load_json(data / 'cfr/shared_qrels.json')['qrels']
    grades = {(row['query_id'], row['chunk_id']): int(row['relevance_grade']) for row in qrels}
    pool_pairs = {(row['query_id'], row['chunk_id']) for row in pool}
    if len(grades) != len(qrels) or len(pool_pairs) != len(pool) or pool_pairs != set(grades):
        raise ValueError('The frozen pool/qrels are duplicated, incomplete, or inconsistent')
    queries = sorted({qid for qid, _ in pool_pairs})
    ideal = {qid: sorted((grade for (query_id, _), grade in grades.items() if query_id == qid), reverse=True)
             for qid in queries}
    rankings = defaultdict(list)
    for row in pool:
        for occurrence in row['system_occurrences']:
            system = occurrence['system']
            if system not in SYSTEMS:
                raise ValueError(f'Unexpected system: {system}')
            rankings[system, row['query_id']].append((int(occurrence['retrieval_rank']), row['chunk_id']))
    ranked = {}
    for system in SYSTEMS:
        for qid in queries:
            # Match the frozen evaluator's rank ordering and duplicate handling.
            ranked[system, qid] = list(dict.fromkeys(cid for _, cid in sorted(rankings[system, qid])))

    archived = load_csv(data / 'retrieval/shared_retrieval_summary_retained.csv')
    expected = {(row['system'], row['relevance_threshold']): row for row in archived}
    retrieval = []
    for system in SYSTEMS:
        for threshold in (1, 2, 3):
            rows = [metrics([grades[qid, cid] for cid in ranked[system, qid]], ideal[qid], threshold, 5)
                    for qid in queries]
            result = {'system': system, 'relevance_threshold': f'grade>={threshold}', 'queries': len(queries)}
            reference = expected[system, result['relevance_threshold']]
            for name in ('P@1', 'Hit@5', 'MRR', 'gNDCG@5'):
                result[name] = sum(row[name] for row in rows) / len(rows)
                close(result[name], float(reference[name]), f'{system}/{threshold}/{name}')
            retrieval.append(result)

    gold = load_json(data / 'cfr/composite_fact_gold_user_accepted.json')
    facts = [fact for query in gold['queries'] for fact in query['atomic_facts']]
    if len(queries) != 58 or len(pool_pairs) != 4196 or len(facts) != 150:
        raise ValueError('Unexpected frozen benchmark dimensions')
    archived_facts = load_json(data / 'cfr/composite_fact_recall_retained.json')['per_fact']
    expected_facts = {(row['system'], row['query_id'], row['fact_id']): row for row in archived_facts}
    expected_cfr = {row['system']: row for row in load_csv(data / 'cfr/composite_fact_recall_retained.csv')}
    cfr = []
    for system in SYSTEMS:
        supported = 0
        by_query = defaultdict(list)
        for fact in facts:
            qid = fact['query_id']
            hit = bool(set(fact['supporting_chunk_ids']) & set(ranked[system, qid][:5]))
            if hit != expected_facts[system, qid, fact['fact_id']]['supported_at_top5']:
                raise ValueError(f'CFR fact mismatch: {system}/{fact["fact_id"]}')
            supported += int(hit)
            by_query[qid].append(int(hit))
        macro = sum(sum(hits) / len(hits) for hits in by_query.values()) / len(by_query)
        value = supported / len(facts)
        reference = expected_cfr[system]
        close(value, float(reference['Composite Fact Recall@5']), f'{system}/CFR@5')
        close(macro, float(reference['macro_query_CFR@5']), f'{system}/macro_CFR@5')
        if supported != int(reference['supported_facts']):
            raise ValueError(f'{system}: supported fact count mismatch')
        cfr.append({'system': system, 'supported_facts': supported, 'facts': len(facts),
                    'CFR@5': value, 'macro_query_CFR@5': macro})
    return {'status': 'verified', 'queries': len(queries), 'pooled_pairs': len(pool_pairs),
            'accepted_facts': len(facts), 'zero_idcg_queries': sum(dcg(v, 5) == 0 for v in ideal.values()),
            'retrieval': retrieval, 'cfr': cfr}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=ROOT / 'experiments/final_v1')
    parser.add_argument('--output', type=Path, default=ROOT / 'outputs/reproduced_final_v1/verification.json')
    args = parser.parse_args()
    results = reproduce(args.data_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2) + '\n', encoding='utf-8')
    print(f'Verified 5 systems, {results["queries"]} queries, {results["pooled_pairs"]} qrels, '
          f'{results["accepted_facts"]} accepted facts. No API calls.')
    print(f'Report: {args.output}')


if __name__ == '__main__':
    main()
