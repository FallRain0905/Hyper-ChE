"""Negative and high-risk merge rules for chemical normalization."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .alias_registry import AliasRegistry
from .fuzzy_matcher import Candidate
from .text_normalizer import normalize_text_for_match


class NegativeRules:
    def __init__(self, registry: AliasRegistry, paths: list[str | Path] | None = None):
        self.registry = registry
        self.negative_pairs: list[tuple[str, str, str]] = []
        self.high_risk_groups: list[set[str]] = []
        self.component_patterns: list[str] = []
        self.generic_terms: set[str] = set()
        for path in paths or []:
            self.load(path)

    def load(self, path: str | Path) -> None:
        path = Path(path)
        if not path.exists():
            return
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for item in data.get("negative_pairs", []):
            left = str(item.get("left"))
            right = str(item.get("right"))
            reason = str(item.get("reason") or "negative_pair")
            self.negative_pairs.append((left, right, reason))
        for group in data.get("high_risk_groups", []):
            ids = group.get("canonical_ids", group if isinstance(group, list) else [])
            self.high_risk_groups.append({str(item) for item in ids})
        self.component_patterns.extend(str(item) for item in data.get("component_patterns", []))
        self.generic_terms.update(normalize_text_for_match(item) for item in data.get("generic_terms", []))

    def violates_negative_rule(
        self,
        mention: str,
        candidate: Candidate | str,
        context: str | None = None,
    ) -> tuple[bool, str | None]:
        candidate_id = candidate.canonical_id if isinstance(candidate, Candidate) else str(candidate)
        mention_norm = normalize_text_for_match(mention)

        for left, right, reason in self.negative_pairs:
            if candidate_id == left and self._mention_matches_side(mention_norm, right):
                return True, reason
            if candidate_id == right and self._mention_matches_side(mention_norm, left):
                return True, reason

        for group in self.high_risk_groups:
            if candidate_id not in group:
                continue
            matched_id = self._canonical_id_for_exact_mention(mention_norm)
            if matched_id in group and matched_id != candidate_id:
                return True, "high_risk_group"

        candidate_entity = self.registry.entities.get(candidate_id)
        if candidate_entity and self.violates_generic_rule(mention, candidate_id):
            return True, "generic_term_not_same_as_specific_entity"

        if candidate_entity and self._looks_like_component_entity(mention_norm, candidate_entity.match_strings):
            return True, "component_or_variant_not_same_as_base"

        return False, None

    def violates_generic_rule(self, mention: str, candidate_id: str) -> bool:
        mention_norm = normalize_text_for_match(mention)
        if mention_norm not in self.generic_terms:
            return False
        candidate_entity = self.registry.entities.get(candidate_id)
        if not candidate_entity:
            return False
        return mention_norm not in candidate_entity.match_strings

    def is_generic_mention(self, mention: str) -> bool:
        return normalize_text_for_match(mention) in self.generic_terms

    def _mention_matches_side(self, mention_norm: str, side: str) -> bool:
        entity = self.registry.entities.get(side)
        if entity:
            return mention_norm in entity.match_strings
        return mention_norm == normalize_text_for_match(side)

    def _canonical_id_for_exact_mention(self, mention_norm: str) -> str | None:
        for entity in self.registry.entities.values():
            if mention_norm in entity.match_strings:
                return entity.canonical_id
        return None

    @staticmethod
    def _looks_like_component_entity(mention_norm: str, candidate_match_strings: tuple[str, ...]) -> bool:
        if "/" not in mention_norm and "@" not in mention_norm:
            return False
        if mention_norm in candidate_match_strings:
            return False
        return any(match and match in mention_norm for match in candidate_match_strings)


def violates_negative_rule(
    mention: str,
    candidate: Candidate | str,
    registry: AliasRegistry,
    paths: list[str | Path] | None = None,
    context: str | None = None,
) -> bool:
    blocked, _ = NegativeRules(registry, paths).violates_negative_rule(mention, candidate, context)
    return blocked
