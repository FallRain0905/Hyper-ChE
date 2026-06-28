"""Condition and metric normalization."""

from __future__ import annotations

from typing import Any
import re

from .unit_parser import UnitParser


class ConditionNormalizer:
    """Attach normalized numerical values to condition and metric entities."""

    CONDITION_TYPES = {
        "CONDITION",
        "METRIC",
        "OPERATING_CONDITION",
        "PERFORMANCE_METRIC",
        "PIEZO_PROPERTY",
    }

    def __init__(self, unit_parser: UnitParser | None = None):
        self.unit_parser = unit_parser or UnitParser()

    def normalize_entity(self, entity: dict[str, Any]) -> dict[str, Any]:
        output = dict(entity)
        entity_type = str(output.get("entity_type") or output.get("type") or "")
        if entity_type not in self.CONDITION_TYPES:
            return output

        name = str(output.get("entity_name") or output.get("name") or "")
        description = str(output.get("description") or "")
        key_attribute = str(output.get("key_attribute") or "")
        value = output.get("value")
        unit = output.get("unit")
        raw_text = " ".join(str(item) for item in [name, value if value is not None else "", unit or "", key_attribute, description] if str(item).strip())
        parsed = self.unit_parser.parse_dict(raw_text, hint=f"{name} {key_attribute}")
        if parsed:
            attributes = dict(output.get("attributes") or {})
            attributes["normalized_value"] = parsed
            output["attributes"] = attributes
        return output

    def normalize_entities(self, entities: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
        normalized = []
        parsed_count = 0
        for entity in entities:
            expanded = self._expand_multi_contact_angle_measurements(entity)
            if expanded:
                for expanded_item in expanded:
                    normalized.append(self.normalize_entity(expanded_item))
                    parsed_count += 1
                continue
            item = self.normalize_entity(entity)
            if (item.get("attributes") or {}).get("normalized_value"):
                parsed_count += 1
            normalized.append(item)
        return normalized, parsed_count

    @staticmethod
    def _expand_multi_contact_angle_measurements(entity: dict[str, Any]) -> list[dict[str, Any]]:
        entity_type = str(entity.get("entity_type") or entity.get("type") or "")
        if entity_type not in {"METRIC", "CONDITION", "PERFORMANCE_METRIC", "OPERATING_CONDITION"}:
            return []
        text = " ".join(
            str(item)
            for item in [
                entity.get("name") or entity.get("entity_name"),
                entity.get("key_attribute"),
                entity.get("description"),
            ]
            if item
        )
        if "contact angle" not in text.lower():
            return []
        values = re.findall(r"([-+]?\d+(?:\.\d+)?)\s*(?:°|deg)", text, flags=re.I)
        if len(values) < 2:
            # Some conversion paths normalize degree signs away before this step.
            tail_match = re.search(r"contact angle(.*)", text, flags=re.I)
            if tail_match and "/" in tail_match.group(1):
                values = re.findall(r"[-+]?\d+(?:\.\d+)?", tail_match.group(1))
        if len(values) < 2:
            return []
        output = []
        for value in values:
            item = dict(entity)
            item["name"] = f"contact angle {value}°"
            item["entity_name"] = item["name"]
            item["type"] = "METRIC"
            item["entity_type"] = "METRIC"
            item["value"] = float(value)
            item["unit"] = "deg"
            output.append(item)
        return output
