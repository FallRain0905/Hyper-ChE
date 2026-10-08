"""Generate retrieval annotation pack from existing Hyper-ChE caches.

The output is for human/agent qrels annotation. It does not fabricate relevance
labels; retrieval_qrels.json is a template with null grades.
"""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
import pickle
import re
from pathlib import Path
from typing import Any


STOPWORDS = {
    "the", "and", "or", "of", "to", "in", "at", "for", "with", "which",
    "what", "was", "were", "is", "are", "that", "this", "evidence",
    "supports", "relation", "involving", "between", "under", "using",
}


def normalize(text: Any) -> str:
    value = str(text or "").lower()
    value = value.replace("cm−2", "cm2").replace("cm-2", "cm2").replace("cm^2", "cm2").replace("cm²", "cm2")
    value = value.replace("ω", "ohm").replace("·", " ").replace("–", "-").replace("—", "-")
    value = re.sub(r"m\s*a\s*(?:/|\s+)\s*cm\s*-?\s*2", "ma/cm2", value)
    value = re.sub(r"mol\s*(?:/|\s+)\s*l(?:-1)?", "mol/l", value)
    value = re.sub(r"[^a-z0-9.%/+:-]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def tokenize(text: Any) -> list[str]:
    return [tok for tok in normalize(text).split() if tok and tok not in STOPWORDS]


def short_hash(text: str) -> str:
    return hashlib.md5(text.encode("utf-8", errors="ignore")).hexdigest()[:16]


def load_cache(cache_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    graph = pickle.loads((cache_dir / "hypergraph_chunk_entity_relation.hgdb").read_bytes())
    chunks_path = cache_dir / "kv_store_text_chunks.json"
    chunks = json.loads(chunks_path.read_text(encoding="utf-8", errors="replace")) if chunks_path.exists() else {}
    return graph, chunks


def split_sep(value: Any) -> list[str]:
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            out.extend(split_sep(item))
        return out
    text = str(value or "")
    if not text:
        return []
    return [part.strip() for part in text.split("<SEP>") if part.strip()]


def edge_doc_ids(edge: dict[str, Any]) -> list[str]:
    docs: list[str] = []
    for key in ("source_doc_id", "source_doc_ids"):
        docs.extend(split_sep(edge.get(key)))
    for inst in edge.get("evidence_instances") or []:
        if isinstance(inst, dict):
            docs.extend(split_sep(inst.get("source_doc_id") or inst.get("source_id")))
    if not docs:
        docs.extend(re.findall(r"RFB_\d{3}", str(edge.get("source_id") or "")))
    return sorted(set(docs))


def edge_chunk_ids(edge: dict[str, Any]) -> list[str]:
    chunks: list[str] = []
    for key in ("source_chunk_id", "source_chunk_ids", "source_id"):
        chunks.extend(split_sep(edge.get(key)))
    for inst in edge.get("evidence_instances") or []:
        if isinstance(inst, dict):
            chunks.extend(split_sep(inst.get("source_chunk_id") or inst.get("source_id")))
    return sorted(set(chunks))


def vertex_label(vertex_id: str, vertex_data: dict[str, Any]) -> str:
    name = vertex_data.get("canonical_name") or vertex_data.get("display_name") or vertex_data.get("raw_name") or vertex_id
    value = vertex_data.get("value")
    unit = vertex_data.get("unit")
    if value is not None and unit:
        return f"{name} = {value} {unit}"
    return str(name)


def evidence_text_from_instances(edge: dict[str, Any]) -> str:
    spans: list[str] = []
    for inst in edge.get("evidence_instances") or []:
        if isinstance(inst, dict):
            for key in ("source_span", "evidence_span", "sentence", "description"):
                value = inst.get(key)
                if value:
                    spans.append(str(value))
    return " ; ".join(dict.fromkeys(spans[:4]))


def edge_record(group: str, key: Any, edge: dict[str, Any], vertex_store: dict[str, Any], *, view: str) -> dict[str, Any]:
    vertices = list(key) if isinstance(key, tuple) else [str(key)]
    labels = [vertex_label(v, vertex_store.get(v, {})) for v in vertices]
    relation_type = str(edge.get("relation_type") or "")
    desc = str(edge.get("description") or "")
    source_span = edge.get("source_span") or edge.get("evidence_span") or evidence_text_from_instances(edge)
    original_id = "|".join(vertices)
    candidate_id = f"{group}:{short_hash(original_id + relation_type + desc + str(source_span))}"
    readable = "\n".join(
        part
        for part in [
            f"Relation type: {relation_type}",
            "Readable labels: " + "; ".join(labels),
            "Description: " + desc if desc else "",
            "Source evidence: " + str(source_span) if source_span else "",
        ]
        if part
    )
    return {
        "candidate_id": candidate_id,
        "candidate_group": group,
        "candidate_type": view,
        "candidate_source_id": ";".join(edge_chunk_ids(edge)),
        "source_doc_ids": edge_doc_ids(edge),
        "source_chunk_ids": edge_chunk_ids(edge),
        "original_evidence_id": original_id,
        "relation_type": relation_type,
        "canonical_vertices": vertices,
        "readable_labels": labels,
        "readable_evidence": readable,
        "source_span": source_span,
        "evidence_instances": edge.get("evidence_instances") or [],
    }


def chunk_record(group: str, chunk_id: str, chunk: dict[str, Any] | str) -> dict[str, Any]:
    content = chunk.get("content", "") if isinstance(chunk, dict) else str(chunk)
    doc_id = chunk.get("doc_id") or chunk.get("source_doc_id") if isinstance(chunk, dict) else None
    source_file = chunk.get("source_file") if isinstance(chunk, dict) else None
    return {
        "candidate_id": f"{group}:{short_hash(chunk_id)}",
        "candidate_group": group,
        "candidate_type": "text",
        "candidate_source_id": chunk_id,
        "source_doc_ids": [doc_id] if doc_id else re.findall(r"RFB_\d{3}", chunk_id),
        "source_chunk_ids": [chunk_id],
        "source_file": source_file,
        "original_evidence_id": chunk_id,
        "relation_type": "TEXT_CHUNK",
        "canonical_vertices": [],
        "readable_labels": [],
        "readable_evidence": content,
        "source_span": content[:1200],
        "evidence_instances": [],
    }


def candidate_text(item: dict[str, Any]) -> str:
    fields = [
        item.get("relation_type"),
        " ".join(map(str, item.get("canonical_vertices") or [])),
        " ".join(map(str, item.get("readable_labels") or [])),
        item.get("readable_evidence"),
        item.get("source_span"),
    ]
    return "\n".join(str(field) for field in fields if field)


def bm25_rank(query: str, items: list[dict[str, Any]]) -> list[tuple[float, dict[str, Any]]]:
    q_terms = tokenize(query)
    docs = [tokenize(candidate_text(item)) for item in items]
    if not docs:
        return []
    avgdl = sum(len(doc) for doc in docs) / max(1, len(docs))
    df: dict[str, int] = defaultdict(int)
    for doc in docs:
        for term in set(doc):
            df[term] += 1
    n_docs = len(docs)
    k1 = 1.5
    b = 0.75
    ranked: list[tuple[float, dict[str, Any]]] = []
    for item, doc in zip(items, docs):
        tf: dict[str, int] = defaultdict(int)
        for term in doc:
            tf[term] += 1
        score = 0.0
        for term in q_terms:
            if not tf.get(term):
                continue
            idf = math.log(1 + (n_docs - df[term] + 0.5) / (df[term] + 0.5))
            denom = tf[term] + k1 * (1 - b + b * len(doc) / max(avgdl, 1e-9))
            score += idf * (tf[term] * (k1 + 1)) / denom
        ranked.append((score, item))
    ranked.sort(key=lambda pair: pair[0], reverse=True)
    return ranked


def same_doc_candidates(items: list[dict[str, Any]], doc_id: str) -> list[dict[str, Any]]:
    if not doc_id or doc_id == "UNKNOWN":
        return items
    matched = [
        item
        for item in items
        if doc_id in set(map(str, item.get("source_doc_ids") or []))
        or doc_id in " ".join(map(str, item.get("source_chunk_ids") or []))
        or doc_id in str(item.get("candidate_source_id") or "")
    ]
    return matched or items


def query_from_edge(index: int, item: dict[str, Any]) -> dict[str, Any]:
    doc_id = (item.get("source_doc_ids") or ["UNKNOWN"])[0]
    relation_type = item.get("relation_type") or "RELATION"
    labels = item.get("readable_labels") or item.get("canonical_vertices") or []
    compact_labels = "; ".join(str(x) for x in labels[:8])
    claim = str(item.get("source_span") or item.get("readable_evidence") or compact_labels)
    if len(claim) > 700:
        claim = claim[:700].rsplit(" ", 1)[0]
    return {
        "query_id": f"Q-{doc_id}-{index:03d}",
        "question": f"Which retrieved evidence best supports the {relation_type} relation involving: {compact_labels}?",
        "source_doc_id": doc_id,
        "gold_claim": claim,
        "fact_type": relation_type,
        "required_entities": list(item.get("canonical_vertices") or [])[:12],
        "required_conditions": [],
        "required_metrics": [],
        "required_mechanisms": [],
        "seed_candidate_id": item.get("candidate_id"),
        "seed_candidate_group": item.get("candidate_group"),
    }


def select_seed_queries(items: list[dict[str, Any]], *, limit_per_doc: int, max_queries: int) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        docs = item.get("source_doc_ids") or []
        if not docs:
            continue
        if item.get("candidate_type") != "hyper":
            continue
        if len(item.get("canonical_vertices") or []) < 3:
            continue
        docs_key = docs[0]
        buckets[docs_key].append(item)
    selected: list[dict[str, Any]] = []
    for doc in sorted(buckets):
        ranked = sorted(
            buckets[doc],
            key=lambda item: (
                len(item.get("canonical_vertices") or []),
                len(str(item.get("source_span") or item.get("readable_evidence") or "")),
            ),
            reverse=True,
        )
        selected.extend(ranked[:limit_per_doc])
    selected = selected[:max_queries]
    return [query_from_edge(idx + 1, item) for idx, item in enumerate(selected)]


def load_queries_file(path: Path, *, max_queries: int | None = None) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    queries = list(data.get("queries") or data.get("retrieval_queries") or data)
    if max_queries:
        queries = queries[:max_queries]
    normalized = []
    for index, query in enumerate(queries, start=1):
        item = dict(query)
        item.setdefault("query_id", f"QRAW-{index:04d}")
        item.setdefault("question", item.get("gold_claim") or item.get("claim") or "")
        item.setdefault("gold_claim", item.get("claim") or item.get("question") or "")
        item.setdefault("source_doc_id", "UNKNOWN")
        item.setdefault("fact_type", "RAW_FACT")
        item.setdefault("required_entities", [])
        item.setdefault("required_conditions", [])
        item.setdefault("required_metrics", [])
        item.setdefault("required_mechanisms", [])
        normalized.append(item)
    return normalized


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate retrieval queries, candidate evidence, and qrels template.")
    parser.add_argument("--base-cache", required=True, type=Path)
    parser.add_argument("--chem-cache", required=True, type=Path)
    parser.add_argument("--norm-cache", type=Path, help="Optional normalized chemistry hypergraph cache.")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--top-n", type=int, default=20)
    parser.add_argument("--limit-per-doc", type=int, default=8)
    parser.add_argument("--max-queries", type=int, default=80)
    parser.add_argument("--queries-file", type=Path, help="Use independent retrieval queries instead of generating from hyperedges.")
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    base_graph, base_chunks = load_cache(args.base_cache)
    chem_graph, chem_chunks = load_cache(args.chem_cache)
    norm_graph: dict[str, Any] | None = None
    if args.norm_cache:
        norm_graph, _ = load_cache(args.norm_cache)

    candidate_corpus: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for chunk_id, chunk in base_chunks.items():
        candidate_corpus["text_segments"].append(chunk_record("text_segments", chunk_id, chunk))

    for key, edge in base_graph.get("e_data", {}).items():
        candidate_corpus["original_hypergraph"].append(edge_record("original_hypergraph", key, edge, base_graph.get("v_data", {}), view="hyper"))

    for key, edge in chem_graph.get("e_data", {}).items():
        vertices = list(key) if isinstance(key, tuple) else [str(key)]
        hyper_item = edge_record("chem_prompt_hypergraph", key, edge, chem_graph.get("v_data", {}), view="hyper")
        candidate_corpus["chem_prompt_hypergraph"].append(hyper_item)
        if len(vertices) == 2:
            graph_item = dict(hyper_item)
            graph_item["candidate_group"] = "chem_prompt_graph"
            graph_item["candidate_type"] = "graph"
            graph_item["candidate_id"] = "chem_prompt_graph:" + graph_item["candidate_id"].split(":", 1)[-1]
            candidate_corpus["chem_prompt_graph"].append(graph_item)

    if norm_graph is not None:
        for key, edge in norm_graph.get("e_data", {}).items():
            candidate_corpus["chem_norm_hypergraph"].append(
                edge_record("chem_norm_hypergraph", key, edge, norm_graph.get("v_data", {}), view="hyper")
            )

    if args.queries_file:
        queries = load_queries_file(args.queries_file, max_queries=args.max_queries)
    else:
        seed_pool = candidate_corpus["chem_prompt_hypergraph"]
        queries = select_seed_queries(seed_pool, limit_per_doc=args.limit_per_doc, max_queries=args.max_queries)

    all_candidates: list[dict[str, Any]] = []
    qrel_templates: list[dict[str, Any]] = []
    groups = ["text_segments", "original_hypergraph", "chem_prompt_graph", "chem_prompt_hypergraph"]
    if norm_graph is not None:
        groups.append("chem_norm_hypergraph")
    for query in queries:
        qtext = "\n".join(
            [
                query.get("question", ""),
                " ".join(query.get("required_entities") or []),
                " ".join(str(x.get("canonical_id") or x) for x in query.get("required_conditions") or []),
                " ".join(str(x.get("canonical_id") or x) for x in query.get("required_metrics") or []),
                " ".join(query.get("required_mechanisms") or []),
            ]
        )
        for group in groups:
            local_items = same_doc_candidates(candidate_corpus[group], str(query.get("source_doc_id") or ""))
            ranked = bm25_rank(qtext, local_items)
            for rank, (score, item) in enumerate(ranked[: args.top_n], start=1):
                record = dict(item)
                record.update(
                    {
                        "query_id": query["query_id"],
                        "candidate_group_label": group,
                        "retrieval_rank": rank,
                        "retrieval_score": round(float(score), 6),
                        "ranking_method": "bm25_candidate_pool",
                        "top_n_pool": args.top_n,
                    }
                )
                all_candidates.append(record)
                qrel_templates.append(
                    {
                        "query_id": query["query_id"],
                        "candidate_id": record["candidate_id"],
                        "candidate_group": group,
                        "relevance_grade": None,
                        "relevance_label": None,
                        "matched_elements": {"entities": [], "conditions": [], "measurements": [], "mechanisms": []},
                        "missing_elements": {"entities": [], "conditions": [], "measurements": [], "mechanisms": []},
                        "wrong_or_conflicting_elements": [],
                        "rationale": "",
                    }
                )

    metadata = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base_cache": str(args.base_cache),
        "chem_cache": str(args.chem_cache),
        "norm_cache": str(args.norm_cache) if args.norm_cache else None,
        "top_n_per_group_per_query": args.top_n,
        "groups": groups,
        "queries_file": str(args.queries_file) if args.queries_file else None,
        "query_generation": "external_queries_file" if args.queries_file else "chem_prompt_hypergraph_seed_queries",
        "note": "retrieval_qrels.json is an unlabeled template; fill relevance_grade 0-3 before metric evaluation.",
        "grade_schema": {"0": "IRRELEVANT", "1": "BACKGROUND", "2": "STRONG_SUPPORT", "3": "DIRECT"},
    }
    queries_obj = {"metadata": {**metadata, "num_queries": len(queries)}, "queries": queries}
    candidates_obj = {"metadata": {**metadata, "num_candidate_evidence": len(all_candidates)}, "candidate_evidence": all_candidates}
    qrels_obj = {"metadata": {**metadata, "num_qrels": len(qrel_templates), "annotation_status": "unlabeled_template"}, "qrels": qrel_templates}
    summary = {
        "metadata": metadata,
        "counts": {
            "queries": len(queries),
            "candidate_evidence": len(all_candidates),
            "qrels": len(qrel_templates),
            "candidate_corpus_by_group": {group: len(candidate_corpus[group]) for group in groups},
        },
        "outputs": {
            "retrieval_queries": str(args.output_dir / "retrieval_queries.json"),
            "candidate_evidence": str(args.output_dir / "candidate_evidence.json"),
            "retrieval_qrels": str(args.output_dir / "retrieval_qrels.json"),
        },
    }
    (args.output_dir / "retrieval_queries.json").write_text(json.dumps(queries_obj, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.output_dir / "candidate_evidence.json").write_text(json.dumps(candidates_obj, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.output_dir / "retrieval_qrels.json").write_text(json.dumps(qrels_obj, ensure_ascii=False, indent=2), encoding="utf-8")
    with (args.output_dir / "candidate_evidence.jsonl").open("w", encoding="utf-8") as f:
        for record in all_candidates:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    with (args.output_dir / "retrieval_qrels.jsonl").open("w", encoding="utf-8") as f:
        for record in qrel_templates:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    (args.output_dir / "retrieval_annotation_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    with (args.output_dir / "retrieval_queries_preview.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["query_id", "source_doc_id", "fact_type", "question", "gold_claim"])
        writer.writeheader()
        for query in queries:
            writer.writerow({key: query.get(key, "") for key in ["query_id", "source_doc_id", "fact_type", "question", "gold_claim"]})
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
