"""Top-k fuzzy candidate retrieval for canonical chemical entities."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from difflib import SequenceMatcher

from .alias_registry import AliasRegistry, CanonicalEntity
from .text_normalizer import normalize_text_for_match

try:
    from rapidfuzz import fuzz
except Exception:  # pragma: no cover - exercised only when rapidfuzz is absent.
    fuzz = None


@dataclass(frozen=True)
class Candidate:
    canonical_id: str
    canonical_name: str
    entity_type: str
    best_alias: str
    score: float
    score_method: str
    ratio_score: float
    partial_ratio_score: float
    token_set_ratio_score: float
    length_ratio: float
    semantic_group: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _ratio(a: str, b: str) -> float:
    if fuzz:
        return float(fuzz.ratio(a, b))
    return SequenceMatcher(None, a, b).ratio() * 100.0


def _partial_ratio(a: str, b: str) -> float:
    if fuzz:
        return float(fuzz.partial_ratio(a, b))
    if not a or not b:
        return 0.0
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    if shorter in longer:
        return 100.0
    return SequenceMatcher(None, shorter, longer).ratio() * 100.0


def _token_set_ratio(a: str, b: str) -> float:
    if fuzz:
        return float(fuzz.token_set_ratio(a, b))
    return _ratio(a, b)


def _length_ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return min(len(a), len(b)) / max(len(a), len(b))


def _best_score(mention_norm: str, entity: CanonicalEntity) -> tuple[float, str, str, float, float, float, float]:
    best_score = 0.0
    best_alias = ""
    best_method = "ratio"
    best_ratio = 0.0
    best_partial = 0.0
    best_token = 0.0
    best_length_ratio = 0.0
    for alias in entity.match_strings:
        scores = {
            "ratio": _ratio(mention_norm, alias),
            "partial_ratio": _partial_ratio(mention_norm, alias),
            "token_set_ratio": _token_set_ratio(mention_norm, alias),
        }
        method, score = max(scores.items(), key=lambda item: item[1])
        if score > best_score:
            best_score = score
            best_alias = alias
            best_method = method
            best_ratio = scores["ratio"]
            best_partial = scores["partial_ratio"]
            best_token = scores["token_set_ratio"]
            best_length_ratio = _length_ratio(mention_norm, alias)
    return (
        round(best_score, 4),
        best_alias,
        best_method,
        round(best_ratio, 4),
        round(best_partial, 4),
        round(best_token, 4),
        round(best_length_ratio, 4),
    )


def get_top_k_candidates(
    mention: str,
    entity_type: str | None,
    registry: AliasRegistry,
    k: int = 5,
) -> list[Candidate]:
    mention_norm = normalize_text_for_match(mention)
    candidates: list[Candidate] = []
    for entity in registry.get_candidates_by_type(entity_type):
        score, best_alias, method, ratio_score, partial_score, token_score, length_ratio = _best_score(mention_norm, entity)
        candidates.append(
            Candidate(
                canonical_id=entity.canonical_id,
                canonical_name=entity.canonical_name,
                entity_type=entity.entity_type,
                best_alias=best_alias,
                score=score,
                score_method=method,
                ratio_score=ratio_score,
                partial_ratio_score=partial_score,
                token_set_ratio_score=token_score,
                length_ratio=length_ratio,
                semantic_group=entity.semantic_group,
            )
        )
    candidates.sort(key=lambda item: item.score, reverse=True)
    return candidates[:k]
