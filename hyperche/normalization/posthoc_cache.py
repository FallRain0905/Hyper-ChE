"""Automatic, resumable post-hoc normalization for an extracted Hyper-RAG cache."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import itertools
import json
import logging
import os
import pickle
import re
import shutil
import time
import unicodedata
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from .alias_registry import AliasRegistry
from .text_normalizer import normalize_text, normalize_text_for_match

GRAPH_FILE = "hypergraph_chunk_entity_relation.hgdb"
PROMPT_VERSION = "posthoc-entity-pair-v2"
CLUSTER_PROMPT_VERSION = "posthoc-cluster-audit-v1"
NORMALIZATION_VERSION = "posthoc-v1"
CANDIDATE_VERSION = "posthoc-candidates-v2"
DECISIONS = {"SAME_ENTITY", "ALIAS", "VARIANT", "RELATED", "DIFFERENT", "UNCERTAIN"}
POSITIVE = {"SAME_ENTITY", "ALIAS"}
LOGGER = logging.getLogger("hyper_rag.posthoc_normalization")


def stable_hash(value: str, length: int = 12) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def json_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, ensure_ascii=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(tmp, path)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    result = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                result.append(json.loads(line))
            except json.JSONDecodeError:
                LOGGER.warning("Ignoring malformed JSONL line in %s", path)
    return result


def _deep_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _deep_strings(item)
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            yield from _deep_strings(item)


def extract_ids(value: Any, pattern: str) -> list[str]:
    seen = []
    rx = re.compile(pattern)
    for text in _deep_strings(value):
        for match in rx.findall(text):
            item = match if isinstance(match, str) else match[0]
            if item not in seen:
                seen.append(item)
    return seen


def _formula_key(text: str) -> str:
    value = normalize_text(text, lowercase=False).replace(" ", "")
    return re.sub(r"\s*([·.])\s*", "·", value).lower()


_CHEMICAL_ELEMENTS = frozenset(
    "H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn Ga Ge As Se Br Kr "
    "Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm "
    "Yb Lu Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi Po At Rn Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf Es Fm Md No Lr "
    "Rf Db Sg Bh Hs Mt Ds Rg Cn Nh Fl Mc Lv Ts Og".split()
)
_FORMULA_UNIT = r"(?:[A-Z][a-z]?\d*|\((?:[A-Z][a-z]?\d*)+\)\d*)"
_FORMULA_CANDIDATE_RE = re.compile(
    rf"(?<![A-Za-z0-9])(?:{_FORMULA_UNIT}){{2,}}(?:[·.]\d*(?:{_FORMULA_UNIT})+)*(?![A-Za-z])"
)
_ROMAN_NUMERALS = frozenset({"I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"})
_NO_DIGIT_FORMULA_ALLOWLIST = frozenset({
    "CO", "NO", "OH", "VO", "HCL", "HBR", "NACL", "KCL", "LICL", "LIF", "NAOH", "KOH", "LIOH",
    "AGCL", "AGBR", "KI", "NAI", "KBR", "NABR",
})
_ABBREVIATION_STOPWORDS = frozenset({"A", "AN", "THE", "AND", "OR", "OF", "FOR", "TO", "IN", "ON", "WITH", "BY"})


def _text_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, dict):
        return [str(item) for item in value.values() if item is not None and str(item).strip()]
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if item is not None and str(item).strip()]
    return [str(value)]


def _additional_property_map(value: Any) -> dict[str, list[str]]:
    """Parse structured additional_properties without treating free prose as identity signals."""
    result: dict[str, list[str]] = defaultdict(list)
    if isinstance(value, dict):
        for key, item in value.items():
            result[str(key).strip().lower()].extend(_text_values(item))
        return dict(result)
    for text in _text_values(value):
        for part in re.split(r"<SEP>|[;\r\n]+", text):
            if "=" not in part:
                continue
            key, item = part.split("=", 1)
            if key.strip() and item.strip():
                result[key.strip().lower()].append(item.strip())
    return dict(result)


def _structured_values(data: dict[str, Any], properties: dict[str, list[str]], *keys: str) -> list[str]:
    values: list[str] = []
    for key in keys:
        values.extend(_text_values(data.get(key)))
        values.extend(properties.get(key.lower(), []))
    return values


def _formula_candidate_is_valid(candidate: str) -> bool:
    compact = re.sub(r"[·.]", "", candidate)
    upper = compact.upper()
    if upper in _ROMAN_NUMERALS:
        return False
    if not any(char.isdigit() for char in compact) and upper not in _NO_DIGIT_FORMULA_ALLOWLIST:
        return False
    symbols = re.findall(r"[A-Z][a-z]?", candidate)
    return len(symbols) >= 2 and all(symbol in _CHEMICAL_ELEMENTS for symbol in symbols)


def _extract_formula_keys(text: str) -> list[str]:
    formulas: set[str] = set()
    normalized = normalize_text(text, lowercase=False)
    for match in _FORMULA_CANDIDATE_RE.finditer(normalized):
        candidate = match.group(0)
        if _formula_candidate_is_valid(candidate):
            formulas.add(_formula_key(candidate))
    return sorted(formulas)


def _extract_models(text: str) -> list[str]:
    """Extract concrete grades while rejecting compositions and generic family names."""
    pattern = re.compile(
        r"\b(?P<family>nafion|snpbi|speek|sptpc|gdl|aem|pem|pbi|carbon\s+felt|carbon\s+paper)"
        r"(?!\s*/)(?:\s*[-–—]\s*|\s*)(?P<grade>[A-Za-z]*\d+(?:\.\d+)?[A-Za-z0-9.-]*)\b",
        re.I,
    )
    models: set[str] = set()
    for match in pattern.finditer(text):
        family = re.sub(r"\s+", "", match.group("family")).lower()
        grade = match.group("grade")
        if family in {"carbonfelt", "carbonpaper"}:
            if not re.search(r"[A-Za-z]", grade) or _extract_formula_keys(grade):
                continue
        models.add(re.sub(r"[\s–—_/.-]+", "", match.group(0)).lower())
    return sorted(models)


def _extract_models_from_values(values: Iterable[str]) -> list[str]:
    return sorted({model for value in values for model in _extract_models(str(value))})


def _normalize_abbreviation(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "", value).upper()


def _initialism(name: str) -> str | None:
    text = unicodedata.normalize("NFKC", str(name or ""))
    text = re.sub(r"\([^)]*\)", " ", text)
    words = [word.lower() for word in re.findall(r"[A-Za-z]+", text)]
    words = [word for word in words if word.upper() not in _ABBREVIATION_STOPWORDS]
    if len(words) >= 3:
        value = "".join(word[0] for word in words).upper()
        return value if 3 <= len(value) <= 12 else None
    if len(words) == 2 and words[0].startswith("perfluoro"):
        remainder = words[0][len("perfluoro"):]
        value = "PF" + (remainder[:1].upper() if remainder else "") + words[1][:1].upper()
        return value if 3 <= len(value) <= 12 else None
    return None


def _explicit_abbreviation_tokens(name: str, extra_values: Iterable[str] = ()) -> list[str]:
    values: set[str] = set()
    for text in [str(name or ""), *(str(item) for item in extra_values)]:
        for candidate in re.findall(r"(?<![A-Za-z0-9])(?:[A-Z][A-Z0-9-]{2,11})(?![A-Za-z0-9])", text):
            normalized = _normalize_abbreviation(candidate)
            if normalized not in _ROMAN_NUMERALS and 3 <= len(normalized) <= 12 and not _extract_formula_keys(candidate):
                values.add(normalized)
    return sorted(values)


def _explicit_abbreviations(name: str, extra_values: Iterable[str] = ()) -> list[str]:
    values = set(_explicit_abbreviation_tokens(name, extra_values))
    generated = _initialism(name)
    if generated:
        values.add(generated)
    return sorted(values)


def _slug(text: str) -> str:
    value = normalize_text(str(text or ""), lowercase=True)
    value = re.sub(r"[^\w]+", "_", value, flags=re.UNICODE).strip("_")
    return value or "unnamed"


def _prefix(entity_type: str, semantic_group: str) -> str:
    value = (semantic_group or entity_type or "entity").lower()
    value = re.sub(r"[^a-z0-9]+", "_", value).strip("_")
    return value or "entity"


def _similarity(left: str, right: str) -> tuple[float, float, float]:
    try:
        from rapidfuzz import fuzz
        return float(fuzz.WRatio(left, right)), float(fuzz.token_set_ratio(left, right)), float(fuzz.ratio(left, right))
    except Exception:
        from difflib import SequenceMatcher
        score = SequenceMatcher(None, left, right).ratio() * 100.0
        return score, score, score


@dataclass
class EntityFeatures:
    node_id: str
    raw_name: str
    normalized_name: str
    entity_type: str
    semantic_group: str
    abbreviations: list[str]
    explicit_abbreviations: list[str]
    formulas: list[str]
    oxidation_states: list[str]
    charges: list[str]
    models: list[str]
    numeric_signals: list[str]
    metrics: list[str]
    phases: list[str]
    modifiers: list[str]
    documents: list[str]
    chunks: list[str]
    description: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def extract_features(node_id: str, data: dict[str, Any] | None = None) -> EntityFeatures:
    data = dict(data or {})
    name = str(data.get("entity_name") or data.get("name") or data.get("canonical_name") or node_id)
    description = str(data.get("description") or data.get("descriptions") or "")
    entity_type = str(data.get("entity_type") or data.get("type") or "UNKNOWN").upper()
    semantic_group = str(data.get("semantic_group") or data.get("semantic_type") or "").upper()
    properties = _additional_property_map(data.get("additional_properties"))
    formula_text = " ".join([name, *_structured_values(data, properties, "formula", "chemical_formula", "molecular_formula", "key_attribute")])
    oxidation_text = " ".join([name, *_structured_values(data, properties, "oxidation_state", "oxidation_states")])
    charge_text = " ".join([name, *_structured_values(data, properties, "charge", "ionic_charge")])
    model_values = [name, *_structured_values(data, properties, "model", "grade", "material_model", "membrane_model", "product_grade", "key_attribute")]
    identity_text = " ".join([name, *_structured_values(data, properties, "subtype", "phase", "state", "key_attribute")])
    condition_text = name
    if entity_type in {"CONDITION", "OPERATING_CONDITION", "PARAMETER", "METRIC", "PERFORMANCE_METRIC", "MEASUREMENT"}:
        value_parts = _structured_values(data, properties, "value", "value_min", "value_max", "unit", "temperature", "concentration", "current_density", "cycle_count", "cycles", "duration")
        condition_text = " ".join([name, " ".join(value_parts)])
    abbreviation_values = _structured_values(data, properties, "abbreviation", "abbreviations", "acronym", "acronyms")
    formulas = _extract_formula_keys(formula_text)
    oxidation = sorted({x.upper().replace(" ", "") for x in re.findall(r"(?<!\w)[A-Z][a-z]?\s*\((?:II|III|IV|V|VI|VII|VIII|[0-9]+)\)(?!\w)|(?<!\w)[A-Z][a-z]?\s*[0-9]+[+-](?!\w)", oxidation_text)})
    charges = sorted({x.replace(" ", "") for x in re.findall(r"(?:\^?\s*[0-9]+\s*[+-]|[0-9]+[+-])", charge_text)})
    models = _extract_models_from_values(model_values)
    numeric = sorted({x.lower().replace(" ", "") for x in re.findall(r"\b\d+(?:\.\d+)?\s*(?:°?c|degc|mol\s*/\s*l|mmol\s*/\s*l|m[aA]\s*/\s*cm\^?2|%|cycles?|h|hours?|mV|V)\b", condition_text, re.I)})
    metrics = []
    for pattern, label in ((r"(?<![a-z])ce(?![a-z])|coulombic efficiency", "CE"), (r"(?<![a-z])ve(?![a-z])|voltage efficiency", "VE"), (r"(?<![a-z])ee(?![a-z])|energy efficiency", "EE"), (r"capacity retention", "CAPACITY_RETENTION"), (r"resistance", "RESISTANCE")):
        if re.search(pattern, identity_text, re.I):
            metrics.append(label)
    phases = sorted({x.lower() for x in re.findall(r"\b(?:aqueous|solid|liquid|gas|gaseous|membrane|electrolyte|catholyte|anolyte|solution|powder|film)\b", identity_text, re.I)})
    modifiers = sorted({x.lower() for x in re.findall(r"\b(?:modified|composite|doped|coated|functionalized|loaded|supported|decorated|substituted|crosslinked|reinforced|pristine|base|acid-treated)\b", identity_text, re.I)})
    return EntityFeatures(
        node_id=str(node_id), raw_name=name, normalized_name=normalize_text_for_match(name), entity_type=entity_type,
        semantic_group=semantic_group, abbreviations=_explicit_abbreviations(name, abbreviation_values),
        explicit_abbreviations=_explicit_abbreviation_tokens(name, abbreviation_values), formulas=formulas,
        oxidation_states=oxidation, charges=charges, models=models, numeric_signals=numeric, metrics=sorted(set(metrics)),
        phases=phases, modifiers=modifiers, documents=extract_ids(data, r"RFB_\d{3}"),
        chunks=extract_ids(data, r"RFB_\d{3}_CHK_\d{3}"), description=description,
    )


def load_graph(cache: Path) -> dict[str, Any]:
    path = cache / GRAPH_FILE
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open("rb") as stream:
        graph = pickle.load(stream)
    if isinstance(graph, dict):
        return {"v_data": graph.get("v_data") or {}, "v_inci": graph.get("v_inci") or {}, "e_data": graph.get("e_data") or {}}
    return {"v_data": getattr(graph, "v_data", getattr(graph, "_v_data", {})), "v_inci": getattr(graph, "v_inci", getattr(graph, "_v_inci", {})), "e_data": getattr(graph, "e_data", getattr(graph, "_e_data", {}))}


def edge_records(graph: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for vertices, data in (graph.get("e_data") or {}).items():
        ids = [str(v) for v in vertices] if isinstance(vertices, (tuple, list, set)) else [str(vertices)]
        result.append({"vertices": ids, "data": dict(data or {})})
    return result


def load_chunks(cache: Path) -> dict[str, Any]:
    path = cache / "kv_store_text_chunks.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def chunk_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("content", "text", "chunk", "full_text"):
            if value.get(key):
                return str(value[key])
    return " ".join(_deep_strings(value))


def chunk_doc_id(chunk_id: str, value: Any) -> str:
    found = extract_ids(value, r"RFB_\d{3}")
    return found[0] if found else (chunk_id.split("_CHK_")[0] if "_CHK_" in chunk_id else "")


def build_context_index(graph: dict[str, Any], chunks: dict[str, Any]) -> tuple[dict[str, EntityFeatures], dict[str, list[str]], dict[str, str]]:
    records = {str(k): dict(v or {}) for k, v in (graph.get("v_data") or {}).items()}
    chunk_refs: dict[str, set[str]] = defaultdict(set)
    doc_refs: dict[str, set[str]] = defaultdict(set)
    for node, data in records.items():
        chunk_refs[node].update(extract_ids(data, r"RFB_\d{3}_CHK_\d{3}"))
        doc_refs[node].update(extract_ids(data, r"RFB_\d{3}"))
    for edge in edge_records(graph):
        ids = extract_ids(edge["data"], r"RFB_\d{3}_CHK_\d{3}")
        docs = extract_ids(edge["data"], r"RFB_\d{3}")
        for node in edge["vertices"]:
            records.setdefault(node, {})
            chunk_refs[node].update(ids)
            doc_refs[node].update(docs)
    for node, item in records.items():
        all_chunks = sorted(chunk_refs[node])
        all_docs = sorted(doc_refs[node] | {value.split("_CHK_")[0] for value in all_chunks})
        if all_chunks:
            item["source_chunk_ids"] = all_chunks
            item["source_chunk_id"] = "<SEP>".join(all_chunks)
        if all_docs:
            item["source_document_ids"] = all_docs
            item["source_doc_id"] = "<SEP>".join(all_docs)
    features = {node: extract_features(node, data) for node, data in records.items()}
    by_doc: dict[str, list[str]] = defaultdict(list)
    texts: dict[str, str] = {}
    for cid, value in chunks.items():
        cid = str(cid)
        texts[cid] = chunk_text(value)
        by_doc[chunk_doc_id(cid, value)].append(cid)
    for values in by_doc.values():
        values.sort()
    return features, by_doc, texts

def _load_vectors(path: Path) -> tuple[list[dict[str, Any]], np.ndarray] | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw = payload.get("matrix")
    if not isinstance(raw, str):
        return None
    matrix = np.frombuffer(base64.b64decode(raw), dtype=np.float32).reshape(-1, int(payload["embedding_dim"]))
    return list(payload.get("data") or []), matrix


def _type_compatible(left: EntityFeatures, right: EntityFeatures) -> bool:
    if left.entity_type == right.entity_type:
        return True
    groups = (
        {"MATERIAL", "CHEMICAL", "CHEMICAL_COMPOUND", "ACTIVE_SPECIES", "SPECIES", "MEMBRANE", "POLYMER", "ELECTRODE", "CATALYST", "ELECTROLYTE"},
        {"CONCEPT", "SYSTEM", "TECHNOLOGY"},
        {"METRIC", "PERFORMANCE_METRIC"},
        {"CONDITION", "OPERATING_CONDITION", "PARAMETER"},
        {"DEVICE", "EQUIPMENT", "COMPONENT"},
    )
    return any(left.entity_type in group and right.entity_type in group for group in groups)


def risk_filter(
    left: EntityFeatures,
    right: EntityFeatures,
    negative_pairs: set[tuple[str, str]] | None = None,
) -> tuple[str | None, str | None]:
    if not _type_compatible(left, right):
        return "DIFFERENT", f"incompatible entity types: {left.entity_type} vs {right.entity_type}"
    if left.formulas and right.formulas and set(left.formulas).isdisjoint(right.formulas):
        return "VARIANT", f"chemical formula conflict: {left.formulas} vs {right.formulas}"
    if left.oxidation_states and right.oxidation_states and set(left.oxidation_states).isdisjoint(right.oxidation_states):
        return "VARIANT", f"oxidation-state conflict: {left.oxidation_states} vs {right.oxidation_states}"
    if left.charges and right.charges and set(left.charges).isdisjoint(right.charges):
        return "VARIANT", f"charge conflict: {left.charges} vs {right.charges}"
    if left.models and right.models and set(left.models).isdisjoint(right.models):
        return "VARIANT", f"model/grade conflict: {left.models} vs {right.models}"
    if left.numeric_signals and right.numeric_signals and set(left.numeric_signals).isdisjoint(right.numeric_signals):
        return "VARIANT", f"numeric condition conflict: {left.numeric_signals} vs {right.numeric_signals}"
    if left.metrics and right.metrics and set(left.metrics).isdisjoint(right.metrics):
        return "DIFFERENT", f"performance metric conflict: {left.metrics} vs {right.metrics}"
    if left.phases and right.phases and set(left.phases).isdisjoint(right.phases):
        return "VARIANT", f"phase/state conflict: {left.phases} vs {right.phases}"
    structural_modifiers = {"modified", "composite", "doped", "coated", "functionalized", "loaded", "supported", "decorated", "substituted", "crosslinked", "reinforced"}
    left_modifiers = set(left.modifiers) & structural_modifiers
    right_modifiers = set(right.modifiers) & structural_modifiers
    if left_modifiers != right_modifiers and (left_modifiers or right_modifiers):
        return "VARIANT", f"base/modified/composite conflict: {sorted(left_modifiers)} vs {sorted(right_modifiers)}"
    if negative_pairs and tuple(sorted((left.normalized_name, right.normalized_name))) in negative_pairs:
        return "DIFFERENT", "blocked by configured negative/high-risk normalization rule"
    return None, None


def _registry_terms(registry: AliasRegistry, value: str) -> set[str]:
    entity = registry.entities.get(str(value))
    if entity:
        return set(entity.match_strings)
    return {normalize_text_for_match(value)}


def load_negative_pairs(paths: Iterable[Path], registry: AliasRegistry | None = None) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    registry = registry or AliasRegistry()
    try:
        import yaml
    except Exception:
        return pairs
    for path in paths:
        path = Path(path)
        if not path.exists():
            continue
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for item in raw.get("negative_pairs", raw.get("pairs", [])):
            if not isinstance(item, dict) or not item.get("left") or not item.get("right"):
                continue
            for left in _registry_terms(registry, str(item["left"])):
                for right in _registry_terms(registry, str(item["right"])):
                    pairs.add(tuple(sorted((left, right))))
        for group in raw.get("high_risk_groups", []):
            ids = group.get("canonical_ids", []) if isinstance(group, dict) else group
            for left_id, right_id in itertools.combinations([str(item) for item in ids], 2):
                for left in _registry_terms(registry, left_id):
                    for right in _registry_terms(registry, right_id):
                        pairs.add(tuple(sorted((left, right))))
    return pairs

def _pair_id(left: str, right: str) -> str:
    a, b = sorted((str(left), str(right)))
    return "pair-" + stable_hash(a + "\0" + b, 20)


def _add_candidate(store: dict[str, dict[str, Any]], left: EntityFeatures, right: EntityFeatures, reason: str, scores: dict[str, float] | None = None) -> None:
    if left.node_id == right.node_id:
        return
    a, b = (left, right) if left.node_id < right.node_id else (right, left)
    key = _pair_id(a.node_id, b.node_id)
    row = store.setdefault(key, {"pair_id": key, "left_id": a.node_id, "right_id": b.node_id, "candidate_reasons": [], "scores": {}})
    if reason not in row["candidate_reasons"]:
        row["candidate_reasons"].append(reason)
    for name, value in (scores or {}).items():
        row["scores"][name] = max(float(value), float(row["scores"].get(name, 0.0)))


def _candidate_score(row: dict[str, Any]) -> float:
    scores = row.get("scores") or {}
    return max(
        float(scores.get("cosine") or 0.0) * 100.0,
        float(scores.get("wratio") or 0.0),
        float(scores.get("token_set_ratio") or 0.0),
        float(scores.get("ratio") or 0.0),
        float(scores.get("context_jaccard") or 0.0) * 100.0,
    )


def _truncate_candidates(store: dict[str, dict[str, Any]], top_k: int) -> list[dict[str, Any]]:
    exempt_reasons = {"normalized_exact", "alias_registry", "formula_match"}
    exempt = [row for row in store.values() if exempt_reasons.intersection(row.get("candidate_reasons") or [])]
    exempt_pair_ids = {str(row["pair_id"]) for row in exempt}
    ranked = [row for row in store.values() if str(row["pair_id"]) not in exempt_pair_ids]
    ranked.sort(key=lambda row: (-_candidate_score(row), str(row["pair_id"])))
    degree: Counter[str] = Counter()
    selected = list(exempt)
    for row in ranked:
        left, right = str(row["left_id"]), str(row["right_id"])
        if top_k <= 0 or degree[left] >= top_k or degree[right] >= top_k:
            continue
        selected.append(row)
        degree[left] += 1
        degree[right] += 1
    return selected


def _simhash_codes(norms: np.ndarray, projection: np.ndarray) -> np.ndarray:
    """Return stable integer SimHash codes for every vector row."""
    bit_count = int(projection.shape[0])
    if bit_count > 16:
        raise ValueError("SimHash code uses uint16 and supports at most 16 bits")
    bits = (norms @ projection.T) >= 0
    bit_weights = (1 << np.arange(bit_count, dtype=np.uint16))
    return (bits.astype(np.uint16) * bit_weights).sum(axis=1, dtype=np.uint16)


def generate_candidates(
    cache: Path,
    *,
    top_k: int = 8,
    registry_paths: Iterable[Path] = (),
    negative_paths: Iterable[Path] = (),
) -> list[dict[str, Any]]:
    graph = load_graph(cache)
    chunks = load_chunks(cache)
    features, _, _ = build_context_index(graph, chunks)
    ordered = [features[key] for key in sorted(features)]
    LOGGER.info("candidate generation: loaded %d graph vertices and %d chunks", len(ordered), len(chunks))
    store: dict[str, dict[str, Any]] = {}
    registry = AliasRegistry.from_yaml_files(registry_paths) if registry_paths else AliasRegistry()
    negative_pairs = load_negative_pairs(negative_paths, registry)
    by_norm: dict[tuple[str, str], list[EntityFeatures]] = defaultdict(list)
    by_formula: dict[tuple[str, str], list[EntityFeatures]] = defaultdict(list)
    by_abbreviation: dict[str, list[EntityFeatures]] = defaultdict(list)
    by_bucket: dict[tuple[str, str, str], list[EntityFeatures]] = defaultdict(list)
    for item in ordered:
        by_norm[(item.entity_type, item.normalized_name)].append(item)
        for formula in item.formulas:
            by_formula[(item.entity_type, formula)].append(item)
        for abbreviation in item.abbreviations:
            by_abbreviation[abbreviation].append(item)
        by_bucket[(item.entity_type, item.semantic_group, item.normalized_name[:4])].append(item)

    alias_groups: dict[str, list[EntityFeatures]] = defaultdict(list)
    for item in ordered:
        match = registry.match_exact(item.raw_name, item.entity_type)
        if match:
            alias_groups[match.canonical_id].append(item)
    for values in by_norm.values():
        for left, right in itertools.combinations(values, 2):
            _add_candidate(store, left, right, "normalized_exact")
    for values in alias_groups.values():
        for left, right in itertools.combinations(values, 2):
            _add_candidate(store, left, right, "alias_registry")
    for values in by_formula.values():
        for left, right in itertools.combinations(values, 2):
            _add_candidate(store, left, right, "formula_match")
    for values in by_abbreviation.values():
        if len(values) > 100:
            continue
        for left, right in itertools.combinations(values, 2):
            shared = set(left.abbreviations) & set(right.abbreviations)
            anchored = any(
                abbreviation in left.explicit_abbreviations or abbreviation in right.explicit_abbreviations
                for abbreviation in shared
            )
            if anchored and _type_compatible(left, right):
                _add_candidate(store, left, right, "abbreviation_match")
    LOGGER.info("candidate generation: %d seed pairs after exact/registry/formula/abbreviation", len(store))

    for values in by_bucket.values():
        if len(values) > 200:
            continue
        for left, right in itertools.combinations(values, 2):
            wr, ts, ratio = _similarity(left.normalized_name, right.normalized_name)
            if wr >= 88 or ts >= 90:
                _add_candidate(store, left, right, "lexical_similarity", {"wratio": wr, "token_set_ratio": ts, "ratio": ratio})
    LOGGER.info("candidate generation: %d pairs after lexical similarity", len(store))

    context_signatures: dict[str, set[str]] = defaultdict(set)
    for edge in edge_records(graph):
        relation_values = _value_list(edge["data"].get("relation_type")) + _value_list(edge["data"].get("relation_types"))
        relation_tokens = {"rel:" + normalize_text_for_match(value) for value in relation_values if str(value).strip()}
        for node in edge["vertices"]:
            context_signatures[node].update(relation_tokens)
            for other in edge["vertices"]:
                if other != node and other in features:
                    context_signatures[node].add("nbr:" + features[other].normalized_name)
    inverted_context: dict[tuple[str, str], list[str]] = defaultdict(list)
    for node, tokens in context_signatures.items():
        for token in tokens:
            inverted_context[(features[node].entity_type, token)].append(node)
    context_pairs: set[tuple[str, str]] = set()
    for values in inverted_context.values():
        if len(values) > 100:
            continue
        context_pairs.update(tuple(sorted(pair)) for pair in itertools.combinations(sorted(set(values)), 2))
    for left_id, right_id in context_pairs:
        left_tokens, right_tokens = context_signatures[left_id], context_signatures[right_id]
        union = left_tokens | right_tokens
        overlap = len(left_tokens & right_tokens) / len(union) if union else 0.0
        if overlap >= 0.60 and len(left_tokens & right_tokens) >= 2:
            _add_candidate(store, features[left_id], features[right_id], "context_overlap", {"context_jaccard": overlap})
    LOGGER.info("candidate generation: %d pairs after context overlap", len(store))

    vector_info = _load_vectors(cache / "vdb_entities.json")
    if vector_info:
        rows, matrix = vector_info
        if len(rows) == len(matrix) and len(matrix):
            norms = matrix / np.maximum(np.linalg.norm(matrix, axis=1, keepdims=True), 1e-12)
            exact_lookup: dict[str, EntityFeatures] = {}
            normalized_lookup: dict[str, list[EntityFeatures]] = defaultdict(list)
            for item in ordered:
                exact_lookup[item.node_id] = item
                exact_lookup[item.raw_name] = item
                normalized_lookup[item.normalized_name].append(item)
            row_feature: dict[int, EntityFeatures] = {}
            for index, row in enumerate(rows):
                matched = None
                for key in (row.get("entity_name"), row.get("canonical_id"), row.get("raw_name")):
                    if key is None:
                        continue
                    matched = exact_lookup.get(str(key))
                    if matched is None:
                        candidates = normalized_lookup.get(normalize_text_for_match(str(key))) or []
                        if len(candidates) == 1:
                            matched = candidates[0]
                    if matched is not None:
                        break
                if matched is not None:
                    row_feature[index] = matched
            rng = np.random.default_rng(20260811)
            projections = rng.standard_normal((12, 12, matrix.shape[1]), dtype=np.float32)
            tables: list[dict[int, list[int]]] = []
            codes_by_table: list[np.ndarray] = []
            for table_index, projection in enumerate(projections, start=1):
                codes = _simhash_codes(norms, projection)
                table: dict[int, list[int]] = defaultdict(list)
                for index, code in enumerate(codes):
                    table[int(code)].append(index)
                tables.append(table)
                codes_by_table.append(codes)
                LOGGER.info("candidate generation: built LSH table %d/%d", table_index, len(projections))
            scanned = 0
            total_mapped_rows = len(row_feature)
            for index, left in row_feature.items():
                nearby: set[int] = set()
                for table_index, codes in enumerate(codes_by_table):
                    code = int(codes[index])
                    nearby.update(tables[table_index].get(code, []))
                    for bit_index in range(12):
                        nearby.update(tables[table_index].get(code ^ (1 << bit_index), []))
                other_indices = [
                    other_index
                    for other_index in nearby
                    if other_index > index
                    and other_index in row_feature
                    and row_feature[other_index].node_id != left.node_id
                    and _type_compatible(left, row_feature[other_index])
                ]
                if other_indices:
                    cosine_values = norms[other_indices] @ norms[index]
                    for other_index, cosine_value in zip(other_indices, cosine_values):
                        cosine = float(cosine_value)
                        if cosine < 0.78:
                            continue
                        right = row_feature[other_index]
                        wr, ts, ratio = _similarity(left.normalized_name, right.normalized_name)
                        if cosine >= 0.82 or max(wr, ts) >= 85:
                            _add_candidate(
                                store,
                                left,
                                right,
                                "vector_lsh",
                                {"cosine": cosine, "wratio": wr, "token_set_ratio": ts, "ratio": ratio},
                            )
                scanned += 1
                if scanned % 1000 == 0 or scanned == total_mapped_rows:
                    LOGGER.info(
                        "candidate generation: LSH scan %d/%d mapped vector rows; %d pairs accumulated",
                        scanned,
                        total_mapped_rows,
                        len(store),
                    )

    result = []
    selected = sorted(_truncate_candidates(store, top_k), key=lambda item: item["pair_id"])
    LOGGER.info("candidate generation: selected %d pairs before risk filtering", len(selected))
    blocked = 0
    for row in selected:
        left, right = features[row["left_id"]], features[row["right_id"]]
        rule_decision, rule_reason = risk_filter(left, right, negative_pairs)
        row["left_features"] = left.to_dict()
        row["right_features"] = right.to_dict()
        row["rule_decision"] = rule_decision
        row["rule_reasons"] = [rule_reason] if rule_reason else []
        if rule_decision in {"DIFFERENT", "VARIANT"}:
            blocked += 1
        result.append(row)
    LOGGER.info("candidate generation: completed with %d pairs; %d rule-blocked", len(result), blocked)
    return result

def _split_keys(value: str | None) -> list[str]:
    return [part.strip() for part in re.split(r"[;,\r\n]+", value or "") if part.strip()]


def _api_keys(kind: str) -> list[str]:
    for name in (f"{kind}_API_KEY", f"{kind}_API_KEYS"):
        values = _split_keys(os.getenv(name))
        if values:
            return values
    return []


class AsyncKeyPool:
    """Concurrency-safe strict round-robin API-key pool."""

    def __init__(self, keys: Iterable[str], *, name: str):
        self.keys = [str(key).strip() for key in keys if str(key).strip()]
        if not self.keys:
            raise ValueError(f"{name} key pool is empty")
        self.name = name
        self.index = 0
        self.lock = asyncio.Lock()

    @property
    def size(self) -> int:
        return len(self.keys)

    async def next(self) -> str:
        async with self.lock:
            key = self.keys[self.index % len(self.keys)]
            self.index += 1
            return key


@dataclass(frozen=True)
class LLMEndpoint:
    """One OpenAI-compatible endpoint and its key.

    The judge can use several providers in one resumable pass.  Keeping the
    URL paired with the key prevents a key from being sent to the wrong
    provider when the pool rotates across endpoints.
    """

    base_url: str
    api_key: str


class AsyncLLMEndpointPool:
    """Concurrency-safe round-robin pool of provider/key pairs."""

    def __init__(self, endpoints: Iterable[LLMEndpoint], *, name: str):
        self.endpoints = [
            endpoint
            for endpoint in endpoints
            if str(endpoint.base_url).strip() and str(endpoint.api_key).strip()
        ]
        if not self.endpoints:
            raise ValueError(f"{name} endpoint pool is empty")
        self.name = name
        self.index = 0
        self.lock = asyncio.Lock()

    @property
    def size(self) -> int:
        return len(self.endpoints)

    async def next(self) -> LLMEndpoint:
        async with self.lock:
            endpoint = self.endpoints[self.index % len(self.endpoints)]
            self.index += 1
            return endpoint


def _latest_records(
    path: Path,
    key: str,
    *,
    successful_statuses: set[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Keep an earlier success authoritative over a later failed retry."""
    records: dict[str, dict[str, Any]] = {}
    for row in read_jsonl(path):
        value = row.get(key)
        if value:
            record_key = str(value)
            previous = records.get(record_key)
            if previous is not None and successful_statuses:
                previous_ok = str(previous.get("status") or "") in successful_statuses
                current_ok = str(row.get("status") or "") in successful_statuses
                if previous_ok and not current_ok:
                    continue
            records[record_key] = row
    return records


