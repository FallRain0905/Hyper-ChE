"""Rewrite raw sentence retrieval queries into researcher-style questions.

The rewritten question avoids copying the gold sentence. The gold_claim remains
in the file for qrels annotation only, not for retrieval ranking.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
import re
from pathlib import Path
from typing import Any


def normalize(text: Any) -> str:
    value = str(text or "")
    value = value.replace("$", " ").replace("\\mathrm", " ").replace("\\mathbf", " ")
    value = re.sub(r"[{}_^~]", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def unique(items: list[str]) -> list[str]:
    out = []
    seen = set()
    for item in items:
        value = str(item).strip()
        key = value.lower()
        if value and key not in seen:
            seen.add(key)
            out.append(value)
    return out


def claim_terms(claim: str) -> list[str]:
    text = normalize(claim)
    patterns = [
        r"\b\d+(?:\.\d+)?\s*%",
        r"\b\d+(?:\.\d+)?\s*mA\s*(?:/|\s*)cm\s*-?2",
        r"\b\d+(?:\.\d+)?\s*mol\s*(?:/|\s*)L",
        r"\b\d+(?:\.\d+)?\s*cycles?\b",
        r"\b\d+(?:\.\d+)?\s*mAh\b",
        r"\b\d+(?:\.\d+)?\s*Wh\s*L",
        r"\b\d+(?:\.\d+)?\s*V\b",
        r"\b\d+(?:\.\d+)?\s*wt\s*%",
        r"\b4-TMA\s*TEMPO\b",
        r"\b3-TMA\s*PROXYL\b",
        r"\bT-\d+\s*V-\d+\b",
        r"\bT-\d+\s*Q-\d+\b",
        r"\bB-CF\b",
        r"\bCF\b",
        r"\bNafion\s*\d+\b",
        r"\bSPEEK/[A-Z]+\b",
        r"\bSPTPC[-\w.]*\b",
        r"\bSNPBI[-\w.]*\b",
    ]
    found: list[str] = []
    for pattern in patterns:
        found.extend(re.findall(pattern, text, flags=re.IGNORECASE))
    keywords = [
        "crossover",
        "chemical degradation",
        "capacity fade",
        "self-discharge",
        "coulombic efficiency",
        "voltage efficiency",
        "energy efficiency",
        "capacity retention",
        "open-circuit voltage",
        "power density",
        "limiting current density",
        "charge transfer impedance",
        "polarization losses",
        "water content",
        "posolyte",
        "negolyte",
        "membrane",
        "redox flow battery",
        "DES-based RFB",
        "vanadium",
        "TEMPO",
        "PROXYL",
    ]
    lower = text.lower()
    found.extend(term for term in keywords if term.lower() in lower)
    return unique(found)[:12]


def metric_phrase(metrics: list[dict[str, Any]], terms: list[str]) -> str:
    if metrics:
        pieces = []
        for metric in metrics[:4]:
            mtype = str(metric.get("metric_type") or "metric")
            value = metric.get("value")
            unit = metric.get("unit")
            if value is not None and unit:
                pieces.append(f"{mtype} {value} {unit}")
            else:
                pieces.append(mtype)
        return ", ".join(pieces)
    metric_terms = [
        term
        for term in terms
        if any(k in term.lower() for k in ["efficiency", "retention", "density", "capacity", "resistance", "impedance", "voltage"])
    ]
    return ", ".join(metric_terms[:4])


def condition_phrase(conditions: list[dict[str, Any]], terms: list[str]) -> str:
    pieces = []
    for condition in conditions[:4]:
        qtype = str(condition.get("quantity_type") or "condition")
        value = condition.get("value")
        unit = condition.get("unit")
        if value is not None and unit:
            pieces.append(f"{qtype} {value} {unit}")
    for term in terms:
        if any(k in term.lower() for k in ["ma", "mol", "cycles", "wt"]):
            pieces.append(term)
    return ", ".join(unique(pieces)[:5])


def entity_phrase(query: dict[str, Any], terms: list[str]) -> str:
    entities = unique([str(x) for x in query.get("required_entities") or []])
    extra = [
        term
        for term in terms
        if any(k in term.lower() for k in ["tempo", "proxyl", "nafion", "cf", "snpbi", "speek", "sptpc", "vanadium", "membrane", "rfb"])
    ]
    values = unique(entities + extra)
    return ", ".join(values[:6]) or "the reported flow-battery system"


def rewrite_question(query: dict[str, Any]) -> str:
    claim = str(query.get("gold_claim") or "")
    terms = claim_terms(claim)
    ftype = str(query.get("fact_type") or "").upper()
    entities = entity_phrase(query, terms)
    metrics = metric_phrase(query.get("required_metrics") or [], terms)
    conditions = condition_phrase(query.get("required_conditions") or [], terms)
    mechanisms = unique([str(x) for x in query.get("required_mechanisms") or []] + [t for t in terms if any(k in t.lower() for k in ["crossover", "degradation", "fade", "self-discharge", "polarization"])])

    if ftype == "COMPARISON":
        focus = metrics or "performance or stability"
        return f"Which evidence compares {entities} in terms of {focus}" + (f" under {conditions}?" if conditions else "?")
    if ftype == "DEGRADATION_OR_MECHANISM":
        mech = ", ".join(mechanisms[:4]) or "the reported degradation mechanism"
        return f"Which evidence links {entities} to {mech}" + (f" under {conditions}?" if conditions else "?")
    if ftype == "OPERATION_PERFORMANCE":
        focus = metrics or "electrochemical performance"
        return f"Which evidence reports {focus} for {entities}" + (f" under {conditions}?" if conditions else "?")
    if ftype == "COMPOSITION":
        return f"Which evidence describes the material design or composition involving {entities}?"
    if ftype == "MEASUREMENT":
        focus = metrics or "the measured property"
        return f"Which evidence reports {focus} for {entities}" + (f" under {conditions}?" if conditions else "?")
    return f"Which evidence supports the flow-battery fact involving {entities}?"


def max_shared_ngrams(a: str, b: str, n: int = 6) -> int:
    def ngrams(text: str) -> set[tuple[str, ...]]:
        words = re.findall(r"[a-zA-Z0-9.%/+:-]+", text.lower())
        return {tuple(words[i : i + n]) for i in range(max(0, len(words) - n + 1))}
    return len(ngrams(a) & ngrams(b))


def main() -> None:
    parser = argparse.ArgumentParser(description="Rewrite retrieval queries to reduce source-sentence leakage.")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    data = json.loads(args.input.read_text(encoding="utf-8-sig"))
    queries = []
    overlap_counts = Counter()
    for item in data.get("queries", []):
        out = dict(item)
        old_question = str(out.get("question") or "")
        new_question = rewrite_question(out)
        out["original_question"] = old_question
        out["question"] = new_question
        out["query_rewrite_method"] = "deterministic_research_question_v1"
        shared = max_shared_ngrams(new_question, out.get("gold_claim") or "", n=6)
        out["max_shared_6gram_with_gold_claim"] = shared
        overlap_counts[str(shared)] += 1
        queries.append(out)

    result = {
        "metadata": {
            **data.get("metadata", {}),
            "query_rewrite_method": "deterministic_research_question_v1",
            "note": "question fields were rewritten to avoid copying raw source sentences; gold_claim is retained only for qrels annotation.",
            "num_queries": len(queries),
        },
        "queries": queries,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    report = {
        "input": str(args.input),
        "output": str(args.output),
        "num_queries": len(queries),
        "shared_6gram_distribution": dict(sorted(overlap_counts.items(), key=lambda x: int(x[0]))),
    }
    if args.report:
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
