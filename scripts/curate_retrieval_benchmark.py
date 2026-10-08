"""Curate the provisional 58-query retrieval benchmark from the audited draft.

Deterministic and read-only with respect to HyperRAG caches. It does not call an
LLM or run retrieval. Original candidate fields are preserved for audit.
"""
from __future__ import annotations
import argparse, csv, json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RETRIEVABLE_IDS = """RQ_RFB_002_01 RQ_RFB_003_02 RQ_RFB_005_02 RQ_RFB_006_02 RQ_RFB_007_02 RQ_RFB_008_01 RQ_RFB_010_02 RQ_RFB_011_01 RQ_RFB_012_02 RQ_RFB_013_02 RQ_RFB_014_01 RQ_RFB_015_02 RQ_RFB_016_02 RQ_RFB_019_01 RQ_RFB_020_02 RQ_RFB_021_01 RQ_RFB_022_02 RQ_RFB_023_01 RQ_RFB_024_02 RQ_RFB_025_01 RQ_RFB_026_01 RQ_RFB_029_02 RQ_RFB_031_02 RQ_RFB_032_02 RQ_RFB_033_02 RQ_RFB_034_01 RQ_RFB_035_02 RQ_RFB_036_02 RQ_RFB_037_02 RQ_RFB_038_02 RQ_RFB_040_02 RQ_RFB_041_01 RQ_RFB_043_02 RQ_RFB_045_02 RQ_RFB_046_02 RQ_RFB_047_02 RQ_RFB_048_02 RQ_RFB_050_02 RQ_RFB_051_01 RQ_RFB_052_02 RQ_RFB_055_02 RQ_RFB_056_02 RQ_RFB_058_02 RQ_RFB_059_02 RQ_RFB_060_02""".split()
UNRETRIEVABLE_IDS = "UQ_001 UQ_002 UQ_003 UQ_004 UQ_009 UQ_010 UQ_011 UQ_012 UQ_013 UQ_015 UQ_016 UQ_018 UQ_019".split()
EXCLUDED_DOCUMENTS = {
 "RFB_001":"award/editorial", "RFB_004":"review/broad overview", "RFB_009":"award/editorial",
 "RFB_017":"review/broad overview", "RFB_018":"review/broad overview", "RFB_027":"review/broad overview",
 "RFB_028":"review/broad overview", "RFB_030":"review/broad overview", "RFB_039":"review/broad overview",
 "RFB_042":"outside primary flow-battery topic", "RFB_044":"outside primary flow-battery topic",
 "RFB_049":"outside primary flow-battery topic", "RFB_053":"review/broad overview",
 "RFB_054":"review/broad overview", "RFB_057":"review/broad overview",
}
FACT_TYPE_MAP = {
 "performance_comparison":"performance_comparison", "method_comparison":"performance_comparison",
 "crossover_comparison":"performance_comparison", "molecular_performance_comparison":"performance_comparison",
 "operating_performance":"operating_conditions", "condition_effect":"operating_conditions",
 "impurity_effect":"operating_conditions", "concentration_stability_tradeoff":"operating_conditions",
 "operating_parameter_sensitivity":"operating_conditions", "operating_optimum_metrics":"operating_conditions",
 "cycling_performance":"cycling_stability", "cycling_stability":"cycling_stability",
 "coordination_mechanism":"mechanism", "phase_separation_mechanism":"mechanism",
 "electrolyte_additive_mechanism":"mechanism", "electrode_design_rule":"material_design",
 "architecture_comparison":"system_architecture", "integrated_performance":"system_architecture",
 "model_inputs":"modeling_diagnostics", "model_experiment_validation":"modeling_diagnostics",
 "degradation_diagnostic":"modeling_diagnostics", "multimetric_performance":"performance_metrics",
 "performance_metrics":"performance_metrics", "performance_metric":"performance_metrics",
 "membrane_performance_metrics":"performance_metrics", "molecular_performance_metrics":"performance_metrics",
 "prototype_performance_metrics":"performance_metrics",
}

def load_json(path: Path) -> Any:
 return json.loads(path.read_text(encoding="utf-8"))
def write_json(path: Path, value: Any) -> None:
 path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
def calibrated_difficulty(q: dict[str, Any]) -> str:
 support, arity = str(q.get("support_mode") or ""), int(q.get("fact_arity") or 0)
 if support == "cross_section": return "high_order"
 if support == "single_chunk" and arity <= 4: return "simple"
 if support == "adjacent_chunks" and arity >= 6: return "high_order"
 return "compositional"