def _parse_json_response(text: str) -> dict[str, Any]:
    value = str(text or "").strip()
    fence = chr(96) * 3
    value = value.replace(fence + "json", "").replace(fence, "").strip()
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        # Some chat models wrap the requested object in reasoning text. Scan
        # for complete JSON objects rather than slicing from the first opening
        # brace to the last closing brace, which can join unrelated fragments.
        decoder = json.JSONDecoder()
        candidates: list[dict[str, Any]] = []
        for index, character in enumerate(value):
            if character != "{":
                continue
            try:
                candidate, _ = decoder.raw_decode(value[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(candidate, dict):
                candidates.append(candidate)
        parsed = next(
            (
                candidate
                for candidate in reversed(candidates)
                if {"decision", "confidence", "reason"}.issubset(candidate)
            ),
            candidates[-1] if candidates else None,
        )
        if parsed is None:
            raise ValueError("LLM response does not contain a JSON object")
    if not isinstance(parsed, dict):
        raise ValueError("LLM response must be a JSON object")
    return parsed


def _is_retryable_judge_exception(exc: BaseException) -> bool:
    """Retry only transport failures and timeouts for pair judgements."""
    name = type(exc).__name__.lower()
    message = str(exc).lower()
    if "timeout" in name or "timeout" in message:
        return True
    if "connection" in name or "connection" in message:
        return True
    # openai_complete_if_cache wraps retryable provider exceptions in
    # tenacity.RetryError after exhausting its inner attempt.
    if name == "retryerror" and any(token in message for token in ("api", "connect", "timeout", "tempor")):
        return True
    return False


def _pair_context_hash(pair: dict[str, Any]) -> str:
    """Stable lightweight hash for resumable judgement keys.

    The full prompt is built once inside the worker.  Hashing that prompt
    during candidate scheduling caused every pending pair to be serialized a
    second time before any API request could start.
    """
    return json_hash({
        "pair_id": str(pair["pair_id"]),
        "prompt_version": PROMPT_VERSION,
        "context_schema": "pair-context-v2",
    })


SYSTEM_PROMPT = """You are a conservative chemical-knowledge entity normalization judge.
Compare entity A and entity B using only the supplied metadata and evidence.
Return JSON only with fields: decision, canonical_name, preferred_name_source, confidence, reason, evidence_chunk_ids.
Decision must be one of SAME_ENTITY, ALIAS, VARIANT, RELATED, DIFFERENT, UNCERTAIN.
preferred_name_source must be exactly one of A, B, NEW, NONE. A means the canonical
name is selected from Entity A; B means it is selected from Entity B; NEW means you
choose a new canonical name; NONE is required for DIFFERENT, RELATED, and UNCERTAIN.
Never put an entity name, document ID, chunk ID, "inferred", or a descriptive phrase
in preferred_name_source. evidence_chunk_ids must copy IDs from the supplied Evidence
IDs exactly; never invent or paraphrase an ID.
Use SAME_ENTITY only when the two mentions denote the same chemical object or concept.
Use ALIAS for abbreviation, spelling, notation, or naming variants of the same object.
Use VARIANT when composition, oxidation state, charge, grade, model, condition, modification, or performance metric differs.
Use RELATED when they are connected but not identical. Use DIFFERENT for distinct objects. Use UNCERTAIN when evidence is insufficient.
Never merge a base material with a composite or modified material, a generic category with a specific grade, or different metrics or conditions.
confidence must be a number in [0,1]. reason must be non-empty and evidence_chunk_ids must cite only supplied chunk IDs."""


def _stable_context_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _stable_context_value(item)
            for key, item in sorted(value.items(), key=lambda entry: str(entry[0]))
        }
    if isinstance(value, (set, frozenset)):
        items = [_stable_context_value(item) for item in value]
        return sorted(
            items,
            key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True, default=str),
        )
    if isinstance(value, (list, tuple)):
        return [_stable_context_value(item) for item in value]
    return value


