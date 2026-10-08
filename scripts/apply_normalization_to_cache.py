"""Apply conservative normalization to an existing Hyper-ChE cache.

This is an offline patch utility for experiment caches. It does not call the
LLM and does not re-run extraction. The script copies an extracted cache, rewrites
the hypergraph vertices/hyperedges with canonical node ids, and writes a
normalization report for auditing.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
import pickle
from pathlib import Path
import shutil
import sys
from typing import Any

from hyperdb import HypergraphDB

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from hyperche.normalization import (  # noqa: E402
    AliasRegistry,
    ConditionNormalizer,
    EntityNormalizer,
    HyperedgeRewriter,
    NegativeRules,
    build_normalization_report,
)


DEFAULT_REGISTRY = REPO_ROOT / "configs" / "normalization" / "alias_registry.yaml"
DEFAULT_NEGATIVE_RULES = [
    REPO_ROOT / "configs" / "normalization" / "negative_pairs.yaml",
    REPO_ROOT / "configs" / "normalization" / "high_risk_rules.yaml",
    REPO_ROOT / "configs" / "normalization" / "generic_terms.yaml",
]
GRAPH_FILE = "hypergraph_chunk_entity_relation.hgdb"


def _load_graph(cache_dir: Path) -> dict[str, Any]:
    graph_path = cache_dir / GRAPH_FILE
    if not graph_path.exists():
        raise FileNotFoundError(f"Missing hypergraph file: {graph_path}")
    with graph_path.open("rb") as stream:
        return pickle.load(stream)


def _entity_records(graph: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for vertex_id, vertex_data in (graph.get("v_data") or {}).items():
        item = dict(vertex_data or {})
        item["entity_name"] = str(item.get("entity_name") or vertex_id)
        item["name"] = str(item.get("name") or item["entity_name"])
        item["node_id"] = str(item.get("node_id") or vertex_id)
        records.append(item)
    return records


def _hyperedge_records(graph: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for vertices, edge_data in (graph.get("e_data") or {}).items():
        item = dict(edge_data or {})
        item["vertices"] = list(vertices) if isinstance(vertices, tuple) else [str(vertices)]
        records.append(item)
    return records


def _split_sep(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in str(value).split("<SEP>") if item.strip()]


def _extend_unique(target: list[Any], values: list[Any]) -> None:
    seen = {json.dumps(item, sort_keys=True, ensure_ascii=False) if isinstance(item, dict) else str(item) for item in target}
    for value in values:
        key = json.dumps(value, sort_keys=True, ensure_ascii=False) if isinstance(value, dict) else str(value)
        if value not in (None, "", []) and key not in seen:
            target.append(value)
            seen.add(key)


def _compact_scalar(values: list[str]) -> str:
    if not values:
        return ""
    return values[0] if len(values) == 1 else "<SEP>".join(values)


def _merge_vertex(existing: dict[str, Any] | None, incoming: dict[str, Any], normalized: dict[str, Any]) -> dict[str, Any]:
    output = dict(existing or {})
    node_id = normalized.get("node_id") or normalized.get("instance_id") or normalized.get("canonical_id")
    canonical_id = normalized.get("canonical_id") or node_id
    canonical_name = normalized.get("canonical_name") or incoming.get("entity_name") or str(node_id)
    raw_name = incoming.get("entity_name") or incoming.get("raw_name") or incoming.get("name") or canonical_name

    output.setdefault("node_id", node_id)
    output.setdefault("entity_name", node_id)
    output["canonical_id"] = canonical_id
    output["canonical_name"] = canonical_name
    output["raw_name"] = raw_name if not output.get("raw_name") else output.get("raw_name")
    output["entity_type"] = normalized.get("type") or normalized.get("entity_type") or incoming.get("entity_type") or incoming.get("type") or "UNKNOWN"
    output["semantic_group"] = normalized.get("semantic_group") or incoming.get("semantic_group") or output.get("semantic_group") or ""
    output["normalization_method"] = normalized.get("normalization_method") or normalized.get("method") or output.get("normalization_method") or ""
    output["normalization_confidence"] = normalized.get("confidence", output.get("normalization_confidence"))
    output["need_review"] = bool(normalized.get("need_review") or output.get("need_review"))
    for key in ("value", "min_value", "max_value", "unit"):
        if normalized.get(key) is not None:
            output[key] = normalized.get(key)

    mentions = list(output.get("source_mentions") or output.get("mentions") or [])
    _extend_unique(mentions, [raw_name, *list(normalized.get("mentions") or [])])
    output["source_mentions"] = mentions
    output["mentions"] = mentions

    descriptions = _split_sep(output.get("description"))
    _extend_unique(descriptions, _split_sep(incoming.get("description")))
    _extend_unique(descriptions, list(normalized.get("descriptions") or []))
    output["description"] = _compact_scalar(descriptions[:20])

    for singular, plural in [
        ("source_id", "source_ids"),
        ("source_doc_id", "source_doc_ids"),
        ("source_chunk_id", "source_chunk_ids"),
        ("source_file", "source_files"),
    ]:
        values = list(output.get(plural) or [])
        _extend_unique(values, _split_sep(incoming.get(singular)))
        _extend_unique(values, _split_sep(incoming.get(plural)))
        _extend_unique(values, list(normalized.get(plural) or []))
        if values:
            output[plural] = values
            output[singular] = values[0] if len(values) == 1 else "<SEP>".join(values)
    return output


def _merge_evidence_instances(existing: list[dict[str, Any]], incoming: dict[str, Any]) -> list[dict[str, Any]]:
    evidence_instances: list[dict[str, Any]] = list(existing or [])
    raw_instances = incoming.get("evidence_instances")
    if isinstance(raw_instances, list) and raw_instances:
        _extend_unique(evidence_instances, [dict(item) for item in raw_instances if isinstance(item, dict)])
    else:
        evidence = {
            "source_id": incoming.get("source_id"),
            "source_doc_id": incoming.get("source_doc_id"),
            "source_chunk_id": incoming.get("source_chunk_id"),
            "source_file": incoming.get("source_file"),
            "description": incoming.get("description"),
            "source_span": incoming.get("source_span") or incoming.get("evidence_span"),
            "sentence": incoming.get("sentence") or incoming.get("source_span") or incoming.get("evidence_span"),
        }
        if any(value for value in evidence.values()):
            _extend_unique(evidence_instances, [evidence])
    return evidence_instances


def _merge_edge(existing: dict[str, Any] | None, edge: dict[str, Any], canonical_vertices: list[str]) -> dict[str, Any]:
    output = dict(existing or {})
    output.setdefault("efu_id", edge.get("efu_id"))
    output["vertices"] = canonical_vertices
    output["node_ids"] = canonical_vertices
    output["canonical_vertices"] = canonical_vertices
    raw_vertices = list(output.get("raw_vertices") or [])
    _extend_unique(raw_vertices, [str(v) for v in edge.get("vertices", [])])
    output["raw_vertices"] = raw_vertices
    output["normalization_status"] = edge.get("normalization_status", output.get("normalization_status", "resolved"))
    if edge.get("unresolved_vertices"):
        unresolved = list(output.get("unresolved_vertices") or [])
        _extend_unique(unresolved, [str(v) for v in edge.get("unresolved_vertices", [])])
        output["unresolved_vertices"] = unresolved
        output["normalization_status"] = "unresolved"

    for key in ("relation_type", "keywords", "source_doc_id", "source_chunk_id", "source_file", "source_span", "evidence_span"):
        if edge.get(key) and not output.get(key):
            output[key] = edge.get(key)

    descriptions = _split_sep(output.get("description"))
    _extend_unique(descriptions, _split_sep(edge.get("description")))
    if descriptions:
        output["description"] = descriptions[0]
        output["description_variants"] = descriptions

    output["evidence_instances"] = _merge_evidence_instances(output.get("evidence_instances") or [], edge)
    output["weight"] = max(float(output.get("weight") or 0.0), float(edge.get("weight") or 1.0))
    return output


def _write_graph(cache_dir: Path, vertices: dict[str, dict[str, Any]], edges: dict[tuple[str, ...], dict[str, Any]]) -> None:
    graph = HypergraphDB()
    for node_id, data in vertices.items():
        graph.add_v(node_id, data)
    for edge_key, data in edges.items():
        if len(edge_key) >= 2:
            graph.add_e(edge_key, data)
    graph.save(cache_dir / GRAPH_FILE)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def apply_normalization(args: argparse.Namespace) -> dict[str, Any]:
    input_cache = args.input_cache.resolve()
    output_cache = args.output_cache.resolve()
    if not input_cache.exists():
        raise FileNotFoundError(input_cache)
    if output_cache.exists():
        if not args.overwrite:
            raise FileExistsError(f"{output_cache} exists; pass --overwrite to replace it.")
        shutil.rmtree(output_cache)
    shutil.copytree(input_cache, output_cache)

    graph = _load_graph(input_cache)
    entities = _entity_records(graph)
    hyperedges = _hyperedge_records(graph)

    print(f"[normalize-cache] input vertices={len(entities)} hyperedges={len(hyperedges)}")
    normalized_records, parsed_count = ConditionNormalizer().normalize_entities(entities)
    registry = AliasRegistry.from_yaml_files([args.registry])
    negative_rules = NegativeRules(registry, args.negative_pairs or DEFAULT_NEGATIVE_RULES)
    entity_result = EntityNormalizer(
        registry,
        negative_rules=negative_rules,
        auto_threshold=args.fuzzy_threshold,
        use_llm=False,
    ).normalize_entities(normalized_records)
    mention_map = entity_result["mention_to_canonical_map"]
    hyperedge_result = HyperedgeRewriter(mention_map).rewrite_hyperedges(hyperedges)

    canonical_by_node = {item["node_id"]: item for item in entity_result["canonical_entities"]}
    normalized_vertices: dict[str, dict[str, Any]] = {}
    for record in normalized_records:
        original_name = str(record.get("entity_name") or record.get("name") or record.get("node_id"))
        mapped = mention_map.get(original_name)
        if not mapped:
            node_id = original_name
            mapped = {
                "node_id": node_id,
                "canonical_id": record.get("canonical_id") or node_id,
                "canonical_name": record.get("canonical_name") or original_name,
                "type": record.get("entity_type") or record.get("type") or "UNKNOWN",
                "normalization_method": "unmapped",
                "confidence": 0.0,
                "need_review": True,
            }
        node_id = str(mapped.get("node_id") or mapped.get("instance_id") or mapped.get("canonical_id"))
        normalized = dict(canonical_by_node.get(node_id) or {})
        normalized.update(mapped)
        normalized_vertices[node_id] = _merge_vertex(normalized_vertices.get(node_id), record, normalized)

    normalized_edges: dict[tuple[str, ...], dict[str, Any]] = {}
    for edge in hyperedge_result["hyperedges"]:
        canonical_vertices = [str(v) for v in edge.get("canonical_vertices") or edge.get("vertices") or []]
        canonical_vertices = list(dict.fromkeys(canonical_vertices))
        if len(canonical_vertices) < 2:
            continue
        edge_key = tuple(sorted(canonical_vertices))
        normalized_edges[edge_key] = _merge_edge(normalized_edges.get(edge_key), edge, canonical_vertices)

    _write_graph(output_cache, normalized_vertices, normalized_edges)

    report = build_normalization_report(
        entity_result["normalization_results"],
        raw_hyperedge_count=hyperedge_result["raw_hyperedge_count"],
        normalized_hyperedge_count=len(normalized_edges),
        unresolved_hyperedge_count=hyperedge_result["unresolved_hyperedge_count"],
    )
    report.update(
        {
            "input_cache": str(input_cache),
            "output_cache": str(output_cache),
            "parsed_value_count": parsed_count,
            "raw_vertex_count": len(entities),
            "normalized_vertex_count": len(normalized_vertices),
            "raw_hyperedge_count": len(hyperedges),
            "normalized_hyperedge_count_after_merge": len(normalized_edges),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "llm_used": False,
        }
    )

    report_dir = output_cache / "normalization"
    _write_json(report_dir / "normalization_report.json", report)
    _write_json(report_dir / "mention_to_canonical_map.json", mention_map)
    _write_json(report_dir / "normalization_results.json", entity_result["normalization_results"])

    run_config_path = output_cache / "run_config.json"
    if run_config_path.exists():
        try:
            run_config = json.loads(run_config_path.read_text(encoding="utf-8"))
        except Exception:
            run_config = {}
    else:
        run_config = {}
    run_config.update(
        {
            "experiment_mode": args.mode_name,
            "enable_entity_normalization": True,
            "normalization_source_cache": str(input_cache),
            "normalization_report": str(report_dir / "normalization_report.json"),
            "normalization_llm_used": False,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    _write_json(run_config_path, run_config)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply rule-based normalization to an existing Hyper-ChE cache.")
    parser.add_argument("--input-cache", required=True, type=Path)
    parser.add_argument("--output-cache", required=True, type=Path)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--negative-pairs", action="append", type=Path, default=[])
    parser.add_argument("--fuzzy-threshold", type=float, default=95.0)
    parser.add_argument("--mode-name", default="chem_norm_hypergraph")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    report = apply_normalization(args)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
