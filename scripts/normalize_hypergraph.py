"""Normalize extracted chemical entities and rewrite hyperedges.

This script is an audit/post-processing utility. The online extraction pipeline
also runs normalization immediately after entity extraction.
"""

from __future__ import annotations

import argparse
import json
import pickle
from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from hyperche.normalization import (
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


def load_input(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if path.suffix.lower() == ".hgdb":
        with path.open("rb") as stream:
            data = pickle.load(stream)
        entities = []
        for vertex_id, vertex_data in (data.get("v_data") or {}).items():
            item = dict(vertex_data or {})
            item["entity_name"] = str(vertex_id)
            entities.append(item)
        hyperedges = []
        for vertices, edge_data in (data.get("e_data") or {}).items():
            item = dict(edge_data or {})
            item["vertices"] = list(vertices)
            hyperedges.append(item)
        return entities, hyperedges

    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(data, list):
        return data, []
    return data.get("entities", []), data.get("hyperedges", data.get("relations", []))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _bool_arg(value: str) -> bool:
    return str(value).lower() in {"1", "true", "yes", "y", "on"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize extracted HyperChE entities and hyperedges.")
    parser.add_argument("--input", required=True, type=Path, help="Input .hgdb or extracted JSON.")
    parser.add_argument("--output", type=Path, help="Normalized JSON output path.")
    parser.add_argument("--output-dir", type=Path, help="Backward-compatible output directory.")
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY, help="Alias registry YAML.")
    parser.add_argument("--negative-pairs", action="append", type=Path, default=[], help="Negative/high-risk YAML. Can repeat.")
    parser.add_argument("--config", action="append", type=Path, default=[], help="Backward-compatible alias registry YAML.")
    parser.add_argument("--use-llm", type=_bool_arg, default=False, help="Reserved; default false.")
    parser.add_argument("--report", type=Path, help="Normalization report JSON path.")
    parser.add_argument("--fuzzy-threshold", type=float, default=95.0, help="Auto-merge fuzzy threshold, 0-100.")
    args = parser.parse_args()

    registry_paths = args.config or [args.registry]
    negative_paths = args.negative_pairs or DEFAULT_NEGATIVE_RULES
    entities, hyperedges = load_input(args.input)
    registry = AliasRegistry.from_yaml_files(registry_paths)
    negative_rules = NegativeRules(registry, negative_paths)
    condition_normalizer = ConditionNormalizer()
    normalized_entity_records, _ = condition_normalizer.normalize_entities(entities)
    entity_result = EntityNormalizer(
        registry,
        negative_rules=negative_rules,
        auto_threshold=args.fuzzy_threshold,
        use_llm=args.use_llm,
    ).normalize_entities(normalized_entity_records)
    hyperedge_result = HyperedgeRewriter(entity_result["mention_to_canonical_map"]).rewrite_hyperedges(hyperedges)
    report = build_normalization_report(
        entity_result["normalization_results"],
        raw_hyperedge_count=hyperedge_result["raw_hyperedge_count"],
        normalized_hyperedge_count=hyperedge_result["normalized_hyperedge_count"],
        unresolved_hyperedge_count=hyperedge_result["unresolved_hyperedge_count"],
    )

    output_payload = {
        "canonical_entities": entity_result["canonical_entities"],
        "mention_to_canonical_map": entity_result["mention_to_canonical_map"],
        "normalization_results": entity_result["normalization_results"],
        "hyperedges": hyperedge_result["hyperedges"],
        "report": report,
    }

    if args.output:
        write_json(args.output, output_payload)
    if args.output_dir:
        write_json(args.output_dir / "canonical_entities.json", entity_result["canonical_entities"])
        write_json(args.output_dir / "mention_to_canonical_map.json", entity_result["mention_to_canonical_map"])
        write_json(args.output_dir / "normalization_results.json", entity_result["normalization_results"])
        write_json(args.output_dir / "normalized_hyperedges.json", hyperedge_result["hyperedges"])
        write_json(args.output_dir / "normalization_report.json", report)
    if args.report:
        write_json(args.report, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