def _edge_context(graph: dict[str, Any], node_id: str) -> list[dict[str, Any]]:
    incidence = graph.get("v_inci") or {}
    edge_data = graph.get("e_data") or {}
    referenced = incidence.get(node_id) or incidence.get(str(node_id))
    if referenced:
        result = []
        for edge_key in referenced:
            lookup_keys: list[Any] = [edge_key]
            if isinstance(edge_key, (list, tuple, set, frozenset)):
                lookup_keys.extend((tuple(edge_key), frozenset(edge_key)))
                vertices = sorted({str(item) for item in edge_key})
            else:
                vertices = [str(edge_key)]
            data: Any = {}
            for lookup_key in lookup_keys:
                try:
                    if lookup_key in edge_data:
                        data = edge_data[lookup_key]
                        break
                except TypeError:
                    continue
            result.append({"vertices": vertices, "data": _stable_context_value(dict(data or {}))})
    else:
        result = [
            {
                "vertices": sorted({str(item) for item in edge.get("vertices") or []}),
                "data": _stable_context_value(dict(edge.get("data") or {})),
            }
            for edge in edge_records(graph)
            if node_id in edge["vertices"]
        ]
    result.sort(
        key=lambda edge: (
            tuple(edge["vertices"]),
            json.dumps(edge["data"], ensure_ascii=False, sort_keys=True, default=str),
        )
    )
    return result


def _document_title(value: Any) -> str:
    text = chunk_text(value)
    for line in text.splitlines():
        cleaned = line.strip().lstrip("#").strip()
        if cleaned:
            return cleaned[:300]
    return ""


def _representative_chunks(feature: dict[str, Any], chunks: dict[str, Any], max_chunks: int) -> list[str]:
    raw_name = str(feature.get("raw_name") or "").casefold()
    available = [str(item) for item in feature.get("chunks") or [] if str(item) in chunks]
    available = list(dict.fromkeys(available))
    available.sort(key=lambda chunk_id: (raw_name not in chunk_text(chunks[chunk_id]).casefold(), chunk_id))
    return available[:max_chunks]


def _context_for_pair(
    pair: dict[str, Any],
    graph: dict[str, Any],
    chunks: dict[str, Any],
    docs: dict[str, Any] | None = None,
    *,
    max_chunks: int = 3,
) -> tuple[str, list[str]]:
    docs = docs or {}
    sections: list[str] = []
    supplied: list[str] = []
    newline = chr(10)
    for label, feat in (("A", pair["left_features"]), ("B", pair["right_features"])):
        documents = sorted({str(item) for item in feat.get("documents") or []})
        stable_signals = {
            name: sorted({str(item) for item in feat.get(name) or []})
            for name in (
                "formulas", "oxidation_states", "charges", "models",
                "numeric_signals", "metrics", "phases", "modifiers",
            )
        }
        sections.append(newline.join((
            f"Entity {label}: {feat['raw_name']}",
            f"Type: {feat['entity_type']}",
            f"Description: {feat.get('description', '')}",
            f"Source documents: {documents}",
            "Protected signals: "
            f"formulas={stable_signals['formulas']}; oxidation={stable_signals['oxidation_states']}; "
            f"charges={stable_signals['charges']}; models={stable_signals['models']}; "
            f"numeric={stable_signals['numeric_signals']}; metrics={stable_signals['metrics']}; "
            f"phases={stable_signals['phases']}; modifiers={stable_signals['modifiers']}",
        )))
        for doc_id in documents[:3]:
            if doc_id in docs:
                sections.append(f"Document {doc_id} title: {_document_title(docs[doc_id])}")
        for chunk_id in _representative_chunks(feat, chunks, max_chunks):
            if chunk_id not in supplied:
                supplied.append(chunk_id)
            sections.append(f"Evidence {chunk_id}: {chunk_text(chunks[chunk_id])[:5000]}")

    adjacent: dict[str, set[str]] = {}
    for label, node_id in (("A", pair["left_id"]), ("B", pair["right_id"])):
        names: set[str] = set()
        for edge in _edge_context(graph, node_id)[:12]:
            other = sorted(vertex for vertex in edge["vertices"] if vertex not in {pair["left_id"], pair["right_id"]})
            names.update(other)
            sections.append(
                f"{label} adjacent relation vertices={other}; "
                f"relation_data={json.dumps(edge['data'], ensure_ascii=False, sort_keys=True, default=str)[:1800]}"
            )
        adjacent[label] = names
    sections.append(f"Common adjacent vertices: {sorted(adjacent.get('A', set()) & adjacent.get('B', set()))[:30]}")
    sections.append(f"A-only adjacent vertices: {sorted(adjacent.get('A', set()) - adjacent.get('B', set()))[:30]}")
    sections.append(f"B-only adjacent vertices: {sorted(adjacent.get('B', set()) - adjacent.get('A', set()))[:30]}")
    prompt = "Compare the following candidate pair. Cite evidence_chunk_ids from the supplied evidence only." + newline * 2 + (newline * 2).join(sections)
    return prompt, supplied

