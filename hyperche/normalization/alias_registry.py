"""YAML-backed canonical chemical entity registry."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import yaml

from .text_normalizer import normalize_text_for_match


@dataclass(frozen=True)
class CanonicalEntity:
    canonical_id: str
    canonical_name: str
    entity_type: str
    aliases: tuple[str, ...] = field(default_factory=tuple)
    parent_id: str | None = None
    notes: str | None = None
    semantic_group: str | None = None
    properties: dict[str, Any] = field(default_factory=dict)
    compatible_types: tuple[str, ...] = field(default_factory=tuple)
    match_strings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def type(self) -> str:
        return self.entity_type


@dataclass(frozen=True)
class AliasMatch:
    canonical_id: str
    canonical_name: str
    entity_type: str
    confidence: float
    method: str
    parent_id: str | None = None
    semantic_group: str | None = None
    properties: dict[str, Any] = field(default_factory=dict)

    @property
    def type(self) -> str:
        return self.entity_type

    @property
    def normalization_method(self) -> str:
        return self.method


class AliasRegistry:
    """Load canonical entities and precomputed match strings from YAML."""

    TYPE_ALIASES = {
        "SPECIES": "ACTIVE_SPECIES",
        "ADDITIVE": "ACTIVE_SPECIES",
        "PERFORMANCE_METRIC": "METRIC",
        "OPERATING_CONDITION": "CONDITION",
        "MECHANISM": "DEGRADATION",
    }

    def __init__(self, entities: Iterable[CanonicalEntity] = ()):
        self.entities: dict[str, CanonicalEntity] = {}
        self.exact_index: dict[tuple[str, str], str] = {}
        for entity in entities:
            self.add(entity)

    @classmethod
    def from_yaml_files(cls, paths: Iterable[str | Path]) -> "AliasRegistry":
        entities: list[CanonicalEntity] = []
        for path in paths:
            path = Path(path)
            if not path.exists():
                continue
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            for raw in data.get("entities", data.get("canonical_entities", [])):
                entity_type = str(raw.get("entity_type") or raw.get("type") or "UNKNOWN")
                aliases = tuple(str(item) for item in raw.get("aliases", []))
                terms = [str(raw["canonical_name"]), *aliases]
                match_strings = tuple(dict.fromkeys(normalize_text_for_match(term) for term in terms if term))
                entities.append(
                    CanonicalEntity(
                        canonical_id=str(raw["canonical_id"]),
                        canonical_name=str(raw["canonical_name"]),
                        entity_type=entity_type,
                        aliases=aliases,
                        parent_id=raw.get("parent_id"),
                        notes=raw.get("notes"),
                        semantic_group=raw.get("semantic_group"),
                        properties=raw.get("properties") or {},
                        compatible_types=tuple(str(item) for item in raw.get("compatible_types", [])),
                        match_strings=match_strings,
                    )
                )
        return cls(entities)

    def add(self, entity: CanonicalEntity) -> None:
        self.entities[entity.canonical_id] = entity
        for match_string in entity.match_strings:
            for entity_type in self._index_types(entity):
                key = (entity_type, match_string)
                # Keep the first mapping to avoid unstable alias collisions.
                self.exact_index.setdefault(key, entity.canonical_id)

    def exact_match(self, mention: str, entity_type: str | None = None) -> CanonicalEntity | None:
        mention_norm = normalize_text_for_match(mention)
        for candidate_type in self._candidate_types(entity_type):
            canonical_id = self.exact_index.get((candidate_type, mention_norm))
            if canonical_id:
                return self.entities[canonical_id]
        return None

    def match_exact(self, mention: str, entity_type: str | None = None) -> AliasMatch | None:
        entity = self.exact_match(mention, entity_type)
        if not entity:
            return None
        return AliasMatch(
            canonical_id=entity.canonical_id,
            canonical_name=entity.canonical_name,
            entity_type=entity.entity_type,
            confidence=1.0,
            method="exact_alias_match",
            parent_id=entity.parent_id,
            semantic_group=entity.semantic_group,
            properties=entity.properties,
        )

    def match_formula(self, mention: str, entity_type: str | None = None) -> AliasMatch | None:
        return self.match_exact(mention, entity_type)

    def get_candidates_by_type(self, entity_type: str | None) -> list[CanonicalEntity]:
        if not entity_type:
            return list(self.entities.values())
        entity_type = self.TYPE_ALIASES.get(str(entity_type).upper(), entity_type)
        return [
            entity
            for entity in self.entities.values()
            if entity.entity_type == entity_type or entity_type in entity.compatible_types
        ]

    def by_type(self, entity_type: str) -> list[CanonicalEntity]:
        return self.get_candidates_by_type(entity_type)

    def _candidate_types(self, entity_type: str | None) -> list[str]:
        if not entity_type:
            return sorted({entity.entity_type for entity in self.entities.values()})
        entity_type = str(entity_type).upper()
        return [entity_type, self.TYPE_ALIASES.get(entity_type, entity_type)]

    @staticmethod
    def _index_types(entity: CanonicalEntity) -> tuple[str, ...]:
        return (entity.entity_type, *entity.compatible_types)
