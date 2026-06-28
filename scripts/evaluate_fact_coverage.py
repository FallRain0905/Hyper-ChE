"""Evaluate Fact Coverage@k for Hyper-ChE experiment caches."""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from datetime import datetime, timezone
import json
import os
import pickle
import re
import statistics
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except Exception:  # pragma: no cover
    yaml = None


REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_ROOT = REPO_ROOT / "configs" / "normalization"
DEFAULT_EQUIVALENCE_MAP = CONFIG_ROOT / "canonical_equivalence_map.yaml"

JUDGE_ALIASES = {
    "kimi": {"api_key_env": "KIMI_API_KEY", "base_url_env": "KIMI_BASE_URL", "model_env": "KIMI_MODEL", "base_url": "https://api.moonshot.cn/v1", "model": "moonshot-v1-8k"},
    "deepseek": {"api_key_env": "DEEPSEEK_API_KEY", "base_url_env": "DEEPSEEK_BASE_URL", "model_env": "DEEPSEEK_MODEL", "base_url": "https://api.deepseek.com", "model": "deepseek-v4-flash"},
    "qwen": {"api_key_env": "QWEN_API_KEY", "base_url_env": "QWEN_BASE_URL", "model_env": "QWEN_MODEL", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen-plus"},
}


def normalize(text: Any) -> str:
    text = str(text or "").lower()
    text = text.replace("−", "-").replace("–", "-").replace("—", "-")
    text = text.replace("cm-2", "cm2").replace("cm^2", "cm2").replace("cm²", "cm2")
    text = re.sub(r"m[aA]\s*(?:/|\s+)\s*cm\s*-?\s*2", "ma/cm2", text)
    text = re.sub(r"mol\s*(?:/|\s+)\s*l(?:-1)?", "mol/l", text)
    text = re.sub(r"mmol\s*(?:/|\s+)\s*l(?:-1)?", "mmol/l", text)
    text = re.sub(r"mmol\s*(?:/|\s+)\s*g", "mmol/g", text)
    text = re.sub(r"°\s*c|degc", "c", text)
    text = re.sub(r"[^a-z0-9.%/+:-]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def compact(text: Any) -> str:
    return re.sub(r"[^a-z0-9.%/+:-]+", "", normalize(text))


def slug_number(value: Any, *, keep_decimal_for_integer: bool = False) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return compact(value).replace(".", "_") or "unknown"
    if keep_decimal_for_integer and numeric.is_integer():
        return f"{numeric:.1f}".replace("-", "minus_").replace(".", "_")
    return f"{numeric:g}".replace("-", "minus_").replace(".", "_")


def unit_slug(unit: Any) -> str:
    unit_norm = normalize(unit)
    if unit_norm in {"%", "percent"}:
        return "percent"
    if unit_norm == "ma/cm2":
        return "ma_cm2"
    if unit_norm == "mol/l":
        return "mol_l"
    if unit_norm == "mmol/l":
        return "mmol_l"
    if unit_norm == "mmol/g":
        return "mmol_g"
    if unit_norm in {"c", "degc"}:
        return "c"
    if unit_norm in {"degree", "deg"}:
        return "degree"
    if unit_norm in {"cycle", "cycles"}:
        return "cycle"
    if unit_norm == "v":
        return "v"
    return compact(unit_norm).replace("/", "_") or "unitless"


def read_yaml_or_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(path)
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() in {".yaml", ".yml"} and yaml:
        return yaml.safe_load(text) or {}
    return json.loads(text)


def load_equivalence_map(path: Path | None) -> dict[str, str]:
    if not path or not path.exists():
        return {}
    data = read_yaml_or_json(path)
    return {str(k): str(v) for k, v in (data.get("equivalences") or data).items()}


def canonicalize_id(identifier: Any, equivalences: dict[str, str]) -> str:
    value = str(identifier or "").strip()
    seen = set()
    while value in equivalences and value not in seen:
        seen.add(value)
        value = equivalences[value]
    return value


def load_gold(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8-sig"), strict=False)
    return list(data.get("gold_facts", data if isinstance(data, list) else []))


def load_cache(cache_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    graph_path = cache_dir / "hypergraph_chunk_entity_relation.hgdb"
    chunks_path = cache_dir / "kv_store_text_chunks.json"
    if not graph_path.exists():
        raise FileNotFoundError(f"Missing hypergraph DB: {graph_path}")
    graph = pickle.loads(graph_path.read_bytes())
    chunks = json.loads(chunks_path.read_text(encoding="utf-8")) if chunks_path.exists() else {}
    return graph, chunks


def vertex_label(vertex_id: str, vertex_data: dict[str, Any]) -> str:
    name = vertex_data.get("canonical_name") or vertex_data.get("display_name") or vertex_data.get("raw_name") or vertex_id
    value = vertex_data.get("value")
    unit = vertex_data.get("unit")
    if value is not None and unit:
        return f"{name} = {value} {unit}"
    if vertex_data.get("min_value") is not None or vertex_data.get("max_value") is not None:
        return f"{name} = {vertex_data.get('min_value')} to {vertex_data.get('max_value')} {unit or ''}".strip()
    return str(name)


def readable_evidence(vertices: list[str], edge: dict[str, Any], vertex_store: dict[str, Any]) -> str:
    labels = [vertex_label(v, vertex_store.get(v, {})) for v in vertices]
    relation_type = edge.get("relation_type") or "RELATION"
    description = str(edge.get("description") or "").strip()
    instance_sentences = []
    for instance in edge.get("evidence_instances") or []:
        if isinstance(instance, dict):
            sentence = instance.get("sentence") or instance.get("evidence_span") or instance.get("description")
            if sentence:
                instance_sentences.append(str(sentence))
    sentence_text = " ; ".join(dict.fromkeys(instance_sentences[:3]))
    parts = [f"Relation type: {relation_type}", "Readable labels: " + "; ".join(labels)]
    if description:
        parts.append("Description: " + description)
    if sentence_text:
        parts.append("Source evidence: " + sentence_text)
    return "\n".join(parts)


def evidence_from_graph(graph: dict[str, Any], view: str, equivalences: dict[str, str]) -> list[dict[str, Any]]:
    evidence = []
    vertex_store = graph.get("v_data", {})
    for key, data in graph.get("e_data", {}).items():
        vertices = list(key) if isinstance(key, tuple) else [str(key)]
        if view == "graph" and len(vertices) != 2:
            continue
        canonical_vertices = [canonicalize_id(v, equivalences) for v in vertices]
        labels = [vertex_label(v, vertex_store.get(v, {})) for v in vertices]
        relation_type = str(data.get("relation_type") or "")
        readable = readable_evidence(vertices, data, vertex_store)
        text = "\n".join(["evidence_id: " + "|".join(canonical_vertices), "relation_type: " + relation_type, "canonical_vertices: " + ", ".join(canonical_vertices), "readable_labels: " + "; ".join(labels), readable])
        evidence.append({"id": "|".join(canonical_vertices), "vertices": canonical_vertices, "raw_vertices": vertices, "canonical_vertices": canonical_vertices, "readable_labels": labels, "relation_type": relation_type, "source_id": data.get("source_id", ""), "source_chunk_id": data.get("source_id", ""), "text": text, "readable_evidence": readable, "evidence_instances": data.get("evidence_instances") or [], "arity": len(vertices), "kind": view})
    return evidence


def evidence_from_chunks(chunks: dict[str, Any]) -> list[dict[str, Any]]:
    evidence = []
    for chunk_id, data in chunks.items():
        text = data.get("content", "") if isinstance(data, dict) else str(data)
        evidence.append({"id": chunk_id, "source_chunk_id": data.get("source_chunk_id") if isinstance(data, dict) else None, "text": text, "readable_evidence": text, "vertices": [], "canonical_vertices": [], "relation_type": "TEXT_CHUNK", "arity": 1, "kind": "naive"})
    return evidence


def query_terms(claim: str) -> set[str]:
    tokens = re.findall(r"[a-zA-Z][a-zA-Z0-9.+/-]*|\d+(?:\.\d+)?", claim)
    stop = {"the", "and", "with", "using", "than", "from", "after", "because", "while", "that", "into", "showed", "achieved", "reached", "at", "under", "for"}
    return {normalize(t) for t in tokens if len(t) > 1 and normalize(t) not in stop}


def expected_condition_id(condition: dict[str, Any], equivalences: dict[str, str]) -> str:
    qtype = str(condition.get("quantity_type") or condition.get("type") or condition.get("canonical_id") or "")
    if qtype.startswith("condition:"):
        return canonicalize_id(qtype, equivalences)
    value = condition.get("value")
    unit = condition.get("unit")
    qnorm = normalize(qtype)
    if "current" in qnorm:
        return f"condition:current_density_{slug_number(value)}_ma_cm2"
    if "temperature" in qnorm:
        return f"condition:temperature_{slug_number(value)}_c"
    if "cycle" in qnorm:
        return f"condition:cycle_number_{slug_number(value)}_cycle"
    if "ph" in qnorm:
        return f"condition:ph_{slug_number(value)}"
    if "bi" in qnorm:
        return f"condition:bi3_concentration_{slug_number(value)}_{unit_slug(unit or 'mmol/L')}"
    if "vanadium" in qnorm:
        return f"condition:vanadium_concentration_{slug_number(value)}_{unit_slug(unit or 'mol/L')}"
    if "acid" in qnorm or "h2so4" in qnorm:
        return f"condition:acid_concentration_{slug_number(value)}_{unit_slug(unit or 'mol/L')}"
    return f"condition:{compact(qtype).replace('/', '_')}_{slug_number(value)}_{unit_slug(unit)}"


def expected_metric_id(metric: dict[str, Any], equivalences: dict[str, str]) -> str:
    mtype = str(metric.get("metric_type") or metric.get("type") or metric.get("canonical_id") or "")
    if mtype.startswith(("metric:", "measurement:", "evidence:", "degradation:")):
        return canonicalize_id(mtype, equivalences)
    value = metric.get("value")
    unit = metric.get("unit")
    mnorm = normalize(mtype)
    if mnorm in {"ce", "coulombic efficiency"} or "coulombic" in mnorm:
        return f"measurement:ce_{slug_number(value, keep_decimal_for_integer=True)}_percent"
    if mnorm in {"ve", "voltage efficiency", "voltaic efficiency"} or "voltage efficiency" in mnorm:
        return f"measurement:ve_{slug_number(value, keep_decimal_for_integer=True)}_percent"
    if mnorm in {"ee", "energy efficiency"} or "energy efficiency" in mnorm:
        return f"measurement:ee_{slug_number(value, keep_decimal_for_integer=True)}_percent"
    if "capacity retention" in mnorm:
        return f"measurement:capacity_retention_{slug_number(value, keep_decimal_for_integer=True)}_percent"
    if "iec" in mnorm or "ion exchange" in mnorm:
        return f"measurement:iec_{slug_number(value)}_mmol_g"
    if "contact angle" in mnorm:
        return f"measurement:contact_angle_{slug_number(value)}_degree"
    if "polarization voltage" in mnorm or "voltage loss" in mnorm:
        return f"measurement:polarization_voltage_delta_{slug_number(value)}_v"
    return f"measurement:{compact(mtype).replace('/', '_')}_{slug_number(value)}_{unit_slug(unit)}"


def fact_required_groups(fact: dict[str, Any], equivalences: dict[str, str]) -> dict[str, list[Any]]:
    return {"entities": [canonicalize_id(item, equivalences) for item in fact.get("required_entities", [])], "conditions": [{**condition, "expected_id": canonicalize_id(expected_condition_id(condition, equivalences), equivalences)} for condition in fact.get("required_conditions", [])], "measurements": [{**metric, "expected_id": canonicalize_id(expected_metric_id(metric, equivalences), equivalences)} for metric in fact.get("required_metrics", [])], "mechanisms": [canonicalize_id(item, equivalences) for item in fact.get("required_mechanisms", [])]}


def element_present(identifier: str, context: str, evidence_ids: set[str], equivalences: dict[str, str]) -> bool:
    raw = canonicalize_id(identifier, equivalences)
    if raw in evidence_ids:
        return True
    norm_context = normalize(context)
    cmp_context = compact(context)
    if raw.startswith(("measurement:", "condition:")):
        return compact(raw.split(":", 1)[1].replace("_", " ")) in cmp_context
    aliases = {"metric:ce": ["ce", "coulombic efficiency"], "metric:ve": ["ve", "voltage efficiency", "voltaic efficiency"], "metric:ee": ["ee", "energy efficiency"], "system:vrfb": ["vrfb", "vanadium redox flow battery"], "system:icrfb": ["icrfb", "iron chromium redox flow battery", "iron-chromium redox flow battery"]}
    if raw in aliases:
        return any(compact(alias) in cmp_context for alias in aliases[raw])
    return compact(raw.split(":", 1)[-1].replace("_", " ")) in cmp_context or raw in norm_context


def rank_evidence(claim: str, evidence: list[dict[str, Any]], k: int, equivalences: dict[str, str], *, enable_hybrid_rerank: bool = True) -> list[dict[str, Any]]:
    terms = query_terms(claim)
    claim_norm = normalize(claim)
    relation_bonus_type = ""
    if any(term in claim_norm for term in ["achieved", "reached", "current density", " at "]):
        relation_bonus_type = "OPERATION_PERFORMANCE"
    elif any(term in claim_norm for term in ["compared", "lower than", "higher than", "versus"]):
        relation_bonus_type = "COMPARISON"
    elif any(term in claim_norm for term in ["due to", "attributed to", "caused by", "mechanism"]):
        relation_bonus_type = "DEGRADATION_CHAIN|MECHANISM_EVIDENCE"
    elif any(term in claim_norm for term in ["prepared", "modified", "iec", "sulfonation"]):
        relation_bonus_type = "COMPOSITION"
    ranked = []
    for item in evidence:
        norm_text = normalize(item["text"])
        lexical_hits = sum(1 for term in terms if term and term in norm_text)
        lexical_score = lexical_hits / max(1, len(terms))
        vertices = {canonicalize_id(v, equivalences) for v in item.get("canonical_vertices", [])}
        entity_overlap = sum(1 for vertex in vertices if any(part and part in claim_norm for part in normalize(vertex).split(":")[-1].split("_"))) / max(1, len(vertices))
        condition_overlap = sum(1 for vertex in vertices if vertex.startswith("condition:") and compact(vertex) in compact(claim)) / max(1, len([v for v in vertices if v.startswith("condition:")]) or 1)
        measurement_overlap = sum(1 for vertex in vertices if vertex.startswith("measurement:") and any(num.replace("_", ".") in claim_norm for num in re.findall(r"\d+(?:_\d+)?", vertex)))
        measurement_overlap = measurement_overlap / max(1, len([v for v in vertices if v.startswith("measurement:")]) or 1)
        relation_bonus = 1.0 if relation_bonus_type and any(token in str(item.get("relation_type", "")) for token in relation_bonus_type.split("|")) else 0.0
        if enable_hybrid_rerank:
            score = 0.45 * lexical_score + 0.25 * entity_overlap + 0.15 * condition_overlap + 0.10 * measurement_overlap + 0.05 * relation_bonus + min(float(item.get("arity", 1)), 6.0) * 0.01
        else:
            score = 0.75 * lexical_score + 0.25 * entity_overlap
        ranked.append((score, item))
    ranked.sort(key=lambda pair: pair[0], reverse=True)
    return [item for score, item in ranked[:k] if score > 0]


def judge_fact(fact: dict[str, Any], evidence: list[dict[str, Any]], equivalences: dict[str, str]) -> dict[str, Any]:
    context = "\n".join(item["text"] for item in evidence)
    evidence_ids = {canonicalize_id(v, equivalences) for item in evidence for v in item.get("canonical_vertices", [])}
    required = fact_required_groups(fact, equivalences)
    missing_entities = [item for item in required["entities"] if not element_present(item, context, evidence_ids, equivalences)]
    missing_conditions = [item for item in required["conditions"] if not element_present(item["expected_id"], context, evidence_ids, equivalences)]
    missing_measurements = [item for item in required["measurements"] if not element_present(item["expected_id"], context, evidence_ids, equivalences)]
    missing_mechanisms = [item for item in required["mechanisms"] if not element_present(item, context, evidence_ids, equivalences)]
    total = max(1, len(required["entities"]) + len(required["conditions"]) + len(required["measurements"]) + len(required["mechanisms"]))
    hits = total - len(missing_entities) - len(missing_conditions) - len(missing_measurements) - len(missing_mechanisms)
    support_score = hits / total
    condition_total = max(1, len(required["conditions"]))
    condition_integrity = (len(required["conditions"]) - len(missing_conditions)) / condition_total
    if support_score >= 0.85 and condition_integrity >= 0.8:
        label = "SUPPORTED"
    elif support_score >= 0.45:
        label = "PARTIALLY_SUPPORTED"
    else:
        label = "UNSUPPORTED"
    return {"support_label": label, "support_score": round(support_score, 4), "condition_integrity": round(condition_integrity, 4), "missing_elements": {"missing_entities": missing_entities, "missing_conditions": missing_conditions, "missing_measurements": missing_measurements, "missing_mechanisms": missing_mechanisms, "id_mismatch_candidates": []}, "wrong_or_conflicting_elements": [], "reason": "Heuristic judge based on structured entity, condition, measurement, and mechanism coverage."}


def llm_context(evidence: list[dict[str, Any]]) -> str:
    return "\n\n".join(json.dumps({"rank": index + 1, "evidence_id": item["id"], "relation_type": item.get("relation_type"), "canonical_vertices": item.get("canonical_vertices"), "readable_evidence": item.get("readable_evidence"), "source_chunk_id": item.get("source_chunk_id"), "evidence_instances": item.get("evidence_instances")}, ensure_ascii=False, indent=2) for index, item in enumerate(evidence))


def judge_fact_with_llm(fact: dict[str, Any], evidence: list[dict[str, Any]], *, model: str, base_url: str | None, api_key: str) -> dict[str, Any]:
    from openai import OpenAI
    prompt = f"""Judge whether the retrieved evidence supports the gold chemical fact.

Gold fact:
{json.dumps(fact, ensure_ascii=False, indent=2)}

Retrieved evidence:
{llm_context(evidence)}

Return strict JSON only:
{{
  "support_label": "SUPPORTED | PARTIALLY_SUPPORTED | UNSUPPORTED",
  "support_score": 0.0,
  "condition_integrity": 0.0,
  "missing_elements": {{
    "missing_entities": [],
    "missing_conditions": [],
    "missing_measurements": [],
    "missing_mechanisms": [],
    "id_mismatch_candidates": []
  }},
  "wrong_or_conflicting_elements": [],
  "reason": "..."
}}
"""
    client = OpenAI(api_key=api_key, base_url=base_url) if base_url else OpenAI(api_key=api_key)
    response = client.chat.completions.create(model=model, messages=[{"role": "user", "content": prompt}], temperature=0, response_format={"type": "json_object"})
    raw_content = response.choices[0].message.content or "{}"
    data = json.loads(raw_content)
    return {"support_label": data.get("support_label", "UNSUPPORTED"), "support_score": float(data.get("support_score", 0.0)), "condition_integrity": float(data.get("condition_integrity", 0.0)), "missing_elements": data.get("missing_elements", {}), "wrong_or_conflicting_elements": list(data.get("wrong_or_conflicting_elements", [])), "reason": str(data.get("reason", "")), "_raw_response": raw_content, "_judge_model": model, "_judge_base_url": base_url}


def format_llm_error(exc: Exception) -> str:
    parts = [f"{type(exc).__name__}: {exc}"]
    for attr in ("status_code", "code"):
        value = getattr(exc, attr, None)
        if value is not None:
            parts.append(f"{attr}={value}")
    body = getattr(exc, "body", None)
    if body:
        parts.append(f"body={body}")
    return " | ".join(parts)


def progress(message: str, *, quiet: bool = False, log_file: Path | None = None) -> None:
    if not quiet:
        print(message, file=sys.stderr, flush=True)
    if log_file:
        with log_file.open("a", encoding="utf-8") as f:
            f.write(message + "\n")


def flatten_missing_for_counter(missing: Any) -> list[str]:
    if isinstance(missing, dict):
        output = []
        for key, values in missing.items():
            for value in values or []:
                output.append(f"{key}:{value.get('expected_id') or value.get('metric_type') or value.get('quantity_type') or value}" if isinstance(value, dict) else f"{key}:{value}")
        return output
    if isinstance(missing, list):
        return [str(item) for item in missing]
    return []


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def evidence_token_budget(evidence: list[dict[str, Any]]) -> int:
    return sum(max(1, len(str(item.get("text") or "").split())) for item in evidence)


def majority_label(labels: list[str]) -> str:
    if not labels:
        return "UNSUPPORTED"
    counts = Counter(labels)
    order = {"SUPPORTED": 3, "PARTIALLY_SUPPORTED": 2, "UNSUPPORTED": 1}
    return max(counts, key=lambda label: (counts[label], order.get(label, 0)))


def aggregate_llm_judgments(judgments: list[dict[str, Any]], fallback: dict[str, Any]) -> dict[str, Any]:
    if not judgments:
        return dict(fallback, judge_source="heuristic_fallback")
    scores = [float(item.get("support_score", 0.0)) for item in judgments]
    conds = [float(item.get("condition_integrity", 0.0)) for item in judgments]
    labels = [str(item.get("support_label", "UNSUPPORTED")) for item in judgments]
    return {"support_label": majority_label(labels), "support_score": round(statistics.mean(scores), 4), "condition_integrity": round(statistics.mean(conds), 4), "mean_score": round(statistics.mean(scores), 4), "std_score": round(statistics.pstdev(scores), 4) if len(scores) > 1 else 0.0, "majority_label": majority_label(labels), "missing_elements": [item.get("missing_elements", {}) for item in judgments], "wrong_or_conflicting_elements": [item.get("wrong_or_conflicting_elements", []) for item in judgments], "reason": "Aggregated from LLM judges.", "judge_source": "llm", "per_model_judgments": judgments}


def load_cache_map(path: Path | None) -> dict[str, Path]:
    if not path:
        return {}
    data = read_yaml_or_json(path)
    mapping = data.get("caches", data)
    return {str(mode): Path(cache_path) for mode, cache_path in mapping.items()}


def load_run_config(cache_dir: Path) -> dict[str, Any]:
    path = cache_dir / "run_config.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def mode_view(mode: str, run_config: dict[str, Any]) -> str:
    if mode in {"graph", "naive", "hyper"}:
        return mode
    query_mode = str(run_config.get("query_mode") or "").lower()
    if query_mode in {"graph", "naive", "hyper"}:
        return query_mode
    if mode.startswith("graph"):
        return "graph"
    return "hyper"


def resolve_judge_configs(names: list[str], *, legacy_model: str | None, legacy_base_url: str | None, legacy_api_key: str | None, errors: list[dict[str, Any]]) -> list[dict[str, str | None]]:
    if legacy_model or legacy_api_key:
        if legacy_api_key and legacy_model:
            return [{"name": legacy_model, "model": legacy_model, "base_url": legacy_base_url, "api_key": legacy_api_key}]
        errors.append({"type": "judge_config", "message": "Legacy LLM judge requires both model and api key."})
        return []
    configs = []
    for name in names:
        alias = JUDGE_ALIASES.get(name)
        if not alias:
            errors.append({"type": "judge_config", "judge": name, "message": "Unknown judge alias."})
            continue
        api_key = os.getenv(alias["api_key_env"])
        if not api_key:
            errors.append({"type": "judge_config", "judge": name, "message": f"Missing {alias['api_key_env']}; skipped."})
            continue
        configs.append({"name": name, "model": os.getenv(alias["model_env"], alias["model"]), "base_url": os.getenv(alias["base_url_env"], alias["base_url"]), "api_key": api_key})
    return configs


def evaluate_pool(gold: list[dict[str, Any]], evidence: list[dict[str, Any]], k_values: list[int], *, mode_name: str, judge_mode: str, judge_configs: list[dict[str, str | None]], equivalences: dict[str, str], enable_hybrid_rerank: bool, verbose: bool, quiet: bool, log_file: Path | None, errors: list[dict[str, Any]], evidence_contexts: list[dict[str, Any]], raw_outputs: list[dict[str, Any]], llm_records: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    by_k: dict[str, Any] = {}
    archive_records: list[dict[str, Any]] = []
    for k in k_values:
        progress(f"[FactCoverage] mode={mode_name} k={k}: evaluating {len(gold)} facts", quiet=quiet, log_file=log_file)
        judgments = []
        budgets = []
        for index, fact in enumerate(gold, start=1):
            fact_id = fact.get("fact_id") or f"fact-{index}"
            if verbose:
                progress(f"[FactCoverage] mode={mode_name} k={k}: {index}/{len(gold)} {fact_id}", quiet=quiet, log_file=log_file)
            top = rank_evidence(fact.get("claim", ""), evidence, k, equivalences, enable_hybrid_rerank=enable_hybrid_rerank)
            budget = evidence_token_budget(top)
            budgets.append(budget)
            evidence_contexts.append({"mode": mode_name, "k": k, "fact_id": fact_id, "claim": fact.get("claim", ""), "evidence": top, "evidence_token_budget": budget})
            heuristic = judge_fact(fact, top, equivalences)
            per_model = []
            if judge_mode == "llm":
                for judge in judge_configs:
                    try:
                        judged = judge_fact_with_llm(fact, top, model=str(judge["model"]), base_url=judge.get("base_url"), api_key=str(judge["api_key"]))
                        judged["judge_name"] = judge["name"]
                        per_model.append(judged)
                        raw_outputs.append({"mode": mode_name, "k": k, "fact_id": fact_id, "judge": judge["name"], "model": judge["model"], "raw_response": judged.get("_raw_response")})
                    except Exception as exc:
                        errors.append({"type": "llm_judge", "mode": mode_name, "k": k, "fact_id": fact_id, "judge": judge.get("name"), "error": format_llm_error(exc)})
                judgment = aggregate_llm_judgments(per_model, heuristic)
            else:
                judgment = dict(heuristic, judge_source="heuristic")
            judgment.update({"fact_id": fact_id, "mode": mode_name, "k": k, "top_evidence_ids": [item["id"] for item in top]})
            judgments.append(judgment)
            archive_records.append({**judgment, "claim": fact.get("claim", ""), "top_evidence": top})
            for item in per_model:
                llm_records.append({**item, "fact_id": fact_id, "mode": mode_name, "k": k, "claim": fact.get("claim", ""), "top_evidence_ids": [ev["id"] for ev in top]})
        missing_counter = Counter()
        wrong_counter = Counter()
        label_counter = Counter(item.get("support_label") for item in judgments)
        for item in judgments:
            missing_counter.update(flatten_missing_for_counter(item.get("missing_elements")))
            wrong_counter.update(str(v) for v in item.get("wrong_or_conflicting_elements", []))
        avg_budget = statistics.mean(budgets) if budgets else 0.0
        soft_score = sum(float(item["support_score"]) for item in judgments) / max(1, len(judgments))
        by_k[str(k)] = {"strict_fact_coverage@k": round(label_counter["SUPPORTED"] / max(1, len(judgments)), 4), "soft_support_score@k": round(soft_score, 4), "condition_integrity@k": round(sum(float(item["condition_integrity"]) for item in judgments) / max(1, len(judgments)), 4), "evidence_token_budget@k": round(avg_budget, 2), "evidence_density@k": round(soft_score / max(1.0, avg_budget / 1000.0), 4), "supported_count": label_counter["SUPPORTED"], "partial_count": label_counter["PARTIALLY_SUPPORTED"], "unsupported_count": label_counter["UNSUPPORTED"], "missing_elements_top": missing_counter.most_common(20), "wrong_or_conflicting_elements_top": wrong_counter.most_common(20), "judgments": judgments}
        progress("[FactCoverage] mode=%s k=%s done: strict=%.4f soft=%.4f condition=%.4f" % (mode_name, k, by_k[str(k)]["strict_fact_coverage@k"], by_k[str(k)]["soft_support_score@k"], by_k[str(k)]["condition_integrity@k"]), quiet=quiet, log_file=log_file)
    return by_k, archive_records


def write_summary_files(summary_json: Path, summary_csv: Path, report: dict[str, Any]) -> None:
    rows = []
    for mode, by_k in report["modes"].items():
        for k, metrics in by_k.items():
            rows.append({"mode": mode, "k": k, "strict_fact_coverage@k": metrics["strict_fact_coverage@k"], "soft_support_score@k": metrics["soft_support_score@k"], "condition_integrity@k": metrics["condition_integrity@k"], "evidence_token_budget@k": metrics["evidence_token_budget@k"], "evidence_density@k": metrics["evidence_density@k"], "supported_count": metrics["supported_count"], "partial_count": metrics["partial_count"], "unsupported_count": metrics["unsupported_count"]})
    summary_json.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    fieldnames = ["mode", "k", "strict_fact_coverage@k", "soft_support_score@k", "condition_integrity@k", "evidence_token_budget@k", "evidence_density@k", "supported_count", "partial_count", "unsupported_count"]
    with summary_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def parse_k_values(args: argparse.Namespace) -> list[int]:
    if args.k_values:
        return [int(item) for item in args.k_values]
    return [int(item.strip()) for item in str(args.k).split(",") if item.strip()]


def make_output_paths(args: argparse.Namespace) -> dict[str, Path]:
    if args.output_dir:
        output_dir = args.output_dir.resolve()
    elif args.output:
        output_dir = args.output.parent.resolve()
    elif args.cache_dir:
        output_dir = args.cache_dir.resolve()
    else:
        run_id = datetime.now(timezone.utc).strftime("run_%Y%m%d_%H%M%S")
        output_dir = (REPO_ROOT / "outputs" / "fact_coverage" / run_id).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    return {"dir": output_dir, "report": (args.output or output_dir / "fact_coverage_report.json").resolve(), "run_config": output_dir / "run_config.json", "summary_csv": output_dir / "fact_coverage_summary.csv", "summary_json": output_dir / "fact_coverage_summary.json", "full_judgments": output_dir / "fact_coverage_full_judgments.json", "llm_judgments": output_dir / "fact_coverage_llm_judgments.jsonl", "heuristic": output_dir / "fact_coverage_heuristic_diagnostics.json", "evidence_contexts": output_dir / "evidence_contexts.jsonl", "raw_outputs": output_dir / "model_raw_outputs.jsonl", "errors": output_dir / "errors.jsonl", "log": output_dir / "run.log"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate Hyper-ChE Fact Coverage@k.")
    parser.add_argument("--gold", required=True, type=Path, help="Gold facts JSON path.")
    parser.add_argument("--cache-dir", type=Path, help="Legacy single HyperRAG cache database directory.")
    parser.add_argument("--modes", nargs="+", help="Experiment modes to evaluate.")
    parser.add_argument("--cache-map", type=Path, help="YAML/JSON mapping from mode to cache dir.")
    parser.add_argument("--k", default="1,3,5,10", help="Legacy comma-separated k values.")
    parser.add_argument("--k-values", nargs="+", type=int, help="New k values, e.g. --k-values 1 3 5 10.")
    parser.add_argument("--judge-mode", choices=["heuristic", "llm"], default="heuristic")
    parser.add_argument("--judge-model", choices=list(JUDGE_ALIASES), help="Single judge alias.")
    parser.add_argument("--judge-models", nargs="+", choices=list(JUDGE_ALIASES), help="Multiple judge aliases.")
    parser.add_argument("--llm-model", default=os.getenv("LLM_MODEL"))
    parser.add_argument("--llm-base-url", default=os.getenv("LLM_BASE_URL"))
    parser.add_argument("--llm-api-key", default=os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY"))
    parser.add_argument("--equivalence-map", type=Path, default=DEFAULT_EQUIVALENCE_MAP)
    parser.add_argument("--verbose", action="store_true", help="Print per-fact progress to stderr.")
    parser.add_argument("--quiet", action="store_true", help="Suppress progress output; stdout remains JSON summary.")
    parser.add_argument("--output", type=Path, help="Optional full JSON report output path.")
    parser.add_argument("--output-dir", type=Path, help="Output directory for the new experiment layout.")
    args = parser.parse_args()
    paths = make_output_paths(args)
    errors: list[dict[str, Any]] = []
    evidence_contexts: list[dict[str, Any]] = []
    raw_outputs: list[dict[str, Any]] = []
    llm_records: list[dict[str, Any]] = []
    all_records: list[dict[str, Any]] = []
    k_values = parse_k_values(args)
    paths["log"].write_text("", encoding="utf-8")
    progress(f"[FactCoverage] loading gold facts: {args.gold}", quiet=args.quiet, log_file=paths["log"])
    gold = load_gold(args.gold)
    equivalences = load_equivalence_map(args.equivalence_map)
    cache_map = load_cache_map(args.cache_map)
    if args.modes:
        modes_to_eval = args.modes
    elif args.cache_dir:
        modes_to_eval = ["hyper", "graph", "naive"]
        cache_map = {mode: args.cache_dir for mode in modes_to_eval}
    else:
        raise RuntimeError("Use either --cache-dir for legacy evaluation or --modes with --cache-map.")
    judge_names = args.judge_models or ([args.judge_model] if args.judge_model else ["deepseek"])
    judge_configs = resolve_judge_configs(judge_names, legacy_model=args.llm_model, legacy_base_url=args.llm_base_url, legacy_api_key=args.llm_api_key, errors=errors) if args.judge_mode == "llm" else []
    modes_report: dict[str, Any] = {}
    for mode_name in modes_to_eval:
        cache_dir = cache_map.get(mode_name)
        if not cache_dir:
            errors.append({"type": "cache_map", "mode": mode_name, "message": "No cache dir configured; skipped."})
            continue
        progress(f"[FactCoverage] loading cache for mode={mode_name}: {cache_dir}", quiet=args.quiet, log_file=paths["log"])
        graph, chunks = load_cache(cache_dir)
        run_config = load_run_config(cache_dir)
        view = mode_view(mode_name, run_config)
        enable_hybrid = bool(run_config.get("enable_hybrid_rerank", not mode_name.endswith("no_rerank")))
        evidence = evidence_from_chunks(chunks) if view == "naive" else evidence_from_graph(graph, view, equivalences)
        progress(f"[FactCoverage] mode={mode_name}: view={view}, evidence={len(evidence)}, hybrid_rerank={enable_hybrid}", quiet=args.quiet, log_file=paths["log"])
        by_k, records = evaluate_pool(gold, evidence, k_values, mode_name=mode_name, judge_mode=args.judge_mode, judge_configs=judge_configs, equivalences=equivalences, enable_hybrid_rerank=enable_hybrid, verbose=args.verbose, quiet=args.quiet, log_file=paths["log"], errors=errors, evidence_contexts=evidence_contexts, raw_outputs=raw_outputs, llm_records=llm_records)
        modes_report[mode_name] = by_k
        all_records.extend(records)
    actual_judge_mode = args.judge_mode
    if args.judge_mode == "llm" and not judge_configs:
        actual_judge_mode = "heuristic_fallback_no_llm_key"
    report = {"gold_file": str(args.gold), "cache_dir": str(args.cache_dir) if args.cache_dir else None, "cache_map": str(args.cache_map) if args.cache_map else None, "corpus_id": args.cache_dir.name if args.cache_dir else None, "k_values": k_values, "modes_requested": modes_to_eval, "judge_mode": args.judge_mode, "actual_judge_mode": actual_judge_mode, "llm_judge_enabled": args.judge_mode == "llm" and bool(judge_configs), "judge_models": [{"name": item["name"], "model": item["model"], "base_url": item.get("base_url")} for item in judge_configs], "equivalence_map": str(args.equivalence_map), "llm_archive_path": str(paths["llm_judgments"]), "heuristic_summary_path": str(paths["heuristic"]), "full_judgment_path": str(paths["full_judgments"]), "evidence_contexts_path": str(paths["evidence_contexts"]), "model_raw_outputs_path": str(paths["raw_outputs"]), "errors_path": str(paths["errors"]), "summary_csv_path": str(paths["summary_csv"]), "summary_json_path": str(paths["summary_json"]), "modes": modes_report}
    paths["report"].write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    paths["run_config"].write_text(json.dumps({k: v for k, v in report.items() if k != "modes"}, ensure_ascii=False, indent=2), encoding="utf-8")
    paths["full_judgments"].write_text(json.dumps(all_records, ensure_ascii=False, indent=2), encoding="utf-8")
    write_jsonl(paths["llm_judgments"], llm_records)
    paths["heuristic"].write_text(json.dumps(all_records if args.judge_mode == "heuristic" else [], ensure_ascii=False, indent=2), encoding="utf-8")
    write_jsonl(paths["evidence_contexts"], evidence_contexts)
    write_jsonl(paths["raw_outputs"], raw_outputs)
    write_jsonl(paths["errors"], errors)
    write_summary_files(paths["summary_json"], paths["summary_csv"], report)
    stdout_summary = {k: v for k, v in report.items() if k != "modes"}
    stdout_summary["mode_count"] = len(modes_report)
    stdout_summary["fact_count"] = len(gold)
    stdout_summary["output_dir"] = str(paths["dir"])
    print(json.dumps(stdout_summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