async def _heartbeat(stop: asyncio.Event, label: str) -> None:
    started = time.monotonic()
    while not stop.is_set():
        await asyncio.sleep(60)
        if not stop.is_set():
            LOGGER.info("[%s] still waiting after %.2fs", label, time.monotonic() - started)


def _normalize_preferred_name_source(value: Any) -> str:
    """Normalize a small, explicitly allow-listed set of LLM output variants.

    The model sometimes adds a harmless label around the requested enum, such
    as ``ENTITY A`` or ``ENTITY B``.  This helper accepts only those known-safe
    variants; arbitrary document, chunk, or entity identifiers remain invalid
    and will still trigger a retry.
    """
    raw = unicodedata.normalize("NFKC", str(value or "NONE")).strip().upper()
    raw = raw.strip("`\"'")
    compact = re.sub(r"[\s_-]+", " ", raw)
    aliases = {
        "A": "A",
        "ENTITY A": "A",
        "B": "B",
        "ENTITY B": "B",
        "NEW": "NEW",
        "NEW ENTITY": "NEW",
        "NONE": "NONE",
        "N/A": "NONE",
        "NA": "NONE",
        "NIL": "NONE",
        "NULL": "NONE",
        "NOT APPLICABLE": "NONE",
    }
    return aliases.get(compact, compact)


def _validate_pair_response(parsed: dict[str, Any], supplied_chunks: list[str]) -> dict[str, Any]:
    decision = str(parsed.get("decision") or "").upper().strip()
    confidence = float(parsed.get("confidence"))
    reason = str(parsed.get("reason") or "").strip()
    evidence = [str(item) for item in (parsed.get("evidence_chunk_ids") or [])]
    preferred = _normalize_preferred_name_source(parsed.get("preferred_name_source"))
    if decision not in DECISIONS:
        raise ValueError(f"invalid decision: {decision}")
    if not 0 <= confidence <= 1:
        raise ValueError("confidence outside [0,1]")
    if not reason:
        raise ValueError("empty reason")
    if preferred not in {"A", "B", "NEW", "NONE"}:
        raise ValueError(f"invalid preferred_name_source: {preferred}")
    if any(item not in supplied_chunks for item in evidence):
        raise ValueError("evidence_chunk_ids contains an unsupplied chunk")
    if decision in POSITIVE and not evidence:
        raise ValueError("positive decision requires evidence_chunk_ids")
    canonical_name = parsed.get("canonical_name")
    if decision in POSITIVE and not str(canonical_name or "").strip():
        raise ValueError("positive decision requires canonical_name")
    return {
        "decision": decision,
        "canonical_name": canonical_name,
        "preferred_name_source": preferred,
        "confidence": confidence,
        "reason": reason,
        "evidence_chunk_ids": evidence,
    }


async def _call_llm_judgement(
    pair: dict[str, Any],
    graph: dict[str, Any],
    chunks: dict[str, Any],
    docs: dict[str, Any],
    *,
    model: str,
    base_url: str,
    key_pool: AsyncKeyPool | AsyncLLMEndpointPool,
    timeout: float,
    semaphore: asyncio.Semaphore,
    attempts_per_pair: int = 2,
) -> dict[str, Any]:
    prompt, supplied_chunks = _context_for_pair(pair, graph, chunks, docs)
    context_hash = _pair_context_hash(pair)
    errors: list[str] = []
    attempt_limit = max(1, min(int(attempts_per_pair), key_pool.size))
    last_finish_reason: str | None = None
    last_reasoning_tokens: int | None = None
    for attempt in range(1, attempt_limit + 1):
        response: Any = None
        attempt_finish_reason: str | None = None
        attempt_reasoning_tokens: int | None = None
        retry_kind: str | None = None
        async with semaphore:
            endpoint = await key_pool.next()
            if isinstance(endpoint, LLMEndpoint):
                request_base_url = endpoint.base_url
                key = endpoint.api_key
            else:
                request_base_url = base_url
                key = endpoint
            stop = asyncio.Event()
            heartbeat_task = asyncio.create_task(
                _heartbeat(stop, f"{pair['pair_id']} normalization judge attempt {attempt}/{attempt_limit}")
            )
            try:
                from hyperrag.llm import openai_complete_if_cache
                # The SDK timeout alone did not stop several provider calls
                # that remained pending for hours.  Keep a hard outer wall
                # clock so one stalled request cannot occupy a worker forever.
                hard_timeout = min(max(float(timeout), 1.0), 120.0)
                response_info = await asyncio.wait_for(
                    openai_complete_if_cache(
                        model,
                        prompt,
                        system_prompt=SYSTEM_PROMPT,
                        base_url=request_base_url,
                        api_key=key,
                        timeout=hard_timeout,
                        temperature=0,
                        reasoning_effort="low",
                        response_format={"type": "json_object"},
                        # Give the first request enough room for DeepSeek's
                        # reasoning plus the JSON answer.  A truncation retry
                        # gets a larger budget below.
                        max_tokens=4096 if attempt == 1 else 8192,
                        return_metadata=True,
                    ),
                    timeout=hard_timeout,
                )
                response = response_info.get("content", "") if isinstance(response_info, dict) else response_info
                if isinstance(response_info, dict):
                    attempt_finish_reason = response_info.get("finish_reason")
                    last_finish_reason = attempt_finish_reason
                    usage = response_info.get("usage") or {}
                    details = usage.get("completion_tokens_details") if isinstance(usage, dict) else None
                    if isinstance(details, dict):
                        value = details.get("reasoning_tokens")
                        attempt_reasoning_tokens = int(value) if value is not None else None
                        last_reasoning_tokens = attempt_reasoning_tokens
                if attempt_finish_reason == "length":
                    retry_kind = "truncated"
                    raise ValueError("finish_reason=length; JSON answer was truncated")
                validated = _validate_pair_response(_parse_json_response(response), supplied_chunks)
                return {
                    "pair_id": pair["pair_id"],
                    "prompt_version": PROMPT_VERSION,
                    "model": model,
                    "context_hash": context_hash,
                    "status": "ok",
                    "api_attempts": attempt,
                    "finish_reason": last_finish_reason,
                    "reasoning_tokens": last_reasoning_tokens,
                    **validated,
                }
            except Exception as exc:
                message = f"{type(exc).__name__}: {exc}"
                errors.append(message)
                preview = re.sub(r"\s+", " ", str(response or "")).strip()[:600]
                if preview:
                    LOGGER.warning(
                        "[%s] normalization judge attempt %s/%s failed: %s; response_preview=%r",
                        pair["pair_id"], attempt, attempt_limit, message, preview,
                    )
                else:
                    LOGGER.warning(
                        "[%s] normalization judge attempt %s/%s failed: %s",
                        pair["pair_id"], attempt, attempt_limit, message,
                    )
                if retry_kind is None and _is_retryable_judge_exception(exc):
                    retry_kind = "transport"
                if retry_kind is None or attempt >= attempt_limit:
                    break
            finally:
                stop.set()
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except asyncio.CancelledError:
                    pass
    return {
        "pair_id": pair["pair_id"],
        "prompt_version": PROMPT_VERSION,
        "model": model,
        "context_hash": context_hash,
        "status": "api_error",
        "api_attempts": attempt_limit,
        "finish_reason": last_finish_reason,
        "reasoning_tokens": last_reasoning_tokens,
        "decision": "UNCERTAIN",
        "canonical_name": None,
        "preferred_name_source": "NONE",
        "confidence": 0.0,
        "reason": "API or response validation failed in this resumable pass: " + " | ".join(errors[-3:]),
        "evidence_chunk_ids": [],
    }


async def judge_candidates(
    work: Path,
    *,
    llm_model: str,
    llm_base_url: str,
    llm_keys: list[str],
    llm_endpoints: list[LLMEndpoint] | None = None,
    max_async: int = 15,
    timeout: float = 3600.0,
    attempts_per_pair: int = 2,
    resume: bool = True,
) -> dict[str, Any]:
    candidates = read_jsonl(work / "normalization_candidates.jsonl")
    state = json.loads((work / "normalization_state.json").read_text(encoding="utf-8"))
    source = Path(state["source_cache"])
    graph, chunks = load_graph(source), load_chunks(source)
    docs = _load_json_dict(source / "kv_store_full_docs.json")
    decision_path = work / "normalization_decisions.jsonl"
    decision_history = read_jsonl(decision_path)
    previous = _latest_records(
        decision_path,
        "judgement_key",
        successful_statuses={"ok", "rule_blocked"},
    )
    successful_pair_models = {
        (str(row.get("pair_id")), str(row.get("prompt_version")), str(row.get("model")))
        for row in decision_history
        if row.get("pair_id") and row.get("status") in {"ok", "rule_blocked"}
    }
    if not llm_keys and not llm_endpoints:
        raise RuntimeError("No LLM API keys or endpoints found. Set LLM_API_KEY(S) or LLM_ENDPOINTS; secrets are never written to output.")
    pending: list[dict[str, Any]] = []
    resume_hits = 0
    resume_context_hash_hits = 0
    rule_blocked = 0
    for pair in candidates:
        if pair.get("rule_decision"):
            rule_key = pair["pair_id"] + ":rule:" + pair["rule_decision"]
            if resume and previous.get(rule_key):
                resume_hits += 1
                continue
            row = {
                "pair_id": pair["pair_id"],
                "judgement_key": rule_key,
                "left_id": pair["left_id"],
                "right_id": pair["right_id"],
                "prompt_version": PROMPT_VERSION,
                "model": llm_model,
                "status": "rule_blocked",
                "decision": pair["rule_decision"],
                "confidence": 1.0,
                "reason": (pair.get("rule_reasons") or ["risk rule"])[0],
                "evidence_chunk_ids": [],
                "api_attempts": 0,
            }
            append_jsonl(decision_path, row)
            previous[rule_key] = row
            rule_blocked += 1
            continue
        legacy_success_key = (str(pair["pair_id"]), PROMPT_VERSION, str(llm_model))
        if resume and legacy_success_key in successful_pair_models:
            # Older context construction could produce a different hash across
            # restarts. Reuse a successful judgement for the same semantic job.
            resume_hits += 1
            resume_context_hash_hits += 1
            continue
        # Do not construct the full prompt here.  Workers build it once when
        # making the actual request; this lightweight key is stable across
        # resumable passes and avoids a second full graph/evidence traversal.
        context_hash = _pair_context_hash(pair)
        judgement_key = ":".join((pair["pair_id"], PROMPT_VERSION, llm_model, context_hash))
        old = previous.get(judgement_key)
        if resume and old and old.get("status") in {"ok", "rule_blocked"}:
            resume_hits += 1
            continue
        item = dict(pair)
        item["judgement_key"] = judgement_key
        pending.append(item)
    semaphore = asyncio.Semaphore(max(1, max_async))
    if llm_endpoints:
        key_pool: AsyncKeyPool | AsyncLLMEndpointPool = AsyncLLMEndpointPool(llm_endpoints, name="LLM_ENDPOINTS")
    else:
        key_pool = AsyncKeyPool(llm_keys, name="LLM_API_KEY")
    results: list[dict[str, Any]] = []

    async def one(pair: dict[str, Any]) -> None:
        result = await _call_llm_judgement(
            pair,
            graph,
            chunks,
            docs,
            model=llm_model,
            base_url=llm_base_url,
            key_pool=key_pool,
            timeout=timeout,
            semaphore=semaphore,
            attempts_per_pair=attempts_per_pair,
        )
        result.update({
            "judgement_key": pair["judgement_key"],
            "left_id": pair["left_id"],
            "right_id": pair["right_id"],
            "candidate_reasons": pair.get("candidate_reasons", []),
        })
        append_jsonl(decision_path, result)
        results.append(result)

    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    for pair in pending:
        queue.put_nowait(pair)
    completed_pairs = 0

    async def worker() -> None:
        nonlocal completed_pairs
        while True:
            try:
                pair = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            try:
                await one(pair)
                completed_pairs += 1
                if completed_pairs % 50 == 0 or completed_pairs == len(pending):
                    LOGGER.info(
                        "normalization judge progress: %d/%d pending candidates completed",
                        completed_pairs,
                        len(pending),
                    )
            finally:
                queue.task_done()

    worker_count = min(max(1, max_async), len(pending))
    if worker_count:
        await asyncio.gather(*(worker() for _ in range(worker_count)))
    api_requests = sum(int(row.get("api_attempts") or 0) for row in results)
    return {
        "candidates": len(candidates),
        "pending_calls": len(pending),
        "completed_calls": sum(row.get("status") == "ok" for row in results),
        "api_errors": sum(row.get("status") == "api_error" for row in results),
        "api_requests": api_requests,
        "api_retries": max(0, api_requests - len(results)),
        "resume_hits": resume_hits,
        "resume_context_hash_hits": resume_context_hash_hits,
        "rule_blocked": rule_blocked,
        "decision_records": len(read_jsonl(decision_path)),
    }

