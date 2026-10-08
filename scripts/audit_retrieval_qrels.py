"""Audit auto-labeled retrieval qrels with stricter, seed-independent rules.

The previous auto labeler is deliberately permissive for pilot use. This audit
pass removes the seed-candidate shortcut and applies conservative checks for
same-document evidence, entity coverage, numeric coverage, and claim overlap.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
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
    "best", "retrieved", "a", "an", "as", "by", "from", "into", "study",
    "shows", "show", "describes", "reports",
}


def normalize(text: Any) -> str:
    value = str(text or "").lower()
    replacements = {
        "cm−2": "cm2",
        "cm-2": "cm2",
        "cm^2": "cm2",
        "cm²": "cm2",
        "ω": "ohm",
        "·": " ",
        "–": "-",
        "—": "-",
        "（": "(",
        "）": ")",
    }
    for old, new in replacements.items():
        value = value.replace(old, new)
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
            out.add(f"{float(match):g}")
        except ValueError:
            out.add(match)
    return out


def candidate_text(item: dict[str, Any]) -> str:
    spans: list[str] = []
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


def same_doc(query: dict[str, Any], candidate: dict[str, Any]) -> bool:
    doc = str(query.get("source_doc_id") or "")
    if not doc:
        return True
    doc_ids = set(map(str, candidate.get("source_doc_ids") or []))
    chunk_ids = " ".join(map(str, candidate.get("source_chunk_ids") or []))
    return doc in doc_ids or doc in chunk_ids or doc in str(candidate.get("candidate_source_id") or "")


def relation_match(query: dict[str, Any], candidate: dict[str, Any]) -> bool:
    fact = normalize(query.get("fact_type"))
    relation = normalize(candidate.get("relation_type"))
    if not fact or not relation:
        return candidate.get("candidate_type") == "text"
    if fact == relation or fact in relation or relation in fact:
        return True
    if "operation" in fact and any(x in relation for x in ["operation", "performance"]):
        return True
    if "composition" in fact and any(x in relation for x in ["composition", "material", "design", "uses"]):
        return True
    if "comparison" in fact and "compar" in relation:
        return True
    if "degradation" in fact and any(x in relation for x in ["degradation", "mechanism"]):
        return True
    return False


def entity_coverage(query: dict[str, Any], text_norm: str, text_compact: str) -> tuple[float, list[str], list[str]]:
    required = [str(item) for item in query.get("required_entities") or [] if str(item).strip()]
    if not required:
        return 1.0, [], []
    matched: list[str] = []
    missing: list[str] = []
    for entity in required:
        norm_entity = normalize(entity.replace("_", " ").replace(":", " "))
        tail = normalize(entity.split(":", 1)[-1].replace("_", " "))
        compact_entity = compact(entity)
        if (
            (norm_entity and norm_entity in text_norm)
            or (tail and tail in text_norm)
            or (compact_entity and compact_entity in text_compact)
        ):
            matched.append(entity)
        else:
            missing.append(entity)
    return len(matched) / len(required), matched, missing


def claim_overlap(query: dict[str, Any], text: str) -> float:
    claim = query.get("gold_claim") or query.get("question") or ""
    claim_terms = tokens(claim)
    if not claim_terms:
        return 0.0
    text_terms = tokens(text)
    return len(claim_terms & text_terms) / len(claim_terms)


def audit_one(query: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    text = candidate_text(candidate)
    text_norm = normalize(text)
    text_compact = compact(text)
    doc_ok = same_doc(query, candidate)
    rel_ok = relation_match(query, candidate)
    ent_cov, matched_entities, missing_entities = entity_coverage(query, text_norm, text_compact)
    overlap = claim_overlap(query, text)
    claim_nums = numbers(query.get("gold_claim") or query.get("question"))
    text_nums = numbers(text)
    num_hits = sorted(claim_nums & text_nums)
    num_cov = len(num_hits) / max(1, len(claim_nums)) if claim_nums else 1.0

    # Conservative evidence categories.
    if not doc_ok and ent_cov < 0.9:
        grade = 0
    elif ent_cov >= 0.85 and overlap >= 0.62 and num_cov >= 0.85 and (rel_ok or candidate.get("candidate_type") == "text"):
        grade = 3
    elif ent_cov >= 0.55 and overlap >= 0.35 and num_cov >= 0.50 and doc_ok:
        grade = 2
    elif doc_ok and (ent_cov >= 0.25 or overlap >= 0.18):
        grade = 1
    elif ent_cov >= 0.35 and overlap >= 0.20:
        grade = 1
    else:
        grade = 0

    wrong: list[str] = []
    if not doc_ok:
        wrong.append(f"source_doc_mismatch expected={query.get('source_doc_id')} got={candidate.get('source_doc_ids')}")
    if claim_nums and num_cov < 0.5:
        wrong.append(f"numeric_mismatch expected={sorted(claim_nums)} matched={num_hits}")
    if not rel_ok and candidate.get("candidate_type") != "text" and grade >= 2:
        wrong.append(f"relation_type_mismatch expected={query.get('fact_type')} got={candidate.get('relation_type')}")

    return {
        "relevance_grade": grade,
        "relevance_label": LABELS[grade],
        "matched_elements": {
            "entities": matched_entities,
            "conditions": [],
            "measurements": num_hits,
            "mechanisms": [],
        },
        "missing_elements": {
            "entities": missing_entities,
            "conditions": [],
            "measurements": sorted(claim_nums - text_nums),
            "mechanisms": [],
        },
        "wrong_or_conflicting_elements": wrong,
        "audit_rationale": (
            f"audit_v1 same_doc={doc_ok}; relation_match={rel_ok}; "
            f"entity_coverage={ent_cov:.2f}; claim_overlap={overlap:.2f}; "
            f"numeric_coverage={num_cov:.2f}"
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit auto-labeled qrels.")
    parser.add_argument("--queries", required=True, type=Path)
    parser.add_argument("--candidates", required=True, type=Path)
    parser.add_argument("--input-qrels", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--jsonl-output", type=Path)
    parser.add_argument("--summary-output", type=Path)
    args = parser.parse_args()

    queries_obj = json.loads(args.queries.read_text(encoding="utf-8-sig"))
    candidates_obj = json.loads(args.candidates.read_text(encoding="utf-8-sig"))
    qrels_obj = json.loads(args.input_qrels.read_text(encoding="utf-8-sig"))
    queries = {str(item["query_id"]): item for item in queries_obj.get("queries", [])}
    candidates = {str(item["candidate_id"]): item for item in candidates_obj.get("candidate_evidence", [])}

    audited: list[dict[str, Any]] = []
    changes: Counter[str] = Counter()
    grade_counts: Counter[int] = Counter()
    group_grade_counts: dict[str, Counter[int]] = defaultdict(Counter)
    missing_records = 0
    examples: list[dict[str, Any]] = []

    for row in qrels_obj.get("qrels", []):
        query = queries.get(str(row.get("query_id")))
        candidate = candidates.get(str(row.get("candidate_id")))
        old_grade = row.get("relevance_grade")
        out = dict(row)
        out["previous_relevance_grade"] = old_grade
        out["previous_relevance_label"] = row.get("relevance_label")
        if not query or not candidate:
            missing_records += 1
            audit = {
                "relevance_grade": 0,
                "relevance_label": "IRRELEVANT",
                "matched_elements": {"entities": [], "conditions": [], "measurements": [], "mechanisms": []},
                "missing_elements": {"entities": [], "conditions": [], "measurements": [], "mechanisms": []},
                "wrong_or_conflicting_elements": ["missing query or candidate record"],
                "audit_rationale": "audit_v1 missing query or candidate record",
            }
        else:
            audit = audit_one(query, candidate)
        out.update(audit)
        new_grade = out["relevance_grade"]
        try:
            old_int = int(old_grade)
        except Exception:
            old_int = -1
        changes[f"{old_int}->{new_grade}"] += 1
        grade_counts[int(new_grade)] += 1
        group_grade_counts[str(out.get("candidate_group") or "UNKNOWN")][int(new_grade)] += 1
        if old_int != new_grade and len(examples) < 80:
            examples.append(
                {
                    "query_id": out.get("query_id"),
                    "candidate_id": out.get("candidate_id"),
                    "candidate_group": out.get("candidate_group"),
                    "old_grade": old_int,
                    "new_grade": new_grade,
                    "audit_rationale": out.get("audit_rationale"),
                }
            )
        audited.append(out)

    result = {
        "metadata": {
            **qrels_obj.get("metadata", {}),
            "annotation_status": "audited_auto_labels_needs_human_spot_check",
            "annotation_method": "heuristic_audit_v1_seed_independent",
            "warning": "This is a stricter machine audit, not a substitute for final human qrels.",
            "grade_schema": {str(k): v for k, v in LABELS.items()},
        },
        "qrels": audited,
    }
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.jsonl_output:
        with args.jsonl_output.open("w", encoding="utf-8") as f:
            for row in audited:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

    summary = {
        "annotation_method": "heuristic_audit_v1_seed_independent",
        "warning": "Stricter machine audit; use for pilot only unless manually checked.",
        "num_qrels": len(audited),
        "missing_records": missing_records,
        "grade_distribution": {str(k): grade_counts.get(k, 0) for k in range(4)},
        "change_distribution": dict(sorted(changes.items())),
        "group_grade_distribution": {
            group: {str(k): counter.get(k, 0) for k in range(4)}
            for group, counter in sorted(group_grade_counts.items())
        },
        "changed_examples": examples,
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
