"""LLM adjudication interface for medium-confidence normalization candidates."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import re
from typing import Any, Callable


@dataclass
class LLMNormalizationDecision:
    decision: str
    target_canonical_id: str | None = None
    relationship: str = "none"
    canonical_name: str | None = None
    confidence: float = 0.0
    reason: str = ""
    aliases_to_add: list[str] = field(default_factory=list)
    need_review: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


async def judge_with_llm(
    payload: dict[str, Any],
    llm_func: Callable[..., Any] | None = None,
) -> LLMNormalizationDecision:
    if llm_func is None:
        return LLMNormalizationDecision(
            decision="NEED_REVIEW",
            reason="LLM normalizer is disabled.",
            need_review=True,
        )
    prompt = _build_prompt(payload)
    raw = await llm_func(prompt)
    data = _parse_json_object(str(raw or ""))
    return LLMNormalizationDecision(
        decision=str(data.get("decision", "NEED_REVIEW")).upper(),
        target_canonical_id=data.get("target_canonical_id"),
        relationship=str(data.get("relationship", "none")),
        canonical_name=data.get("canonical_name"),
        confidence=float(data.get("confidence", 0.0) or 0.0),
        reason=str(data.get("reason", "")),
        aliases_to_add=[str(item) for item in data.get("aliases_to_add", []) if str(item).strip()],
        need_review=bool(data.get("need_review", True)),
    )


def _build_prompt(payload: dict[str, Any]) -> str:
    return (
        "You are a conservative chemical entity normalization judge.\n"
        "Decide whether the extracted mention should be merged into one of the provided top_candidates.\n"
        "Do not choose any canonical_id outside top_candidates.\n"
        "If the mention is a generic/category term and the candidate is a specific entity, return CREATE_PARENT_CHILD or NEED_REVIEW, not MERGE.\n"
        "If the mention is a specific model, modified material, composite, different PFAS target, different valence state, "
        "or a different metric, prefer CREATE_VARIANT, CREATE_COMPONENT_RELATION, NO_MERGE, or NEED_REVIEW instead of MERGE.\n"
        "Return ONLY one JSON object with fields:\n"
        "{\n"
        '  "decision": "MERGE | CREATE_NEW | CREATE_VARIANT | CREATE_COMPONENT_RELATION | CREATE_PARENT_CHILD | NO_MERGE | NEED_REVIEW",\n'
        '  "target_canonical_id": "canonical id from top_candidates or null",\n'
        '  "relationship": "same_as | variant_of | component_of | none",\n'
        '  "canonical_name": "chosen/new canonical name or null",\n'
        '  "confidence": 0.0,\n'
        '  "reason": "short reason",\n'
        '  "aliases_to_add": [],\n'
        '  "need_review": true\n'
        "}\n\n"
        f"Payload:\n{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


def _parse_json_object(text: str) -> dict[str, Any]:
    text = re.sub(r"```json\s*", "", text)
    text = re.sub(r"```\s*", "", text).strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"LLM normalizer returned no JSON object: {text[:300]}")
    return json.loads(match.group(0))
