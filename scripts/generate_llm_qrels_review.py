"""Generate human-review CSV/HTML for provisional retrieval qrels.

Read-only with respect to HyperRAG caches.  Qrels are keyed by the standard
(query_id, candidate_id) pair because one chunk can be retrieved for many queries.
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def flat(value: Any) -> str:
    if isinstance(value, list):
        return "; ".join(str(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return str(value or "")


def looks_bibliographic(text: str) -> bool:
    sample = str(text or "")
    reference_hits = len(re.findall(r"(?:^|\n)\s*\[?\d{1,3}\]?\s", sample))
    doi_hits = sample.lower().count("doi.org")
    return reference_hits >= 3 or doi_hits >= 3


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--queries", required=True, type=Path)
    parser.add_argument("--candidates", required=True, type=Path)
    parser.add_argument("--qrels", required=True, type=Path)
    parser.add_argument("--negative-review", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()

    queries_obj = load_json(args.queries)
    candidates_obj = load_json(args.candidates)
    qrels_obj = load_json(args.qrels)
    negatives_obj = load_json(args.negative_review)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    queries = {str(q["query_id"]): q for q in queries_obj.get("queries", [])}
    candidates = {
        (str(c["query_id"]), str(c["candidate_id"])): c
        for c in candidates_obj.get("candidate_evidence", [])
    }
    qrels = qrels_obj.get("qrels", [])

    expected_pairs = set(candidates)
    actual_pairs = {(str(r["query_id"]), str(r["candidate_id"])) for r in qrels}
    if len(actual_pairs) != len(qrels):
        raise RuntimeError("Duplicate (query_id, candidate_id) qrels found")
    if expected_pairs != actual_pairs:
        raise RuntimeError(
            f"Qrels/candidate mismatch: missing={len(expected_pairs-actual_pairs)}, "
            f"extra={len(actual_pairs-expected_pairs)}"
        )

    grades_by_query: dict[str, list[int]] = defaultdict(list)
    for row in qrels:
        grades_by_query[str(row["query_id"])].append(int(row["relevance_grade"]))
    no_relevant_queries = {
        qid for qid, grades in grades_by_query.items() if not any(grade >= 1 for grade in grades)
    }

    rows: list[dict[str, Any]] = []
    risk_counts: Counter[str] = Counter()
    grade_counts: Counter[int] = Counter()
    for qrel in sorted(qrels, key=lambda r: (str(r["query_id"]), int(r["retrieval_rank"]))):
        qid = str(qrel["query_id"])
        cid = str(qrel["candidate_id"])
        query = queries[qid]
        candidate = candidates[(qid, cid)]
        grade = int(qrel["relevance_grade"])
        source_docs = [str(x) for x in candidate.get("source_doc_ids") or []]
        expected_source = str(query.get("source_doc_id") or "")
        exact_gold = str(candidate.get("chunk_id")) in {str(x) for x in query.get("gold_chunk_ids") or []}
        rationale = str(qrel.get("rationale") or "").strip()
        flags: list[str] = []
        if exact_gold:
            flags.append("exact_gold")
        if grade == 3 and expected_source and expected_source not in source_docs:
            flags.append("cross_source_grade3")
        if not rationale:
            flags.append("empty_rationale_nonzero" if grade > 0 else "empty_rationale")
        if grade in (1, 2):
            flags.append("boundary_grade")
        if qid in no_relevant_queries:
            flags.append("query_no_relevant")
        if looks_bibliographic(str(candidate.get("content") or "")):
            flags.append("bibliography_like")
        for flag in flags:
            risk_counts[flag] += 1
        grade_counts[grade] += 1
        rows.append({
            "query_id": qid,
            "question": query.get("question"),
            "reference_answer": query.get("reference_answer"),
            "expected_source_doc_id": expected_source,
            "gold_chunk_ids": ";".join(str(x) for x in query.get("gold_chunk_ids") or []),
            "rank": int(candidate.get("retrieval_rank") or 0),
            "candidate_id": cid,
            "chunk_id": candidate.get("chunk_id"),
            "candidate_source_doc_ids": ";".join(source_docs),
            "retrieval_channels": flat(candidate.get("retrieval_channels")),
            "grade": grade,
            "label": qrel.get("relevance_label"),
            "supported_elements": flat(qrel.get("supported_elements")),
            "conflicts": flat(qrel.get("conflicts")),
            "rationale": rationale,
            "exact_gold": exact_gold,
            "risk_flags": ";".join(flags),
            "human_grade": "",
            "human_decision": "",
            "human_notes": "",
            "content": candidate.get("content"),
        })

    fieldnames = list(rows[0])
    all_csv = args.output_dir / "qrels_human_review.csv"
    with all_csv.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    priority_rows = [
        row for row in rows
        if int(row["grade"]) >= 1
        or bool(row["exact_gold"])
        or "query_no_relevant" in str(row["risk_flags"])
    ]
    priority_csv = args.output_dir / "qrels_priority_review.csv"
    with priority_csv.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(priority_rows)

    negative_fields = [
        "query_id", "question", "status", "recommended_action",
        "decisive_candidate_ids", "bibliographic_only_candidate_ids",
        "rationale", "dense_top_k", "human_decision", "human_notes",
    ]
    negative_rows = []
    for review in negatives_obj.get("reviews", []):
        qid = str(review["query_id"])
        negative_rows.append({
            "query_id": qid,
            "question": queries.get(qid, {}).get("question"),
            "status": review.get("status"),
            "recommended_action": review.get("recommended_action"),
            "decisive_candidate_ids": flat(review.get("decisive_candidate_ids")),
            "bibliographic_only_candidate_ids": flat(review.get("bibliographic_only_candidate_ids")),
            "rationale": review.get("rationale"),
            "dense_top_k": review.get("dense_top_k"),
            "human_decision": "",
            "human_notes": "",
        })
    negative_csv = args.output_dir / "negative_human_review.csv"
    with negative_csv.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=negative_fields)
        writer.writeheader()
        writer.writerows(negative_rows)

    summary = {
        "status": "provisional_llm_qrels_pending_human_confirmation",
        "query_counts": {
            "positive": sum(1 for q in queries.values() if q.get("retrievable") is True),
            "negative": sum(1 for q in queries.values() if q.get("retrievable") is False),
        },
        "candidate_qrel_pairs": len(rows),
        "grade_distribution": {str(k): grade_counts[k] for k in range(4)},
        "no_relevant_query_count": len(no_relevant_queries),
        "no_relevant_query_ids": sorted(no_relevant_queries),
        "risk_counts": dict(sorted(risk_counts.items())),
        "negative_status_counts": negatives_obj.get("status_counts", {}),
        "methodological_warning": (
            "These are LLM provisional judgments. For fair multi-system gNDCG, "
            "judge the union of all systems' candidates with shared qrels and IDCG."
        ),
    }
    write_json(args.output_dir / "human_review_summary.json", summary)

    def row_html(row: dict[str, Any]) -> str:
        flags = html.escape(str(row["risk_flags"]))
        return (
            f'<tr data-grade="{row["grade"]}" data-risk="{flags}">'
            f'<td>{html.escape(str(row["query_id"]))}</td>'
            f'<td>{row["rank"]}</td>'
            f'<td class="grade g{row["grade"]}">{row["grade"]}</td>'
            f'<td>{html.escape(str(row["chunk_id"]))}<br><small>{html.escape(str(row["candidate_source_doc_ids"]))}</small></td>'
            f'<td>{html.escape(str(row["question"]))}<hr><small>Reference: {html.escape(str(row["reference_answer"]))}</small></td>'
            f'<td class="content">{html.escape(str(row["content"] or ""))}</td>'
            f'<td>{html.escape(str(row["rationale"]))}<hr><small>{flags}</small></td>'
            '<td><input size="3" placeholder="0-3"><br><textarea placeholder="decision / notes"></textarea></td>'
            '</tr>'
        )

    grade_summary = " ".join(f"grade {g}: {grade_counts[g]}" for g in range(4))
    table_rows = "\n".join(row_html(row) for row in rows)
    negative_html = "\n".join(
        '<tr>'
        f'<td>{html.escape(str(row["query_id"]))}</td>'
        f'<td>{html.escape(str(row["question"]))}</td>'
        f'<td>{html.escape(str(row["status"]))}</td>'
        f'<td>{html.escape(str(row["rationale"]))}</td>'
        '<td><textarea placeholder="accept / reject / notes"></textarea></td>'
        '</tr>'
        for row in negative_rows
    )
    page = f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>Hyper-base provisional qrels review</title>
<style>
body{{font-family:Arial,"Microsoft YaHei",sans-serif;margin:20px;color:#172033}} h1,h2{{margin-bottom:8px}}
.summary{{padding:12px 16px;background:#eef4ff;border-left:5px solid #3568d4;margin:12px 0}}
.controls{{position:sticky;top:0;background:white;padding:10px 0;z-index:2}}
input,select,textarea{{font:inherit}} table{{border-collapse:collapse;width:100%;table-layout:fixed}} th,td{{border:1px solid #ccd3df;padding:7px;vertical-align:top}}
th{{background:#263b5e;color:white;position:sticky;top:50px;z-index:1}} td.content{{white-space:pre-wrap;max-height:260px;overflow:auto;font-size:12px}}
.grade{{font-weight:700;text-align:center}} .g0{{background:#f1f3f5}} .g1{{background:#fff2bf}} .g2{{background:#ffd39a}} .g3{{background:#a8e6b5}}
small{{color:#526070}} textarea{{width:95%;min-height:55px}} hr{{border:0;border-top:1px solid #dde2ea}}
</style></head><body>
<h1>hyper_base Retrieval qrels 人工复核</h1>
<div class="summary">共 {len(rows)} 个 query-candidate 对；{grade_summary}；无相关候选的问题 {len(no_relevant_queries)} 个；非零等级但 rationale 为空 {risk_counts['empty_rationale_nonzero']} 条。当前均为 LLM provisional，不是 gold。</div>
<div class="controls">搜索 <input id="search" size="42"> 等级 <select id="grade"><option value="">全部</option><option>0</option><option>1</option><option>2</option><option>3</option></select> <label><input id="risk" type="checkbox">仅看风险项</label></div>
<table id="qrels"><thead><tr><th style="width:8%">Query</th><th style="width:3%">Rank</th><th style="width:3%">Grade</th><th style="width:9%">Chunk / source</th><th style="width:18%">Question / reference</th><th style="width:35%">Chunk content</th><th style="width:16%">Rationale / flags</th><th style="width:8%">Human</th></tr></thead><tbody>{table_rows}</tbody></table>
<h2>13 条 provisional negatives</h2><table><thead><tr><th>Query</th><th>Question</th><th>Status</th><th>LLM rationale</th><th>Human</th></tr></thead><tbody>{negative_html}</tbody></table>
<script>
function applyFilter(){{var s=document.getElementById('search').value.toLowerCase();var g=document.getElementById('grade').value;var risk=document.getElementById('risk').checked;document.querySelectorAll('#qrels tbody tr').forEach(function(row){{var ok=(!s||row.innerText.toLowerCase().indexOf(s)>=0)&&(!g||row.dataset.grade===g)&&(!risk||row.dataset.risk.length>0);row.style.display=ok?'':'none';}});}}
document.getElementById('search').addEventListener('input',applyFilter);document.getElementById('grade').addEventListener('change',applyFilter);document.getElementById('risk').addEventListener('change',applyFilter);
</script></body></html>'''
    (args.output_dir / "qrels_human_review.html").write_text(page, encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
