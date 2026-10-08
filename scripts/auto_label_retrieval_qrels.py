"""Auto-label retrieval qrels for a pilot annotation pack.

This is a conservative machine pre-labeler. It is useful for running a first
retrieval benchmark pass, but the output should be audited before being treated
as final human qrels.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
import re
from pathlib import Path
from typing import Any


LABELS = {
    0: "IRRELEVANT",
    1: "BACKGROUND",
    2: "STRONG_SUPPORT",
    3: "DIRECT",
}


STOPWORDS = {
    "the", "and", "or", "of", "to", "in", "at", "for", "with", "which",
    "what", "was", "were", "is", "are", "that", "this", "evidence",
    "supports", "relation", "involving", "between", "under", "using",
    "best", "retrieved", "a", "an", "as", "by", "from", "into",
}


def normalize(text: Any) -> str:
    value = str(text or "").lower()
    value = value.replace("cm−2", "cm2").replace("cm-2", "cm2").replace("cm^2", "cm2").replace("cm²", "cm2")
    value = value.replace("ω", "ohm").replace("·", " ").replace("–", "-").replace("—", "-")
    value = re.sub(r"m\s*a\s*(?:/|\s+)\s*cm\s*-?\s*2", "ma/cm2", value)
    value = re.sub(r"ohm\s*cm\s*2", "ohm cm2", value)
    value = re.sub(r"mol\s*(?:/|\s+)\s*l(?:-1)?", "mol/l", value)
    value = re.sub(r"[^a-z0-9.%/+:-]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def compact(text: Any) -> str:
    return re.sub(r"[^a-z0-9.%/+:-]+", "", normalize(text))


def tokens(text: Any) -> set[str]:
    return {tok for tok in normalize(text).split() if tok and tok not in STOPWORDS and len(tok) > 1}


def numbers(text: Any) -> set[str]:
    out = set()
    for match in re.findall(r"\d+(?:\.\d+)?", str(text or "")):
        try:
            value = float(match)
            out.add(f"{value:g}")
        except ValueError:
            out.add(match)
    return out


def candidate_text(item: dict[str, Any]) -> str:
    spans = []
    for inst in item.get("evidence_instances") or []:
        if isinstance(inst, dict):
            for key in ("source_span", "evidence_span", "sentence", "description", "keywords"):
                if inst.get(key):
                    spans.append(str(inst[key]))
    fields = [
        item.get("relation_type"),
        " ".join(map(str, item.get("canonical_vertices") or [])),
        " ".join(map(str, item.get("readable_labels") or [])),
        item.get("readable_evidence"),
        item.get("source_span"),
        " ".join(spans),
    ]
    return "\n".join(str(field) for field in fields if field)


def entity_coverage(query: dict[str, Any], text_norm: str, text_compact: str) -> tuple[int, int, list[str], list[str]]:
    required = [str(x) for x in query.get("required_entities") or [] if str(x).strip()]
    matched = []
    missing = []
    for ent in required:
        ent_norm = normalize(ent.replace("_", " ").replace(":", " "))
        ent_tail = normalize(ent.split(":", 1)[-1].replace("_", " "))
        ent_compact = compact(ent)
        if (
            ent_norm and ent_norm in text_norm
            or ent_tail and ent_tail in text_norm
            or ent_compact and ent_compact in text_compact
        ):
            matched.append(ent)
        else:
            missing.append(ent)
    return len(matched), len(required), matched, missing


def relation_match(query: dict[str, Any], candidate: dict[str, Any]) -> bool:
    fact_type = normalize(query.get("fact_type"))
    rel = normalize(candidate.get("relation_type"))
    if not fact_type or not rel:
        return False
    if fact_type == rel:
        return True
    synonyms = {
        "operation": ["operation", "performance", "operation performance", "operates"],
        "composition": ["composition", "material design", "uses", "contains"],
        "comparison": ["comparison", "compares", "compares with", "compare"],
        "degradation": ["degradation", "degradation chain", "mechanism"],
        "mechanism": ["mechanism", "mechanism evidence", "degradation"],
    }
    return any(key in fact_type and any(value in rel for value in values) for key, values in synonyms.items())


def same_doc(query: dict[str, Any], candidate: dict[str, Any]) -> bool:
    doc = str(query.get("source_doc_id") or "")
    if not doc:
        return True
    docs = set(map(str, candidate.get("source_doc_ids") or []))
    chunks = " ".join(map(str, candidate.get("source_chunk_ids") or []))
    return doc in docs or doc in chunks or doc in str(candidate.get("candidate_source_id") or "")


def label_one(query: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    text = candidate_text(candidate)
    text_norm = normalize(text)
    text_compact = compact(text)
    claim = query.get("gold_claim") or query.get("question") or ""
    claim_tokens = tokens(claim)
    text_tokens = tokens(text)
    claim_overlap = len(claim_tokens & text_tokens) / max(1, len(claim_tokens))
    claim_numbers = numbers(claim)
    text_numbers = numbers(text)
    number_hits = sorted(claim_numbers & text_numbers)
    number_cov = len(number_hits) / max(1, len(claim_numbers)) if claim_numbers else 1.0
    ent_hits, ent_total, matched_entities, missing_entities = entity_coverage(query, text_norm, text_compact)
    ent_cov = ent_hits / max(1, ent_total)
    rel_ok = relation_match(query, candidate)
    doc_ok = same_doc(query, candidate)
    seed_ok = candidate.get("candidate_id") == query.get("seed_candidate_id")

    score = 0.0
    score += 0.34 * ent_cov
    score += 0.28 * claim_overlap
    score += 0.18 * number_cov
    score += 0.10 * (1.0 if rel_ok else 0.0)
    score += 0.10 * (1.0 if doc_ok else 0.0)

    wrong = []
    if not doc_ok:
        wrong.append(f"source_doc_mismatch: expected {query.get('source_doc_id')}, got {candidate.get('source_doc_ids')}")
    if claim_numbers and not number_hits:
        wrong.append("no_required_numeric_value_matched")

    if seed_ok:
        grade = 3
    elif not doc_ok and ent_cov < 0.75:
        grade = 0
    elif score >= 0.78 and ent_cov >= 0.70 and number_cov >= 0.75:
        grade = 3
    elif score >= 0.55 and ent_cov >= 0.45 and (number_cov >= 0.40 or not claim_numbers):
        grade = 2
    elif score >= 0.25 or ent_cov > 0 or claim_overlap >= 0.18:
        grade = 1
    else:
        grade = 0

    rationale = (
        f"auto_label score={score:.3f}; same_doc={doc_ok}; relation_match={rel_ok}; "
        f"entity_coverage={ent_hits}/{ent_total}; claim_overlap={claim_overlap:.2f}; "
        f"numeric_coverage={len(number_hits)}/{len(claim_numbers)}"
    )
    return {
        "relevance_grade": grade,
        "relevance_label": LABELS[grade],
        "matched_elements": {
            "entities": matched_entities,
            "conditions": [],
            "measurements": number_hits,
            "mechanisms": [],
        },
        "missing_elements": {
            "entities": missing_entities,
            "conditions": [],
            "measurements": sorted(claim_numbers - text_numbers),
            "mechanisms": [],
        },
        "wrong_or_conflicting_elements": wrong,
        "rationale": rationale,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Auto-label retrieval qrels template.")
    parser.add_argument("--queries", required=True, type=Path)
    parser.add_argument("--candidates", required=True, type=Path)
    parser.add_argument("--qrels-template", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--jsonl-output", type=Path)
    parser.add_argument("--summary-output", type=Path)
    args = parser.parse_args()

    queries_obj = json.loads(args.queries.read_text(encoding="utf-8-sig"))
    candidates_obj = json.loads(args.candidates.read_text(encoding="utf-8-sig"))
    qrels_obj = json.loads(args.qrels_template.read_text(encoding="utf-8-sig"))
    queries = {str(item["query_id"]): item for item in queries_obj.get("queries", [])}
    candidates = {str(item["candidate_id"]): item for item in candidates_obj.get("candidate_evidence", [])}

    labeled = []
    missing = 0
    for row in qrels_obj.get("qrels", []):
        query = queries.get(str(row.get("query_id")))
        candidate = candidates.get(str(row.get("candidate_id")))
        out = dict(row)
        if not query or not candidate:
            missing += 1
            out.update(
                {
                    "relevance_grade": 0,
                    "relevance_label": "IRRELEVANT",
                    "rationale": "auto_label missing query or candidate record",
                }
            )
        else:
            out.update(label_one(query, candidate))
        labeled.append(out)

    counts = Counter(int(row.get("relevance_grade", 0) or 0) for row in labeled)
    by_group: dict[str, Counter] = {}
    for row in labeled:
        group = str(row.get("candidate_group") or "UNKNOWN")
        by_group.setdefault(group, Counter())[int(row.get("relevance_grade", 0) or 0)] += 1

    output_obj = {
        "metadata": {
            **qrels_obj.get("metadata", {}),
            "annotation_status": "auto_labeled_needs_audit",
            "annotation_method": "heuristic_auto_label_v1",
            "warning": "Machine pre-labels are for pilot evaluation only. Audit before using as final qrels.",
            "grade_schema": {str(k): v for k, v in LABELS.items()},
        },
        "qrels": labeled,
    }
    args.output.write_text(json.dumps(output_obj, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.jsonl_output:
        with args.jsonl_output.open("w", encoding="utf-8") as f:
            for row in labeled:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
    summary = {
        "annotation_method": "heuristic_auto_label_v1",
        "warning": "Machine pre-labels are for pilot evaluation only.",
        "num_qrels": len(labeled),
        "missing_records": missing,
        "grade_distribution": {str(k): counts.get(k, 0) for k in range(4)},
        "group_grade_distribution": {
            group: {str(k): counter.get(k, 0) for k in range(4)}
            for group, counter in sorted(by_group.items())
        },
        "outputs": {
            "json": str(args.output),
            "jsonl": str(args.jsonl_output) if args.jsonl_output else None,
        },
    }
    if args.summary_output:
        args.summary_output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
