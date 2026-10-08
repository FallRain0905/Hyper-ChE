
#!/usr/bin/env python3
"""Validate and optionally repair a Hyper-ChE benchmark directory.

This script is intentionally conservative. It fixes only deterministic benchmark
packaging issues that should not change the scientific meaning of the dataset:

- normalize known canonical ID typo(s), e.g. system:vrFB -> system:vrfb
- replace non-ASCII symbols in JSON text fields, e.g. 25 ?C -> 25 C and A ? B -> A -> B
- add DOCxx prefixes to corpus top-level document titles
- repair QA expected_facts when they reference missing fact IDs by using the facts
  that support the QA's expected_efus

It also validates the schema expected by scripts/evaluate_fact_coverage.py and
scripts/evaluate_qa_answers.py.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REQUIRED_FILES = [
    "corpus_documents.md",
    "gold_annotations.json",
    "qa_questions.json",
    "README_benchmark.md",
]

TOP_LEVEL_KEYS = [
    "metadata",
    "documents",
    "gold_efu",
    "gold_facts",
    "qa_questions",
    "evaluation_rubric",
]

EFU_REQUIRED = [
    "gold_id",
    "source_doc_id",
    "source_section",
    "relation_type",
    "claim",
    "entities",
    "conditions",
    "measurements",
    "mechanisms",
    "evidence_text",
]

FACT_REQUIRED = [
    "fact_id",
    "source_doc_id",
    "claim",
    "required_entities",
    "required_conditions",
    "required_metrics",
    "required_mechanisms",
    "supporting_efus",
    "difficulty",
    "fact_type",
]

QA_REQUIRED = [
    "question_id",
    "source_doc_id",
    "level",
    "question_type",
    "question",
    "reference_answer",
    "reference_answer_points",
    "expected_facts",
    "expected_efus",
]

ALLOWED_RELATION_TYPES = {
    "OPERATION_PERFORMANCE",
    "COMPARISON",
    "COMPOSITION",
    "DEGRADATION_CHAIN",
    "MECHANISM_EVIDENCE",
    "DESIGN_SUMMARY",
}

ID_RE = re.compile(r"^[a-z_]+:[a-z0-9_]+$")
DOC_TITLE_RE = re.compile(r"^# (?!Hyper-ChE)(?!DOC\d{2}:\s)(.+)$", re.MULTILINE)


@dataclass
class ValidationReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)
    fixes: list[str] = field(default_factory=list)

    def add_counter(self, key: str, counter: Counter[Any]) -> None:
        self.stats[key] = {str(k): v for k, v in counter.items()}

    @property
    def ok(self) -> bool:
        return not self.errors


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"), strict=False)


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def walk_strings(value: Any, transform) -> Any:
    if isinstance(value, str):
        return transform(value)
    if isinstance(value, list):
        return [walk_strings(item, transform) for item in value]
    if isinstance(value, dict):
        return {key: walk_strings(item, transform) for key, item in value.items()}
    return value


def normalize_text_symbols(text: str) -> str:
    degree = "\u00b0"
    arrow = "\u2192"
    text = text.replace(arrow, "->")
    text = re.sub(rf"(\d+(?:\.\d+)?)\s*{degree}\s*C\b", r"\1 C", text)
    text = re.sub(rf"(\d+(?:\.\d+)?)\s*{degree}", r"\1 degree", text)
    return text


def normalize_canonical_id(value: str) -> str:
    return value.replace("system:vrFB", "system:vrfb")


def normalize_string(value: str) -> str:
    return normalize_canonical_id(normalize_text_symbols(value))


def collect_ids_from_gold(gold: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for fact in gold.get("gold_facts", []):
        ids.extend(x for x in fact.get("required_entities", []) if isinstance(x, str))
        ids.extend(x.get("canonical_id", "") for x in fact.get("required_conditions", []) if isinstance(x, dict))
        ids.extend(x.get("canonical_id", "") for x in fact.get("required_metrics", []) if isinstance(x, dict))
        ids.extend(x for x in fact.get("required_mechanisms", []) if isinstance(x, str))
    for efu in gold.get("gold_efu", []):
        ids.extend(x.get("canonical_id", "") for x in efu.get("entities", []) if isinstance(x, dict))
        ids.extend(x.get("canonical_id", "") for x in efu.get("conditions", []) if isinstance(x, dict))
        ids.extend(x.get("canonical_id", "") for x in efu.get("measurements", []) if isinstance(x, dict))
        ids.extend(x for x in efu.get("mechanisms", []) if isinstance(x, str))
    return [item for item in ids if item]


def add_doc_prefixes(corpus: str) -> tuple[str, int]:
    lines = corpus.splitlines()
    changed = 0
    doc_index = 0
    output: list[str] = []
    for line in lines:
        if line.startswith("# ") and not line.startswith("# Hyper-ChE"):
            doc_index += 1
            title = re.sub(r"^#\s+(?:DOC\d{2}:\s*)?", "", line).strip()
            fixed = f"# DOC{doc_index:02d}: {title}"
            if fixed != line:
                changed += 1
            output.append(fixed)
        else:
            output.append(line)
    suffix = "\n" if corpus.endswith("\n") else ""
    return "\n".join(output) + suffix, changed


def count_corpus_doc_titles(corpus: str) -> int:
    return len(re.findall(r"^# DOC\d{2}: .+$", corpus, flags=re.MULTILINE))


def rebuild_corpus_from_doc_files(root: Path) -> tuple[str, int]:
    parts = [
        "# Hyper-ChE Flow Battery Benchmark Corpus",
        "",
        "**Dataset**: Hyper-ChE Flow Battery Benchmark v1.1",
        "**Domain**: Redox flow battery",
        "**Type**: Synthetic controlled corpus",
        "**Document Count**: 10",
    ]
    rebuilt = 0
    for index in range(1, 11):
        path = root / f"doc{index:02d}.md"
        if not path.exists():
            continue
        raw = normalize_text_symbols(path.read_text(encoding="utf-8-sig", errors="replace"))
        lines = raw.splitlines()
        first_idx = next((i for i, line in enumerate(lines) if line.strip()), None)
        if first_idx is None:
            continue
        title = re.sub(r"^#\s+", "", lines[first_idx].strip())
        title = re.sub(r"^DOC\d{2}:\s*", "", title).strip()
        body = "\n".join(lines[first_idx + 1 :]).strip()
        parts.append("---")
        parts.append("")
        parts.append(f"# DOC{index:02d}: {title}")
        if body:
            parts.append("")
            parts.append(body)
        rebuilt += 1
    return "\n".join(parts).rstrip() + "\n", rebuilt


def fix_missing_qa_fact_refs(gold: dict[str, Any]) -> int:
    fact_ids = {fact.get("fact_id") for fact in gold.get("gold_facts", [])}
    efu_to_facts: dict[str, list[str]] = {}
    for fact in gold.get("gold_facts", []):
        fact_id = fact.get("fact_id")
        if not fact_id:
            continue
        for efu_id in fact.get("supporting_efus", []):
            efu_to_facts.setdefault(efu_id, []).append(fact_id)

    changed = 0
    for qa in gold.get("qa_questions", []):
        expected_facts = [fid for fid in qa.get("expected_facts", []) if fid in fact_ids]
        replacement: list[str] = []
        for efu_id in qa.get("expected_efus", []):
            replacement.extend(efu_to_facts.get(efu_id, []))
        merged: list[str] = []
        for fact_id in expected_facts + replacement:
            if fact_id in fact_ids and fact_id not in merged:
                merged.append(fact_id)
        if merged != qa.get("expected_facts", []):
            qa["expected_facts"] = merged
            changed += 1
    return changed


def validate(root: Path) -> ValidationReport:
    report = ValidationReport()
    report.stats["root"] = str(root.resolve())

    for filename in REQUIRED_FILES:
        if not (root / filename).exists():
            report.errors.append(f"missing required file: {filename}")

    if not (root / "gold_annotations.json").exists():
        return report

    try:
        gold = read_json(root / "gold_annotations.json")
    except Exception as exc:  # pragma: no cover - user data validation
        report.errors.append(f"gold_annotations.json is not valid JSON: {exc}")
        return report

    try:
        qa_data = read_json(root / "qa_questions.json") if (root / "qa_questions.json").exists() else {}
    except Exception as exc:  # pragma: no cover
        report.errors.append(f"qa_questions.json is not valid JSON: {exc}")
        qa_data = {}

    for key in TOP_LEVEL_KEYS:
        if key not in gold:
            report.errors.append(f"gold_annotations.json missing top-level key: {key}")

    documents = gold.get("documents", []) if isinstance(gold.get("documents"), list) else []
    efus = gold.get("gold_efu", []) if isinstance(gold.get("gold_efu"), list) else []
    facts = gold.get("gold_facts", []) if isinstance(gold.get("gold_facts"), list) else []
    qas = gold.get("qa_questions", []) if isinstance(gold.get("qa_questions"), list) else []
    standalone_qas = qa_data.get("qa_questions", qa_data if isinstance(qa_data, list) else [])

    report.stats.update(
        {
            "documents": len(documents),
            "gold_efu": len(efus),
            "gold_facts": len(facts),
            "qa_questions": len(qas),
            "standalone_qa_questions": len(standalone_qas),
        }
    )

    efu_missing = Counter()
    relation_types = Counter()
    efu_by_doc = Counter()
    for efu in efus:
        for key in EFU_REQUIRED:
            if key not in efu:
                efu_missing[key] += 1
        if efu.get("relation_type") not in ALLOWED_RELATION_TYPES:
            efu_missing["invalid_relation_type"] += 1
        relation_types[efu.get("relation_type")] += 1
        efu_by_doc[efu.get("source_doc_id")] += 1
    if efu_missing:
        report.errors.append(f"EFU schema problems: {dict(efu_missing)}")
    report.add_counter("efu_relation_types", relation_types)
    report.add_counter("efu_by_doc", efu_by_doc)

    fact_missing = Counter()
    fact_by_doc = Counter()
    fact_types = Counter()
    fact_difficulty = Counter()
    for fact in facts:
        for key in FACT_REQUIRED:
            if key not in fact:
                fact_missing[key] += 1
        for bad_key in ["required_measurements", "statement", "fact_statement", "text"]:
            if bad_key in fact:
                fact_missing[f"forbidden_{bad_key}"] += 1
        fact_by_doc[fact.get("source_doc_id")] += 1
        fact_types[fact.get("fact_type")] += 1
        fact_difficulty[fact.get("difficulty")] += 1
    if fact_missing:
        report.errors.append(f"Fact schema problems: {dict(fact_missing)}")
    report.add_counter("fact_by_doc", fact_by_doc)
    report.add_counter("fact_types", fact_types)
    report.add_counter("fact_difficulty", fact_difficulty)

    for label, qa_rows in [("gold", qas), ("standalone", standalone_qas)]:
        qa_missing = Counter()
        qa_levels = Counter()
        qa_by_doc = Counter()
        for qa in qa_rows:
            for key in QA_REQUIRED:
                if key not in qa:
                    qa_missing[key] += 1
            for bad_key in ["qid", "qa_id"]:
                if bad_key in qa:
                    qa_missing[f"forbidden_{bad_key}"] += 1
            qa_levels[qa.get("level")] += 1
            qa_by_doc[qa.get("source_doc_id")] += 1
        if qa_missing:
            report.errors.append(f"QA schema problems ({label}): {dict(qa_missing)}")
        report.add_counter(f"qa_{label}_levels", qa_levels)
        report.add_counter(f"qa_{label}_by_doc", qa_by_doc)

    all_ids = collect_ids_from_gold(gold)
    bad_ids = sorted({item for item in all_ids if not ID_RE.match(item)})
    report.stats["canonical_id_count"] = len(all_ids)
    report.stats["canonical_id_unique_count"] = len(set(all_ids))
    if bad_ids:
        report.errors.append(f"bad canonical_id values: {bad_ids[:20]} (count={len(bad_ids)})")

    fact_ids = {fact.get("fact_id") for fact in facts}
    efu_ids = {efu.get("gold_id") for efu in efus}
    missing_refs: list[tuple[str, str, str]] = []
    for fact in facts:
        for efu_id in fact.get("supporting_efus", []):
            if efu_id not in efu_ids:
                missing_refs.append((fact.get("fact_id", ""), "supporting_efu", efu_id))
    for qa in qas:
        for fact_id in qa.get("expected_facts", []):
            if fact_id not in fact_ids:
                missing_refs.append((qa.get("question_id", ""), "expected_fact", fact_id))
        for efu_id in qa.get("expected_efus", []):
            if efu_id not in efu_ids:
                missing_refs.append((qa.get("question_id", ""), "expected_efu", efu_id))
    if missing_refs:
        report.errors.append(f"missing references: {missing_refs[:20]} (count={len(missing_refs)})")
    report.stats["missing_reference_count"] = len(missing_refs)

    if (root / "corpus_documents.md").exists():
        corpus = (root / "corpus_documents.md").read_text(encoding="utf-8-sig", errors="replace")
        title_count = count_corpus_doc_titles(corpus)
        report.stats["corpus_doc_title_count"] = title_count
        if title_count != 10:
            report.errors.append(f"corpus should contain 10 '# DOCxx:' titles, found {title_count}")
        report.stats["corpus_word_count_regex"] = len(re.findall(r"\b\w+\b", corpus))

    special_markers = {
        "degree_symbol": "\u00b0",
        "arrow": "\u2192",
        "superscript_2": "\u00b2",
        "mu_symbol": "\u03bc",
        "micro_sign": "\u00b5",
        "times_symbol": "\u00d7",
        "en_dash": "\u2013",
        "em_dash": "\u2014",
        "minus_sign": "\u2212",
        "replacement_char": "\ufffd",
    }
    for filename in ["corpus_documents.md", "gold_annotations.json", "qa_questions.json"]:
        path = root / filename
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        counts = {name: text.count(marker) for name, marker in special_markers.items() if text.count(marker)}
        if counts:
            report.errors.append(f"{filename} contains special/non-ASCII markers: {counts}")

    return report


def repair(root: Path, report: ValidationReport) -> None:
    gold_path = root / "gold_annotations.json"
    qa_path = root / "qa_questions.json"
    corpus_path = root / "corpus_documents.md"

    gold = read_json(gold_path)
    gold_before = json.dumps(gold, ensure_ascii=False)
    gold = walk_strings(gold, normalize_string)
    ref_fixes = fix_missing_qa_fact_refs(gold)
    if ref_fixes:
        report.fixes.append(f"repaired expected_facts for {ref_fixes} QA rows in gold_annotations.json")
    if json.dumps(gold, ensure_ascii=False) != gold_before:
        write_json(gold_path, gold)
        report.fixes.append("normalized symbols/canonical IDs in gold_annotations.json")

    if qa_path.exists():
        qa_data = read_json(qa_path)
        qa_before = json.dumps(qa_data, ensure_ascii=False)
        qa_data = walk_strings(qa_data, normalize_string)
        # Mirror repaired QA refs from gold into standalone qa_questions.json by question_id.
        gold_qas = {qa.get("question_id"): qa for qa in gold.get("qa_questions", [])}
        standalone = qa_data.get("qa_questions", qa_data if isinstance(qa_data, list) else [])
        for qa in standalone:
            question_id = qa.get("question_id")
            if question_id in gold_qas:
                qa["expected_facts"] = list(gold_qas[question_id].get("expected_facts", []))
                qa["expected_efus"] = list(gold_qas[question_id].get("expected_efus", []))
        if json.dumps(qa_data, ensure_ascii=False) != qa_before:
            write_json(qa_path, qa_data)
            report.fixes.append("normalized symbols/canonical IDs and mirrored QA refs in qa_questions.json")

    if corpus_path.exists():
        corpus = corpus_path.read_text(encoding="utf-8-sig", errors="replace")
        fixed = normalize_text_symbols(corpus)
        fixed, changed_titles = add_doc_prefixes(fixed)
        rebuilt_docs = 0
        if count_corpus_doc_titles(fixed) != 10:
            rebuilt, rebuilt_docs = rebuild_corpus_from_doc_files(root)
            if rebuilt_docs == 10:
                fixed = rebuilt
        if fixed != corpus:
            corpus_path.write_text(fixed, encoding="utf-8")
            if rebuilt_docs == 10:
                report.fixes.append("rebuilt corpus_documents.md from doc01.md-doc10.md with DOC prefixes")
            else:
                report.fixes.append(f"normalized corpus symbols and added {changed_titles} DOC title prefixes")


def print_report(report: ValidationReport) -> None:
    print(json.dumps(
        {
            "ok": report.ok,
            "errors": report.errors,
            "warnings": report.warnings,
            "fixes": report.fixes,
            "stats": report.stats,
        },
        ensure_ascii=False,
        indent=2,
    ))


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate and optionally repair a Hyper-ChE benchmark directory.")
    parser.add_argument("benchmark_dir", type=Path)
    parser.add_argument("--fix", action="store_true", help="Apply deterministic repairs before final validation.")
    args = parser.parse_args()

    root = args.benchmark_dir
    if not root.exists():
        raise SystemExit(f"Benchmark directory does not exist: {root}")

    initial = validate(root)
    if args.fix:
        repair(root, initial)
        final = validate(root)
        final.fixes = initial.fixes
        print_report(final)
        raise SystemExit(0 if final.ok else 1)

    print_report(initial)
    raise SystemExit(0 if initial.ok else 1)


if __name__ == "__main__":
    main()
