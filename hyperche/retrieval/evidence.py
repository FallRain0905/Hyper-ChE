"""Thread-safe copy of the frozen legacy QA evidence formatting.

The historical argument says chars, but its implementation counts whitespace
units over the entire context. Preserve that behavior explicitly for Web QA.
"""
from __future__ import annotations
import json
import re
from typing import Any

def evidence_text(item: dict[str, Any]) -> str:
    labels = "; ".join(item.get("readable_labels") or [])
    readable = item.get("readable_evidence") or item.get("text") or ""
    return "\n".join(part for part in [labels, readable] if part)

def sentence_split(text: str) -> list[str]:
    clean = re.sub(r"\s+", " ", str(text or "")).strip()
    if not clean:
        return []
    return [sentence.strip() for sentence in re.split(r"(?<=[.!?])\s+", clean) if sentence.strip()]

def token_count(text: str) -> int:
    return len(re.findall(r"\S+", str(text or "")))

def query_terms(text: str) -> list[str]:
    stop = {
        "what",
        "which",
        "how",
        "why",
        "does",
        "the",
        "and",
        "with",
        "from",
        "into",
        "than",
        "that",
        "this",
        "under",
        "using",
        "between",
        "compare",
        "compared",
        "explain",
        "is",
        "are",
        "was",
        "were",
        "at",
        "in",
        "of",
        "to",
        "a",
        "an",
        "for",
    }
    tokens = re.findall(r"[A-Za-z0-9.+/%^-]+", str(text).lower())
    return [token for token in tokens if len(token) > 1 and token not in stop]

def query_focused_excerpt(query: str, text: str, max_tokens: int = 300) -> str:
    sentences = sentence_split(text)
    if not sentences:
        return ""
    terms = query_terms(query)
    numbers = re.findall(r"\d+(?:\.\d+)?", query)
    metric_terms = {
        "ce",
        "ve",
        "ee",
        "efficiency",
        "resistance",
        "permeability",
        "capacity",
        "fade",
        "current",
        "density",
        "temperature",
        "crossover",
    }
    scored = []
    for idx, sentence in enumerate(sentences):
        lowered = sentence.lower()
        score = sum(2 for term in terms if term in lowered)
        score += sum(3 for num in numbers if num in lowered)
        score += sum(3 for term in metric_terms if term in lowered)
        if any(entity in lowered for entity in ["nafion", "pbi", "speek", "sptpc", "snpbi", "vrfb", "icrfb"]):
            score += 2
        scored.append((score, idx, sentence))
    chosen = [sentence for score, _idx, sentence in sorted(scored, key=lambda item: (-item[0], item[1])) if score > 0][:4]
    if not chosen:
        chosen = [sentence for _score, _idx, sentence in sorted(scored, key=lambda item: (-item[0], item[1]))[:3]]
    chosen_set = set(chosen)
    ordered = [sentence for _score, _idx, sentence in scored if sentence in chosen_set]
    words: list[str] = []
    for sentence in ordered:
        for word in sentence.split():
            if len(words) >= max_tokens:
                break
            words.append(word)
        if len(words) >= max_tokens:
            break
    return " ".join(words)

def parse_evidence_fields(item: dict[str, Any]) -> dict[str, list[str]]:
    labels = item.get("readable_labels") or []
    vertices = item.get("canonical_vertices") or item.get("vertices") or []
    values = [str(value) for value in labels + vertices if value]
    entities: list[str] = []
    metrics: list[str] = []
    conditions: list[str] = []
    explicit_values: list[str] = []
    for value in values:
        lowered = value.lower()
        if re.search(r"=\s*[-+]?\d", value):
            explicit_values.append(value)
        if any(key in lowered for key in ["efficiency", "resistance", "permeability", "capacity", "fade", "voltage", "current", "retention", "crossover"]):
            metrics.append(value)
        elif any(key in lowered for key in ["temperature", "current density", "m/cm", "mol", "ph", "cycle", " c"]):
            conditions.append(value)
        else:
            entities.append(value)
    return {
        "entities": list(dict.fromkeys(entities))[:12],
        "metrics": list(dict.fromkeys(metrics))[:12],
        "conditions": list(dict.fromkeys(conditions))[:12],
        "values": list(dict.fromkeys(explicit_values))[:12],
    }

def short_claim(item: dict[str, Any]) -> str:
    fields = parse_evidence_fields(item)
    relation = str(item.get("relation_type") or item.get("kind") or "evidence")
    entities = fields["entities"]
    metrics = fields["metrics"]
    conditions = fields["conditions"]
    if "COMPAR" in relation.upper() and len(metrics) >= 2:
        return f"Under {', '.join(conditions) if conditions else 'the reported conditions'}, {metrics[0]}, while {metrics[1]}. Relation: {relation}."
    if any(key in relation.upper() for key in ["MECHANISM", "CAUSE", "DEGRAD"]):
        return f"{', '.join(entities[:3]) or 'The reported factor'} is linked to {', '.join(metrics[:3]) or relation}. Conditions: {', '.join(conditions) if conditions else 'not explicitly stated'}."
    if metrics:
        return f"In the reported system, under {', '.join(conditions) if conditions else 'the stated conditions'}, {', '.join(entities[:4]) or 'the entity'} achieved/reported {', '.join(metrics[:4])}."
    return f"Evidence reports {', '.join(entities[:6]) or relation}. Conditions: {', '.join(conditions) if conditions else 'not explicitly stated'}."

def format_evidence_block(index: int, item: dict[str, Any], query: str) -> str:
    fields = parse_evidence_fields(item)
    raw = evidence_text(item)
    source_id = item.get("source_id") or item.get("source_chunk_id") or item.get("id")
    return f"""Evidence {index}
Source: {source_id}
Relation/Type: {item.get('relation_type') or item.get('kind') or 'TEXT'}
Short claim: {short_claim(item)}
Entities: {json.dumps(fields['entities'], ensure_ascii=False)}
Metrics: {json.dumps(fields['metrics'], ensure_ascii=False)}
Values: {json.dumps(fields['values'], ensure_ascii=False)}
Conditions: {json.dumps(fields['conditions'], ensure_ascii=False)}
Raw support excerpt: {query_focused_excerpt(query, raw, max_tokens=300)}
"""

def format_context(query: str, items: list[dict[str, Any]], *, budget: int = 1500) -> tuple[str, list[str]]:
    parts, selected, used = [], [], 0
    for rank, item in enumerate(items, 1):
        block = format_evidence_block(rank, item, query)
        count = token_count(block)
        if used + count > budget:
            break
        parts.append(block)
        selected.append(str(item['id']))
        used += count
    return '\n\n'.join(parts), selected


def answer_system_prompt(context: str) -> str:
    return ('You answer chemical literature questions using ONLY the retrieved evidence. '
            'Answer in the language of the question. Every key claim must cite its supporting '
            'block using [Evidence N]. Do not invent or mix entities, numeric values, units, '
            'conditions or sources from different studies. If no supplied block supports '
            'the requested relation, say that the retrieved evidence is insufficient. '
            'Use concise Markdown, not a JSON object.\n\nRetrieved evidence:\n' + context)
