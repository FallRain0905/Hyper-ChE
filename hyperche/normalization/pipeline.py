"""Online normalization hooks for the extraction pipeline."""

from __future__ import annotations

from functools import lru_cache
import logging
import re
from pathlib import Path
from typing import Any

from .alias_registry import AliasRegistry
from .condition_normalizer import ConditionNormalizer
from .entity_normalizer import EntityNormalizer, NormalizationResult
from .llm_normalizer import LLMNormalizationDecision, judge_with_llm
from .negative_rules import NegativeRules


CONFIG_ROOT = Path(__file__).resolve().parents[2] / "configs" / "normalization"


DEFAULT_REGISTRY = CONFIG_ROOT / "alias_registry.yaml"
DEFAULT_NEGATIVE_RULES = [
    CONFIG_ROOT / "negative_pairs.yaml",
    CONFIG_ROOT / "high_risk_rules.yaml",
    CONFIG_ROOT / "generic_terms.yaml",
]
logger = logging.getLogger("hyper_rag")


def default_config_paths_for_domain(domain: str) -> list[Path]:
    return [DEFAULT_REGISTRY]


@lru_cache(maxsize=16)
def _registry_from_paths(paths_key: tuple[str, ...]) -> AliasRegistry:
    return AliasRegistry.from_yaml_files(paths_key)


def get_alias_registry(domain: str, config_paths: list[str | Path] | None = None) -> AliasRegistry:
    paths = [Path(path) for path in (config_paths or default_config_paths_for_domain(domain))]
    return _registry_from_paths(tuple(str(path) for path in paths))