def curate_positive(q: dict[str, Any], chunks: dict[str, Any]) -> dict[str, Any]:
 gold = [str(x) for x in q.get("gold_chunk_ids") or []]
 missing = [x for x in gold if x not in chunks]
 wrong = [x for x in gold if x in chunks and str(chunks[x].get("source_doc_id") or chunks[x].get("doc_id") or "") != str(q.get("source_doc_id") or "")]
 if missing or wrong: raise RuntimeError(f"{q['query_id']} invalid gold chunks: missing={missing}, wrong_doc={wrong}")
 old_type = str(q.get("fact_type") or "")
 if old_type not in FACT_TYPE_MAP: raise RuntimeError(f"No normalized type for {q['query_id']}: {old_type}")
 excerpts = []
 for item in q.get("evidence_spans") or []:
  cid, text = str(item.get("chunk_id") or ""), str(item.get("text") or "")
  exact = bool(cid in chunks and text and text in str(chunks[cid].get("content") or ""))
  excerpts.append({**item, "is_exact_chunk_substring":exact, "field_semantics":"display excerpt, not an offset span unless exact=true"})
 return {**q, "original_fact_type":old_type, "fact_type":FACT_TYPE_MAP[old_type],
  "original_difficulty":q.get("difficulty"), "difficulty":calibrated_difficulty(q),
  "original_evidence_spans":q.get("evidence_spans") or [], "evidence_excerpts":excerpts,
  "evidence_spans":[], "gold_chunk_validation":"passed",
  "selection_policy":"one question per eligible primary-research document",
  "review_status":"provisional_curated_pending_human_confirmation"}
def curate_negative(q: dict[str, Any]) -> dict[str, Any]:
 return {**q, "gold_chunk_ids":[], "review_status":"provisional_negative_pending_semantic_validation",
  "absence_verification":"pending_dense_and_llm_review", "semantic_search_status":"pending",
  "selection_policy":"hard negative near the corpus topic but requesting an unobserved measurement or protocol"}
def main() -> None:
 p=argparse.ArgumentParser(); p.add_argument("--draft",required=True,type=Path); p.add_argument("--chunks",required=True,type=Path); p.add_argument("--output-dir",required=True,type=Path); a=p.parse_args()
 draft, chunks = load_json(a.draft), load_json(a.chunks)
 by_id={str(x["query_id"]):x for x in draft.get("queries") or []}
 missing=[x for x in RETRIEVABLE_IDS+UNRETRIEVABLE_IDS if x not in by_id]
 if missing: raise RuntimeError(f"Missing IDs: {missing}")
 pos=[curate_positive(by_id[x],chunks) for x in RETRIEVABLE_IDS]; neg=[curate_negative(by_id[x]) for x in UNRETRIEVABLE_IDS]
 if len({x["source_doc_id"] for x in pos}) != 45: raise RuntimeError("Expected 45 unique positive documents")
 a.output_dir.mkdir(parents=True,exist_ok=True); now=datetime.now(timezone.utc).isoformat()
 out={"metadata":{"status":"provisional_curated","created_at":now,"retrieval_unit":"chunk","corpus_documents":60,"corpus_chunks":len(chunks),"benchmark_target":{"retrievable":45,"unretrievable":13},"selection_policy":"one query from each of 45 eligible primary-research papers; 15 editorial, review, broad, or off-topic documents excluded before retrieval","no_source_doc_filter_during_retrieval":True,"gold_status":"not_gold_until_human_confirmation"},"query_counts":{"retrievable":len(pos),"unretrievable":len(neg),"total":len(pos)+len(neg)},"queries":pos+neg}
 write_json(a.output_dir/"retrieval_queries.json",out)
 fields=["query_id","retrievable","source_doc_id","question","reference_answer","fact_type","difficulty","support_mode","gold_chunk_ids","review_status","human_decision","human_revised_question","human_notes"]
 with (a.output_dir/"retrieval_queries_review.csv").open("w",encoding="utf-8-sig",newline="") as h:
  w=csv.DictWriter(h,fieldnames=fields); w.writeheader()
  for q in pos+neg: w.writerow({**{k:q.get(k) for k in fields},"gold_chunk_ids":";".join(q.get("gold_chunk_ids") or []),"human_decision":"","human_revised_question":"","human_notes":""})
 audit={"created_at":now,"source_draft":str(a.draft.resolve()),"chunk_store":str(a.chunks.resolve()),"selected_retrievable_ids":RETRIEVABLE_IDS,"selected_unretrievable_ids":UNRETRIEVABLE_IDS,"excluded_documents":EXCLUDED_DOCUMENTS,"difficulty_distribution":dict(Counter(x["difficulty"] for x in pos)),"support_mode_distribution":dict(Counter(x["support_mode"] for x in pos)),"fact_type_distribution":dict(Counter(x["fact_type"] for x in pos)),"exact_display_excerpt_count":sum(int(e["is_exact_chunk_substring"]) for q in pos for e in q["evidence_excerpts"]),"display_excerpt_count":sum(len(q["evidence_excerpts"]) for q in pos),"warnings":["Draft evidence_spans are display excerpts, not guaranteed exact character spans; curated output renames them evidence_excerpts.","Unretrievable questions remain provisional until full-corpus dense retrieval and LLM/human absence review.","Benchmark remains provisional until human confirmation."]}
 write_json(a.output_dir/"selection_audit.json",audit); print(json.dumps(audit,ensure_ascii=False,indent=2))
if __name__ == "__main__": main()