class UnionFind:
    def __init__(self, items: Iterable[str]):
        self.parent = {str(item): str(item) for item in items}
        self.rank = {str(item): 0 for item in items}

    def find(self, item: str) -> str:
        item = str(item)
        parent = self.parent[item]
        if parent != item:
            self.parent[item] = self.find(parent)
        return self.parent[item]

    def union(self, left: str, right: str) -> bool:
        a, b = self.find(left), self.find(right)
        if a == b:
            return False
        if self.rank[a] < self.rank[b]:
            a, b = b, a
        self.parent[b] = a
        if self.rank[a] == self.rank[b]:
            self.rank[a] += 1
        return True

    def groups(self) -> list[list[str]]:
        grouped: dict[str, list[str]] = defaultdict(list)
        for item in self.parent:
            grouped[self.find(item)].append(item)
        return [sorted(values) for values in grouped.values()]


def _decision_by_pair(decisions: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in decisions:
        if row.get("pair_id"):
            grouped[str(row["pair_id"])].append(row)
    result: dict[str, dict[str, Any]] = {}
    for pair_id, rows in grouped.items():
        successful = [row for row in rows if row.get("status") in {"ok", "rule_blocked"}]
        if not successful:
            result[pair_id] = rows[-1]
            continue
        decisions_seen = {str(row.get("decision") or "UNCERTAIN") for row in successful}
        if len(decisions_seen) == 1:
            result[pair_id] = max(
                enumerate(successful),
                key=lambda item: (float(item[1].get("confidence") or 0), item[0]),
            )[1]
            continue
        latest = successful[-1]
        result[pair_id] = {
            **latest,
            "status": "conflict",
            "decision": "UNCERTAIN",
            "confidence": 0.0,
            "canonical_name": None,
            "preferred_name_source": "NONE",
            "reason": "Conflicting successful judgements were recorded; conservative merge disabled: "
            + ", ".join(sorted(decisions_seen)),
            "evidence_chunk_ids": sorted({
                str(chunk_id)
                for row in successful
                for chunk_id in row.get("evidence_chunk_ids") or []
            }),
            "conflicting_decisions": sorted(decisions_seen),
            "conflicting_models": sorted({str(row.get("model") or "") for row in successful}),
        }
    return result


def _pair_key(left: str, right: str) -> tuple[str, str]:
    return tuple(sorted((str(left), str(right))))


def _cluster_conflict(left_members: Iterable[str], right_members: Iterable[str], features: dict[str, EntityFeatures], blocked: dict[tuple[str, str], dict[str, Any]], negative_pairs: set[tuple[str, str]]) -> str | None:
    for left in left_members:
        for right in right_members:
            row = blocked.get(_pair_key(left, right))
            if row:
                return f"conflicting judgement {row.get('decision')} for {left} vs {right}"
            decision, reason = risk_filter(features[left], features[right], negative_pairs)
            if decision:
                return reason or decision
    return None


def conservative_clusters(features: dict[str, EntityFeatures], decisions: Iterable[dict[str, Any]], *, merge_confidence: float = 0.90, negative_pairs: set[tuple[str, str]] | None = None, revoked_pairs: set[str] | None = None) -> tuple[list[list[str]], list[dict[str, Any]], list[dict[str, Any]]]:
    negative_pairs = negative_pairs or set()
    revoked_pairs = revoked_pairs or set()
    latest = _decision_by_pair(decisions)
    blocked: dict[tuple[str, str], dict[str, Any]] = {}
    positive: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for row in latest.values():
        decision = str(row.get("decision") or "UNCERTAIN")
        if decision in POSITIVE and float(row.get("confidence") or 0) >= merge_confidence and row.get("status") == "ok" and row.get("pair_id") not in revoked_pairs:
            positive.append(row)
        else:
            blocked[_pair_key(row.get("left_id", ""), row.get("right_id", ""))] = row
    uf = UnionFind(features)
    accepted: list[dict[str, Any]] = []
    for row in sorted(positive, key=lambda item: (-float(item.get("confidence") or 0), str(item.get("pair_id")))):
        left, right = str(row["left_id"]), str(row["right_id"])
        left_root, right_root = uf.find(left), uf.find(right)
        if left_root == right_root:
            accepted.append(row)
            continue
        groups = {uf.find(item): [] for item in features}
        for item in features:
            groups[uf.find(item)].append(item)
        conflict = _cluster_conflict(groups[left_root], groups[right_root], features, blocked, negative_pairs)
        if conflict:
            rejected.append({"pair_id": row.get("pair_id"), "left_id": left, "right_id": right, "reason": conflict, "confidence": row.get("confidence")})
            continue
        uf.union(left, right)
        accepted.append(row)
    return sorted(uf.groups(), key=lambda values: (values[0], len(values))), accepted, rejected


def _choose_canonical_name(members: list[str], features: dict[str, EntityFeatures], decisions: list[dict[str, Any]], registry: AliasRegistry) -> tuple[str, str]:
    registry_matches = []
    for member in members:
        match = registry.match_exact(features[member].raw_name, features[member].entity_type)
        if match:
            registry_matches.append((match.canonical_name, match.canonical_id))
    if registry_matches and len({item[1] for item in registry_matches}) == 1:
        return registry_matches[0][0], "registry"
    member_set = set(members)
    suggestions = []
    for row in decisions:
        if row.get("left_id") in member_set and row.get("right_id") in member_set and row.get("decision") in POSITIVE and row.get("canonical_name"):
            suggestions.append((float(row.get("confidence") or 0), str(row["canonical_name"])))
    if suggestions:
        suggestions.sort(key=lambda item: (-item[0], -len(normalize_text_for_match(item[1])), item[1].casefold()))
        return suggestions[0][1], "llm"
    ranked = []
    for member in members:
        feature = features[member]
        ranked.append((len(set(feature.documents)), len(normalize_text_for_match(feature.raw_name)), feature.raw_name.casefold(), feature.raw_name))
    ranked.sort(key=lambda item: (-item[0], -item[1], item[2]))
    return ranked[0][3], "frequency_specificity"


def _build_map_payload(features: dict[str, EntityFeatures], clusters: list[list[str]], decisions: list[dict[str, Any]], registry: AliasRegistry, *, merge_confidence: float, previous: dict[str, Any] | None = None, accepted: list[dict[str, Any]] | None = None, rejected: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    previous_entities = (previous or {}).get("entities") or {}
    used: dict[str, tuple[str, ...]] = {}
    entities: dict[str, dict[str, Any]] = {}
    cluster_rows: list[dict[str, Any]] = []
    decision_index = _decision_by_pair(decisions)
    accepted_ids = {str(row.get("pair_id")) for row in (accepted or [])}
    for members in sorted(clusters, key=lambda values: values[0]):
        canonical_name, name_source = _choose_canonical_name(members, features, decisions, registry)
        existing_ids = sorted({str(previous_entities[m].get("canonical_id")) for m in members if m in previous_entities and previous_entities[m].get("canonical_id")})
        if existing_ids:
            canonical_id = existing_ids[0]
        else:
            first = features[members[0]]
            canonical_id = f"{_prefix(first.entity_type, first.semantic_group)}:{_slug(normalize_text(canonical_name, lowercase=True))}"
        signature = tuple(members)
        if canonical_id in used and used[canonical_id] != signature:
            base_id = canonical_id
            canonical_id = base_id + ":" + stable_hash(normalize_text(canonical_name, lowercase=True), 8)
            if canonical_id in used and used[canonical_id] != signature:
                canonical_id = base_id + ":" + stable_hash("|".join(members), 8)
        used[canonical_id] = signature
        aliases = sorted({features[item].raw_name for item in members}, key=lambda item: item.casefold())
        member_decisions = [decision_index[_pair_id(a, b)] for a, b in itertools.combinations(members, 2) if _pair_id(a, b) in decision_index]
        merge_confidences = [float(row.get("confidence") or 0) for row in member_decisions if row.get("pair_id") in accepted_ids]
        reasons = sorted({str(row.get("reason")) for row in member_decisions if row.get("pair_id") in accepted_ids and row.get("reason")})
        types = sorted({features[item].entity_type for item in members})
        cluster = {
            "canonical_id": canonical_id,
            "canonical_name": canonical_name,
            "name_source": name_source,
            "members": members,
            "aliases": aliases,
            "entity_types": types,
            "merge_confidence": min(merge_confidences) if merge_confidences else 1.0,
            "merge_reasons": reasons,
        }
        cluster_rows.append(cluster)
        for member in members:
            entities[member] = dict(cluster)
            entities[member]["legacy_vertex_id"] = member
    return {
        "metadata": {"normalization_version": NORMALIZATION_VERSION, "merge_confidence": merge_confidence, "entity_count_before": len(features), "entity_count_after": len(clusters)},
        "entities": entities,
        "clusters": cluster_rows,
        "accepted_merge_edges": [dict(row) for row in (accepted or [])],
        "rejected_merge_edges": [dict(row) for row in (rejected or [])],
    }



def _cluster_audit_prompt(cluster: list[str], features: dict[str, EntityFeatures], accepted_edges: list[dict[str, Any]], chunks: dict[str, Any], model: str) -> tuple[str, str]:
    member_payload = [features[member].to_dict() for member in cluster]
    evidence_sections: list[str] = []
    supplied: list[str] = []
    for member in cluster:
        for chunk_id in features[member].chunks[:3]:
            if chunk_id in chunks and chunk_id not in supplied:
                supplied.append(chunk_id)
                evidence_sections.append(f"{chunk_id}: {chunk_text(chunks[chunk_id])[:3500]}")
    edge_payload = [
        {"pair_id": row.get("pair_id"), "left_id": row.get("left_id"), "right_id": row.get("right_id"), "decision": row.get("decision"), "confidence": row.get("confidence"), "reason": row.get("reason")}
        for row in accepted_edges
    ]
    newline = chr(10)
    prompt = (
        "Audit whether every member of this proposed canonical entity cluster is truly the same object or an alias. "
        "Return JSON only with valid (boolean), reason (non-empty string), and weakest_pair_id (string or null). "
        "If any variant, model, oxidation, condition, or base/composite conflict exists, valid must be false."
        + newline + "Members:" + newline + json.dumps(member_payload, ensure_ascii=False)
        + newline + "Accepted merge edges:" + newline + json.dumps(edge_payload, ensure_ascii=False)
        + newline + "Evidence:" + newline + newline.join(evidence_sections)
    )
    audit_key = "cluster:" + stable_hash(json_hash({"members": sorted(cluster), "edges": sorted(str(row.get("pair_id")) for row in accepted_edges), "prompt_version": CLUSTER_PROMPT_VERSION, "model": model, "context_hash": json_hash(prompt)}), 24)
    return prompt, audit_key


async def _call_cluster_audit(
    cluster: list[str],
    features: dict[str, EntityFeatures],
    accepted_edges: list[dict[str, Any]],
    chunks: dict[str, Any],
    *,
    model: str,
    base_url: str,
    key_pool: AsyncKeyPool | AsyncLLMEndpointPool,
    timeout: float,
) -> dict[str, Any]:
    prompt, audit_key = _cluster_audit_prompt(cluster, features, accepted_edges, chunks, model)
    errors: list[str] = []
    attempt_limit = min(key_pool.size, 2)
    for attempt in range(1, attempt_limit + 1):
        credential = await key_pool.next()
        if isinstance(credential, LLMEndpoint):
            request_base_url = credential.base_url
            key = credential.api_key
        else:
            request_base_url = base_url
            key = credential
        stop = asyncio.Event()
        task = asyncio.create_task(_heartbeat(stop, f"{audit_key} cluster audit attempt {attempt}/{attempt_limit}"))
        try:
            from hyperrag.llm import openai_complete_if_cache
            hard_timeout = min(max(float(timeout), 1.0), 120.0)
            response_info = await asyncio.wait_for(
                openai_complete_if_cache(
                    model=model,
                    prompt=prompt,
                    system_prompt="You are a conservative chemical entity cluster auditor. Return strict JSON only.",
                    base_url=request_base_url,
                    api_key=key,
                    timeout=hard_timeout,
                    temperature=0.0,
                    reasoning_effort="low",
                    response_format={"type": "json_object"},
                    max_tokens=4096 if attempt == 1 else 8192,
                    return_metadata=True,
                ),
                timeout=hard_timeout,
            )
            raw = response_info.get("content", "") if isinstance(response_info, dict) else response_info
            if isinstance(response_info, dict) and response_info.get("finish_reason") == "length":
                raise ValueError("finish_reason=length; cluster audit JSON was truncated")
            parsed = _parse_json_response(raw)
            valid = parsed.get("valid")
            if not isinstance(valid, bool):
                raise ValueError("cluster audit valid must be boolean")
            reason = str(parsed.get("reason") or "").strip()
            if not reason:
                raise ValueError("cluster audit reason is empty")
            weakest = parsed.get("weakest_pair_id")
            pair_ids = {str(row.get("pair_id")) for row in accepted_edges}
            if weakest is not None and str(weakest) not in pair_ids:
                weakest = None
            return {
                "audit_type": "cluster",
                "audit_key": audit_key,
                "prompt_version": CLUSTER_PROMPT_VERSION,
                "status": "ok",
                "api_attempts": attempt,
                "members": sorted(cluster),
                "valid": valid,
                "reason": reason,
                "weakest_pair_id": str(weakest) if weakest is not None else None,
                "model": model,
            }
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            errors.append(message)
            LOGGER.warning("[%s] cluster audit attempt %s/%s failed: %s", audit_key, attempt, attempt_limit, message)
            if attempt >= attempt_limit or not (
                _is_retryable_judge_exception(exc)
                or "finish_reason=length" in message
            ):
                break
        finally:
            stop.set()
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    return {
        "audit_type": "cluster",
        "audit_key": audit_key,
        "prompt_version": CLUSTER_PROMPT_VERSION,
        "status": "api_error",
        "api_attempts": len(errors),
        "members": sorted(cluster),
        "valid": False,
        "reason": "Cluster audit failed conservatively across the entire key pool: " + " | ".join(errors[-3:]),
        "weakest_pair_id": None,
        "model": model,
    }


def _cluster_needs_audit(cluster: list[str], features: dict[str, EntityFeatures]) -> bool:
    if len(cluster) >= 3:
        return True
    types = {features[item].entity_type for item in cluster}
    return len(types) > 1 or any(features[item].formulas or features[item].numeric_signals or features[item].models or features[item].oxidation_states for item in cluster)


async def build_canonical_map(
    source: Path,
    work: Path,
    *,
    merge_confidence: float = 0.90,
    registry_paths: Iterable[Path] = (),
    negative_paths: Iterable[Path] = (),
    llm_model: str,
    llm_base_url: str,
    llm_keys: list[str],
    llm_endpoints: list[LLMEndpoint] | None = None,
    max_async: int = 27,
    llm_timeout: float = 3600.0,
    resume: bool = True,
) -> dict[str, Any]:
    graph, chunks = load_graph(source), load_chunks(source)
    features, _, _ = build_context_index(graph, chunks)
    candidate_ids = {str(row.get("pair_id")) for row in read_jsonl(work / "normalization_candidates.jsonl") if row.get("pair_id")}
    decisions = [
        row
        for pair_id, row in _decision_by_pair(read_jsonl(work / "normalization_decisions.jsonl")).items()
        if pair_id in candidate_ids
    ]
    registry = AliasRegistry.from_yaml_files(registry_paths) if registry_paths else AliasRegistry()
    negative_pairs = load_negative_pairs(negative_paths, registry)
    audit_path = work / "normalization_audit.jsonl"
    previous_audits = _latest_records(audit_path, "audit_key", successful_statuses={"ok"})
    revoked = {str(row.get("revoked_pair_id")) for row in previous_audits.values() if row.get("audit_type") == "cluster_revoke" and row.get("revoked_pair_id")}
    if llm_endpoints:
        key_pool: AsyncKeyPool | AsyncLLMEndpointPool | None = AsyncLLMEndpointPool(llm_endpoints, name="LLM_ENDPOINTS")
    else:
        key_pool = AsyncKeyPool(llm_keys, name="LLM_API_KEY") if llm_keys else None
    cluster_audit_stats = {"api_requests": 0, "api_retries": 0, "api_errors": 0, "resume_hits": 0}
    audit_concurrency = max(1, int(max_async))
    while True:
        clusters, accepted, rejected = conservative_clusters(features, decisions, merge_confidence=merge_confidence, negative_pairs=negative_pairs, revoked_pairs=revoked)
        accepted_by_cluster = []
        for cluster in clusters:
            if len(cluster) < 2 or not _cluster_needs_audit(cluster, features):
                continue
            member_set = set(cluster)
            edges = [row for row in accepted if row.get("left_id") in member_set and row.get("right_id") in member_set]
            accepted_by_cluster.append((cluster, edges))
        if not accepted_by_cluster:
            break

        async def audit_one(cluster: list[str], edges: list[dict[str, Any]]) -> tuple[list[str], list[dict[str, Any]], dict[str, Any], bool]:
            _, fingerprint = _cluster_audit_prompt(cluster, features, edges, chunks, llm_model)
            old = previous_audits.get(fingerprint)
            if resume and old and old.get("status") == "ok":
                return cluster, edges, old, True
            if key_pool is None:
                raise RuntimeError("Cluster-level audit requires LLM_API_KEY or LLM_API_KEYS")
            audit = await _call_cluster_audit(cluster, features, edges, chunks, model=llm_model, base_url=llm_base_url, key_pool=key_pool, timeout=llm_timeout)
            return cluster, edges, audit, False

        # Cluster audits are independent within one conservative-clustering
        # round. Run one wave per endpoint/key so all available credentials can
        # make progress; apply revocations only after the wave is complete.
        results: list[tuple[list[str], list[dict[str, Any]], dict[str, Any], bool]] = []
        for offset in range(0, len(accepted_by_cluster), audit_concurrency):
            wave = accepted_by_cluster[offset:offset + audit_concurrency]
            results.extend(await asyncio.gather(*(audit_one(cluster, edges) for cluster, edges in wave)))

        revocations: list[tuple[list[str], dict[str, Any], dict[str, Any]]] = []
        for cluster, edges, audit, resumed in results:
            _, fingerprint = _cluster_audit_prompt(cluster, features, edges, chunks, llm_model)
            if resumed:
                cluster_audit_stats["resume_hits"] += 1
            else:
                attempts = int(audit.get("api_attempts") or 0)
                cluster_audit_stats["api_requests"] += attempts
                cluster_audit_stats["api_retries"] += max(0, attempts - 1)
                cluster_audit_stats["api_errors"] += int(audit.get("status") == "api_error")
                append_jsonl(audit_path, audit)
                previous_audits[fingerprint] = audit
            if audit.get("valid"):
                continue
            valid_edges = [row for row in edges if row.get("pair_id") not in revoked]
            if not valid_edges:
                continue
            requested = str(audit.get("weakest_pair_id") or "")
            weakest = next((row for row in valid_edges if str(row.get("pair_id")) == requested), None)
            if weakest is None:
                weakest = min(valid_edges, key=lambda row: (float(row.get("confidence") or 0), str(row.get("pair_id"))))
            revocations.append((cluster, audit, weakest))

        if not revocations:
            break
        for cluster, audit, weakest in revocations:
            revoked_id = str(weakest["pair_id"])
            if revoked_id in revoked:
                continue
            revoked.add(revoked_id)
            revoke_row = {"audit_type": "cluster_revoke", "audit_key": "revoke:" + revoked_id, "revoked_pair_id": revoked_id, "members": cluster, "reason": audit.get("reason"), "confidence": weakest.get("confidence")}
            append_jsonl(audit_path, revoke_row)
            previous_audits[revoke_row["audit_key"]] = revoke_row
    previous_map = None
    map_path = work / "canonical_entity_map.json"
    if resume and map_path.exists():
        previous_map = json.loads(map_path.read_text(encoding="utf-8"))
    payload = _build_map_payload(features, clusters, decisions, registry, merge_confidence=merge_confidence, previous=previous_map, accepted=accepted, rejected=rejected)
    payload["metadata"].update({"source_cache": str(source.resolve()), "normalization_version": NORMALIZATION_VERSION, "revoked_pair_ids": sorted(revoked), "cluster_audit_count": len([row for row in previous_audits.values() if row.get("audit_type") == "cluster"]), "cluster_audit_api_statistics": cluster_audit_stats})
    write_json(map_path, payload)
    return payload


IMMUTABLE_FILES = (
    "kv_store_full_docs.json",
    "kv_store_text_chunks.json",
    "kv_store_llm_response_cache.json",
    "corpus_manifest.jsonl",
    "build_progress.jsonl",
    "vdb_chunks.json",
)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def copy_immutable_files(source: Path, work: Path) -> dict[str, str]:
    hashes = {}
    for name in IMMUTABLE_FILES:
        src, dst = source / name, work / name
        if not src.exists():
            continue
        source_hash = file_sha256(src)
        if dst.exists() and file_sha256(dst) == source_hash:
            hashes[name] = source_hash
            continue
        shutil.copy2(src, dst)
        if file_sha256(dst) != source_hash:
            raise RuntimeError(f"Hash mismatch while copying {name}")
        hashes[name] = source_hash
    return hashes


def _value_list(value: Any) -> list[Any]:
    if value is None or value == "":
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    if isinstance(value, str) and "<SEP>" in value:
        return [item for item in value.split("<SEP>") if item]
    return [value]


def _unique_values(values: Iterable[Any]) -> list[Any]:
    output = []
    seen = set()
    for value in values:
        marker = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        if marker not in seen:
            seen.add(marker)
            output.append(value)
    return output


def _merge_metadata(existing: dict[str, Any] | None, incoming: dict[str, Any]) -> dict[str, Any]:
    output = dict(existing or {})
    for key, value in incoming.items():
        if value is None or value == "":
            continue
        if key not in output or output[key] in (None, "", [], {}):
            output[key] = value
            continue
        if output[key] == value:
            continue
        merged = _unique_values([*_value_list(output[key]), *_value_list(value)])
        output[key] = merged
    return output


def _write_graph_file(path: Path, vertices: dict[str, dict[str, Any]], edges: dict[tuple[str, ...], dict[str, Any]]) -> None:
    try:
        from hyperdb import HypergraphDB
        graph = HypergraphDB()
        for node_id, data in vertices.items():
            graph.add_v(node_id, data)
        for edge_key, data in edges.items():
            graph.add_e(edge_key, data)
        if not graph.save(path):
            raise RuntimeError(f"HypergraphDB.save returned false for {path}")
    except ImportError:
        incidence: dict[str, set[tuple[str, ...]]] = defaultdict(set)
        for edge_key in edges:
            for node_id in edge_key:
                incidence[node_id].add(edge_key)
        with path.open("wb") as stream:
            pickle.dump({"v_data": vertices, "v_inci": incidence, "e_data": edges}, stream)


def rewrite_graph(source: Path, work: Path, canonical_map: dict[str, Any]) -> dict[str, Any]:
    copy_hashes = copy_immutable_files(source, work)
    graph = load_graph(source)
    mapping = canonical_map["entities"]
    source_vertices = {str(key): dict(value or {}) for key, value in graph["v_data"].items()}
    vertices: dict[str, dict[str, Any]] = {}
    for cluster in canonical_map["clusters"]:
        canonical_id = str(cluster["canonical_id"])
        members = list(cluster["members"])
        member_data = [source_vertices[item] for item in members]
        descriptions = _unique_values(value for data in member_data for value in _value_list(data.get("description") or data.get("descriptions")))
        docs = _unique_values(value for member in members for value in extract_features(member, source_vertices[member]).documents)
        chunks = _unique_values(value for member in members for value in extract_features(member, source_vertices[member]).chunks)
        types = sorted({str(data.get("entity_type") or data.get("type") or "UNKNOWN").upper() for data in member_data})
        semantic_groups = sorted({str(data.get("semantic_group") or data.get("semantic_type") or "") for data in member_data if data.get("semantic_group") or data.get("semantic_type")})
        merged_raw = {}
        for data in member_data:
            merged_raw = _merge_metadata(merged_raw, data)
        merged_raw.update({
            "entity_name": cluster["canonical_name"],
            "canonical_id": canonical_id,
            "canonical_name": cluster["canonical_name"],
            "aliases": cluster["aliases"],
            "legacy_vertex_ids": members,
            "entity_type": types[0] if len(types) == 1 else "COMPATIBLE_MIXED",
            "entity_types": types,
            "semantic_group": semantic_groups[0] if len(semantic_groups) == 1 else "",
            "descriptions": descriptions,
            "description": "<SEP>".join(str(item) for item in descriptions[:20]),
            "source_document_ids": docs,
            "source_chunk_ids": chunks,
            "source_doc_id": "<SEP>".join(docs),
            "source_chunk_id": "<SEP>".join(chunks),
            "normalization_method": "posthoc_llm",
            "normalization_confidence": cluster["merge_confidence"],
            "normalization_reasons": cluster["merge_reasons"],
        })
        vertices[canonical_id] = merged_raw
    edges: dict[tuple[str, ...], dict[str, Any]] = {}
    removed_self = 0
    degraded_edges = 0
    duplicate_edges = 0
    low_before = high_before = low_after = high_after = 0
    audit_path = work / "normalization_audit.jsonl"
    for edge in edge_records(graph):
        original = list(dict.fromkeys(str(item) for item in edge["vertices"]))
        if len(original) == 2:
            low_before += 1
        elif len(original) >= 3:
            high_before += 1
        mapped = tuple(sorted({str(mapping[item]["canonical_id"]) for item in original}))
        if len(mapped) < len(original):
            degraded_edges += 1
        if len(original) >= 2 and len(mapped) == 1:
            removed_self += 1
            append_jsonl(audit_path, {"audit_type": "collapsed_self_relation", "legacy_vertices": original, "canonical_vertices": list(mapped), "edge_data": edge["data"]})
            continue
        if mapped in edges:
            duplicate_edges += 1
        incoming = dict(edge["data"])
        incoming["canonical_vertices"] = list(mapped)
        incoming["legacy_vertex_sets"] = [original]
        incoming["relation_types"] = _unique_values(_value_list(incoming.get("relation_type")) + _value_list(incoming.get("relation_types")))
        incoming["evidence_spans"] = _unique_values(_value_list(incoming.get("evidence_span")) + _value_list(incoming.get("source_span")) + _value_list(incoming.get("evidence_spans")))
        incoming["source_document_ids"] = extract_ids(incoming, r"RFB_\d{3}")
        incoming["source_chunk_ids"] = extract_ids(incoming, r"RFB_\d{3}_CHK_\d{3}")
        edges[mapped] = _merge_metadata(edges.get(mapped), incoming)
    for edge_key in edges:
        if len(edge_key) == 2:
            low_after += 1
        elif len(edge_key) >= 3:
            high_after += 1
    _write_graph_file(work / GRAPH_FILE, vertices, edges)
    summary = {
        "source_vertices": len(source_vertices),
        "canonical_vertices": len(vertices),
        "source_edges": len(graph["e_data"]),
        "canonical_edges": len(edges),
        "low_order_before": low_before,
        "high_order_before": high_before,
        "low_order_after": low_after,
        "high_order_after": high_after,
        "collapsed_self_relations_removed": removed_self,
        "hyperedges_degraded": degraded_edges,
        "duplicate_hyperedges_merged": duplicate_edges,
        "immutable_file_hashes": copy_hashes,
    }
    write_json(work / "normalization_rewrite_summary.json", summary)
    return summary



def _write_vector_file(path: Path, rows_by_id: dict[str, tuple[dict[str, Any], np.ndarray]], embedding_dim: int) -> None:
    ordered = sorted(rows_by_id.items())
    rows = []
    vectors = []
    for vector_id, (metadata, vector) in ordered:
        row = dict(metadata)
        row["__id__"] = vector_id
        rows.append(row)
        vectors.append(np.asarray(vector, dtype=np.float32))
    matrix = np.vstack(vectors).astype(np.float32) if vectors else np.empty((0, embedding_dim), dtype=np.float32)
    payload = {"embedding_dim": embedding_dim, "data": rows, "matrix": base64.b64encode(matrix.tobytes()).decode("ascii")}
    write_json(path, payload)


def _load_vector_file(path: Path) -> tuple[int, dict[str, tuple[dict[str, Any], np.ndarray]]]:
    if not path.exists():
        return 0, {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    dim = int(payload.get("embedding_dim") or 0)
    rows = payload.get("data") or []
    matrix = np.frombuffer(base64.b64decode(payload.get("matrix") or ""), dtype=np.float32)
    if rows:
        matrix = matrix.reshape((len(rows), dim))
    else:
        matrix = np.empty((0, dim), dtype=np.float32)
    return dim, {str(row["__id__"]): ({key: value for key, value in row.items() if key != "__id__"}, matrix[index]) for index, row in enumerate(rows)}


def _text_field(value: Any) -> str:
    if isinstance(value, list):
        return "; ".join(str(item) for item in value)
    return str(value or "")


def build_vector_records(work: Path) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    from hyperrag.utils import compute_mdhash_id, relationship_vector_id
    graph = load_graph(work)
    entity_records = {}
    for canonical_id, data in sorted(graph["v_data"].items()):
        canonical_name = str(data.get("canonical_name") or data.get("entity_name") or canonical_id)
        content = "\n".join(value for value in (
            f"Canonical ID: {canonical_id}",
            f"Canonical name: {canonical_name}",
            f"Entity type: {_text_field(data.get('entity_type'))}",
            f"Semantic group: {_text_field(data.get('semantic_group'))}",
            f"Description: {_text_field(data.get('description') or data.get('descriptions'))}",
        ) if value.split(":", 1)[1].strip())
        vector_id = compute_mdhash_id(str(canonical_id), prefix="ent-")
        entity_records[vector_id] = {
            "content": content,
            "content_hash": json_hash(content),
            "entity_name": str(canonical_id),
            "canonical_id": str(canonical_id),
            "canonical_name": canonical_name,
            "raw_name": canonical_name,
            "aliases": data.get("aliases") or [],
            "entity_type": data.get("entity_type") or "UNKNOWN",
            "semantic_group": data.get("semantic_group") or "",
            "index_view": "canonical",
        }
    relationship_records = {}
    for edge_key, data in sorted(graph["e_data"].items()):
        id_set = sorted(str(item) for item in edge_key)
        names = [str(graph["v_data"][item].get("canonical_name") or item) for item in id_set]
        relation_types = data.get("relation_types") or data.get("relation_type") or ""
        content = "\n".join(value for value in (
            f"Relation type: {_text_field(relation_types)}",
            f"Canonical vertices: {'; '.join(names)}",
            f"Normalized description: {_text_field(data.get('description') or data.get('descriptions'))}",
            f"Keywords: {_text_field(data.get('keywords'))}",
        ) if value.split(":", 1)[1].strip())
        vector_id = relationship_vector_id(id_set)
        relationship_records[vector_id] = {
            "content": content,
            "content_hash": json_hash(content),
            "id_set": id_set,
            "canonical_names": names,
            "relation_type": relation_types,
            "source_doc_id": _text_field(data.get("source_document_ids") or data.get("source_doc_id")),
            "source_chunk_id": _text_field(data.get("source_chunk_ids") or data.get("source_chunk_id")),
            "index_view": "canonical",
        }
    return entity_records, relationship_records


async def _embed_batch(
    batch_index: int,
    records: list[tuple[str, dict[str, Any]]],
    *,
    model: str,
    base_url: str,
    embedding_dim: int,
    key_pool: AsyncKeyPool,
    timeout: float,
    semaphore: asyncio.Semaphore,
    stats: dict[str, int],
) -> list[tuple[str, dict[str, Any], np.ndarray]]:
    texts = [row[1]["content"] for row in records]
    async with semaphore:
        last_error: Exception | None = None
        for attempt in range(1, key_pool.size + 1):
            key = await key_pool.next()
            stats["requests"] = stats.get("requests", 0) + 1
            stop = asyncio.Event()
            task = asyncio.create_task(_heartbeat(stop, f"embedding batch {batch_index} attempt {attempt}/{key_pool.size}"))
            try:
                from hyperrag.llm import openai_embedding
                vectors = np.asarray(
                    await openai_embedding(
                        texts,
                        model=model,
                        base_url=base_url,
                        api_key=key,
                        timeout=timeout,
                        dimensions=embedding_dim,
                    ),
                    dtype=np.float32,
                )
                if vectors.ndim != 2 or vectors.shape[0] != len(records):
                    raise ValueError(f"Embedding response row count {vectors.shape} does not match batch size {len(records)}")
                return [(vector_id, metadata, vectors[index]) for index, (vector_id, metadata) in enumerate(records)]
            except Exception as exc:
                last_error = exc
                stats["errors"] = stats.get("errors", 0) + 1
                LOGGER.warning("Embedding batch %s attempt %s/%s failed: %s", batch_index, attempt, key_pool.size, exc)
            finally:
                stop.set()
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        raise RuntimeError(f"Embedding batch {batch_index} failed across the entire key pool: {last_error}")


async def _embed_record_set(
    path: Path,
    records: dict[str, dict[str, Any]],
    *,
    embedding_dim: int,
    model: str,
    base_url: str,
    key_pool: AsyncKeyPool,
    max_async: int,
    batch_num: int,
    timeout: float,
    resume: bool,
    stats: dict[str, int],
) -> dict[str, int]:
    existing_dim, stored = _load_vector_file(path) if resume else (0, {})
    if existing_dim not in (0, embedding_dim):
        raise ValueError(f"Existing vector dimension {existing_dim} does not match {embedding_dim}: {path}")
    pending = [(vector_id, metadata) for vector_id, metadata in sorted(records.items()) if vector_id not in stored or stored[vector_id][0].get("content_hash") != metadata.get("content_hash")]
    batches = [pending[index:index + batch_num] for index in range(0, len(pending), batch_num)]
    semaphore = asyncio.Semaphore(max(1, max_async))
    completed = 0
    for offset in range(0, len(batches), max(1, max_async)):
        wave = batches[offset:offset + max(1, max_async)]
        results = await asyncio.gather(*(
            _embed_batch(offset + index, batch, model=model, base_url=base_url, embedding_dim=embedding_dim, key_pool=key_pool, timeout=timeout, semaphore=semaphore, stats=stats)
            for index, batch in enumerate(wave)
        ), return_exceptions=True)
        failures = []
        for result in results:
            if isinstance(result, Exception):
                failures.append(result)
                continue
            for vector_id, metadata, vector in result:
                if vector.shape != (embedding_dim,):
                    raise ValueError(f"Vector {vector_id} has dimension {vector.shape}, expected {(embedding_dim,)}")
                stored[vector_id] = (metadata, vector)
                completed += 1
        _write_vector_file(path, stored, embedding_dim)
        if failures:
            raise RuntimeError(f"{len(failures)} embedding batches failed; successful batches were checkpointed: {failures[0]}")
    valid_ids = set(records)
    stored = {key: value for key, value in stored.items() if key in valid_ids}
    _write_vector_file(path, stored, embedding_dim)
    return {"total": len(records), "embedded": completed, "resume_hits": len(records) - len(pending), "api_requests": stats.get("requests", 0), "api_errors": stats.get("errors", 0)}


async def rebuild_vectors(
    work: Path,
    *,
    embedding_model: str,
    embedding_base_url: str,
    embedding_keys: list[str],
    embedding_dim: int = 2560,
    max_async: int = 15,
    batch_num: int = 16,
    timeout: float = 600.0,
    resume: bool = True,
) -> dict[str, Any]:
    if not embedding_keys:
        raise RuntimeError("No embedding API keys found. Set EMB_API_KEY or EMB_API_KEYS; keys are never written to output.")
    entities, relationships = build_vector_records(work)
    key_pool = AsyncKeyPool(embedding_keys, name="EMB_API_KEY")
    stats: dict[str, int] = {"requests": 0, "errors": 0}
    entity_stats = await _embed_record_set(work / "vdb_entities.json", entities, embedding_dim=embedding_dim, model=embedding_model, base_url=embedding_base_url, key_pool=key_pool, max_async=max_async, batch_num=batch_num, timeout=timeout, resume=resume, stats=stats)
    relationship_stats = await _embed_record_set(work / "vdb_relationships.json", relationships, embedding_dim=embedding_dim, model=embedding_model, base_url=embedding_base_url, key_pool=key_pool, max_async=max_async, batch_num=batch_num, timeout=timeout, resume=resume, stats=stats)
    return {"entities": entity_stats, "relationships": relationship_stats, "api_statistics": {"embedding_requests": stats.get("requests", 0), "embedding_errors": stats.get("errors", 0), "embedding_retries": max(0, stats.get("requests", 0) - (stats.get("requests", 0) - stats.get("errors", 0)) )}}

def source_checksums(source: Path) -> dict[str, str]:
    return {path.name: file_sha256(path) for path in sorted(source.iterdir()) if path.is_file() and path.name != "HyperRAG.log"}


def _load_json_dict(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _rows_and_ids(path: Path) -> tuple[int, list[dict[str, Any]], set[str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("data") or []
    ids = [str(row.get("__id__")) for row in rows]
    return int(payload.get("embedding_dim") or 0), rows, set(ids)


def validate_cache(source: Path, work: Path, *, merge_confidence: float = 0.90, negative_paths: Iterable[Path] = (), expected_docs: int = 60, expected_chunks: int = 1328) -> dict[str, Any]:
    from hyperrag.utils import relationship_vector_id

    failures: list[str] = []
    source_docs = _load_json_dict(source / "kv_store_full_docs.json")
    source_chunks = _load_json_dict(source / "kv_store_text_chunks.json")
    target_docs = _load_json_dict(work / "kv_store_full_docs.json")
    target_chunks = _load_json_dict(work / "kv_store_text_chunks.json")
    if len(source_docs) != expected_docs or len(target_docs) != expected_docs:
        failures.append(f"document count must remain {expected_docs}: source={len(source_docs)} target={len(target_docs)}")
    if len(source_chunks) != expected_chunks or len(target_chunks) != expected_chunks:
        failures.append(f"chunk count must remain {expected_chunks}: source={len(source_chunks)} target={len(target_chunks)}")
    for name in IMMUTABLE_FILES:
        if (source / name).exists() and (not (work / name).exists() or file_sha256(source / name) != file_sha256(work / name)):
            failures.append(f"immutable file differs: {name}")

    canonical_map = json.loads((work / "canonical_entity_map.json").read_text(encoding="utf-8"))
    source_graph, target_graph = load_graph(source), load_graph(work)
    source_vertex_ids = {str(item) for item in source_graph["v_data"]}
    target_vertex_ids = {str(item) for item in target_graph["v_data"]}
    entity_map = canonical_map.get("entities") or {}
    mapped_ids = {str(item) for item in entity_map}
    if source_vertex_ids != mapped_ids:
        failures.append(f"canonical map coverage mismatch: missing={len(source_vertex_ids - mapped_ids)} extra={len(mapped_ids - source_vertex_ids)}")

    clusters = canonical_map.get("clusters") or []
    cluster_canonical_ids = [str(row.get("canonical_id") or "") for row in clusters]
    duplicate_cluster_ids = sorted(item for item, count in Counter(cluster_canonical_ids).items() if item and count > 1)
    if duplicate_cluster_ids:
        failures.append(f"duplicate canonical IDs in clusters: {duplicate_cluster_ids[:10]}")
    if any(not item for item in cluster_canonical_ids):
        failures.append("one or more clusters have an empty canonical_id")
    cluster_member_ids = [str(member) for row in clusters for member in (row.get("members") or [])]
    duplicate_cluster_members = sorted(item for item, count in Counter(cluster_member_ids).items() if count > 1)
    if duplicate_cluster_members:
        failures.append(f"source vertices appear in multiple canonical clusters: {duplicate_cluster_members[:10]}")
    cluster_member_set = set(cluster_member_ids)
    if cluster_member_set != source_vertex_ids:
        failures.append(f"canonical cluster membership mismatch: missing={len(source_vertex_ids - cluster_member_set)} extra={len(cluster_member_set - source_vertex_ids)}")
    cluster_id_set = set(cluster_canonical_ids) - {""}
    if cluster_id_set != target_vertex_ids:
        failures.append(f"cluster canonical IDs do not equal graph vertices: missing={len(target_vertex_ids - cluster_id_set)} extra={len(cluster_id_set - target_vertex_ids)}")
    mapped_canonical_ids = {str(row.get("canonical_id") or "") for row in entity_map.values()} - {""}
    if mapped_canonical_ids != target_vertex_ids:
        failures.append(f"entity map canonical IDs do not equal graph vertices: missing={len(target_vertex_ids - mapped_canonical_ids)} extra={len(mapped_canonical_ids - target_vertex_ids)}")
    for legacy_id, row in entity_map.items():
        canonical_id = str(row.get("canonical_id") or "")
        members = {str(item) for item in (row.get("members") or [])}
        if str(legacy_id) not in members:
            failures.append(f"canonical entity map row does not contain its legacy vertex: {legacy_id}")
            break
        if canonical_id not in target_vertex_ids:
            failures.append(f"canonical entity map points to missing graph vertex: {legacy_id} -> {canonical_id}")
            break

    dangling = sorted({str(vertex) for edge in target_graph["e_data"] for vertex in edge if str(vertex) not in target_vertex_ids})
    if dangling:
        failures.append(f"dangling graph vertices: {dangling[:10]}")

    entity_dim, entity_rows, entity_ids = _rows_and_ids(work / "vdb_entities.json")
    relation_dim, relation_rows, relation_ids = _rows_and_ids(work / "vdb_relationships.json")
    chunk_dim, chunk_rows, chunk_ids = _rows_and_ids(work / "vdb_chunks.json")
    if entity_dim != 2560 or relation_dim != 2560 or chunk_dim != 2560:
        failures.append(f"embedding dimensions must all be 2560: chunks={chunk_dim} entities={entity_dim} relationships={relation_dim}")
    if len(entity_rows) != len(target_vertex_ids):
        failures.append(f"entity vector count mismatch: rows={len(entity_rows)} vertices={len(target_vertex_ids)}")
    if len(relation_rows) != len(target_graph["e_data"]):
        failures.append(f"relationship vector count mismatch: rows={len(relation_rows)} edges={len(target_graph['e_data'])}")
    if len(entity_ids) != len(entity_rows):
        failures.append("duplicate entity vector IDs")
    if len(relation_ids) != len(relation_rows):
        failures.append("duplicate relationship vector IDs")

    entity_vector_canonical_ids = [str(row.get("canonical_id") or row.get("entity_name") or "") for row in entity_rows]
    duplicate_entity_canonical_ids = sorted(item for item, count in Counter(entity_vector_canonical_ids).items() if item and count > 1)
    if duplicate_entity_canonical_ids:
        failures.append(f"duplicate canonical IDs in entity vector metadata: {duplicate_entity_canonical_ids[:10]}")
    if any(not item for item in entity_vector_canonical_ids):
        failures.append("one or more entity vectors have no canonical_id metadata")
    entity_vector_id_set = set(entity_vector_canonical_ids) - {""}
    if entity_vector_id_set != target_vertex_ids:
        failures.append(f"entity vector canonical IDs do not equal graph vertices: missing={len(target_vertex_ids - entity_vector_id_set)} extra={len(entity_vector_id_set - target_vertex_ids)}")

    target_edge_sets = {tuple(sorted({str(vertex) for vertex in edge})) for edge in target_graph["e_data"]}
    relationship_id_sets: list[tuple[str, ...]] = []
    for row in relation_rows:
        id_set = tuple(sorted({str(item) for item in (row.get("id_set") or [])}))
        relationship_id_sets.append(id_set)
        expected = relationship_vector_id(id_set)
        if row.get("__id__") != expected:
            failures.append(f"unstable relationship vector ID: {row.get('__id__')} expected={expected}")
            break
        unknown_vertices = sorted(set(id_set) - target_vertex_ids)
        if unknown_vertices:
            failures.append(f"relationship vector references missing graph vertices: {unknown_vertices[:10]}")
            break
    duplicate_relationship_sets = sorted(item for item, count in Counter(relationship_id_sets).items() if count > 1)
    if duplicate_relationship_sets:
        failures.append(f"duplicate relationship vector id_set values: {duplicate_relationship_sets[:10]}")
    relationship_id_set = set(relationship_id_sets)
    if relationship_id_set != target_edge_sets:
        failures.append(f"relationship vector id_set values do not equal graph hyperedges: missing={len(target_edge_sets - relationship_id_set)} extra={len(relationship_id_set - target_edge_sets)}")

    known_docs = {str(item) for item in source_docs}
    known_docs.update({match for value in source_docs.values() for match in extract_ids(value, r"RFB_\d{3}")})
    known_docs.update({chunk_doc_id(str(cid), value) for cid, value in source_chunks.items()})
    known_docs.discard("")
    known_chunks = {str(item) for item in source_chunks}
    for node_id, data in target_graph["v_data"].items():
        unknown_docs = set(extract_ids(data, r"RFB_\d{3}")) - known_docs
        unknown_chunks = set(extract_ids(data, r"RFB_\d{3}_CHK_\d{3}")) - known_chunks
        if unknown_docs or unknown_chunks:
            failures.append(f"invalid source references on vertex {node_id}: docs={sorted(unknown_docs)} chunks={sorted(unknown_chunks)}")
            break
    for edge in edge_records(target_graph):
        unknown_docs = set(extract_ids(edge["data"], r"RFB_\d{3}")) - known_docs
        unknown_chunks = set(extract_ids(edge["data"], r"RFB_\d{3}_CHK_\d{3}")) - known_chunks
        if unknown_docs or unknown_chunks:
            failures.append(f"invalid source references on hyperedge {edge['vertices']}: docs={sorted(unknown_docs)} chunks={sorted(unknown_chunks)}")
            break

    negative_pairs = load_negative_pairs(negative_paths)
    source_features = {str(node): extract_features(str(node), data) for node, data in source_graph["v_data"].items()}
    required_violation_keys = (
        "chemical_formula_conflict_merge",
        "oxidation_state_conflict_merge",
        "charge_or_phase_conflict_merge",
        "model_or_grade_conflict_merge",
        "numeric_condition_conflict_merge",
        "performance_metric_conflict_merge",
        "incompatible_entity_type_merge",
        "base_modified_composite_conflict_merge",
        "negative_rule_violation_merge",
        "low_confidence_positive_merge",
        "accepted_merge_status_violation",
        "accepted_merge_decision_violation",
        "accepted_merge_missing_current_decision",
    )
    violation_counts = Counter({key: 0 for key in required_violation_keys})

    def violation_key(reason: str | None) -> str:
        text = str(reason or "").lower()
        if "chemical formula" in text:
            return "chemical_formula_conflict_merge"
        if "oxidation-state" in text:
            return "oxidation_state_conflict_merge"
        if "charge conflict" in text or "phase/state" in text:
            return "charge_or_phase_conflict_merge"
        if "model/grade" in text:
            return "model_or_grade_conflict_merge"
        if "numeric condition" in text:
            return "numeric_condition_conflict_merge"
        if "performance metric" in text:
            return "performance_metric_conflict_merge"
        if "incompatible entity types" in text:
            return "incompatible_entity_type_merge"
        if "base/modified/composite" in text:
            return "base_modified_composite_conflict_merge"
        if "negative/high-risk" in text:
            return "negative_rule_violation_merge"
        return "other_hard_rule_violation"

    for cluster in clusters:
        members = [str(item) for item in (cluster.get("members") or [])]
        if len(members) > 1 and float(cluster.get("merge_confidence") or 0) < merge_confidence:
            violation_counts["low_confidence_positive_merge"] += 1
        for left, right in itertools.combinations(members, 2):
            if left not in source_features or right not in source_features:
                violation_counts["canonical_cluster_unknown_member"] += 1
                continue
            decision, reason = risk_filter(source_features[left], source_features[right], negative_pairs)
            if decision:
                violation_counts[violation_key(reason)] += 1

    state = json.loads((work / "normalization_state.json").read_text(encoding="utf-8"))
    initial_hashes = state.get("source_checksums") or {}
    current_hashes = source_checksums(source)
    if initial_hashes != current_hashes:
        failures.append("source cache changed during normalization")

    candidates = read_jsonl(work / "normalization_candidates.jsonl")
    candidate_ids = {str(row.get("pair_id")) for row in candidates if row.get("pair_id")}
    latest_decisions = _decision_by_pair(read_jsonl(work / "normalization_decisions.jsonl"))
    current_decisions = {pair_id: row for pair_id, row in latest_decisions.items() if pair_id in candidate_ids}
    missing_decision_ids = sorted(candidate_ids - set(current_decisions))
    if missing_decision_ids:
        failures.append(f"candidate pairs missing decisions: count={len(missing_decision_ids)} examples={missing_decision_ids[:10]}")
    invalid_decisions = sorted({str(row.get("decision") or "") for row in current_decisions.values()} - DECISIONS)
    if invalid_decisions:
        failures.append(f"invalid normalization decisions: {invalid_decisions}")
    decision_distribution = {decision: 0 for decision in sorted(DECISIONS)}
    for row in current_decisions.values():
        decision = str(row.get("decision") or "UNCERTAIN")
        if decision in decision_distribution:
            decision_distribution[decision] += 1

    accepted_merge_edges = canonical_map.get("accepted_merge_edges") or []
    for row in accepted_merge_edges:
        pair_id = str(row.get("pair_id") or "")
        if row.get("status") != "ok":
            violation_counts["accepted_merge_status_violation"] += 1
        if str(row.get("decision") or "") not in POSITIVE or float(row.get("confidence") or 0) < merge_confidence:
            violation_counts["accepted_merge_decision_violation"] += 1
        latest = current_decisions.get(pair_id)
        if latest is None or latest.get("status") != "ok" or str(latest.get("decision") or "") not in POSITIVE or float(latest.get("confidence") or 0) < merge_confidence:
            violation_counts["accepted_merge_missing_current_decision"] += 1

    nonzero_violations = {key: value for key, value in violation_counts.items() if value}
    if nonzero_violations:
        failures.append("hard-rule merge violations: " + json.dumps(nonzero_violations, ensure_ascii=False))

    cluster_sizes = Counter("singleton" if len(row.get("members") or []) == 1 else "pair" if len(row.get("members") or []) == 2 else "multi" for row in clusters)
    source_type_counts = Counter(feature.entity_type for feature in source_features.values())
    normalized_type_counts = Counter()
    for cluster in clusters:
        for entity_type in set(cluster.get("entity_types") or []):
            normalized_type_counts[entity_type] += 1
    type_compression = {
        entity_type: {
            "before": count,
            "after": normalized_type_counts.get(entity_type, 0),
            "compression_rate": (count - normalized_type_counts.get(entity_type, 0)) / count if count else 0.0,
        }
        for entity_type, count in sorted(source_type_counts.items())
    }
    rewrite_summary = _load_json_dict(work / "normalization_rewrite_summary.json")
    summary = {
        "validation_passed": not failures,
        "validation_failures": failures,
        "original_entity_count": len(source_vertex_ids),
        "normalized_entity_count": len(target_vertex_ids),
        "entity_compression_rate": (len(source_vertex_ids) - len(target_vertex_ids)) / len(source_vertex_ids) if source_vertex_ids else 0.0,
        "candidate_pair_count": len(candidates),
        "candidate_pairs_with_decisions": len(current_decisions),
        "candidate_pairs_missing_decisions": len(missing_decision_ids),
        "decision_distribution": decision_distribution,
        "merged_cluster_count": sum(1 for row in clusters if len(row.get("members") or []) > 1),
        "merged_alias_count": sum(max(0, len(row.get("members") or []) - 1) for row in clusters),
        "cluster_size_distribution": dict(cluster_sizes),
        "low_order_relations_before": rewrite_summary.get("low_order_before", 0),
        "high_order_relations_before": rewrite_summary.get("high_order_before", 0),
        "low_order_relations_after": rewrite_summary.get("low_order_after", 0),
        "high_order_relations_after": rewrite_summary.get("high_order_after", 0),
        "collapsed_self_relations_removed": rewrite_summary.get("collapsed_self_relations_removed", 0),
        "hyperedges_degraded": rewrite_summary.get("hyperedges_degraded", 0),
        "duplicate_hyperedges_merged": rewrite_summary.get("duplicate_hyperedges_merged", 0),
        "entity_type_compression": type_compression,
        "api_statistics": state.get("api_statistics") or {},
        "hard_rule_violation_counts": {key: violation_counts.get(key, 0) for key in sorted(violation_counts)},
        "documents": len(target_docs),
        "chunks": len(target_chunks),
        "chunk_vectors": len(chunk_rows),
        "entity_vectors": len(entity_rows),
        "relationship_vectors": len(relation_rows),
    }
    write_json(work / "normalization_summary.json", summary)
    if failures:
        raise RuntimeError("Post-hoc normalization validation failed:\n- " + "\n- ".join(failures))
    return summary


def update_run_config(source: Path, work: Path, *, merge_confidence: float, llm_model: str, embedding_model: str, candidate_top_k: int, source_hashes: dict[str, str]) -> None:
    config = _load_json_dict(source / "run_config.json")
    config.update({
        "parent_cache": str(source.resolve()),
        "parent_cache_checksums": source_hashes,
        "normalization_mode": "posthoc",
        "normalization_version": NORMALIZATION_VERSION,
        "normalization_decision_model": llm_model,
        "merge_confidence": merge_confidence,
        "enable_entity_normalization": True,
        "index_profile": "canonical_only",
        "candidate_version": CANDIDATE_VERSION,
        "candidate_thresholds": {"candidate_top_k": candidate_top_k, "wratio": 88, "token_set_ratio": 90, "cosine": 0.82, "cosine_with_lexical": 0.78},
        "prompt_version": PROMPT_VERSION,
        "embedding_model": embedding_model,
        "embedding_dim": 2560,
    })
    write_json(work / "run_config.json", config)


class TargetCacheLock:
    def __init__(self, target: Path):
        self.path = target.parent / f".{target.name}.lock"
        self.fd: int | None = None

    def __enter__(self) -> "TargetCacheLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise RuntimeError(f"Another normalization process may be writing this target: {self.path}") from exc
        os.write(self.fd, f"pid={os.getpid()} started={time.time()}".encode("utf-8"))
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


def prepare_work(source: Path, target: Path, *, resume: bool) -> tuple[Path, dict[str, Any]]:
    source, target = source.resolve(), target.resolve()
    if source == target:
        raise ValueError("source-cache and target-cache must be different")
    if not source.exists():
        raise FileNotFoundError(source)
    if target.exists():
        raise FileExistsError(f"Target cache already exists and will not be overwritten: {target}")
    work = target.with_name(target.name + ".work")
    state_path = work / "normalization_state.json"
    if work.exists() and not resume:
        raise FileExistsError(f"Work directory exists; pass --resume or choose another target: {work}")
    work.mkdir(parents=True, exist_ok=True)
    current_hashes = source_checksums(source)
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if Path(state.get("source_cache", "")).resolve() != source:
            raise RuntimeError("Work directory belongs to a different source cache")
        if state.get("source_checksums") != current_hashes:
            raise RuntimeError("Source cache differs from the cache used to create this work directory")
    else:
        state = {"source_cache": str(source), "target_cache": str(target), "source_checksums": current_hashes, "normalization_version": NORMALIZATION_VERSION, "stages": {}, "api_statistics": {}}
        write_json(state_path, state)
    return work, state


def update_state(work: Path, stage: str, status: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    path = work / "normalization_state.json"
    state = json.loads(path.read_text(encoding="utf-8"))
    state.setdefault("stages", {})[stage] = {"status": status, "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "details": details or {}}
    write_json(path, state)
    return state


def publish_work(work: Path, target: Path) -> None:
    if target.exists():
        raise FileExistsError(f"Refusing to replace existing target cache: {target}")
    os.replace(work, target)