def normalize_entities_for_extraction(
    entities_json: list[dict[str, Any]],
    *,
    domain: str,
    config_paths: list[str | Path] | None = None,
    fuzzy_threshold: float = 95.0,
    max_fuzzy_candidates: int = 50,
    negative_rule_paths: list[str | Path] | None = None,
    use_llm: bool = False,
    enable_measurement_instances: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Normalize parsed JSON entities before relation extraction and graph writes.

    The returned entities keep the original extraction schema, but their ``name``
    fields are replaced by canonical names when a confident alias/formula match
    exists. Raw mentions are retained in ``raw_name`` and ``mentions``.
    """

    condition_normalizer = ConditionNormalizer()
    enriched_entities, parsed_value_count = condition_normalizer.normalize_entities(entities_json)
    registry = get_alias_registry(domain, config_paths)
    negative_rules = NegativeRules(registry, negative_rule_paths or DEFAULT_NEGATIVE_RULES)
    normalizer = EntityNormalizer(
        registry,
        negative_rules=negative_rules,
        fuzzy_threshold=fuzzy_threshold,
        top_k=5,
        max_fuzzy_candidates=max_fuzzy_candidates,
        use_llm=use_llm,
    )
    normalized = normalizer.normalize_entities(enriched_entities)
    if not enable_measurement_instances:
        normalized = _disable_measurement_instances(normalized)
    mention_map = normalized["mention_to_canonical_map"]
    result_items = normalized.get("normalization_results") or []

    grouped: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = {}
    for index, entity in enumerate(enriched_entities):
        name = str(entity.get("name") or entity.get("entity_name") or "").strip()
        match = result_items[index] if index < len(result_items) else mention_map.get(name)
        node_id = (
            match.get("node_id")
            or match.get("instance_id")
            or match.get("canonical_id")
            if match
            else f"raw:{name}"
        )
        grouped.setdefault(node_id, []).append((entity, match or {}))

    canonical_meta = {
        item.get("node_id", item["canonical_id"]): item
        for item in normalized["canonical_entities"]
    }
    output: list[dict[str, Any]] = []
    for node_id, grouped_items in grouped.items():
        raw_items = [item for item, _ in grouped_items]
        first_result = grouped_items[0][1] if grouped_items else {}
        base = dict(raw_items[0])
        meta = canonical_meta.get(node_id)
        if not meta:
            output.append(base)
            continue

        mentions = []
        for raw in raw_items:
            raw_name = str(raw.get("name") or raw.get("entity_name") or "").strip()
            if raw_name and raw_name not in mentions:
                mentions.append(raw_name)

        descriptions = [
            str(raw.get("description") or "").strip()
            for raw in raw_items
            if str(raw.get("description") or "").strip()
        ]

        raw_name = str(base.get("name") or base.get("entity_name") or "").strip()
        is_instance = bool(meta.get("value") is not None or meta.get("min_value") is not None or meta.get("max_value") is not None)
        base["node_id"] = node_id
        base["raw_name"] = raw_name
        base["source_mentions"] = mentions
        base["mentions"] = mentions
        base["canonical_id"] = meta["canonical_id"]
        base["canonical_name"] = meta["canonical_name"]
        base["name"] = node_id if is_instance else meta["canonical_name"]
        base["display_name"] = meta["canonical_name"]
        base["type"] = meta["type"]
        base["semantic_group"] = meta.get("semantic_group")
        base["normalization_method"] = meta["normalization_method"]
        base["normalization_confidence"] = meta["confidence"]
        base["need_review"] = meta.get("need_review", False)
        for field in ("value", "min_value", "max_value", "unit"):
            if meta.get(field) is not None:
                base[field] = meta[field]
        if first_result:
            base["normalization_candidates"] = first_result.get("candidates", [])
            base["normalization_reason"] = first_result.get("reason", "")
        if meta.get("parent_id"):
            base["parent_id"] = meta["parent_id"]
        if descriptions:
            base["description"] = " | ".join(dict.fromkeys(descriptions))
        output.append(base)

    output = _apply_cell_decomposition(output, "")

    report = dict(normalized.get("report") or {})
    report.update({
        "raw_entity_count": len(entities_json),
        "normalized_entity_count": len(output),
        "merged_entity_count": max(0, len(entities_json) - len(output)),
        "parsed_value_count": parsed_value_count,
        "alias_match_count": report.get("exact_match_count", 0) + report.get("fuzzy_auto_match_count", 0),
        "fuzzy_match_count": report.get("fuzzy_auto_match_count", 0),
    })
    return output, report


async def normalize_entities_for_extraction_async(
    entities_json: list[dict[str, Any]],
    *,
    domain: str,
    config_paths: list[str | Path] | None = None,
    fuzzy_threshold: float = 95.0,
    max_fuzzy_candidates: int = 50,
    negative_rule_paths: list[str | Path] | None = None,
    use_llm: bool = True,
    enable_measurement_instances: bool = True,
    llm_func: Any = None,
    local_context: str = "",
    chunk_key: str = "",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    condition_normalizer = ConditionNormalizer()
    enriched_entities, parsed_value_count = condition_normalizer.normalize_entities(entities_json)
    logger.info(
        "[%s] Step 1N.1: Condition/unit normalization done: raw_entities=%s, parsed_values=%s",
        chunk_key,
        len(entities_json),
        parsed_value_count,
    )

    registry = get_alias_registry(domain, config_paths)
    negative_rules = NegativeRules(registry, negative_rule_paths or DEFAULT_NEGATIVE_RULES)
    normalizer = EntityNormalizer(
        registry,
        negative_rules=negative_rules,
        fuzzy_threshold=fuzzy_threshold,
        top_k=5,
        max_fuzzy_candidates=max_fuzzy_candidates,
        use_llm=use_llm,
    )
    logger.info(
        "[%s] Step 1N.2: Registry loaded: canonical_entities=%s, use_llm=%s, fuzzy_auto_threshold=%s",
        chunk_key,
        len(registry.entities),
        use_llm,
        normalizer.auto_threshold,
    )

    results = []
    for index, entity in enumerate(enriched_entities):
        result = normalizer.normalize_entity(entity, context=local_context)
        logger.info(
            "[%s] Step 1N.3 entity[%s]: mention=%r type=%s initial_decision=%s method=%s confidence=%.4f target=%s review=%s reason=%s top_candidates=%s",
            chunk_key,
            index,
            result.original_name,
            result.entity_type,
            result.decision,
            result.method,
            result.confidence,
            result.canonical_id,
            result.need_review,
            result.reason,
            _candidate_summary(result.candidates),
        )
        results.append(result)

    if use_llm:
        results = await _apply_llm_judgement(
            results,
            enriched_entities,
            normalizer=normalizer,
            negative_rules=negative_rules,
            llm_func=llm_func,
            local_context=local_context,
            chunk_key=chunk_key,
        )
    else:
        logger.info("[%s] Step 1N.4: LLM normalization disabled", chunk_key)

    if not enable_measurement_instances:
        results = [_collapse_instance_result(result) for result in results]
        logger.info("[%s] Step 1N.4b: measurement/condition instance nodes disabled", chunk_key)

    normalized = normalizer.build_normalized_output(enriched_entities, results)
    if not enable_measurement_instances:
        normalized = _disable_measurement_instances(normalized)
    output, report = _build_online_output(enriched_entities, normalized, entities_json, parsed_value_count, local_context)
    for index, item in enumerate(normalized.get("normalization_results", [])):
        logger.info(
            "[%s] Step 1N.5 final entity[%s]: mention=%r decision=%s method=%s canonical_id=%s canonical_name=%r confidence=%s review=%s reason=%s",
            chunk_key,
            index,
            item.get("original_name"),
            item.get("decision"),
            item.get("method"),
            item.get("canonical_id"),
            item.get("canonical_name"),
            item.get("confidence"),
            item.get("need_review"),
            item.get("reason"),
        )
    logger.info(
        "[%s] Step 1N.5: Final normalization output built: normalized_entities=%s, decisions=%s",
        chunk_key,
        len(output),
        report.get("decision_counts", {}),
    )
    return output, report


async def _apply_llm_judgement(
    results: list[NormalizationResult],
    entities: list[dict[str, Any]],
    *,
    normalizer: EntityNormalizer,
    negative_rules: NegativeRules,
    llm_func: Any,
    local_context: str,
    chunk_key: str,
) -> list[NormalizationResult]:
    if llm_func is None:
        logger.warning("[%s] Step 1N.4: LLM normalization requested but llm_func is missing", chunk_key)
        return results

    updated = []
    for index, (entity, result) in enumerate(zip(entities, results)):
        should_judge = result.decision == "NEED_REVIEW" and bool(result.candidates) and not result.blocked_reason
        if not should_judge:
            updated.append(result)
            continue

        payload = {
            "mention": result.original_name,
            "entity_type": result.entity_type,
            "local_context": local_context[:3000],
            "nearby_entities": [
                str(item.get("name") or item.get("entity_name") or "")
                for item in entities
                if item is not entity
            ][:20],
            "top_candidates": result.candidates[:5],
            "negative_constraints": "Do not merge different PFAS targets, valence states, membrane models, composites, or distinct metrics.",
        }
        logger.info(
            "[%s] Step 1N.4 LLM request entity[%s]: mention=%r candidates=%s",
            chunk_key,
            index,
            result.original_name,
            _candidate_summary(result.candidates),
        )
        try:
            decision = await judge_with_llm(payload, llm_func)
            logger.info(
                "[%s] Step 1N.4 LLM response entity[%s]: decision=%s target=%s confidence=%.4f review=%s reason=%s",
                chunk_key,
                index,
                decision.decision,
                decision.target_canonical_id,
                decision.confidence,
                decision.need_review,
                decision.reason,
            )
            updated.append(_apply_llm_decision(result, decision, normalizer, negative_rules))
        except Exception as e:
            logger.warning(
                "[%s] Step 1N.4 LLM failed entity[%s]: mention=%r error=%s: %s",
                chunk_key,
                index,
                result.original_name,
                type(e).__name__,
                e,
            )
            updated.append(result)
    return updated


def _apply_llm_decision(
    result: NormalizationResult,
    decision: LLMNormalizationDecision,
    normalizer: EntityNormalizer,
    negative_rules: NegativeRules,
) -> NormalizationResult:
    candidate_ids = {item["canonical_id"] for item in result.candidates}
    decision_name = decision.decision.upper()

    if decision_name == "MERGE" and decision.target_canonical_id in candidate_ids:
        blocked, blocked_reason = negative_rules.violates_negative_rule(result.original_name, decision.target_canonical_id)
        if blocked:
            return NormalizationResult(
                **{
                    **result.to_dict(),
                    "reason": f"LLM suggested MERGE but negative rule blocked it: {blocked_reason}",
                    "blocked_reason": blocked_reason,
                    "need_review": True,
                }
            )
        entity = normalizer.alias_registry.entities.get(decision.target_canonical_id)
        if entity:
            mention_group = result.semantic_group or normalizer._infer_semantic_group(result.original_name, result.entity_type)
            if entity.semantic_group and mention_group and entity.semantic_group != mention_group:
                return NormalizationResult(
                    **{
                        **result.to_dict(),
                        "reason": (
                            "LLM suggested MERGE but semantic_group conflict blocked it: "
                            f"mention={mention_group}, candidate={entity.semantic_group}"
                        ),
                        "blocked_reason": "semantic_group_conflict",
                        "need_review": True,
                    }
                )
            if result.entity_type in {"METRIC", "PERFORMANCE_METRIC", "CONDITION", "OPERATING_CONDITION"}:
                if not entity.semantic_group or not mention_group:
                    return NormalizationResult(
                        **{
                            **result.to_dict(),
                            "reason": "LLM suggested MERGE but metric/condition semantic_group is missing.",
                            "blocked_reason": "missing_semantic_group",
                            "need_review": True,
                        }
                    )
            return NormalizationResult(
                original_entity_id=result.original_entity_id,
                original_name=result.original_name,
                entity_type=result.entity_type,
                decision="MERGE",
                canonical_id=entity.canonical_id,
                canonical_name=entity.canonical_name,
                confidence=max(0.0, min(1.0, decision.confidence or result.confidence)),
                method="llm_judged",
                node_id=entity.canonical_id,
                raw_mention=result.original_name,
                semantic_group=entity.semantic_group,
                candidates=result.candidates,
                reason=decision.reason or "LLM judged same_as top candidate.",
                need_review=decision.need_review,
            )

    if decision_name in {"CREATE_NEW", "CREATE_VARIANT", "CREATE_COMPONENT_RELATION", "CREATE_PARENT_CHILD", "NO_MERGE"}:
        canonical_id = result.canonical_id
        canonical_name = result.canonical_name
        if decision_name == "CREATE_NEW":
            canonical_id = normalizer._new_canonical_id(result.original_name or "unknown", result.entity_type)
            canonical_name = decision.canonical_name or result.original_name
        return NormalizationResult(
            original_entity_id=result.original_entity_id,
            original_name=result.original_name,
            entity_type=result.entity_type,
            decision=decision_name,
            canonical_id=canonical_id,
            canonical_name=canonical_name,
            confidence=max(0.0, min(1.0, decision.confidence or result.confidence)),
            method="llm_judged",
            node_id=canonical_id,
            raw_mention=result.original_name,
            semantic_group=result.semantic_group,
            candidates=result.candidates,
            reason=decision.reason or f"LLM returned {decision_name}.",
            need_review=decision.need_review if decision_name not in {"CREATE_NEW"} else False,
        )

    return NormalizationResult(
        **{
            **result.to_dict(),
            "method": "llm_judged",
            "reason": decision.reason or "LLM kept entity in review.",
            "need_review": True,
        }
    )


def _build_online_output(
    enriched_entities: list[dict[str, Any]],
    normalized: dict[str, Any],
    raw_entities: list[dict[str, Any]],
    parsed_value_count: int,
    local_context: str = "",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    mention_map = normalized["mention_to_canonical_map"]
    result_items = normalized.get("normalization_results") or []
    grouped: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = {}
    for index, entity in enumerate(enriched_entities):
        name = str(entity.get("name") or entity.get("entity_name") or "").strip()
        match = result_items[index] if index < len(result_items) else mention_map.get(name)
        node_id = (
            match.get("node_id")
            or match.get("instance_id")
            or match.get("canonical_id")
            if match
            else f"raw:{name}"
        )
        grouped.setdefault(node_id, []).append((entity, match or {}))

    canonical_meta = {
        item.get("node_id", item["canonical_id"]): item
        for item in normalized["canonical_entities"]
    }
    output: list[dict[str, Any]] = []
    for node_id, grouped_items in grouped.items():
        raw_items = [item for item, _ in grouped_items]
        first_result = grouped_items[0][1] if grouped_items else {}
        base = dict(raw_items[0])
        meta = canonical_meta.get(node_id)
        if not meta:
            output.append(base)
            continue

        mentions = []
        for raw in raw_items:
            raw_name = str(raw.get("name") or raw.get("entity_name") or "").strip()
            if raw_name and raw_name not in mentions:
                mentions.append(raw_name)

        descriptions = [
            str(raw.get("description") or "").strip()
            for raw in raw_items
            if str(raw.get("description") or "").strip()
        ]

        raw_name = str(base.get("name") or base.get("entity_name") or "").strip()
        is_instance = bool(meta.get("value") is not None or meta.get("min_value") is not None or meta.get("max_value") is not None)
        base["node_id"] = node_id
        base["raw_name"] = raw_name
        base["source_mentions"] = mentions
        base["mentions"] = mentions
        base["canonical_id"] = meta["canonical_id"]
        base["canonical_name"] = meta["canonical_name"]
        base["name"] = node_id if is_instance else meta["canonical_name"]
        base["display_name"] = meta["canonical_name"]
        base["type"] = meta["type"]
        base["semantic_group"] = meta.get("semantic_group")
        base["normalization_method"] = meta["normalization_method"]
        base["normalization_confidence"] = meta["confidence"]
        base["need_review"] = meta.get("need_review", False)
        for field in ("value", "min_value", "max_value", "unit"):
            if meta.get(field) is not None:
                base[field] = meta[field]
        if first_result:
            base["normalization_candidates"] = first_result.get("candidates", [])
            base["normalization_reason"] = first_result.get("reason", "")
        if meta.get("parent_id"):
            base["parent_id"] = meta["parent_id"]
        if descriptions:
            base["description"] = " | ".join(dict.fromkeys(descriptions))
        output.append(base)

    output = _apply_cell_decomposition(output, local_context)

    report = dict(normalized.get("report") or {})
    report.update({
        "raw_entity_count": len(raw_entities),
        "normalized_entity_count": len(output),
        "merged_entity_count": max(0, len(raw_entities) - len(output)),
        "parsed_value_count": parsed_value_count,
        "normalization_results": normalized.get("normalization_results", []),
        "alias_match_count": report.get("exact_match_count", 0)
        + report.get("fuzzy_auto_match_count", 0)
        + report.get("llm_judged_count", 0),
        "fuzzy_match_count": report.get("fuzzy_auto_match_count", 0),
    })
    return output, report


def _collapse_instance_result(result: NormalizationResult) -> NormalizationResult:
    """Collapse measurement/condition instance nodes back to concept nodes for ablations."""

    is_instance = bool(result.instance_id) or str(result.node_id or "").startswith("measurement:")
    node_id = str(result.node_id or "")
    if node_id.startswith("condition:") and re.search(r"_\d", node_id):
        is_instance = True
    if not is_instance:
        return result
    return NormalizationResult(
        original_entity_id=result.original_entity_id,
        original_name=result.original_name,
        entity_type=result.entity_type,
        decision=result.decision,
        canonical_id=result.canonical_id,
        canonical_name=result.canonical_name,
        confidence=result.confidence,
        method=f"{result.method}_concept_only",
        node_id=result.canonical_id,
        instance_id=None,
        raw_mention=result.raw_mention,
        semantic_group=result.semantic_group,
        candidates=result.candidates,
        reason=(result.reason or "") + " Instance node disabled by experiment config.",
        need_review=result.need_review,
        blocked_reason=result.blocked_reason,
    )


def _disable_measurement_instances(normalized: dict[str, Any]) -> dict[str, Any]:
    """Remove measurement/condition instance IDs from normalized output metadata."""

    output = dict(normalized)
    rewritten_results = []
    for item in output.get("normalization_results") or []:
        result = dict(item)
        node_id = str(result.get("node_id") or result.get("instance_id") or "")
        is_instance = bool(result.get("instance_id")) or node_id.startswith("measurement:")
        if node_id.startswith("condition:") and re.search(r"_\d", node_id):
            is_instance = True
        if is_instance:
            result["node_id"] = result.get("canonical_id")
            result["instance_id"] = None
            result["method"] = f"{result.get('method', 'normalization')}_concept_only"
            for field in ("value", "min_value", "max_value", "unit"):
                result[field] = None
        rewritten_results.append(result)
    output["normalization_results"] = rewritten_results

    canonical = {}
    for item in output.get("canonical_entities") or []:
        meta = dict(item)
        node_id = str(meta.get("node_id") or "")
        is_instance = node_id.startswith("measurement:") or (node_id.startswith("condition:") and re.search(r"_\d", node_id))
        if is_instance:
            meta["node_id"] = meta.get("canonical_id")
            meta["normalization_method"] = f"{meta.get('normalization_method', 'normalization')}_concept_only"
            for field in ("value", "min_value", "max_value", "unit"):
                meta[field] = None
        canonical[meta.get("node_id") or meta.get("canonical_id")] = meta
    output["canonical_entities"] = list(canonical.values())

    report = dict(output.get("report") or {})
    report["measurement_instances_enabled"] = False
    report["measurement_instance_disabled_count"] = sum(
        1 for item in output.get("normalization_results") or []
        if str(item.get("method") or "").endswith("_concept_only")
    )
    output["report"] = report
    return output
def _apply_cell_decomposition(entities: list[dict[str, Any]], local_context: str = "") -> list[dict[str, Any]]:
    """Add explicit material/system role nodes for cell-level mentions.

    Cell labels such as "SPEEK/APK cell" are useful surface mentions but poor
    role nodes. Keeping them while adding membrane/electrode/system nodes gives
    relationship extraction a cleaner EFU vocabulary without deleting evidence.
    """

    output = list(entities)
    existing = {str(item.get("node_id") or item.get("name") or "") for item in output}
    context = " ".join(
        [
            local_context or "",
            " ".join(str(item.get("name") or "") for item in entities),
            " ".join(str(item.get("raw_name") or "") for item in entities),
        ]
    ).lower()

    def add(node_id: str, canonical_name: str, entity_type: str, semantic_group: str, raw_mention: str, reason: str) -> None:
        if node_id in existing:
            return
        existing.add(node_id)
        output.append(
            {
                "node_id": node_id,
                "name": canonical_name,
                "display_name": canonical_name,
                "raw_name": raw_mention,
                "source_mentions": [raw_mention],
                "mentions": [raw_mention],
                "canonical_id": node_id,
                "canonical_name": canonical_name,
                "type": entity_type,
                "semantic_group": semantic_group,
                "normalization_method": "cell_decomposition",
                "normalization_confidence": 0.9,
                "need_review": False,
                "description": reason,
            }
        )

    for entity in entities:
        surfaces = " ".join(
            str(value)
            for value in [
                entity.get("name"),
                entity.get("raw_name"),
                " ".join(entity.get("mentions") or []),
                " ".join(entity.get("source_mentions") or []),
            ]
            if value
        ).lower()
        if "cell" not in surfaces:
            continue
        if "speek/apk" in surfaces or "speek apk" in surfaces:
            add("system:vrfb", "vanadium redox flow battery", "SYSTEM", "flow_battery_system", "SPEEK/APK cell", "Decomposed SPEEK/APK cell into VRFB system.")
            add("membrane:speek_apk", "SPEEK/APK", "MEMBRANE", "membrane_model", "SPEEK/APK cell", "Decomposed SPEEK/APK cell into membrane role.")
        if "sptpc-2.59" in surfaces or "sptpc_2_59" in surfaces or "sptpc 2.59" in surfaces:
            add("system:vrfb", "vanadium redox flow battery", "SYSTEM", "flow_battery_system", "SPTPC-2.59 cell", "Decomposed SPTPC-2.59 cell into VRFB system.")
            add("membrane:sptpc_2_59", "SPTPC-2.59", "MEMBRANE", "membrane_model", "SPTPC-2.59 cell", "Decomposed SPTPC-2.59 cell into membrane role.")
        if "snpbi-1.42" in surfaces or "snpbi_1_42" in surfaces or "snpbi 1.42" in surfaces:
            add("system:vrfb", "vanadium redox flow battery", "SYSTEM", "flow_battery_system", "SNPBI-1.42 cell", "Decomposed SNPBI-1.42 cell into VRFB system.")
            add("membrane:snpbi_1_42", "SNPBI-1.42", "MEMBRANE", "membrane_model", "SNPBI-1.42 cell", "Decomposed SNPBI-1.42 cell into membrane role.")
        if "baseline cell" in surfaces and any(term in context for term in ["vrfb", "vanadium redox"]):
            add("system:vrfb", "vanadium redox flow battery", "SYSTEM", "flow_battery_system", "baseline cell", "Resolved baseline cell system from local VRFB context.")
            if any(term in context for term in ["nafion", "n117", "n212"]):
                add("membrane:nafion", "Nafion", "MEMBRANE", "membrane_family", "baseline cell", "Resolved baseline cell membrane from local context.")
            if "graphite felt" in context:
                add("electrode:graphite_felt", "graphite felt", "ELECTRODE", "electrode_material", "baseline cell", "Resolved baseline cell electrode from local context.")
        if "activated carbon felt cell" in surfaces:
            if any(term in context for term in ["vrfb", "vanadium redox"]):
                add("system:vrfb", "vanadium redox flow battery", "SYSTEM", "flow_battery_system", "activated carbon felt cell", "Resolved activated carbon felt cell system from local context.")
            add("electrode:activated_carbon_felt", "activated carbon felt", "ELECTRODE", "electrode_material", "activated carbon felt cell", "Decomposed activated carbon felt cell into electrode role.")

    return output


def _candidate_summary(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": item.get("canonical_id"),
            "name": item.get("canonical_name"),
            "score": item.get("score"),
        }
        for item in candidates[:5]
    ]

