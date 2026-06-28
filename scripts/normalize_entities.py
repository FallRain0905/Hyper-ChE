"""Normalize a JSON list of extracted entities."""

from __future__ import annotations

import argparse
import json
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
    NegativeRules,
    build_normalization_report,
)


DEFAULT_REGISTRY = REPO_ROOT / "configs" / "normalization" / "alias_registry.yaml"
DEFAULT_NEGATIVE_RULES = [
    REPO_ROOT / "configs" / "normalization" / "negative_pairs.yaml",
    REPO_ROOT / "configs" / "normalization" / "high_risk_rules.yaml",
    REPO_ROOT / "configs" / "normalization" / "generic_terms.yaml",
]


def load_entities(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(data, dict):
        for key in ["entities", "nodes", "data"]:
            if isinstance(data.get(key), list):
                return data[key]
    if isinstance(data, list):
        return data
    raise ValueError("Input JSON must be a list or contain an 'entities' list.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize extracted entity JSON.")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--config", action="append", type=Path, default=[])
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--negative-pairs", action="append", type=Path, default=[])
    parser.add_argument("--fuzzy-threshold", type=float, default=95.0)
    parser.add_argument("--max-fuzzy-candidates", type=int, default=250)
    args = parser.parse_args()

    entities = load_entities(args.input)
    condition_normalizer = ConditionNormalizer()
    normalized_entities, unit_parse_count = condition_normalizer.normalize_entities(entities)
    registry = AliasRegistry.from_yaml_files(args.config or [args.registry])
    negative_rules = NegativeRules(registry, args.negative_pairs or DEFAULT_NEGATIVE_RULES)
    result = EntityNormalizer(
        registry,
        negative_rules=negative_rules,
        auto_threshold=args.fuzzy_threshold,
        max_fuzzy_candidates=args.max_fuzzy_candidates,
    ).normalize_entities(normalized_entities)
    report = build_normalization_report(result["normalization_results"])
    report["parsed_value_count"] = unit_parse_count

    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "canonical_entities.json").write_text(json.dumps(result["canonical_entities"], ensure_ascii=False, indent=2), encoding="utf-8")
    (args.output_dir / "mention_to_canonical_map.json").write_text(json.dumps(result["mention_to_canonical_map"], ensure_ascii=False, indent=2), encoding="utf-8")
    (args.output_dir / "normalization_results.json").write_text(json.dumps(result["normalization_results"], ensure_ascii=False, indent=2), encoding="utf-8")
    (args.output_dir / "normalization_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
