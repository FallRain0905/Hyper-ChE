"""Conservative exact/fuzzy chemical entity normalization."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
import re
from typing import Any

from .alias_registry import AliasRegistry
from .fuzzy_matcher import Candidate, get_top_k_candidates
from .negative_rules import NegativeRules
from .text_normalizer import normalize_text, normalize_text_for_match


@dataclass
class NormalizationResult:
    original_entity_id: str | None
    original_name: str
    entity_type: str
    decision: str
    canonical_id: str
    canonical_name: str
    confidence: float
    method: str
    node_id: str | None = None
    instance_id: str | None = None
    raw_mention: str | None = None
    semantic_group: str | None = None
    value: float | None = None
    min_value: float | None = None
    max_value: float | None = None
    unit: str | None = None
    candidates: list[dict[str, Any]] = field(default_factory=list)
    reason: str = ""
    need_review: bool = False
    blocked_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class NormalizedEntity:
    node_id: str
    canonical_id: str
    canonical_name: str
    type: str
    mentions: list[str] = field(default_factory=list)
    source_ids: list[str] = field(default_factory=list)
    descriptions: list[str] = field(default_factory=list)
    parent_id: str | None = None
    properties: dict[str, Any] = field(default_factory=dict)
    attributes: dict[str, Any] = field(default_factory=dict)
    normalization_method: str = "CREATE_NEW"
    confidence: float = 1.0
    need_review: bool = False
    raw_mention: str | None = None
    semantic_group: str | None = None
    value: float | None = None
    min_value: float | None = None
    max_value: float | None = None
    unit: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class EntityNormalizer:
    def __init__(
        self,
        alias_registry: AliasRegistry,
        *,
        negative_rules: NegativeRules | None = None,
        auto_threshold: float = 95.0,
        review_threshold: float = 85.0,
        top_k: int = 5,
        use_llm: bool = False,
        fuzzy_threshold: float | None = None,
        max_fuzzy_candidates: int | None = None,
    ):
        self.alias_registry = alias_registry
        self.negative_rules = negative_rules or NegativeRules(alias_registry)
        if fuzzy_threshold is None:
            self.auto_threshold = auto_threshold
        elif fuzzy_threshold <= 1:
            self.auto_threshold = fuzzy_threshold * 100.0
        else:
            self.auto_threshold = fuzzy_threshold
        self.review_threshold = review_threshold
        self.top_k = top_k
        self.use_llm = use_llm
        self.max_fuzzy_candidates = max_fuzzy_candidates

    def normalize_entity(self, entity: dict[str, Any], context: str | None = None) -> NormalizationResult:
        name = self._entity_name(entity)
        entity_type = self._entity_type(entity) or "UNKNOWN"
        original_id = entity.get("id") or entity.get("entity_id") or entity.get("entity_name")
        if not name:
            return self._create_new("", entity_type, original_id, reason="empty entity name")

        instance = self._try_measurement_or_condition_instance(entity, name, entity_type, original_id)
        if instance:
            return instance

        exact = self.alias_registry.match_exact(name, entity_type)
        if exact:
            blocked, reason = self.negative_rules.violates_negative_rule(name, exact.canonical_id, context)
            if not blocked:
                return NormalizationResult(
                    original_entity_id=str(original_id) if original_id else None,
                    original_name=name,
                    entity_type=entity_type,
                    decision="MERGE",
                    canonical_id=exact.canonical_id,
                    canonical_name=exact.canonical_name,
                    confidence=1.0,
                    method="exact_alias_match",
                    node_id=exact.canonical_id,
                    raw_mention=name,
                    semantic_group=exact.semantic_group,
                    reason="Matched canonical alias after string normalization.",
                )
            return self._need_review(name, entity_type, original_id, [], f"Blocked exact match: {reason}", reason)

        candidates = get_top_k_candidates(name, entity_type, self.alias_registry, self.top_k)
        candidate_dicts = [candidate.to_dict() for candidate in candidates]
        top = candidates[0] if candidates else None
        if not top or top.score < self.review_threshold:
            return self._create_new(name, entity_type, original_id, candidate_dicts, "No reliable fuzzy candidate.")

        blocked, blocked_reason = self.negative_rules.violates_negative_rule(name, top, context)
        if blocked:
            return self._need_review(
                name,
                entity_type,
                original_id,
                candidate_dicts,
                f"Blocked high-risk fuzzy merge: {blocked_reason}",
                blocked_reason,
            )

        auto_allowed, auto_reason = self._can_fuzzy_auto_merge(name, entity_type, top)
        if auto_allowed:
            return NormalizationResult(
                original_entity_id=str(original_id) if original_id else None,
                original_name=name,
                entity_type=entity_type,
                decision="MERGE",
                canonical_id=top.canonical_id,
                canonical_name=top.canonical_name,
                confidence=round(min(top.ratio_score, top.token_set_ratio_score) / 100.0, 4),
                method="fuzzy_auto_match",
                node_id=top.canonical_id,
                raw_mention=name,
                semantic_group=top.semantic_group,
                candidates=candidate_dicts,
                reason=auto_reason,
            )

        return self._need_review(
            name,
            entity_type,
            original_id,
            candidate_dicts,
            f"Top fuzzy score {top.score} requires review or LLM judgement; auto merge blocked: {auto_reason}",
            None,
        )

    def normalize_entities(self, entities: list[dict[str, Any]]) -> dict[str, Any]:
        results = [self.normalize_entity(entity) for entity in entities]
        return self.build_normalized_output(entities, results)

    def build_normalized_output(
        self,
        entities: list[dict[str, Any]],
        results: list[NormalizationResult],
    ) -> dict[str, Any]:
        canonical: dict[str, NormalizedEntity] = {}
        mention_map: dict[str, dict[str, Any]] = {}

        for entity, result in zip(entities, results):
            name = self._entity_name(entity)
            node_id = result.node_id or result.instance_id or result.canonical_id
            source_ids = self._split_sep(entity.get("source_id"))
            descriptions = self._split_sep(entity.get("description"))
            if node_id not in canonical:
                registry_entity = self.alias_registry.entities.get(result.canonical_id)
                canonical[node_id] = NormalizedEntity(
                    node_id=node_id,
                    canonical_id=result.canonical_id,
                    canonical_name=result.canonical_name,
                    type=result.entity_type,
                    parent_id=registry_entity.parent_id if registry_entity else None,
                    properties=registry_entity.properties if registry_entity else {},
                    normalization_method=result.method,
                    confidence=result.confidence,
                    need_review=result.need_review,
                    raw_mention=result.raw_mention or result.original_name,
                    semantic_group=result.semantic_group or (registry_entity.semantic_group if registry_entity else None),
                    value=result.value,
                    min_value=result.min_value,
                    max_value=result.max_value,
                    unit=result.unit,
                )
            item = canonical[node_id]
            if name and name not in item.mentions:
                item.mentions.append(name)
            for source_id in source_ids:
                if source_id and source_id not in item.source_ids:
                    item.source_ids.append(source_id)
            for description in descriptions:
                if description and description not in item.descriptions:
                    item.descriptions.append(description)
            mention_map[name] = {
                "node_id": node_id,
                "canonical_id": result.canonical_id,
                "canonical_name": result.canonical_name,
                "type": result.entity_type,
                "semantic_group": result.semantic_group,
                "confidence": result.confidence,
                "normalization_method": result.method,
                "decision": result.decision,
                "need_review": result.need_review,
                "instance_id": result.instance_id,
                "value": result.value,
                "min_value": result.min_value,
                "max_value": result.max_value,
                "unit": result.unit,
                "candidates": result.candidates,
                "reason": result.reason,
                "blocked_reason": result.blocked_reason,
            }

        return {
            "canonical_entities": [entity.to_dict() for entity in canonical.values()],
            "mention_to_canonical_map": mention_map,
            "normalization_results": [result.to_dict() for result in results],
            "report": self._build_report(results),
        }

    def _create_new(
        self,
        name: str,
        entity_type: str,
        original_id: Any,
        candidates: list[dict[str, Any]] | None = None,
        reason: str = "",
    ) -> NormalizationResult:
        canonical_name = name.strip() if name else "UNKNOWN"
        canonical_id = self._new_canonical_id(name or "unknown", entity_type)
        return NormalizationResult(
            original_entity_id=str(original_id) if original_id else None,
            original_name=name,
            entity_type=entity_type,
            decision="CREATE_NEW",
            canonical_id=canonical_id,
            canonical_name=canonical_name,
            confidence=0.0,
            method="create_new",
            node_id=canonical_id,
            raw_mention=name,
            semantic_group=self._infer_semantic_group(name, entity_type),
            candidates=candidates or [],
            reason=reason,
            need_review=False,
        )

    def _need_review(
        self,
        name: str,
        entity_type: str,
        original_id: Any,
        candidates: list[dict[str, Any]],
        reason: str,
        blocked_reason: str | None,
    ) -> NormalizationResult:
        canonical_name = name.strip()
        canonical_id = f"unresolved:{self._new_canonical_key(name)}"
        confidence = candidates[0]["score"] / 100.0 if candidates else 0.0
        return NormalizationResult(
            original_entity_id=str(original_id) if original_id else None,
            original_name=name,
            entity_type=entity_type,
            decision="NEED_REVIEW",
            canonical_id=canonical_id,
            canonical_name=canonical_name,
            confidence=round(confidence, 4),
            method="need_review",
            node_id=canonical_id,
            raw_mention=name,
            semantic_group=self._infer_semantic_group(name, entity_type),
            candidates=candidates,
            reason=reason,
            need_review=True,
            blocked_reason=blocked_reason,
        )

    @staticmethod
    def _build_report(results: list[NormalizationResult]) -> dict[str, Any]:
        exact = [item for item in results if item.method == "exact_alias_match"]
        fuzzy_auto = [item for item in results if item.method == "fuzzy_auto_match"]
        llm_judged = [item for item in results if item.method == "llm_judged"]
        created = [item for item in results if item.decision == "CREATE_NEW"]
        review = [item for item in results if item.need_review]
        blocked = [item for item in results if item.blocked_reason]
        merged = [item for item in results if item.decision == "MERGE"]
        return {
            "raw_entity_count": len(results),
            "exact_match_count": len(exact),
            "fuzzy_auto_match_count": len(fuzzy_auto),
            "llm_judged_count": len(llm_judged),
            "created_new_count": len(created),
            "need_review_count": len(review),
            "canonical_entity_count": len({item.node_id or item.instance_id or item.canonical_id for item in results}),
            "decision_counts": dict(Counter(item.decision for item in results)),
            "method_counts": dict(Counter(item.method for item in results)),
            "merge_ratio": round(len(merged) / len(results), 4) if results else 0.0,
            "top_unresolved_entities": [item.original_name for item in review[:20]],
            "top_added_aliases": [],
            "high_risk_blocked_merges": [
                {
                    "original_name": item.original_name,
                    "candidate": item.candidates[0] if item.candidates else None,
                    "reason": item.blocked_reason,
                }
                for item in blocked[:20]
            ],
        }

    def _can_fuzzy_auto_merge(self, mention: str, entity_type: str, candidate: Candidate) -> tuple[bool, str]:
        if candidate.score < self.auto_threshold:
            return False, f"top score {candidate.score} < auto threshold {self.auto_threshold}"
        if candidate.ratio_score < 97 or candidate.token_set_ratio_score < 95:
            return False, (
                "partial_ratio is retrieval-only; auto merge requires "
                f"ratio>=97 and token_set_ratio>=95, got ratio={candidate.ratio_score}, "
                f"token_set={candidate.token_set_ratio_score}"
            )
        if candidate.length_ratio < 0.75:
            return False, f"normalized length ratio {candidate.length_ratio} < 0.75"
        if self._has_numeric_signal(mention):
            return False, "numeric metric/condition mention must be preserved as an instance, not fuzzy-merged"
        if self.negative_rules.is_generic_mention(mention):
            return False, "generic mention cannot auto-merge into a specific entity"
        mention_group = self._infer_semantic_group(mention, entity_type)
        if candidate.semantic_group and mention_group and candidate.semantic_group != mention_group:
            return False, f"semantic group conflict: mention={mention_group}, candidate={candidate.semantic_group}"
        if entity_type in {"METRIC", "PERFORMANCE_METRIC", "CONDITION", "OPERATING_CONDITION"}:
            if not candidate.semantic_group or not mention_group:
                return False, "metric/condition fuzzy auto merge requires semantic group on both sides"
        return True, (
            "Conservative fuzzy auto match: ratio>=97, token_set_ratio>=95, "
            "length protected, semantic group compatible."
        )

    def _try_measurement_or_condition_instance(
        self,
        entity: dict[str, Any],
        name: str,
        entity_type: str,
        original_id: Any,
    ) -> NormalizationResult | None:
        upper_type = entity_type.upper()
        signal_text = self._entity_signal_text(entity, name)
        entity_surface_text = " ".join(str(item) for item in [name, entity.get("value"), entity.get("unit"), entity.get("key_attribute")] if item not in (None, ""))
        surface_condition = self._condition_base_from_name(entity_surface_text)
        if surface_condition and upper_type in {"METRIC", "PERFORMANCE_METRIC", "CONDITION", "OPERATING_CONDITION", "PIEZO_PROPERTY"}:
            condition_result = self._build_condition_instance(entity, name, entity_type, original_id, surface_condition)
            if condition_result and self._condition_should_precede_metric(surface_condition[0], entity_surface_text, False):
                return condition_result
        normalized_signal = normalize_text(signal_text)
        condition = self._condition_base_from_name(signal_text)

        # Hard condition units have priority over metric words. This prevents
        # values such as 120 mA/cm2 or 200 cycles from being flattened into
        # CE/VE/EE/capacity-retention measurement nodes when the LLM assigns a
        # noisy entity type or description.
        if upper_type in {"METRIC", "PERFORMANCE_METRIC", "CONDITION", "OPERATING_CONDITION", "PIEZO_PROPERTY"}:
            metric = self._metric_base_from_name(signal_text)
            metric_value = self._metric_value_from_text(metric[0], signal_text) if metric else None
            metric_has_explicit_value = metric is not None and metric_value is not None
            if condition and self._condition_should_precede_metric(condition[0], normalized_signal, metric_has_explicit_value):
                condition_result = self._build_condition_instance(entity, name, entity_type, original_id, condition)
                if condition_result:
                    return condition_result

        if upper_type in {"METRIC", "PERFORMANCE_METRIC", "CONDITION", "OPERATING_CONDITION", "PIEZO_PROPERTY"}:
            metric = self._metric_base_from_name(signal_text)
            parsed_value = self._metric_value_from_text(metric[0], signal_text) if metric else None
            if parsed_value is None:
                parsed_value = self._numeric_value_from_entity(entity, name, expected_kind="metric")
            if metric and parsed_value is not None:
                canonical_id, canonical_name, group = metric
                unit = self._unit_from_entity_or_text(entity, signal_text, default=self._metric_default_unit(canonical_id))
                if not self._metric_unit_allowed(canonical_id, unit, signal_text):
                    condition = self._condition_base_from_name(signal_text)
                    if condition:
                        condition_result = self._build_condition_instance(entity, name, entity_type, original_id, condition)
                        if condition_result:
                            return condition_result
                    return None
                instance_key = canonical_id.split(":", 1)[1]
                if canonical_id == "metric:polarization_voltage":
                    instance_key = "polarization_voltage_delta"
                value_slug = self._measurement_value_slug(canonical_id, parsed_value, unit)
                instance_id = f"measurement:{canonical_id.split(':', 1)[1]}_{value_slug}_{self._unit_slug(unit)}"
                if canonical_id == "metric:polarization_voltage":
                    instance_id = f"measurement:{instance_key}_{value_slug}_{self._unit_slug(unit)}"
                return NormalizationResult(
                    original_entity_id=str(original_id) if original_id else None,
                    original_name=name,
                    entity_type=entity_type,
                    decision="MERGE",
                    canonical_id=canonical_id,
                    canonical_name=canonical_name,
                    confidence=1.0,
                    method="measurement_instance",
                    node_id=instance_id,
                    instance_id=instance_id,
                    raw_mention=name,
                    semantic_group=group,
                    value=parsed_value,
                    unit=unit,
                    reason="Preserved numeric metric as measurement instance.",
                )

        if upper_type in {"CONDITION", "OPERATING_CONDITION"}:
            if condition:
                return self._build_condition_instance(entity, name, entity_type, original_id, condition)
        return None

    def _build_condition_instance(
        self,
        entity: dict[str, Any],
        name: str,
        entity_type: str,
        original_id: Any,
        condition: tuple[str, str, str, str],
    ) -> NormalizationResult | None:
        canonical_id, canonical_name, group, unit_default = condition
        value = self._numeric_value_from_entity(entity, name, expected_kind="condition")
        min_value = entity.get("value_min")
        max_value = entity.get("value_max")
        range_match = re.search(
            r"([-+]?\d+(?:\.\d+)?)\s*(?:-|to|~)\s*([-+]?\d+(?:\.\d+)?)",
            normalize_text(name),
            flags=re.I,
        )
        if range_match:
            min_value = float(range_match.group(1))
            max_value = float(range_match.group(2))
            if min_value > max_value:
                min_value, max_value = max_value, min_value
        if value is None and min_value is None and max_value is None:
            return None
        unit = self._unit_from_entity_or_text(entity, name, unit_default)
        if canonical_id == "condition:ph":
            unit = None
        if min_value is not None or max_value is not None:
            value_part = f"{self._slug_number(min_value)}_to_{self._slug_number(max_value)}"
        else:
            value_part = self._slug_number(value)
        suffix = f"_{self._unit_slug(unit)}" if unit and canonical_id != "condition:ph" else ""
        instance_id = f"condition:{canonical_id.split(':', 1)[1]}_{value_part}{suffix}"
        return NormalizationResult(
            original_entity_id=str(original_id) if original_id else None,
            original_name=name,
            entity_type=entity_type,
            decision="MERGE",
            canonical_id=canonical_id,
            canonical_name=canonical_name,
            confidence=1.0,
            method="condition_instance",
            node_id=instance_id,
            instance_id=instance_id,
            raw_mention=name,
            semantic_group=group,
            value=value,
            min_value=float(min_value) if min_value is not None else None,
            max_value=float(max_value) if max_value is not None else None,
            unit=unit,
            reason="Preserved numeric condition as condition instance.",
        )

    @staticmethod
    def _metric_base_from_name(name: str) -> tuple[str, str, str] | None:
        normalized = normalize_text_for_match(name)
        if (
            "polarizationvoltage" in normalized
            or "voltageloss" in normalized
            or "voltagedrop" in normalized
            or "ohmicvoltagedrop" in normalized
        ):
            return "metric:polarization_voltage", "polarization voltage", "polarization_metric"
        if "peakseparation" in normalized:
            return "metric:peak_separation", "peak separation", "electrochemical_evidence_metric"
        if re.search(r"(^|[^a-z])ce([^a-z]|$)|coulombic", name, flags=re.I) or normalized.startswith("ce"):
            return "metric:ce", "coulombic efficiency", "efficiency_metric"
        if re.search(r"(^|[^a-z])ve([^a-z]|$)|voltage efficiency|voltaic efficiency", name, flags=re.I) or normalized.startswith("ve"):
            return "metric:ve", "voltage efficiency", "efficiency_metric"
        if re.search(r"(^|[^a-z])ee([^a-z]|$)|energy", name, flags=re.I) or normalized.startswith("ee"):
            return "metric:ee", "energy efficiency", "efficiency_metric"
        if "capacityretention" in normalized:
            return "metric:capacity_retention", "capacity retention", "capacity_metric"
        if "energydensity" in normalized:
            return "metric:energy_density", "energy density", "energy_metric"
        if "ionexchangecapacity" in normalized or re.search(r"(^|[^a-z])iec([^a-z]|$)", name, flags=re.I):
            return "metric:ion_exchange_capacity", "ion exchange capacity", "ion_exchange_metric"
        if "arearesistance" in normalized:
            return "metric:area_resistance", "area resistance", "resistance_metric"
        if "ohmicresistance" in normalized or "ohmicloss" in normalized:
            return "metric:ohmic_resistance", "ohmic resistance", "resistance_metric"
        if "chargetransferresistance" in normalized or "rct" in normalized:
            return "metric:charge_transfer_resistance", "charge-transfer resistance", "resistance_metric"
        if "membraneresistance" in normalized:
            return "metric:membrane_resistance", "membrane resistance", "resistance_metric"
        if "surfaceroughness" in normalized:
            return "metric:surface_roughness", "surface roughness", "morphology_metric"
        if "contactangle" in normalized or "wettability" in normalized:
            return "metric:contact_angle", "contact angle", "morphology_metric"
        return None

    @staticmethod
    def _condition_base_from_name(name: str) -> tuple[str, str, str, str] | None:
        normalized = normalize_text_for_match(name)
        readable = normalize_text(name).lower()
        if "ma/cm2" in readable or "currentdensity" in normalized or re.search(r"\bma\b.*\bcm\b.*2", readable, flags=re.I):
            return "condition:current_density", "current density", "current_condition", "mA/cm2"
        if "flowrate" in normalized:
            return "condition:flow_rate", "flow rate", "flow_condition", "mL/min"
        if ("bi3" in normalized or "bismuth" in normalized) and ("mol/l" in readable or "mmol/l" in readable or "concentration" in normalized):
            return "condition:bi3_concentration", "Bi3+ concentration", "concentration_condition", "mmol/L"
        if "vanadium" in normalized and ("mol/l" in readable or "concentration" in normalized):
            return "condition:vanadium_concentration", "vanadium concentration", "concentration_condition", "mol/L"
        if ("h2so4" in normalized or "acid" in normalized) and ("mol/l" in readable or "concentration" in normalized):
            return "condition:acid_concentration", "acid concentration", "concentration_condition", "mol/L"
        if "electrolyte" in normalized and ("mol/l" in readable or "concentration" in normalized):
            return "condition:electrolyte_concentration", "electrolyte concentration", "concentration_condition", "mol/L"
        if "temperature" in normalized or "degc" in normalized or re.search(r"\b\d+(?:\.\d+)?\s*(?:°c|c)\b", readable, flags=re.I):
            return "condition:temperature", "temperature", "temperature_condition", "C"
        if "cycle" in normalized:
            return "condition:cycle_number", "cycle number", "cycle_condition", "cycle"
        if "ph" in normalized:
            return "condition:ph", "pH", "ph_condition", ""
        if "mol/l" in readable:
            return "condition:electrolyte_concentration", "electrolyte concentration", "concentration_condition", "mol/L"
        return None

    @staticmethod
    def _condition_should_precede_metric(condition_id: str, text: str, metric_has_explicit_value: bool) -> bool:
        lowered = normalize_text(text, lowercase=True)
        if metric_has_explicit_value:
            return False
        if condition_id == "condition:current_density":
            return "ma/cm2" in lowered
        if condition_id in {
            "condition:vanadium_concentration",
            "condition:acid_concentration",
            "condition:electrolyte_concentration",
            "condition:bi3_concentration",
        }:
            return "mol/l" in lowered or "mmol/l" in lowered
        if condition_id == "condition:temperature":
            return "degc" in lowered or re.search(r"\b\d+(?:\.\d+)?\s*c\b", lowered) is not None
        if condition_id == "condition:cycle_number":
            return "cycle" in lowered
        if condition_id == "condition:ph":
            return "ph" in lowered
        return False

    @staticmethod
    def _metric_unit_allowed(canonical_id: str, unit: str | None, text: str) -> bool:
        normalized_unit = (unit or "").lower()
        lowered = normalize_text(text, lowercase=True)
        raw = str(text or "")
        if canonical_id in {"metric:ce", "metric:ve", "metric:ee", "metric:capacity_retention"}:
            return normalized_unit == "%" and "%" in raw
        if canonical_id == "metric:ion_exchange_capacity":
            return normalized_unit == "mmol/g"
        if canonical_id == "metric:contact_angle":
            return normalized_unit in {"degree", "deg", "degrees"} and (
                "contact angle" in lowered or "degree" in lowered or "deg" in lowered
            )
        if canonical_id == "metric:polarization_voltage":
            return normalized_unit == "v"
        return True

    @staticmethod
    def _first_number(text: str, fallback: Any = None) -> float | None:
        if fallback is not None:
            try:
                return float(fallback)
            except (TypeError, ValueError):
                pass
        match = re.search(r"[-+]?\d+(?:\.\d+)?", str(text))
        return float(match.group(0)) if match else None

    @classmethod
    def _numeric_value_from_entity(cls, entity: dict[str, Any], name: str, *, expected_kind: str) -> float | None:
        if entity.get("value") is not None:
            try:
                return float(entity.get("value"))
            except (TypeError, ValueError):
                pass
        name_value = cls._first_number(name)
        if name_value is not None:
            return name_value
        parsed = (entity.get("attributes") or {}).get("normalized_value") or {}
        if not isinstance(parsed, dict):
            return None
        parsed_unit = str(parsed.get("unit") or "")
        quantity_type = str(parsed.get("quantity_type") or "").lower()
        if expected_kind == "metric":
            if parsed_unit == "%" or quantity_type in {"efficiency", "removal_rate", "defluorination_rate"}:
                try:
                    return float(parsed.get("value"))
                except (TypeError, ValueError):
                    return None
            return None
        try:
            return float(parsed.get("value"))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _unit_from_entity_or_text(entity: dict[str, Any], text: str, default: str | None = None) -> str | None:
        if entity.get("unit"):
            return EntityNormalizer._canonical_unit(normalize_text(str(entity["unit"])).replace("cm-2", "cm2"))
        lowered = normalize_text(text).lower()
        raw_lowered = str(text or "").lower()
        if "%" in text:
            return "%"
        if "mmol/g" in raw_lowered or "mmol g" in raw_lowered:
            return "mmol/g"
        if "ma/cm2" in lowered or "ma cm" in lowered:
            return "mA/cm2"
        if re.search(r"\bma\b.*\bcm\b.*2", lowered, flags=re.I):
            return "mA/cm2"
        if "mmol/l" in lowered:
            return "mmol/L"
        if "mol/l" in lowered:
            return "mol/L"
        if "ml/min" in lowered or "ml min" in lowered:
            return "mL/min"
        if "degc" in lowered or re.search(r"\b\d+(?:\.\d+)?\s*(?:°c|c)\b", raw_lowered):
            return "C"
        if "contactangle" in normalize_text_for_match(text) or "°" in str(text or "") or "degree" in lowered:
            return "degree"
        if re.search(r"\b\d+(?:\.\d+)?\s*v\b", lowered):
            return "V"
        if "ph" in lowered:
            return None
        if "cycle" in lowered:
            return "cycle"
        return EntityNormalizer._canonical_unit(default)

    @staticmethod
    def _canonical_unit(unit: str | None) -> str | None:
        if not unit:
            return unit
        raw = str(unit).strip()
        lowered = normalize_text(raw, lowercase=True)
        if lowered in {"%", "percent"}:
            return "%"
        if "ma/cm2" in lowered or ("ma" in lowered and "cm" in lowered):
            return "mA/cm2"
        if lowered in {"mol/l", "m"}:
            return "mol/L"
        if lowered in {"mmol/l", "mm"}:
            return "mmol/L"
        if lowered in {"mmol/g", "mmolg"}:
            return "mmol/g"
        if lowered in {"ml/min", "mlmin"}:
            return "mL/min"
        if lowered in {"degc", "°c", "c"}:
            return "C"
        if lowered in {"deg", "degree", "degrees", "°"}:
            return "degree"
        if lowered == "v":
            return "V"
        if lowered in {"cycle", "cycles"}:
            return "cycle"
        if lowered == "ph":
            return None
        return raw

    @staticmethod
    def _unit_slug(unit: str | None) -> str:
        if not unit:
            return "unitless"
        if unit == "%":
            return "percent"
        if unit.lower() == "ma/cm2":
            return "ma_cm2"
        if unit.lower() == "mol/l":
            return "mol_l"
        if unit.lower() == "mmol/l":
            return "mmol_l"
        if unit.lower() == "mmol/g":
            return "mmol_g"
        if unit.lower() == "ml/min":
            return "ml_min"
        if unit.lower() in {"deg", "degree", "degrees"}:
            return "degree"
        if unit.lower() == "c":
            return "c"
        if unit.lower() == "v":
            return "v"
        value = unit.replace("%", "percent").replace("/", "_").replace("\u00b0", "deg")
        value = value.replace("-", "_").replace(" ", "_")
        return normalize_text_for_match(value) or "unitless"

    @staticmethod
    def _slug_number(value: Any) -> str:
        if value is None:
            return "none"
        return f"{float(value):g}".replace("-", "minus_").replace(".", "_")

    @staticmethod
    def _measurement_value_slug(canonical_id: str, value: Any, unit: str | None) -> str:
        if value is None:
            return "none"
        numeric = float(value)
        if (
            canonical_id in {"metric:ce", "metric:ve", "metric:ee", "metric:capacity_retention"}
            and unit == "%"
            and numeric.is_integer()
        ):
            return f"{numeric:.1f}".replace("-", "minus_").replace(".", "_")
        return f"{numeric:g}".replace("-", "minus_").replace(".", "_")

    @staticmethod
    def _infer_semantic_group(name: str, entity_type: str) -> str | None:
        normalized = normalize_text_for_match(name)
        if entity_type in {"METRIC", "PERFORMANCE_METRIC"}:
            if "efficiency" in normalized or normalized in {"ce", "ve", "ee"}:
                return "efficiency_metric"
            if "resistance" in normalized or "rct" in normalized:
                return "resistance_metric"
            if "roughness" in normalized or "contactangle" in normalized or "wettability" in normalized:
                return "morphology_metric"
            if "capacityretention" in normalized:
                return "capacity_metric"
            if "energydensity" in normalized:
                return "energy_metric"
            if "ionexchangecapacity" in normalized or normalized == "iec":
                return "ion_exchange_metric"
            if "polarization" in normalized:
                return "polarization_metric"
            if "peakseparation" in normalized:
                return "electrochemical_evidence_metric"
            if "pumpingloss" in normalized:
                return "hydraulic_metric"
            if "masstransfer" in normalized:
                return "transport_metric"
        if entity_type in {"CONDITION", "OPERATING_CONDITION"}:
            if "currentdensity" in normalized:
                return "current_condition"
            if "flowrate" in normalized:
                return "flow_condition"
            if "concentration" in normalized or "mol/l" in normalize_text(name, lowercase=True):
                return "concentration_condition"
            if "temperature" in normalized or "degc" in normalized:
                return "temperature_condition"
            if "cycle" in normalized:
                return "cycle_condition"
            if "ph" in normalized:
                return "ph_condition"
        if entity_type in {"DEGRADATION", "MECHANISM"}:
            if any(term in normalized for term in ["crossover", "her", "hydrogenevolution", "capacityfading", "dendrite", "imbalance", "masstransfer", "polarization"]):
                return "degradation_mechanism"
        if entity_type in {"ACTIVE_SPECIES", "ADDITIVE"}:
            return "species_or_additive"
        return None

    @staticmethod
    def _has_numeric_signal(text: str) -> bool:
        return bool(re.search(r"\d", str(text or "")))

    @staticmethod
    def _entity_signal_text(entity: dict[str, Any], name: str) -> str:
        parts = [
            name,
            entity.get("value"),
            entity.get("unit"),
            entity.get("key_attribute"),
            entity.get("description"),
        ]
        parsed = (entity.get("attributes") or {}).get("normalized_value") or {}
        if isinstance(parsed, dict):
            parts.extend([parsed.get("raw"), parsed.get("value"), parsed.get("unit"), parsed.get("quantity_type")])
        return " ".join(str(item) for item in parts if item not in (None, ""))

    @staticmethod
    def _metric_default_unit(canonical_id: str) -> str:
        if canonical_id == "metric:ion_exchange_capacity":
            return "mmol/g"
        if canonical_id == "metric:contact_angle":
            return "degree"
        if canonical_id == "metric:peak_separation":
            return "V"
        if canonical_id == "metric:polarization_voltage":
            return "V"
        return "%"

    @staticmethod
    def _metric_value_from_text(canonical_id: str, text: str) -> float | None:
        normalized = normalize_text(text)
        patterns: list[str] = []
        if canonical_id == "metric:ce":
            patterns = [r"\bCE\b\s*(?:=|:)?\s*([-+]?\d+(?:\.\d+)?)\s*%", r"coulombic efficiency\s*(?:=|:|of)?\s*([-+]?\d+(?:\.\d+)?)\s*%"]
        elif canonical_id == "metric:ve":
            patterns = [r"\bVE\b\s*(?:=|:)?\s*([-+]?\d+(?:\.\d+)?)\s*%", r"voltage efficiency\s*(?:=|:|of)?\s*([-+]?\d+(?:\.\d+)?)\s*%"]
        elif canonical_id == "metric:ee":
            patterns = [r"\bEE\b\s*(?:=|:)?\s*([-+]?\d+(?:\.\d+)?)\s*%", r"energy efficiency\s*(?:=|:|of)?\s*([-+]?\d+(?:\.\d+)?)\s*%"]
        elif canonical_id == "metric:ion_exchange_capacity":
            patterns = [r"\bIEC\b\s*(?:=|:)?\s*([-+]?\d+(?:\.\d+)?)\s*mmol\s*/?\s*g", r"ion exchange capacity\s*(?:=|:|of)?\s*([-+]?\d+(?:\.\d+)?)\s*mmol\s*/?\s*g"]
        elif canonical_id == "metric:contact_angle":
            patterns = [r"contact angle\s*(?:=|:|of)?\s*([-+]?\d+(?:\.\d+)?)\s*(?:deg|°)?", r"\b([-+]?\d+(?:\.\d+)?)\s*(?:deg|°)\b"]
        elif canonical_id == "metric:peak_separation":
            patterns = [r"peak separation\s*(?:=|:|of)?\s*([-+]?\d+(?:\.\d+)?)\s*(?:v|mv)?"]
        elif canonical_id == "metric:polarization_voltage":
            patterns = [
                r"(?:polarization voltage|voltage loss|voltage drop|ohmic voltage drop)\s*(?:difference|delta)?\s*(?:=|:|of|by)?\s*([-+]?\d+(?:\.\d+)?)\s*v",
                r"\b([-+]?\d+(?:\.\d+)?)\s*v\b",
            ]
        for pattern in patterns:
            match = re.search(pattern, normalized, flags=re.I)
            if match:
                return float(match.group(1))
        if canonical_id in {"metric:ce", "metric:ve", "metric:ee", "metric:capacity_retention"}:
            percent_values = re.findall(r"([-+]?\d+(?:\.\d+)?)\s*%", normalized)
            if percent_values:
                return float(percent_values[-1])
        return None

    @staticmethod
    def _entity_name(entity: dict[str, Any]) -> str:
        return str(entity.get("entity_name") or entity.get("name") or entity.get("id") or "").strip()

    @staticmethod
    def _entity_type(entity: dict[str, Any]) -> str | None:
        value = entity.get("entity_type") or entity.get("type")
        return str(value).strip() if value else None

    @staticmethod
    def _split_sep(value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return [item.strip() for item in str(value).split("<SEP>") if item.strip()]

    @staticmethod
    def _new_canonical_key(name: str) -> str:
        value = normalize_text(str(name or ""), lowercase=True)
        value = value.replace("+", " plus ").replace("/", " ").replace("-", " ")
        tokens = re.findall(r"[a-z0-9]+", value)
        key = "_".join(tokens)
        return key or "unknown"

    def _new_canonical_id(self, name: str, entity_type: str | None) -> str:
        prefix = self._canonical_prefix(entity_type or "entity")
        return f"{prefix}:{self._new_canonical_key(name)}"

    @staticmethod
    def _canonical_prefix(entity_type: str | None) -> str:
        value = str(entity_type or "entity").strip().upper()
        mapping = {
            "ACTIVE_SPECIES": "active_species",
            "SPECIES": "active_species",
            "ADDITIVE": "active_species",
            "PERFORMANCE_METRIC": "metric",
            "METRIC": "metric",
            "OPERATING_CONDITION": "condition",
            "CONDITION": "condition",
            "DEGRADATION": "degradation",
            "MECHANISM": "degradation",
            "MECHANISM_EVIDENCE": "evidence",
            "EVIDENCE": "evidence",
            "MEMBRANE": "membrane",
            "ELECTRODE": "electrode",
            "SYSTEM": "system",
        }
        return mapping.get(value, normalize_text_for_match(value).replace("/", "_") or "entity")
