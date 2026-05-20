import sys
import asyncio
import json
import re
import traceback
import time
from datetime import datetime
from typing import Union
from collections import Counter, defaultdict
import warnings


from .utils import (
    logger,
    clean_str,
    compute_mdhash_id,
    decode_tokens_by_tiktoken,
    encode_string_by_tiktoken,
    is_float_regex,
    list_of_list_to_csv,
    pack_user_ass_to_openai_messages,
    split_string_by_multi_markers,
    truncate_list_by_token_size,
    process_combine_contexts,
    deduplicate_by_key,
)
from .base import (
    BaseKVStorage,
    BaseVectorStorage,
    TextChunkSchema,
    QueryParam, BaseHypergraphStorage,
)

# Import domain manager for multi-domain support
try:
    from .domains.domain_manager import domain_manager
    from .domains.validator import DomainValidator
    DOMAIN_SUPPORT_AVAILABLE = True
except ImportError:
    DOMAIN_SUPPORT_AVAILABLE = False
    domain_manager = None
    DomainValidator = None

from .prompt import GRAPH_FIELD_SEP, PROMPTS

# ========== JSON Output Support Functions ==========

def _format_llm_exception(error: Exception) -> str:
    """Expand Tenacity/OpenAI wrapper errors so chunk-step logs show the provider error."""
    messages = [f"{type(error).__name__}: {error}"]

    try:
        last_attempt = getattr(error, "last_attempt", None)
        inner_error = last_attempt.exception() if last_attempt else None
        if inner_error is not None:
            messages.append(f"{type(inner_error).__name__}: {inner_error}")
            for attr in ("body", "status_code", "code"):
                value = getattr(inner_error, attr, None)
                if value:
                    messages.append(f"{attr}={value}")
    except Exception:
        pass

    for chain_attr in ("__cause__", "__context__"):
        try:
            chained = getattr(error, chain_attr, None)
            if chained is not None:
                messages.append(f"{chain_attr}={type(chained).__name__}: {chained}")
                for attr in ("body", "status_code", "code"):
                    value = getattr(chained, attr, None)
                    if value:
                        messages.append(f"{chain_attr}.{attr}={value}")
        except Exception:
            pass

    return " | ".join(dict.fromkeys(str(message) for message in messages))

def _log_step_exception(chunk_key: str, step: str, label: str, error: Exception) -> None:
    detail = _format_llm_exception(error)
    logger.error(f"[{chunk_key}] {step} FAILED - {label}: {detail}")
    logger.debug(
        f"[{chunk_key}] {step} FAILED traceback:\n"
        f"{''.join(traceback.format_exception(type(error), error, error.__traceback__))}"
    )

def parse_json_entities(json_str: str, chunk_key: str = "") -> list:
    """
    Parse JSON format entity output from LLM with enhanced error handling

    Args:
        json_str: JSON string from LLM
        chunk_key: Chunk key for error reporting

    Returns:
        List of entity dictionaries
    """
    import re

    # Log the raw response for debugging
    logger.debug(f"[{chunk_key}] parse_json_entities: Raw response (first 500 chars): {json_str[:500]}")

    # Remove markdown code blocks if present
    json_str = re.sub(r'```json\s*', '', json_str)
    json_str = re.sub(r'```\s*', '', json_str)
    json_str = json_str.strip()

    # Try to extract JSON array from the response
    json_match = re.search(r'\[.*\]', json_str, re.DOTALL)
    if not json_match:
        logger.warning(f"[{chunk_key}] parse_json_entities: No JSON array found in response (first 200 chars): {json_str[:200]}")
        # Try to find JSON object instead
        json_match = re.search(r'\{.*\}', json_str, re.DOTALL)
        if json_match:
            logger.info(f"[{chunk_key}] parse_json_entities: Found JSON object instead of array, wrapping in array")
            json_str = f"[{json_match.group()}]"
            json_match = re.search(r'\[.*\]', json_str, re.DOTALL)

    if not json_match:
        logger.error(f"[{chunk_key}] parse_json_entities: No valid JSON found, full response (first 1000 chars): {json_str[:1000]}")
        return []

    try:
        extracted_json = json_match.group()
        logger.debug(f"[{chunk_key}] parse_json_entities: Extracted JSON (first 500 chars): {extracted_json[:500]}")
        entities = json.loads(extracted_json)
        if not isinstance(entities, list):
            logger.info(f"[{chunk_key}] parse_json_entities: JSON is not an array, wrapping in list")
            entities = [entities]
        logger.debug(f"[{chunk_key}] parse_json_entities: Successfully parsed {len(entities)} entities")
        return entities
    except json.JSONDecodeError as e:
        logger.warning(f"[{chunk_key}] parse_json_entities: JSON decode error at position {e.pos}: {e.msg}")
        logger.debug(f"[{chunk_key}] parse_json_entities: Problematic JSON (first 500 chars): {json_match.group()[:500]}")

        # Try to fix common JSON issues
        try:
            fixed_json = json_match.group()

            # Fix 1: Remove trailing commas
            fixed_json = re.sub(r',\s*([}\]])', r'\1', fixed_json)

            # Fix 2: Remove backticks and markdown
            fixed_json = re.sub(r'```[a-z]*', '', fixed_json)
            fixed_json = re.sub(r'```', '', fixed_json)

            # Fix 3: Remove extra whitespace
            fixed_json = re.sub(r'\s+', ' ', fixed_json)

            logger.debug(f"[{chunk_key}] parse_json_entities: Attempting to fix JSON...")
            entities = json.loads(fixed_json)
            if not isinstance(entities, list):
                entities = [entities]
            logger.info(f"[{chunk_key}] parse_json_entities: Successfully parsed after fixing: {len(entities)} entities")
            return entities
        except Exception as e2:
            logger.warning(f"[{chunk_key}] parse_json_entities: Fix attempt failed: {e2}")
            logger.error(f"[{chunk_key}] parse_json_entities: LLM returned invalid JSON format. Consider switching to a model with better JSON output support.")
        return []

def parse_json_relations(json_str: str, chunk_key: str = "") -> list:
    """
    Parse JSON format relationship output from LLM with enhanced error handling

    Args:
        json_str: JSON string from LLM
        chunk_key: Chunk key for error reporting

    Returns:
        List of relationship dictionaries
    """
    import re

    # Log the raw response for debugging
    logger.debug(f"[{chunk_key}] parse_json_relations: Raw response (first 500 chars): {json_str[:500]}")

    # Remove markdown code blocks if present
    json_str = re.sub(r'```json\s*', '', json_str)
    json_str = re.sub(r'```\s*', '', json_str)
    json_str = json_str.strip()

    # Try to extract JSON array from the response
    json_match = re.search(r'\[.*\]', json_str, re.DOTALL)
    if not json_match:
        logger.warning(f"[{chunk_key}] parse_json_relations: No JSON array found in response (first 200 chars): {json_str[:200]}")
        # Try to find JSON object instead
        json_match = re.search(r'\{.*\}', json_str, re.DOTALL)
        if json_match:
            logger.info(f"[{chunk_key}] parse_json_relations: Found JSON object instead of array, wrapping in array")
            json_str = f"[{json_match.group()}]"
            json_match = re.search(r'\[.*\]', json_str, re.DOTALL)

    if not json_match:
        logger.error(f"[{chunk_key}] parse_json_relations: No valid JSON found, full response (first 1000 chars): {json_str[:1000]}")
        return []

    try:
        extracted_json = json_match.group()
        logger.debug(f"[{chunk_key}] parse_json_relations: Extracted JSON (first 500 chars): {extracted_json[:500]}")
        relations = json.loads(extracted_json)
        if not isinstance(relations, list):
            logger.info(f"[{chunk_key}] parse_json_relations: JSON is not an array, wrapping in list")
            relations = [relations]
        logger.debug(f"[{chunk_key}] parse_json_relations: Successfully parsed {len(relations)} relations")
        return relations
    except json.JSONDecodeError as e:
        logger.warning(f"[{chunk_key}] parse_json_relations: JSON decode error at position {e.pos}: {e.msg}")
        logger.debug(f"[{chunk_key}] parse_json_relations: Problematic JSON (first 500 chars): {json_match.group()[:500]}")

        # Try to fix common JSON issues
        try:
            fixed_json = json_match.group()

            # Fix 1: Remove trailing commas
            fixed_json = re.sub(r',\s*([}\]])', r'\1', fixed_json)

            # Fix 2: Remove backticks and markdown
            fixed_json = re.sub(r'```[a-z]*', '', fixed_json)
            fixed_json = re.sub(r'```', '', fixed_json)

            # Fix 3: Remove extra whitespace
            fixed_json = re.sub(r'\s+', ' ', fixed_json)

            logger.debug(f"[{chunk_key}] parse_json_relations: Attempting to fix JSON...")
            relations = json.loads(fixed_json)
            if not isinstance(relations, list):
                relations = [relations]
            logger.info(f"[{chunk_key}] parse_json_relations: Successfully parsed after fixing: {len(relations)} relations")
            return relations
        except Exception as e2:
            logger.warning(f"[{chunk_key}] parse_json_relations: Fix attempt failed: {e2}")
        return []

def parse_json_hyperedges(json_str: str, chunk_key: str = "") -> list:
    """
    Parse JSON format hyperedge output from LLM with enhanced error handling

    Args:
        json_str: JSON string from LLM
        chunk_key: Chunk key for error reporting

    Returns:
        List of hyperedge dictionaries
    """
    import re

    # Log the raw response for debugging
    logger.debug(f"[{chunk_key}] parse_json_hyperedges: Raw response (first 500 chars): {json_str[:500]}")

    # Remove markdown code blocks if present
    json_str = re.sub(r'```json\s*', '', json_str)
    json_str = re.sub(r'```\s*', '', json_str)
    json_str = json_str.strip()

    # Try to extract JSON array from the response
    json_match = re.search(r'\[.*\]', json_str, re.DOTALL)
    if not json_match:
        logger.warning(f"[{chunk_key}] parse_json_hyperedges: No JSON array found in response (first 200 chars): {json_str[:200]}")
        # Try to find JSON object instead
        json_match = re.search(r'\{.*\}', json_str, re.DOTALL)
        if json_match:
            logger.info(f"[{chunk_key}] parse_json_hyperedges: Found JSON object instead of array, wrapping in array")
            json_str = f"[{json_match.group()}]"
            json_match = re.search(r'\[.*\]', json_str, re.DOTALL)

    if not json_match:
        logger.error(f"[{chunk_key}] parse_json_hyperedges: No valid JSON found, full response (first 1000 chars): {json_str[:1000]}")
        return []

    try:
        extracted_json = json_match.group()
        logger.debug(f"[{chunk_key}] parse_json_hyperedges: Extracted JSON (first 500 chars): {extracted_json[:500]}")
        hyperedges = json.loads(extracted_json)
        if not isinstance(hyperedges, list):
            logger.info(f"[{chunk_key}] parse_json_hyperedges: JSON is not an array, wrapping in list")
            hyperedges = [hyperedges]
        logger.debug(f"[{chunk_key}] parse_json_hyperedges: Successfully parsed {len(hyperedges)} hyperedges")
        return hyperedges
    except json.JSONDecodeError as e:
        logger.warning(f"[{chunk_key}] parse_json_hyperedges: JSON decode error at position {e.pos}: {e.msg}")
        logger.debug(f"[{chunk_key}] parse_json_hyperedges: Problematic JSON (first 500 chars): {json_match.group()[:500]}")

        # Try to fix common JSON issues
        try:
            fixed_json = json_match.group()

            # Fix 1: Remove trailing commas
            fixed_json = re.sub(r',\s*([}\]])', r'\1', fixed_json)

            # Fix 2: Remove backticks and markdown
            fixed_json = re.sub(r'```[a-z]*', '', fixed_json)
            fixed_json = re.sub(r'```', '', fixed_json)

            # Fix 3: Remove extra whitespace
            fixed_json = re.sub(r'\s+', ' ', fixed_json)

            logger.debug(f"[{chunk_key}] parse_json_hyperedges: Attempting to fix JSON...")
            hyperedges = json.loads(fixed_json)
            if not isinstance(hyperedges, list):
                hyperedges = [hyperedges]
            logger.info(f"[{chunk_key}] parse_json_hyperedges: Successfully parsed after fixing: {len(hyperedges)} hyperedges")
            return hyperedges
        except Exception as e2:
            logger.warning(f"[{chunk_key}] parse_json_hyperedges: Fix attempt failed: {e2}")
        return []

def parse_json_combined_relationships(json_str: str, chunk_key: str = "") -> tuple[list, list]:
    """
    Parse combined relationship extraction output.

    Expected format:
    {
      "low_order_relations": [...],
      "high_order_hyperedges": [...]
    }
    """
    logger.debug(f"[{chunk_key}] parse_json_combined_relationships: Raw response (first 500 chars): {json_str[:500]}")

    json_str = re.sub(r'```json\s*', '', json_str)
    json_str = re.sub(r'```\s*', '', json_str)
    json_str = json_str.strip()

    json_match = re.search(r'\{.*\}', json_str, re.DOTALL)
    if not json_match:
        logger.error(f"[{chunk_key}] parse_json_combined_relationships: No JSON object found (first 1000 chars): {json_str[:1000]}")
        return [], []

    extracted_json = json_match.group()
    try:
        data = json.loads(extracted_json)
    except json.JSONDecodeError as e:
        logger.warning(f"[{chunk_key}] parse_json_combined_relationships: JSON decode error at position {e.pos}: {e.msg}")
        try:
            fixed_json = re.sub(r',\s*([}\]])', r'\1', extracted_json)
            fixed_json = re.sub(r'\s+', ' ', fixed_json)
            data = json.loads(fixed_json)
            logger.info(f"[{chunk_key}] parse_json_combined_relationships: Successfully parsed after fixing")
        except Exception as e2:
            logger.warning(f"[{chunk_key}] parse_json_combined_relationships: Fix attempt failed: {e2}")
            return [], []

    if not isinstance(data, dict):
        logger.warning(f"[{chunk_key}] parse_json_combined_relationships: Expected object, got {type(data)}")
        return [], []

    low_relations = data.get("low_order_relations", [])
    high_relations = data.get("high_order_hyperedges", [])

    if not isinstance(low_relations, list):
        logger.warning(f"[{chunk_key}] parse_json_combined_relationships: low_order_relations is not a list")
        low_relations = []
    if not isinstance(high_relations, list):
        logger.warning(f"[{chunk_key}] parse_json_combined_relationships: high_order_hyperedges is not a list")
        high_relations = []

    logger.info(
        f"[{chunk_key}] parse_json_combined_relationships: Parsed "
        f"{len(low_relations)} low-order relations and {len(high_relations)} high-order hyperedges"
    )
    return low_relations, high_relations

def convert_json_entity_to_standard_format(entity: dict, chunk_key: str = "") -> dict:
    """
    Convert JSON entity format to standard Hyper-RAG entity format
    Preserves structured fields (subtype, value, unit, etc.) as native types
    for structured queries (e.g., "find temperature > 40°C")
    """
    result = {
        "entity_name": entity.get("name", ""),
        "entity_type": entity.get("type", ""),
        "description": entity.get("description", ""),
        "source_id": chunk_key,
    }

    # Preserve structured fields as native types (not flattened strings)
    if entity.get("subtype") is not None:
        result["subtype"] = entity["subtype"]

    # Handle value or value range - keep as numbers for comparisons
    if entity.get("value") is not None:
        result["value"] = entity["value"]
    elif entity.get("value_min") is not None or entity.get("value_max") is not None:
        if entity.get("value_min") is not None:
            result["value_min"] = entity["value_min"]
        if entity.get("value_max") is not None:
            result["value_max"] = entity["value_max"]

    if entity.get("unit") is not None:
        result["unit"] = entity["unit"]

    if entity.get("key_attribute") is not None:
        result["key_attribute"] = entity["key_attribute"]

    return result

def convert_json_relation_to_standard_format(relation: dict, chunk_key: str = "") -> dict:
    """
    Convert JSON relation format to standard Hyper-RAG relation format
    Preserves evidence_span and relation_type for retrieval and traceability
    """
    # For low-order relations (pair relationships)
    if "source" in relation and "target" in relation:
        result = {
            "entityN": (relation["source"], relation["target"]),
            "entities_pair": (relation["source"], relation["target"]),
            "weight": float(relation.get("strength", 5)) / 10.0,
            "description": relation.get("description", ""),
            "keywords": relation.get("keywords", ""),
            "source_id": chunk_key,
            "level_hg": "Low-order Hyperedge",
        }
        # Preserve relation_type and evidence_span if present
        if relation.get("relation_type"):
            result["relation_type"] = relation["relation_type"]
        if relation.get("evidence_span"):
            result["evidence_span"] = relation["evidence_span"]
        return result

    # For high-order relations (hyperedges)
    elif "vertices" in relation:
        vertices = relation["vertices"]
        result = {
            "entityN": tuple(vertices),
            "entities_set": tuple(vertices),
            "weight": float(relation.get("strength", 5)) / 10.0,
            "description": relation.get("description", ""),
            "keywords": relation.get("keywords", ""),
            "source_id": chunk_key,
            "level_hg": "High-order Hyperedge",
        }
        # Preserve relation_type and evidence_span for traceability
        if relation.get("relation_type"):
            result["relation_type"] = relation["relation_type"]
        if relation.get("evidence_span"):
            result["evidence_span"] = relation["evidence_span"]
        return result

    return {}

_SUBSCRIPT_TRANSLATION = str.maketrans({
    "₀": "0", "₁": "1", "₂": "2", "₃": "3", "₄": "4",
    "₅": "5", "₆": "6", "₇": "7", "₈": "8", "₉": "9",
    "⁰": "0", "¹": "1", "²": "2", "³": "3", "⁴": "4",
    "⁵": "5", "⁶": "6", "⁷": "7", "⁸": "8", "⁹": "9",
})

def _normalize_entity_reference(value: str) -> str:
    value = str(value or "").translate(_SUBSCRIPT_TRANSLATION).lower()
    value = re.sub(r"\[u\+208([0-9])\]", r"\1", value)
    value = re.sub(r"\[u\+207([0-9])\]", r"\1", value)
    value = re.sub(r"[\s_\-–—−]+", "", value)
    return value

def _strip_numeric_suffix_for_lookup(value: str) -> str:
    value = str(value or "").translate(_SUBSCRIPT_TRANSLATION).lower()
    value = re.sub(r"\b\d+(?:\.\d+)?\s*(?:%|mg/l|g/l|mol/l|mmol|mm|h|min|s|khz|w|mpa|cycles?|cycle|ppm|ppb)\b", "", value)
    value = re.sub(r"\b\d+(?:\.\d+)?\b", "", value)
    value = re.sub(r"[\s_\-–—−]+", "", value)
    return value

def _build_entity_reference_lookup(entities_json: list[dict]) -> dict[str, str]:
    lookup = {}

    def add(key: str, name: str):
        if not key:
            return
        existing = lookup.get(key)
        if existing is None:
            lookup[key] = name
        elif existing != name:
            lookup[key] = ""

    for entity in entities_json:
        name = entity.get("name", "")
        if not name:
            continue
        add(_normalize_entity_reference(name), name)
        if entity.get("type") in {"CONDITION", "METRIC"}:
            add(_strip_numeric_suffix_for_lookup(name), name)

    return {key: value for key, value in lookup.items() if value}

def _canonicalize_entity_reference(value: str, lookup: dict[str, str]) -> str | None:
    return lookup.get(_normalize_entity_reference(value)) or lookup.get(_strip_numeric_suffix_for_lookup(value))

def _filter_relations_to_known_entities(
    low_relations: list[dict],
    high_relations: list[dict],
    entities_json: list[dict],
    chunk_key: str,
) -> tuple[list[dict], list[dict]]:
    """Ensure relation vertices reference entities from the current chunk extraction."""
    lookup = _build_entity_reference_lookup(entities_json)
    filtered_low = []
    filtered_high = []
    skipped = []

    for relation in low_relations:
        source = _canonicalize_entity_reference(relation.get("source"), lookup)
        target = _canonicalize_entity_reference(relation.get("target"), lookup)
        if not source or not target:
            skipped.append({
                "kind": "low",
                "missing": [x for x, y in [(relation.get("source"), source), (relation.get("target"), target)] if not y],
                "relation_type": relation.get("relation_type"),
            })
            continue
        relation = dict(relation)
        relation["source"] = source
        relation["target"] = target
        filtered_low.append(relation)

    for relation in high_relations:
        vertices = relation.get("vertices", [])
        canonical_vertices = []
        missing_vertices = []
        for vertex in vertices:
            canonical = _canonicalize_entity_reference(vertex, lookup)
            if canonical:
                canonical_vertices.append(canonical)
            else:
                missing_vertices.append(vertex)
        if missing_vertices or len(set(canonical_vertices)) < 3:
            skipped.append({
                "kind": "high",
                "missing": missing_vertices,
                "relation_type": relation.get("relation_type"),
            })
            continue
        relation = dict(relation)
        relation["vertices"] = list(dict.fromkeys(canonical_vertices))
        filtered_high.append(relation)

    if skipped:
        logger.warning(
            f"[{chunk_key}] Relation entity validation skipped {len(skipped)} invalid relations/hyperedges; "
            f"examples={skipped[:5]}"
        )

    return filtered_low, filtered_high

def validate_domain_output(entities: list, relations: list, domain: str = 'default'):
    """
    Validate domain-specific output using DomainValidator

    Args:
        entities: List of entities
        relations: List of relations
        domain: Domain name

    Returns:
        Validation results
    """
    if not DOMAIN_SUPPORT_AVAILABLE or domain == 'default':
        return {"valid": True, "errors": []}

    try:
        domain_config = domain_manager.load_domain_config(domain)
        validator = DomainValidator()

        # Validate entities
        entity_errors = []
        for i, entity in enumerate(entities):
            if not isinstance(entity, dict):
                continue
            errors = validator.validate_entity(entity, domain_config)
            if errors:
                entity_errors.extend([f"Entity {i}: {error}" for error in errors])

        # Validate relations
        relation_errors = []
        for i, relation in enumerate(relations):
            if not isinstance(relation, dict):
                continue
            if "vertices" in relation:  # Hyperedge
                errors = validator.validate_hyperedge(relation, domain_config)
            else:  # Low-order relation
                errors = validator.validate_relation(relation, domain_config)

            if errors:
                relation_errors.extend([f"Relation {i}: {error}" for error in errors])

        all_errors = entity_errors + relation_errors

        return {
            "valid": len(all_errors) == 0,
            "errors": all_errors,
            "entity_errors_count": len(entity_errors),
            "relation_errors_count": len(relation_errors)
        }

    except Exception as e:
        logger.warning(f"Error validating domain output: {e}")
        return {"valid": True, "errors": [], "validation_failed": str(e)}

def get_domain_from_config(global_config: dict) -> str:
    """
    Get current domain from global configuration

    Args:
        global_config: Global configuration dictionary

    Returns:
        Domain name
    """
    return global_config.get("domain", "default")

def is_json_output_domain(domain: str) -> bool:
    """
    Check if domain uses JSON output format

    Args:
        domain: Domain name

    Returns:
        True if domain uses JSON output, False otherwise
    """
    if not DOMAIN_SUPPORT_AVAILABLE:
        return False

    try:
        output_format = domain_manager.get_output_format(domain)
        return output_format == "json"
    except:
        return False

def _get_query_keywords_prompt(query: str, global_config: dict) -> str:
    """
    Build query-keyword prompt from the active domain when available.
    Falls back to the original generic keyword prompt.
    """
    current_domain = get_domain_from_config(global_config)
    if current_domain != "default":
        try:
            from .prompt import get_query_keywords_prompt

            return get_query_keywords_prompt(
                domain=current_domain,
                query=query,
                QUERY=query,
            )
        except Exception as e:
            logger.warning(f"Failed to load domain query keyword prompt for '{current_domain}': {e}")

    return PROMPTS["keywords_extraction"].format(query=query)

def _parse_query_keywords(result: str, kw_prompt: str, need_relation_keywords: bool = True) -> tuple[str, str]:
    """
    Parse keyword extraction JSON while preserving the existing retrieval contract.
    Supports both high/low fields and older domain prompt aliases.
    """
    def _as_list(value):
        if value is None:
            return []
        if isinstance(value, list):
            return [str(v) for v in value if v is not None]
        if isinstance(value, str):
            return [value] if value.strip() else []
        return [str(value)]

    try:
        keywords_data = json.loads(result)
    except json.JSONDecodeError:
        result = (
            result.replace(kw_prompt[:-1], "")
            .replace("user", "")
            .replace("model", "")
            .strip()
        )
        if "{" not in result or "}" not in result:
            raise json.JSONDecodeError("No JSON object found in keyword extraction result", result, 0)
        result = "{" + result.split("{", 1)[1].split("}", 1)[0] + "}"
        keywords_data = json.loads(result)

    entity_keywords = _as_list(keywords_data.get("low_level_keywords", []))
    if not entity_keywords:
        entity_keywords = _as_list(keywords_data.get("entity_keywords", []))

    relation_keywords = []
    if need_relation_keywords:
        relation_keywords = _as_list(keywords_data.get("high_level_keywords", []))
        if not relation_keywords:
            relation_keywords = _as_list(keywords_data.get("theme_keywords", []))

    condition_keywords = _as_list(keywords_data.get("condition_keywords", []))
    if condition_keywords:
        entity_keywords = entity_keywords + condition_keywords

    return ", ".join(entity_keywords), ", ".join(relation_keywords)

def chunking_by_token_size(
    content: str, overlap_token_size=128, max_token_size=1024, tiktoken_model="gpt-4o"
):
    tokens = encode_string_by_tiktoken(content, model_name=tiktoken_model)
    results = []
    for index, start in enumerate(
        range(0, len(tokens), max_token_size - overlap_token_size)
    ):
        chunk_content = decode_tokens_by_tiktoken(
            tokens[start : start + max_token_size], model_name=tiktoken_model
        )
        results.append(
            {
                "tokens": min(max_token_size, len(tokens) - start),
                "content": chunk_content.strip(),
                "chunk_order_index": index,
            }
        )
    return results

# summarize the descriptions of the entity
async def _handle_entity_summary(
    entity_or_relation_name: str,
    description: str,
    global_config: dict,
) -> str:
    use_llm_func: callable = global_config["llm_model_func"]
    llm_max_tokens = global_config["llm_model_max_token_size"]
    tiktoken_model_name = global_config["tiktoken_model_name"]
    summary_max_tokens = global_config["entity_summary_to_max_tokens"] # 500

    tokens = encode_string_by_tiktoken(description, model_name=tiktoken_model_name)
    if len(tokens) < summary_max_tokens:  # No need for summary
        return description
    prompt_template = PROMPTS["summarize_entity_descriptions"]
    use_description = decode_tokens_by_tiktoken(
        tokens[:llm_max_tokens], model_name=tiktoken_model_name
    )
    context_base = dict(
        entity_name=entity_or_relation_name,
        description_list=use_description.split(GRAPH_FIELD_SEP),
    )
    use_prompt = prompt_template.format(**context_base)
    logger.debug(f"Trigger summary: {entity_or_relation_name}")
    summary = await use_llm_func(use_prompt, max_tokens=summary_max_tokens)
    if summary is None:
        print("entity description summary not found")
        summary = use_description
    return summary

# summarize the additional properties of the entity
async def _handle_entity_additional_properties(
    entity_name: str,
    additional_properties: str,
    global_config: dict,
) -> str:
    use_llm_func: callable = global_config["llm_model_func"]
    llm_max_tokens = global_config["llm_model_max_token_size"]
    tiktoken_model_name = global_config["tiktoken_model_name"]
    summary_max_tokens = global_config["entity_additional_properties_to_max_tokens"] # 可能需要修改 entity_properties_summary_to_max_tokens

    tokens = encode_string_by_tiktoken(additional_properties, model_name=tiktoken_model_name)
    if len(tokens) < summary_max_tokens:  # No need for summary
        return additional_properties
    prompt_template = PROMPTS["summarize_entity_additional_properties"]
    use_additional_properties = decode_tokens_by_tiktoken(
        tokens[:llm_max_tokens], model_name=tiktoken_model_name
    )
    context_base = dict(
        entity_name=entity_name,
        additional_properties_list=use_additional_properties.split(GRAPH_FIELD_SEP),
    )
    use_prompt = prompt_template.format(**context_base)
    logger.debug(f"Trigger summary: {entity_name}")
    summary = await use_llm_func(use_prompt, max_tokens=summary_max_tokens)
    if summary is None:
        print("entity additional_properties summary not found")
        summary = use_additional_properties
    return summary

# summarize the descriptions of the relation
async def _handle_relation_summary(
    relation_name: str,
    description: str,
    global_config: dict,
) -> str:
    use_llm_func: callable = global_config["llm_model_func"]
    llm_max_tokens = global_config["llm_model_max_token_size"]
    tiktoken_model_name = global_config["tiktoken_model_name"]
    summary_max_tokens = global_config["relation_summary_to_max_tokens"]  # 可能需要修改  relation_summary_to_max_tokens

    tokens = encode_string_by_tiktoken(description, model_name=tiktoken_model_name)
    if len(tokens) < summary_max_tokens:  # No need for summary
        return description
    prompt_template = PROMPTS["summarize_relation_descriptions"]
    use_description = decode_tokens_by_tiktoken(
        tokens[:llm_max_tokens], model_name=tiktoken_model_name
    )
    context_base = dict(
        relation_name=relation_name,
        relation_description_list=use_description.split(GRAPH_FIELD_SEP),
    )
    use_prompt = prompt_template.format(**context_base)
    logger.debug(f"Trigger summary: {relation_name}")
    summary = await use_llm_func(use_prompt, max_tokens=summary_max_tokens)
    if summary is None:
        print("relation description summary not found")
        summary = use_description
    return summary

# summarize the keywords of the relation
async def _handle_relation_keywords_summary(
    relation_name: str,
    keywords: str,
    global_config: dict,
) -> str:
    use_llm_func: callable = global_config["llm_model_func"]
    llm_max_tokens = global_config["llm_model_max_token_size"]
    tiktoken_model_name = global_config["tiktoken_model_name"]
    summary_max_tokens = global_config["relation_keywords_to_max_tokens"]  # 可能需要修改relation_keywords_summary_to_max_tokens

    tokens = encode_string_by_tiktoken(keywords, model_name=tiktoken_model_name)
    if len(tokens) < summary_max_tokens:  # No need for summary
        return keywords
    prompt_template = PROMPTS["summarize_relation_keywords"]
    use_keywords = decode_tokens_by_tiktoken(
        tokens[:llm_max_tokens], model_name=tiktoken_model_name
    )
    context_base = dict(
        relation_name=relation_name,
        keywords_list=use_keywords.split(GRAPH_FIELD_SEP),
    )
    use_prompt = prompt_template.format(**context_base)
    logger.debug(f"Trigger summary: {relation_name}")
    summary = await use_llm_func(use_prompt, max_tokens=summary_max_tokens)
    if summary is None:
        print("relation keywords summary not found")
        summary = use_keywords
    return summary

async def _handle_single_entity_extraction(
    record_attributes: list[str],
    chunk_key: str,
):
    if len(record_attributes) < 4 or record_attributes[0] != '"Entity"' :
        return None
    # add this record as a node in the G
    entity_name = clean_str(record_attributes[1].upper())
    if not entity_name.strip():
        return None
    entity_type = clean_str(record_attributes[2].upper())
    entity_description = clean_str(record_attributes[3])
    entity_source_id = chunk_key
    entity_additional_properties = clean_str(record_attributes[4:])

    return dict(
        entity_name=entity_name,
        entity_type=entity_type,
        description=entity_description,
        source_id=entity_source_id,
        additional_properties=entity_additional_properties,
    )


async def _handle_single_relationship_extraction_low(
    record_attributes: list[str],
    chunk_key: str,
):
    if len(record_attributes) < 6 or record_attributes[0] != '"Low-order Hyperedge"':
        return None
    # add this record as hyperedge
    entity_num = len(record_attributes) - 3
    entities = []
    for i in range(1, entity_num):
        entities.append(clean_str(record_attributes[i].upper()))
    edge_description = clean_str(record_attributes[-3])

    edge_keywords = clean_str(record_attributes[-2])
    edge_source_id = chunk_key
    weight = (
        float(record_attributes[-1]) if is_float_regex(record_attributes[-1]) else 0.75 # 如果无权重，则默认0.75
    )
    return dict(
        entityN=entities,
        weight=weight,
        description=edge_description,
        keywords=edge_keywords,
        source_id=edge_source_id,
        level_hg="Low-order Hyperedge",
    )

async def _handle_single_relationship_extraction_high(
    record_attributes: list[str],
    chunk_key: str,
):
    if len(record_attributes) < 7 or record_attributes[0] != '"High-order Hyperedge"':
        return None
    # add this record as hyperedge
    entity_num = len(record_attributes) - 4
    entities = []
    for i in range(1, entity_num):
        entities.append(clean_str(record_attributes[i].upper()))
    edge_description = clean_str(record_attributes[-4])
    edge_keywords = clean_str(record_attributes[-2])
    edge_source_id = chunk_key
    weight = (
        float(record_attributes[-1]) if is_float_regex(record_attributes[-1]) else 0.75
    )
    return dict(
        entityN=entities,
        weight=weight,
        description=edge_description,
        keywords=edge_keywords,
        source_id=edge_source_id,
        level_hg="High-order Hyperedge",
    )


def _format_structured_fields_as_string(structured_fields: dict) -> str:
    """
    Format structured fields into a human-readable string for display.

    Example output: "subtype=operating, value=40, unit=°C"
    """
    parts = []

    # Order for consistent display
    field_order = ["subtype", "value", "value_min", "value_max", "unit", "key_attribute"]

    for field in field_order:
        if field in structured_fields and structured_fields[field] is not None:
            value = structured_fields[field]
            if isinstance(value, list):
                # Join multiple values with commas
                value_str = ", ".join(str(v) for v in value)
            else:
                value_str = str(value)
            parts.append(f"{field}={value_str}")

    return GRAPH_FIELD_SEP.join(sorted(parts))


def _merge_structured_fields(nodes_data: list[dict], already_fields: dict) -> dict:
    """
    Merge structured fields from multiple node data instances.

    Strategy:
    - For categorical fields (subtype, unit, key_attribute): keep all unique values
    - For numeric fields (value, value_min, value_max): use smart aggregation
      * If all same: use that value
      * If different: use range (min/max)
    """
    merged = {}

    # Collect all values for each field (统一使用 list)
    all_values = {
        "subtype": [],
        "unit": [],
        "key_attribute": [],
        "value": [],
        "value_min": [],
        "value_max": [],
    }

    # Add values from new nodes
    for node in nodes_data:
        for field in all_values.keys():
            if field in node and node[field] is not None:
                value = node[field]
                # Handle case where value might be a set or other iterable
                if isinstance(value, (list, set)):
                    all_values[field].extend(list(value))
                else:
                    all_values[field].append(value)

    # Add values from existing node
    for field, value in already_fields.items():
        if value is not None and field in all_values:
            # Handle case where value might be a set or other iterable
            if isinstance(value, (list, set)):
                all_values[field].extend(list(value))
            else:
                all_values[field].append(value)

    # Merge categorical fields (keep unique values as list)
    for field in ["subtype", "unit", "key_attribute"]:
        if all_values[field]:
            # Convert all values to strings to avoid type mixing
            string_values = [str(v) if v is not None else "" for v in all_values[field]]
            unique_values = set(string_values)
            if len(unique_values) == 1:
                merged[field] = list(unique_values)[0]
            else:
                merged[field] = list(unique_values)

    # Merge numeric fields with range strategy
    for field in ["value", "value_min", "value_max"]:
        if all_values[field]:
            # Filter only numeric values
            values = []
            for v in all_values[field]:
                if isinstance(v, (int, float)):
                    values.append(v)
                elif isinstance(v, str) and v.replace('.', '', 1).isdigit():
                    # Try to convert string to number
                    try:
                        if '.' in v:
                            values.append(float(v))
                        else:
                            values.append(int(v))
                    except ValueError:
                        pass

            if values:
                if len(values) == 1:
                    merged[field] = values[0]
                else:
                    # Use range for different values
                    if field == "value":
                        merged["value_min"] = min(values)
                        merged["value_max"] = max(values)
                        merged[field] = None  # Remove single value when using range
                    else:
                        merged[field] = min(values) if "min" in field else max(values)

    return merged


async def _merge_nodes_then_upsert(
    entity_name: str,
    nodes_data: list[dict],
    knowledge_hypergraph_inst,
    global_config: dict,
):
    already_entity_types = []
    already_source_ids = []
    already_description = []
    already_structured_fields = {}

    already_node = await knowledge_hypergraph_inst.get_vertex(entity_name)
    if already_node is not None:
        already_entity_types.append(already_node["entity_type"])
        already_source_ids.extend(
            split_string_by_multi_markers(already_node["source_id"], [GRAPH_FIELD_SEP])
        )
        already_description.append(already_node["description"])

        # Extract structured fields from existing node if available
        for field in ["subtype", "value", "value_min", "value_max", "unit", "key_attribute"]:
            if field in already_node and already_node[field] is not None:
                # Convert to list to avoid type errors during merging
                value = already_node[field]
                if isinstance(value, set):
                    already_structured_fields[field] = list(value)
                elif not isinstance(value, list):
                    already_structured_fields[field] = [value]
                else:
                    already_structured_fields[field] = value

    entity_type = sorted(
        Counter(
            [dp["entity_type"] for dp in nodes_data] + already_entity_types
        ).items(),
        key=lambda x: x[1],
        reverse=True,
    )[0][0]

    description = GRAPH_FIELD_SEP.join(
        sorted(set([dp["description"] for dp in nodes_data] + already_description))
    )
    source_id = GRAPH_FIELD_SEP.join(
        set([dp["source_id"] for dp in nodes_data] + already_source_ids)
    )

    # Merge structured fields with smart strategy
    merged_structured_fields = _merge_structured_fields(nodes_data, already_structured_fields)

    description = await _handle_entity_summary(
        entity_name, description, global_config
    )

    # Build human-readable additional_properties string from structured fields
    additional_properties = _format_structured_fields_as_string(merged_structured_fields)

    # Build node data with structured fields
    node_data = dict(
        entity_type=entity_type,
        description=description,
        source_id=source_id,
        additional_properties=additional_properties,  # For display and backward compatibility
    )

    # Add merged structured fields (for structured queries)
    node_data.update(merged_structured_fields)

    await knowledge_hypergraph_inst.upsert_vertex(
        entity_name,
        node_data,
    )
    node_data["entity_name"] = entity_name
    return node_data


async def _merge_edges_then_upsert(
    id_set: tuple,
    edges_data: list[dict],
    knowledge_hypergraph_inst,
    global_config: dict,
):
    already_weights = []
    already_source_ids = []
    already_description = []
    already_keywords = []
    already_evidence_spans = []
    already_relation_types = []

    if await knowledge_hypergraph_inst.has_hyperedge(id_set):
        already_edge = await knowledge_hypergraph_inst.get_hyperedge(id_set)
        already_weights.append(already_edge["weight"])
        already_source_ids.extend(
            split_string_by_multi_markers(already_edge["source_id"], [GRAPH_FIELD_SEP])
        )
        already_description.append(already_edge["description"])
        already_keywords.extend(
            split_string_by_multi_markers(already_edge["keywords"], [GRAPH_FIELD_SEP])
        )
        # Load existing evidence_span and relation_type
        if already_edge.get("evidence_span"):
            already_evidence_spans.append(already_edge["evidence_span"])
        if already_edge.get("relation_type"):
            already_relation_types.append(already_edge["relation_type"])

    weight = sum([dp["weight"] for dp in edges_data] + already_weights)
    description = GRAPH_FIELD_SEP.join(
        sorted(set([dp["description"] for dp in edges_data] + already_description))
    )
    keywords = GRAPH_FIELD_SEP.join(
        sorted(set([dp["keywords"] for dp in edges_data] + already_keywords))
    )
    source_id = GRAPH_FIELD_SEP.join(
        set([dp["source_id"] for dp in edges_data] + already_source_ids)
    )

    # Merge evidence_spans (preserve for traceability)
    evidence_spans = [dp.get("evidence_span", "") for dp in edges_data if dp.get("evidence_span")]
    all_evidence_spans = evidence_spans + already_evidence_spans
    evidence_span = GRAPH_FIELD_SEP.join(sorted(set(all_evidence_spans))) if all_evidence_spans else ""

    # Merge relation_types (may have multiple types for same entity set)
    relation_types = [dp.get("relation_type", "") for dp in edges_data if dp.get("relation_type")]
    all_relation_types = relation_types + already_relation_types
    relation_type = GRAPH_FIELD_SEP.join(sorted(set(all_relation_types))) if all_relation_types else ""

    # Track UNKNOWN vertex creation
    unknown_count = 0
    unknown_reference_count = 0
    unknown_names = []
    unknown_references = []

    for need_insert_id in id_set:
        if not (await knowledge_hypergraph_inst.has_vertex(need_insert_id)):
            logger.warning(f"[{source_id}] Creating UNKNOWN vertex for: {need_insert_id}")
            unknown_count += 1
            unknown_reference_count += 1
            unknown_names.append(need_insert_id)
            unknown_references.append(need_insert_id)
            await knowledge_hypergraph_inst.upsert_vertex(
                need_insert_id,
                {
                    "source_id": source_id,
                    "description": "UNKNOWN", # 超边描述
                    "additional_properties": "UNKNOWN", # 超边关键词
                    "entity_type": "UNKNOWN",
                },
            )
        else:
            existing_vertex = await knowledge_hypergraph_inst.get_vertex(need_insert_id)
            if existing_vertex and existing_vertex.get("entity_type") == "UNKNOWN":
                unknown_reference_count += 1
                unknown_references.append(need_insert_id)

    # Log UNKNOWN vertex statistics with context
    if unknown_reference_count > 0:
        unknown_rate = unknown_reference_count / len(id_set) * 100 if id_set else 0
        logger.warning(
            f"[{source_id}] UNKNOWN vertices in edge: created={unknown_count}, "
            f"references={unknown_reference_count}, vertices_total={len(id_set)}, "
            f"unknown_rate={unknown_rate:.2f}%"
        )
        logger.warning(f"[{source_id}] UNKNOWN names: {unknown_references[:20]}")
        logger.warning(f"[{source_id}] Full hyperedge vertices: {list(id_set)}")
        if relation_type:
            logger.warning(f"[{source_id}] Relation type: {relation_type}")
        if evidence_span:
            logger.warning(f"[{source_id}] Evidence span: {evidence_span[:500]}")
        if description:
            logger.warning(f"[{source_id}] Edge description: {description[:500]}")
        if unknown_reference_count > len(id_set) * 0.5:
            logger.warning(f"[{source_id}] HIGH UNKNOWN RATE: More than 50% vertices are UNKNOWN in this edge")
            logger.warning(f"[{source_id}] Unknown vertex names: {unknown_references[:10]}")  # Log first 10 to avoid flooding
            logger.warning(f"[{source_id}] This likely indicates composite names (e.g., 'CP + MEMBr') or numeric suffixes (e.g., 'CE 99.1%')")
    description = await _handle_relation_summary(  # 应该重新写一个针对超边描述进行合并的函数
        id_set, description, global_config
    )

    filter_keywords = await _handle_relation_keywords_summary(  # 应该重新写一个针对超边的关键词进行合并的函数
        id_set, keywords, global_config
    )

    edge_dict = dict(
        description=description,
        keywords=filter_keywords,
        source_id=source_id,
        weight=weight
    )
    # Add evidence_span and relation_type if present
    if evidence_span:
        edge_dict["evidence_span"] = evidence_span
    if relation_type:
        edge_dict["relation_type"] = relation_type

    await knowledge_hypergraph_inst.upsert_hyperedge(id_set, edge_dict)

    edge_data = dict(
        id_set=id_set,
        description=description,
        keywords=filter_keywords,
        source_id=source_id,
        unknown_created_count=unknown_count,
        unknown_reference_count=unknown_reference_count,
        unknown_names=unknown_references,
        vertex_count=len(id_set),
    )
    if evidence_span:
        edge_data["evidence_span"] = evidence_span
    if relation_type:
        edge_data["relation_type"] = relation_type

    return edge_data


def _log_unknown_summary(relationships_data: list[dict]):
    """Log aggregate UNKNOWN vertex statistics for prompt-quality debugging."""
    relationships_data = [dp for dp in relationships_data if dp]
    if not relationships_data:
        return

    total_edges = len(relationships_data)
    edges_with_unknown = sum(
        1 for dp in relationships_data if dp.get("unknown_reference_count", 0) > 0
    )
    total_vertex_mentions = sum(dp.get("vertex_count", len(dp.get("id_set", []))) for dp in relationships_data)
    unknown_vertex_mentions = sum(dp.get("unknown_reference_count", 0) for dp in relationships_data)
    unknown_created_mentions = sum(dp.get("unknown_created_count", 0) for dp in relationships_data)
    unknown_rate = (
        unknown_vertex_mentions / total_vertex_mentions * 100
        if total_vertex_mentions
        else 0
    )

    unknown_counter = Counter()
    unknown_by_relation_type = Counter()
    for dp in relationships_data:
        unknown_names = dp.get("unknown_names", [])
        if unknown_names:
            unknown_counter.update(unknown_names)
            relation_type = dp.get("relation_type", "UNKNOWN_RELATION_TYPE") or "UNKNOWN_RELATION_TYPE"
            for rel_type in split_string_by_multi_markers(str(relation_type), [GRAPH_FIELD_SEP]):
                unknown_by_relation_type[rel_type or "UNKNOWN_RELATION_TYPE"] += len(unknown_names)

    if unknown_vertex_mentions == 0:
        logger.info(
            "UNKNOWN SUMMARY: total_edges=%s, total_vertex_mentions=%s, "
            "unknown_vertex_mentions=0, unknown_rate=0.00%%",
            total_edges,
            total_vertex_mentions,
        )
        return

    logger.warning(
        "UNKNOWN SUMMARY: total_edges=%s, edges_with_unknown=%s, "
        "total_vertex_mentions=%s, unknown_vertex_mentions=%s, "
        "unknown_created_mentions=%s, unknown_rate=%.2f%%, unique_unknown_vertices=%s",
        total_edges,
        edges_with_unknown,
        total_vertex_mentions,
        unknown_vertex_mentions,
        unknown_created_mentions,
        unknown_rate,
        len(unknown_counter),
    )
    logger.warning("UNKNOWN SUMMARY top_unknown_vertices=%s", unknown_counter.most_common(20))
    logger.warning("UNKNOWN SUMMARY unknown_by_relation_type=%s", dict(unknown_by_relation_type))


async def _process_json_format_extraction(
    content: str,
    chunk_key: str,
    use_llm_func: callable,
    global_config: dict,
    domain: str = 'default'
) -> tuple[list, list]:
    """
    Process JSON format extraction for domain-specific prompts

    Args:
        content: Text content to process
        chunk_key: Chunk identifier
        use_llm_func: LLM function to use
        global_config: Global configuration
        domain: Current domain

    Returns:
        Tuple of (entities, relations) in standard format
    """
    from .prompt import (
        get_entity_extraction_prompt,
        get_high_order_extraction_prompt,
        get_low_order_extraction_prompt,
        get_relationship_extraction_prompt,
    )

    chunk_extract_start = time.perf_counter()
    logger.info(f"[{chunk_key}] Starting JSON format extraction for domain: {domain}")

    # Step 1: Extract entities using domain-specific prompt
    logger.debug(f"[{chunk_key}] Step 1: Generating entity extraction prompt...")
    entity_prompt = get_entity_extraction_prompt(
        domain=domain,
        CHUNK_TEXT=content
    )
    logger.debug(f"[{chunk_key}] Step 1: Prompt length = {len(entity_prompt)} chars")

    try:
        logger.info(f"[{chunk_key}] Step 1: Calling LLM for entity extraction...")
        step_start = time.perf_counter()
        entity_result = await use_llm_func(entity_prompt)
        logger.info(f"[{chunk_key}] Step 1: LLM returned {len(entity_result)} chars in {time.perf_counter() - step_start:.2f}s")
        entities_json = parse_json_entities(entity_result, chunk_key)
        logger.info(f"[{chunk_key}] Step 1: Parsed {len(entities_json)} entities from JSON")
    except Exception as e:
        _log_step_exception(chunk_key, "Step 1", "Entity extraction error", e)
        return [], []

    if not entities_json:
        logger.warning(f"[{chunk_key}] Step 1: No entities extracted, aborting pipeline")
        return [], []

    # Log entity type distribution
    from collections import Counter
    entity_types = Counter(e.get("type", "UNKNOWN") for e in entities_json)
    logger.info(f"[{chunk_key}] Step 1: Entity types: {dict(entity_types)}")

    # Convert to standard format
    entities = [convert_json_entity_to_standard_format(entity, chunk_key) for entity in entities_json]
    logger.debug(f"[{chunk_key}] Step 1: Converted {len(entities)} entities to standard format")

    # Step 2: Extract low-order relationships
    # Build enriched entity info for better LLM context (not just names)
    entity_info = []
    for e in entities_json:
        info = {"name": e.get("name", "")}
        if e.get("type"):
            info["type"] = e["type"]
        # Include value or range for CONDITION/METRIC entities
        if e.get("value") is not None:
            info["value"] = e["value"]
        elif e.get("value_min") is not None or e.get("value_max") is not None:
            info["value_range"] = {}
            if e.get("value_min") is not None:
                info["value_range"]["min"] = e["value_min"]
            if e.get("value_max") is not None:
                info["value_range"]["max"] = e["value_max"]
        if e.get("unit"):
            info["unit"] = e["unit"]
        entity_info.append(info)

    low_relations_json = []
    high_relations_json = []

    logger.debug(f"[{chunk_key}] Step 2: Generating combined relationship prompt with {len(entity_info)} entities...")
    combined_prompt = get_relationship_extraction_prompt(
        domain=domain,
        K_v_JSON=json.dumps(entity_info),
        CHUNK_TEXT=content
    )

    if combined_prompt is not None:
        logger.debug(f"[{chunk_key}] Step 2: Combined prompt length = {len(combined_prompt)} chars")
        try:
            logger.info(f"[{chunk_key}] Step 2: Calling LLM for combined low/high relationship extraction...")
            step_start = time.perf_counter()
            combined_result = await use_llm_func(combined_prompt)
            logger.info(f"[{chunk_key}] Step 2: LLM returned {len(combined_result)} chars in {time.perf_counter() - step_start:.2f}s")
            low_relations_json, high_relations_json = parse_json_combined_relationships(
                combined_result, chunk_key
            )
            if low_relations_json:
                rel_types = Counter(r.get("relation_type", "UNKNOWN") for r in low_relations_json)
                logger.debug(f"[{chunk_key}] Step 2: Low-order relation types: {dict(rel_types)}")
            if high_relations_json:
                rel_types = Counter(r.get("relation_type", "UNKNOWN") for r in high_relations_json)
                logger.debug(f"[{chunk_key}] Step 2: High-order hyperedge types: {dict(rel_types)}")
        except Exception as e:
            _log_step_exception(chunk_key, "Step 2", "Combined relationship extraction error", e)
    else:
        logger.info(f"[{chunk_key}] Step 2: Combined relationship template not found; using legacy low/high extraction")

        logger.debug(f"[{chunk_key}] Step 2a: Generating low-order prompt with {len(entity_info)} entities...")
        low_prompt = get_low_order_extraction_prompt(
            domain=domain,
            K_v_JSON=json.dumps(entity_info),
            CHUNK_TEXT=content
        )
        logger.debug(f"[{chunk_key}] Step 2a: Prompt length = {len(low_prompt)} chars")

        try:
            logger.info(f"[{chunk_key}] Step 2a: Calling LLM for low-order relations...")
            low_result = await use_llm_func(low_prompt)
            logger.info(f"[{chunk_key}] Step 2a: LLM returned {len(low_result)} chars")
            low_relations_json = parse_json_relations(low_result, chunk_key)
            logger.info(f"[{chunk_key}] Step 2a: Parsed {len(low_relations_json)} low-order relations")
            if low_relations_json:
                rel_types = Counter(r.get("relation_type", "UNKNOWN") for r in low_relations_json)
                logger.debug(f"[{chunk_key}] Step 2a: Relation types: {dict(rel_types)}")
        except Exception as e:
            _log_step_exception(chunk_key, "Step 2a", "Low-order relation extraction error", e)

        logger.debug(f"[{chunk_key}] Step 2b: Generating high-order prompt with {len(entity_info)} entities...")
        high_prompt = get_high_order_extraction_prompt(
            domain=domain,
            K_v_JSON=json.dumps(entity_info),
            CHUNK_TEXT=content
        )
        logger.debug(f"[{chunk_key}] Step 2b: Prompt length = {len(high_prompt)} chars")

        try:
            logger.info(f"[{chunk_key}] Step 2b: Calling LLM for high-order relations (hyperedges)...")
            high_result = await use_llm_func(high_prompt)
            logger.info(f"[{chunk_key}] Step 2b: LLM returned {len(high_result)} chars")
            high_relations_json = parse_json_hyperedges(high_result, chunk_key)
            logger.info(f"[{chunk_key}] Step 2b: Parsed {len(high_relations_json)} high-order relations (hyperedges)")
            if high_relations_json:
                rel_types = Counter(r.get("relation_type", "UNKNOWN") for r in high_relations_json)
                logger.debug(f"[{chunk_key}] Step 2b: Hyperedge types: {dict(rel_types)}")
        except Exception as e:
            _log_step_exception(chunk_key, "Step 2b", "High-order relation extraction error", e)

    low_relations_json, high_relations_json = _filter_relations_to_known_entities(
        low_relations_json,
        high_relations_json,
        entities_json,
        chunk_key,
    )

    # Convert all relations to standard format after entity-reference validation.
    relations = []
    for relation_json in low_relations_json:
        standard_relation = convert_json_relation_to_standard_format(relation_json, chunk_key)
        if standard_relation:
            relations.append(standard_relation)

    for relation_json in high_relations_json:
        standard_relation = convert_json_relation_to_standard_format(relation_json, chunk_key)
        if standard_relation:
            relations.append(standard_relation)

    logger.info(f"[{chunk_key}] Pipeline complete in {time.perf_counter() - chunk_extract_start:.2f}s: "
                f"{len(entities)} entities, {len(relations)} relations "
                f"(low={len(low_relations_json)}, high={len(high_relations_json)})")

    # Validate output if domain support is available (non-blocking)
    try:
        validation_result = validate_domain_output(entities_json, low_relations_json + high_relations_json, domain)
        if not validation_result["valid"]:
            logger.warning(f"[{chunk_key}] Validation: {validation_result['errors']}")
        else:
            logger.info(f"[{chunk_key}] Validation passed")
    except Exception as e:
        logger.warning(f"[{chunk_key}] Validation check failed: {e}")

    return entities, relations


async def extract_entities(
    chunks: dict[str, TextChunkSchema],
    knowledge_hypergraph_inst: BaseHypergraphStorage,
    entity_vdb: BaseVectorStorage,
    relationships_vdb: BaseVectorStorage,
    global_config: dict,
) -> BaseHypergraphStorage | None:
    use_llm_func: callable = global_config["llm_model_func"]
    entity_extract_max_gleaning = global_config["entity_extract_max_gleaning"]

    # Get current domain from configuration
    current_domain = get_domain_from_config(global_config)
    is_json_output = is_json_output_domain(current_domain)

    logger.info(f"Using domain: {current_domain}, JSON output: {is_json_output}")

    ordered_chunks = list(chunks.items())
    logger.info(f"Processing {len(ordered_chunks)} chunks for entity extraction")

    entity_extract_prompt = PROMPTS["entity_extraction"]
    # We can choose the example what we want from the prompt.
    example_base = dict(
        tuple_delimiter=PROMPTS["DEFAULT_TUPLE_DELIMITER"],
        record_delimiter=PROMPTS["DEFAULT_RECORD_DELIMITER"],
        completion_delimiter=PROMPTS["DEFAULT_COMPLETION_DELIMITER"]
    )
    example_prompt = PROMPTS["entity_extraction_examples"][3]
    example_str = example_prompt.format(**example_base)

    context_base = dict(
        language=PROMPTS["DEFAULT_LANGUAGE"],
        entity_types=",".join(PROMPTS["DEFAULT_ENTITY_TYPES"]),
        tuple_delimiter=PROMPTS["DEFAULT_TUPLE_DELIMITER"],
        record_delimiter=PROMPTS["DEFAULT_RECORD_DELIMITER"],
        completion_delimiter=PROMPTS["DEFAULT_COMPLETION_DELIMITER"],
        examples = example_str
    )
    continue_prompt = PROMPTS["entity_continue_extraction"]
    if_loop_prompt = PROMPTS["entity_if_loop_extraction"]

    already_processed = 0
    already_entities = 0
    already_relations = 0
    already_relations_low = 0
    already_relations_high = 0

    async def _process_single_content(chunk_key_dp: tuple[str, TextChunkSchema]):
        nonlocal already_processed, already_entities, already_relations, already_relations_low, already_relations_high
        chunk_key = chunk_key_dp[0]
        chunk_dp = chunk_key_dp[1]
        content = chunk_dp["content"]

        logger.debug(f"Processing chunk {chunk_key} (content length: {len(content)} chars)")

        # Handle JSON format output for domain-specific prompts
        if is_json_output:
            try:
                entities, relations = await _process_json_format_extraction(
                    content, chunk_key, use_llm_func, global_config, current_domain
                )
                logger.debug(f"[{chunk_key}] JSON extraction returned: {len(entities)} entities, {len(relations)} relations")
            except Exception as e:
                logger.error(f"[{chunk_key}] JSON extraction FAILED with exception: {type(e).__name__}: {e}")
                import traceback
                logger.debug(f"[{chunk_key}] Traceback: {traceback.format_exc()}")
                return None, None, None, None

            # Initialize containers for this chunk
            chunk_maybe_nodes = defaultdict(list)
            chunk_maybe_edges = defaultdict(list)
            chunk_maybe_edges_low = defaultdict(list)
            chunk_maybe_edges_high = defaultdict(list)

            # Process entities
            for entity in entities:
                entity_name = entity["entity_name"]
                chunk_maybe_nodes[entity_name].append(entity)

            # Process relations
            for relation in relations:
                if "entities_pair" in relation:  # Low-order relation
                    edge_key = tuple(relation["entities_pair"])
                    chunk_maybe_edges[edge_key].append(relation)
                    chunk_maybe_edges_low[edge_key].append(relation)
                elif "entities_set" in relation:  # High-order relation
                    edge_key = relation["entities_set"]
                    chunk_maybe_edges[edge_key].append(relation)
                    chunk_maybe_edges_high[edge_key].append(relation)

            # Update counters
            already_entities += len(entities)
            already_relations += len(relations)
            already_relations_low += len([r for r in relations if "entities_pair" in r])
            already_relations_high += len([r for r in relations if "entities_set" in r])
            already_processed += 1

            return chunk_maybe_nodes, chunk_maybe_edges, chunk_maybe_edges_low, chunk_maybe_edges_high

        # Original delimiter-based processing for default domain
        hint_prompt = entity_extract_prompt.format(**context_base, input_text=content)

        final_result = await use_llm_func(hint_prompt)
        if final_result is None:
            return None,None,None,None

        history = pack_user_ass_to_openai_messages(hint_prompt, final_result)
        for now_glean_index in range(entity_extract_max_gleaning):
            glean_result = await use_llm_func(continue_prompt, history_messages=history)
            if glean_result is None:
                break

            history += pack_user_ass_to_openai_messages(continue_prompt, glean_result)
            final_result += glean_result
            if now_glean_index == entity_extract_max_gleaning - 1:
                break

            if_loop_result: str = await use_llm_func(
                if_loop_prompt, history_messages=history
            )
            if_loop_result = if_loop_result.strip().strip('"').strip("'").lower()
            if if_loop_result != "yes":
                break

        records = split_string_by_multi_markers(
            final_result,
            [context_base["record_delimiter"], context_base["completion_delimiter"]],
        )

        maybe_nodes = defaultdict(list)
        maybe_edges = defaultdict(list)
        maybe_edges_low = defaultdict(list)
        maybe_edges_high = defaultdict(list)
        for record in records:
            record = re.search(r"\((.*)\)", record)
            if record is None:
                continue
            record = record.group(1)
            record_attributes = split_string_by_multi_markers(
                record, [context_base["tuple_delimiter"]]
            )
            if_entities = await _handle_single_entity_extraction(
                record_attributes, chunk_key
            )
            if if_entities is not None:
                maybe_nodes[if_entities["entity_name"]].append(if_entities)
                continue

            if_relation = await _handle_single_relationship_extraction_low(
                record_attributes, chunk_key
            )
            if if_relation is not None:
                maybe_edges[tuple((if_relation["entityN"]))].append(
                    if_relation
                )
                maybe_edges_low[tuple((if_relation["entityN"]))].append(
                    if_relation
                )

            if_relation = await _handle_single_relationship_extraction_high(
                record_attributes, chunk_key
            )
            if if_relation is not None:
                maybe_edges[tuple((if_relation["entityN"]))].append(
                    if_relation
                )
                maybe_edges_high[tuple((if_relation["entityN"]))].append(
                    if_relation
                )

        already_processed += 1
        already_entities += len(maybe_nodes)
        already_relations += len(maybe_edges)
        already_relations_low += len(maybe_edges_low)
        already_relations_high += len(maybe_edges_high)
        now_ticks = PROMPTS["process_tickers"][
            already_processed % len(PROMPTS["process_tickers"])
        ]

        # 计算用时
        current_time = datetime.now()
        time = current_time - begin_time
        total_seconds = int(time.total_seconds())
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        # 进度条
        percent = (already_processed / len(ordered_chunks)) * 100
        bar_length = int(50 * already_processed // len(ordered_chunks))
        bar = '█' * bar_length + '-' * (50 - bar_length)
        sys.stdout.write(
            f'\n\r|{bar}| {percent:.2f}% |{hours:02}:{minutes:02}:{seconds:02}| {now_ticks} Processed, {already_entities} entities, {already_relations} relations, {already_relations_low} relations_low, {already_relations_high} relations_high \n')
        sys.stdout.flush()
        return dict(maybe_nodes), dict(maybe_edges), dict(maybe_edges_low), dict(maybe_edges_high)

    # ----------------------------------------------------------------------------
    # use_llm_func is wrapped in ascynio.Semaphore, limiting max_async callings
    begin_time = datetime.now()
    extract_start = time.perf_counter()
    logger.info(f"Starting parallel processing of {len(ordered_chunks)} chunks...")
    results = await asyncio.gather(
        *[_process_single_content(c) for c in ordered_chunks],
        return_exceptions=True
    )
    logger.info(f"Chunk LLM extraction wall time: {time.perf_counter() - extract_start:.2f}s")

    # Count successes and failures
    success_count = 0
    failure_count = 0
    for i, result in enumerate(results):
        chunk_key = ordered_chunks[i][0]
        if isinstance(result, Exception):
            logger.error(f"Chunk {i+1}/{len(results)} ({chunk_key}) FAILED: {type(result).__name__}: {result}")
            failure_count += 1
        else:
            success_count += 1
            logger.debug(f"Chunk {i+1}/{len(results)} ({chunk_key}) SUCCESS")

    logger.info(f"Chunk processing complete: {success_count} succeeded, {failure_count} failed")

    # print()  # clear the progress bar
    maybe_nodes = defaultdict(list)
    maybe_edges = defaultdict(list)
    high = defaultdict(list)
    low = defaultdict(list)
    for result in results:
        if isinstance(result, Exception):
            continue
        m_nodes, m_edges, low_edge, high_edge = result
        if m_nodes is not None:
            for k, v in m_nodes.items():
                maybe_nodes[k].extend(v)
        if m_edges is not None:
            for k, v in m_edges.items():
                maybe_edges[tuple(sorted(k))].extend(v)
        if low_edge is not None:
            for k, v in low_edge.items():
                low[tuple(sorted(k))].extend(v)
        if high_edge is not None:
            for k, v in high_edge.items():
                high[tuple(sorted(k))].extend(v)
    # ----------------------------------------------------------------------------
    """
        update the hypergraph database
    """
    merge_start = time.perf_counter()
    logger.info(f"Merging and upserting {len(maybe_nodes)} unique entities to hypergraph...")
    all_entities_data = await asyncio.gather(
        *[
            _merge_nodes_then_upsert(k, v, knowledge_hypergraph_inst, global_config)
            for k, v in maybe_nodes.items()
        ]
    )

    logger.info(f"Merging and upserting {len(maybe_edges)} unique relationships to hypergraph...")
    all_relationships_data = await asyncio.gather(
        *[
            _merge_edges_then_upsert(k, v, knowledge_hypergraph_inst, global_config)
            for k, v in maybe_edges.items()
        ]
    )
    _log_unknown_summary(all_relationships_data)
    logger.info(f"Hypergraph merge/upsert wall time: {time.perf_counter() - merge_start:.2f}s")
    if not len(all_entities_data):
        logger.warning("Didn't extract any entities, maybe your LLM is not working")
        return None
    if not len(all_relationships_data):
        logger.warning(
            "Didn't extract any relationships, maybe your LLM is not working"
        )
        return None

    if entity_vdb is not None:
        entity_vdb_start = time.perf_counter()
        data_for_vdb = {
            compute_mdhash_id(dp["entity_name"], prefix="ent-"): {
                "content": dp["entity_name"] + dp["description"],
                "entity_name": dp["entity_name"],
            }
            for dp in all_entities_data
        }
        await entity_vdb.upsert(data_for_vdb)
        logger.info(f"Entity vector upsert wall time: {time.perf_counter() - entity_vdb_start:.2f}s")

    if relationships_vdb is not None:
        relationship_vdb_start = time.perf_counter()
        data_for_vdb = {
            compute_mdhash_id(str(sorted(dp["id_set"])), prefix="rel-"): {
                "id_set": dp["id_set"],
                "content": dp["keywords"]
                           + str(dp["id_set"])
                           + dp["description"],
            }
            for dp in all_relationships_data
        }
        await relationships_vdb.upsert(data_for_vdb)
        logger.info(f"Relationship vector upsert wall time: {time.perf_counter() - relationship_vdb_start:.2f}s")

    return knowledge_hypergraph_inst


async def _build_entity_query_context(
    query,
    knowledge_hypergraph_inst: BaseHypergraphStorage,
    entities_vdb: BaseVectorStorage,
    text_chunks_db: BaseKVStorage[TextChunkSchema],
    query_param: QueryParam,
):
    results = await entities_vdb.query(query, top_k=query_param.top_k)
    if not len(results):
        return None
    node_datas = await asyncio.gather(
        *[knowledge_hypergraph_inst.get_vertex(r["entity_name"]) for r in results]
    )

    if not all([n is not None for n in node_datas]):
        logger.warning("Some nodes are missing, maybe the storage is damaged")
    node_degrees = await asyncio.gather(
        *[knowledge_hypergraph_inst.vertex_degree(r["entity_name"]) for r in results]
    )

    node_datas = [
        {**n, "entity_name": k["entity_name"], "rank": d}
        for k, n, d in zip(results, node_datas, node_degrees)
        if n is not None
    ]

    use_text_units = await _find_most_related_text_unit_from_entities(
        node_datas, query_param, text_chunks_db, knowledge_hypergraph_inst
    )

    use_relations = await _find_most_related_edges_from_entities(
        node_datas, query_param, knowledge_hypergraph_inst
    )

    logger.info(
        f"entity query uses {len(node_datas)} entites, {len(use_relations)} relations, {len(use_text_units)} text units"
    )
    entities_section_list = [["id", "entity", "type", "description", "additional properties", "rank"]]
    for i, n in enumerate(node_datas):
        entities_section_list.append(
            [
                i,
                n["entity_name"],
                n.get("entity_type", "UNKNOWN"),
                n.get("description", "UNKNOWN"),
                n.get("additional_properties", "UNKNOWN"),
                n["rank"],
            ]
        )

    entities_context = list_of_list_to_csv(entities_section_list)

    relations_section_list = [
        ["id", "entity set", "description", "keywords", "weight", "rank"]
    ]
    for i, e in enumerate(use_relations):
        relations_section_list.append(
            [
                i,
                e["src_tgt"],
                e["description"],
                e["keywords"],
                e["weight"],
                e["rank"],
            ]
        )

    relations_context = list_of_list_to_csv(relations_section_list)

    text_units_section_list = [["id", "content"]]
    for i, t in enumerate(use_text_units):
        text_units_section_list.append([i, t["content"]])
    text_units_context = list_of_list_to_csv(text_units_section_list)

    context_string = f"""
-----Entities-----
```csv
{entities_context}
```
-----Relationships-----
```csv
{relations_context}
```
-----Sources-----
```csv
{text_units_context}
```
"""
    
    # 返回包含上下文字符串和结构化数据的字典
    return {
        "context": context_string,
        "entities": [
            {
                "id": i,
                "entity_name": n["entity_name"],
                "entity_type": n.get("entity_type", "UNKNOWN"),
                "description": n.get("description", "UNKNOWN"),
                "additional_properties": n.get("additional_properties", "UNKNOWN"),
                "rank": n["rank"]
            }
            for i, n in enumerate(node_datas)
        ],
        "hyperedges": [
            {
                "id": i,
                "entity_set": e["src_tgt"],
                "description": e["description"],
                "keywords": e["keywords"],
                "weight": e["weight"],
                "rank": e["rank"]
            }
            for i, e in enumerate(use_relations)
        ],
        "text_units": [
            {
                "id": i,
                "content": t["content"]
            }
            for i, t in enumerate(use_text_units)
        ]
    }



async def _find_most_related_text_unit_from_entities(
    node_datas: list[dict],
    query_param: QueryParam,
    text_chunks_db: BaseKVStorage[TextChunkSchema],
    knowledge_hypergraph_inst: BaseHypergraphStorage,
):
    text_units = [
        split_string_by_multi_markers(dp["source_id"], [GRAPH_FIELD_SEP])
        for dp in node_datas
    ]

    edges = await asyncio.gather(
        *[knowledge_hypergraph_inst.get_nbr_e_of_vertex(dp['entity_name']) for dp in node_datas]
    )

    all_one_hop_nodes = set()
    for this_edges in edges:
        if not this_edges:
            continue
        for edge_tuple in this_edges:
            all_one_hop_nodes.update(edge_tuple)

    all_one_hop_nodes = list(all_one_hop_nodes)
    all_one_hop_nodes_data = await asyncio.gather(
        *[knowledge_hypergraph_inst.get_vertex(e) for e in all_one_hop_nodes]
    )
    
    # Add null check for node data
    all_one_hop_text_units_lookup = {
        k: set(split_string_by_multi_markers(v["source_id"], [GRAPH_FIELD_SEP]))
        for k, v in zip(all_one_hop_nodes, all_one_hop_nodes_data)
        if v is not None and "source_id" in v  # Add source_id check
    }

    all_text_units_lookup = {}
    for index, (this_text_units, this_edges) in enumerate(zip(text_units, edges)):
        for c_id in this_text_units:
            if c_id in all_text_units_lookup:
                continue
            relation_counts = 0
            if this_edges:  # Add check for None edges
                for edge_tuple in this_edges:
                    for e in edge_tuple:                    
                        if (
                            e in all_one_hop_text_units_lookup
                            and c_id in all_one_hop_text_units_lookup[e]
                        ):
                            relation_counts += 1
            
            chunk_data = await text_chunks_db.get_by_id(c_id)
            if chunk_data is not None and "content" in chunk_data:  # Add content check
                all_text_units_lookup[c_id] = {
                    "data": chunk_data,
                    "order": index,
                    "relation_counts": relation_counts,
                }

    # Filter out None values and ensure data has content
    all_text_units = [
        {"id": k, **v} 
        for k, v in all_text_units_lookup.items() 
        if v is not None and v.get("data") is not None and "content" in v["data"]
    ]

    if not all_text_units:
        logger.warning("No valid text units found")
        return []

    all_text_units = sorted(
        all_text_units, 
        key=lambda x: (x["order"], -x["relation_counts"])
    )

    all_text_units = truncate_list_by_token_size(
        all_text_units,
        key=lambda x: x["data"]["content"],
        max_token_size=query_param.max_token_for_text_unit,
    )

    all_text_units = [t["data"] for t in all_text_units]
    return all_text_units


async def _find_most_related_edges_from_entities(
    node_datas: list[dict],
    query_param: QueryParam,
    knowledge_hypergraph_inst: BaseHypergraphStorage,
):
    all_related_edges = await asyncio.gather(
        *[knowledge_hypergraph_inst.get_nbr_e_of_vertex(dp['entity_name']) for dp in node_datas]
    )

    all_edges = set()
    for this_edges in all_related_edges:
        all_edges.update([tuple(sorted(e)) for e in this_edges])
    all_edges = list(all_edges)
    all_edges_pack = await asyncio.gather(
        *[knowledge_hypergraph_inst.get_hyperedge(e) for e in all_edges]
    )

    all_edges_degree = await asyncio.gather(
        *[knowledge_hypergraph_inst.hyperedge_degree(e) for e in all_edges]
    )
    all_edges_data = [
        {"src_tgt": k, "rank": d, **v}
        for k, v, d in zip(all_edges, all_edges_pack, all_edges_degree)
        if v !=[]
    ]

    all_edges_data = sorted(
        all_edges_data, key=lambda x: (x["rank"], x["weight"]), reverse=True
    )
    all_edges_data = truncate_list_by_token_size(
        all_edges_data,
        key=lambda x: x["description"],
        max_token_size=query_param.max_token_for_relation_context,
    )
    return all_edges_data


async def _build_relation_query_context(
    keywords,
    knowledge_hypergraph_inst: BaseHypergraphStorage,
    entities_vdb: BaseVectorStorage,
    relationships_vdb: BaseVectorStorage,
    text_chunks_db: BaseKVStorage[TextChunkSchema],
    query_param: QueryParam,
):
    results = await relationships_vdb.query(keywords, top_k=query_param.top_k)

    if not len(results):
        return None

    edge_datas = await asyncio.gather(
        *[knowledge_hypergraph_inst.get_hyperedge(r['id_set']) for r in results]
    )

    if not all([n is not None for n in edge_datas]):
        logger.warning("Some edges are missing, maybe the storage is damaged")
    edge_degree = await asyncio.gather(
        *[knowledge_hypergraph_inst.hyperedge_degree(e['id_set']) for e in results]
    )

    edge_datas = [
        {"id_set": k["id_set"], "rank": d, **v}
        for k, v, d in zip(results, edge_datas, edge_degree)
        if v is not None
    ]
    edge_datas = sorted(
        edge_datas, key=lambda x: (x["rank"], x["weight"]), reverse=True
    )
    edge_datas = truncate_list_by_token_size(
        edge_datas,
        key=lambda x: x["description"],
        max_token_size=query_param.max_token_for_relation_context,
    )

    use_entities = await _find_most_related_entities_from_relationships(
        edge_datas, query_param, knowledge_hypergraph_inst
    )
    use_text_units = await _find_related_text_unit_from_relationships(
        edge_datas, query_param, text_chunks_db, knowledge_hypergraph_inst
    )
    logger.info(
        f"relation query uses {len(use_entities)} entites, {len(edge_datas)} relations, {len(use_text_units)} text units"
    )
    relations_section_list = [
        ["id", "entity set", "description", "keywords", "weight", "rank"]
    ]
    for i, e in enumerate(edge_datas):
        relations_section_list.append(
            [
                i,
                e["id_set"],
                e["description"],
                e["keywords"],
                e["weight"],
                e["rank"],
            ]
        )
    relations_context = list_of_list_to_csv(relations_section_list)

    entites_section_list = [["id", "entity", "type", "description", "additional properties", "rank"]]
    for i, n in enumerate(use_entities):
        entites_section_list.append(
            [
                i,
                n["entity_name"],
                n.get("entity_type", "UNKNOWN"),
                n.get("description", "UNKNOWN"),
                n.get("additional properties", "UNKNOWN"),
                n["rank"],
            ]
        )
    entities_context = list_of_list_to_csv(entites_section_list)

    text_units_section_list = [["id", "content"]]
    for i, t in enumerate(use_text_units):
        text_units_section_list.append([i, t["content"]])
    text_units_context = list_of_list_to_csv(text_units_section_list)

    context_string = f"""
-----Entities-----
```csv
{entities_context}
```
-----Relationships-----
```csv
{relations_context}
```
-----Sources-----
```csv
{text_units_context}
```
"""

    # 返回包含上下文字符串和结构化数据的字典
    return {
        "context": context_string,
        "entities": [
            {
                "id": i,
                "entity_name": n["entity_name"],
                "entity_type": n.get("entity_type", "UNKNOWN"),
                "description": n.get("description", "UNKNOWN"),
                "additional_properties": n.get("additional properties", "UNKNOWN"),
                "rank": n["rank"]
            }
            for i, n in enumerate(use_entities)
        ],
        "hyperedges": [
            {
                "id": i,
                "entity_set": e["id_set"],
                "description": e["description"],
                "keywords": e["keywords"],
                "weight": e["weight"],
                "rank": e["rank"]
            }
            for i, e in enumerate(edge_datas)
        ],
        "text_units": [
            {
                "id": i,
                "content": t["content"]
            }
            for i, t in enumerate(use_text_units)
        ]
    }

async def _find_most_related_entities_from_relationships(
    edge_datas: list[dict],
    query_param: QueryParam,
    knowledge_hypergraph_inst: BaseHypergraphStorage,
):
    entity_names = set()
    for e in edge_datas:
        for f in e["id_set"]:
            if await knowledge_hypergraph_inst.has_vertex(f):
                entity_names.add(f)

    node_datas = await asyncio.gather(
        *[knowledge_hypergraph_inst.get_vertex(entity_name) for entity_name in entity_names]
    )

    node_degrees = await asyncio.gather(
        *[knowledge_hypergraph_inst.vertex_degree(entity_name) for entity_name in entity_names]
    )

    node_datas = [
        {**n, "entity_name": k, "rank": d}
        for k, n, d in zip(entity_names, node_datas, node_degrees)
    ]

    node_datas = truncate_list_by_token_size(
        node_datas,
        key=lambda x: x["description"],
        max_token_size=query_param.max_token_for_entity_context,
    )

    return node_datas


async def _find_related_text_unit_from_relationships(
    edge_datas: list[dict],
    query_param: QueryParam,
    text_chunks_db: BaseKVStorage[TextChunkSchema],
    knowledge_hypergraph_inst: BaseHypergraphStorage,
):
    text_units = [
        split_string_by_multi_markers(dp["source_id"], [GRAPH_FIELD_SEP])
        for dp in edge_datas
    ]

    all_text_units_lookup = {}

    for index, unit_list in enumerate(text_units):
        for c_id in unit_list:
            if c_id not in all_text_units_lookup:
                all_text_units_lookup[c_id] = {
                    "data": await text_chunks_db.get_by_id(c_id),
                    "order": index,
                }

    if any([v is None for v in all_text_units_lookup.values()]):
        logger.warning("Text chunks are missing, maybe the storage is damaged")
    all_text_units = [
        {"id": k, **v} for k, v in all_text_units_lookup.items() if v is not None
    ]
    all_text_units = sorted(all_text_units, key=lambda x: x["order"])
    all_text_units = truncate_list_by_token_size(
        all_text_units,
        key=lambda x: x["data"]["content"],
        max_token_size=query_param.max_token_for_text_unit,
    )
    all_text_units: list[TextChunkSchema] = [t["data"] for t in all_text_units]

    return all_text_units


async def hyper_query(
    query,
    knowledge_hypergraph_inst: BaseHypergraphStorage,
    entities_vdb: BaseVectorStorage,
    relationships_vdb: BaseVectorStorage,
    text_chunks_db: BaseKVStorage[TextChunkSchema],
    query_param: QueryParam,
    global_config: dict,
):
    entity_context = None
    relation_context = None
    use_model_func = global_config["llm_model_func"]

    kw_prompt = _get_query_keywords_prompt(query, global_config)

    result = await use_model_func(kw_prompt)

    try:
        entity_keywords, relation_keywords = _parse_query_keywords(
            result, kw_prompt, need_relation_keywords=True
        )
    except json.JSONDecodeError:
        print(f"JSON parsing error: {result}")
        return PROMPTS["fail_response"]
    """
        Perform different actions based on keywords:
            ll_keywords: Find information based on low-level keywords.
            hl_keywords: Define topic information based on high-level keywords.
    """
    if entity_keywords:
        """
        low_level_context: Retrieves vertices and their first-order neighbor hyperedges.
        high_level_context: Retrieves hyperedges and their first-order neighbor vertices.
        """
        entity_context = await _build_entity_query_context(
            entity_keywords,
            knowledge_hypergraph_inst,
            entities_vdb,
            text_chunks_db,
            query_param,
        )

    if relation_keywords:
        relation_context = await _build_relation_query_context(
            relation_keywords,
            knowledge_hypergraph_inst,
            entities_vdb,
            relationships_vdb,
            text_chunks_db,
            query_param,
        )
    """
        combine the information from the local_query and global_query,
        so that we can have the final retrieval information.
    """
    context = combine_contexts(relation_context.get("context"), entity_context.get("context"))

    contextJson = {
        "entities": deduplicate_by_key(entity_context.get("entities", []) + relation_context.get("entities", []), "entity_name"),
        "hyperedges": deduplicate_by_key(entity_context.get("hyperedges", []) + relation_context.get("hyperedges", []), "entity_set"),
        "text_units": deduplicate_by_key(entity_context.get("text_units", []) + relation_context.get("text_units", []), "content")
    }

    if query_param.only_need_context:
        return context
    if context is None:
        return PROMPTS["fail_response"]
    define_str = ""
    if entity_keywords or relation_keywords:
        """
        High-level keywords serve as qualifiers to the topic information
        """
        entity_keywords = entity_keywords if entity_keywords else ""
        relation_keywords = relation_keywords if relation_keywords else ""
        define_str = PROMPTS["rag_define"]
        define_str = define_str.format(ll_keywords=entity_keywords,hl_keywords=relation_keywords)
    sys_prompt_temp = PROMPTS["rag_response"]
    sys_prompt = sys_prompt_temp.format(
        context_data=context, response_type=query_param.response_type
    )
    response = await use_model_func(
        query + define_str,
        system_prompt=sys_prompt,
    )
    if len(response) > len(sys_prompt):
        response = (
            response.replace(sys_prompt, "")
            .replace("user", "")
            .replace("model", "")
            .replace(query, "")
            .replace("<system>", "")
            .replace("</system>", "")
            .strip()
        )
    if query_param.return_type == "json":
        contextJson["response"] = response
        response = contextJson
    return response 

async def hyper_query_stream(
    query,
    knowledge_hypergraph_inst: BaseHypergraphStorage,
    entities_vdb: BaseVectorStorage,
    relationships_vdb: BaseVectorStorage,
    text_chunks_db: BaseKVStorage[TextChunkSchema],
    query_param: QueryParam,
    global_config: dict,
):
    entity_context = None
    relation_context = None
    use_model_func = global_config["llm_model_func"]
    use_model_stream_func = global_config.get("llm_model_stream_func", None)
    if use_model_stream_func is None:
        raise AttributeError("llm_model_stream_func not found; streaming is unavailable.")

    kw_prompt = _get_query_keywords_prompt(query, global_config)

    result = await use_model_func(kw_prompt)

    try:
        entity_keywords, relation_keywords = _parse_query_keywords(
            result, kw_prompt, need_relation_keywords=True
        )
    except json.JSONDecodeError:
        print(f"JSON parsing error: {result}")
        yield PROMPTS["fail_response"]
        return

    """
        Perform different actions based on keywords:
            ll_keywords: Find information based on low-level keywords.
            hl_keywords: Define topic information based on high-level keywords.
    """
    if entity_keywords:
        """
        low_level_context: Retrieves vertices and their first-order neighbor hyperedges.
        high_level_context: Retrieves hyperedges and their first-order neighbor vertices.
        """
        entity_context = await _build_entity_query_context(
            entity_keywords,
            knowledge_hypergraph_inst,
            entities_vdb,
            text_chunks_db,
            query_param,
        )

    if relation_keywords:
        relation_context = await _build_relation_query_context(
            relation_keywords,
            knowledge_hypergraph_inst,
            entities_vdb,
            relationships_vdb,
            text_chunks_db,
            query_param,
        )
    """
        combine the information from the local_query and global_query,
        so that we can have the final retrieval information.
    """
    context = combine_contexts(relation_context.get("context"), entity_context.get("context"))

    contextJson = {
        "entities": deduplicate_by_key(entity_context.get("entities", []) + relation_context.get("entities", []), "entity_name"),
        "hyperedges": deduplicate_by_key(entity_context.get("hyperedges", []) + relation_context.get("hyperedges", []), "entity_set"),
        "text_units": deduplicate_by_key(entity_context.get("text_units", []) + relation_context.get("text_units", []), "content")
    }

    if query_param.only_need_context:
        yield context or ""
        return

    if context is None:
        yield PROMPTS["fail_response"]
        return

    define_str = ""
    if entity_keywords or relation_keywords:
        """
        High-level keywords serve as qualifiers to the topic information
        """
        entity_keywords = entity_keywords if entity_keywords else ""
        relation_keywords = relation_keywords if relation_keywords else ""
        define_str = PROMPTS["rag_define"]
        define_str = define_str.format(ll_keywords=entity_keywords,hl_keywords=relation_keywords)
    sys_prompt_temp = PROMPTS["rag_response"]
    sys_prompt = sys_prompt_temp.format(
        context_data=context, response_type=query_param.response_type
    )
    # ====== 1) 流式接口不建议支持 json（json 必须完整结构，不适合边吐边返回）======
    if query_param.return_type == "json":
        raise ValueError("Streaming does not support return_type='json'. Use return_type='text'.")

    # ====== 2) 真流式输出：逐 token 产出 ======
    async for tok in use_model_stream_func(query + define_str, system_prompt=sys_prompt,):
        if tok:
            yield tok

    return


async def hyper_query_lite(
    query,
    knowledge_hypergraph_inst: BaseHypergraphStorage,
    entities_vdb: BaseVectorStorage,
    text_chunks_db: BaseKVStorage[TextChunkSchema],
    query_param: QueryParam,
    global_config: dict,
) -> str:

    entity_context = None
    use_model_func = global_config["llm_model_func"]

    kw_prompt = _get_query_keywords_prompt(query, global_config)

    result = await use_model_func(kw_prompt)

    try:
        entity_keywords, _ = _parse_query_keywords(
            result, kw_prompt, need_relation_keywords=False
        )
    except json.JSONDecodeError:
        print(f"JSON parsing error: {result}")
        return PROMPTS["fail_response"]
    """
        Perform different actions based on keywords:
            ll_keywords: Find information based on low-level keywords.
    """
    if entity_keywords:
        """
        low_level_context: Retrieves vertices and their first-order neighbor hyperedges.
        high_level_context: Retrieves hyperedges and their first-order neighbor vertices.
        """
        entity_context = await _build_entity_query_context(
            entity_keywords,
            knowledge_hypergraph_inst,
            entities_vdb,
            text_chunks_db,
            query_param,
        )
    """
        combine the information from the local_query and global_query,
        so that we can have the final retrieval information.
    """
    context = entity_context.get("context")

    if query_param.only_need_context:
        return context
    if context is None:
        return PROMPTS["fail_response"]
    define_str = ""
    if entity_keywords:
        """
        High-level keywords serve as qualifiers to the topic information
        """
        entity_keywords = entity_keywords if entity_keywords else ""
        define_str = PROMPTS["rag_define"]
        define_str = define_str.format(ll_keywords=entity_keywords, hl_keywords="")
    sys_prompt_temp = PROMPTS["rag_response"]
    sys_prompt = sys_prompt_temp.format(
        context_data=context, response_type=query_param.response_type
    )
    response = await use_model_func(
        query + define_str,
        system_prompt=sys_prompt,
    )
    if len(response) > len(sys_prompt):
        response = (
            response.replace(sys_prompt, "")
            .replace("user", "")
            .replace("model", "")
            .replace(query, "")
            .replace("<system>", "")
            .replace("</system>", "")
            .strip()
        )
    if query_param.return_type == "json":
        entity_context["response"] = response
        response = entity_context
    return response


async def graph_query(
    query,
    knowledge_hypergraph_inst: BaseHypergraphStorage,
    entities_vdb: BaseVectorStorage,
    relationships_vdb: BaseVectorStorage,
    text_chunks_db: BaseKVStorage[TextChunkSchema],
    query_param: QueryParam,
    global_config: dict,
):
    """
    检索和返回 hypergraph db 中的成对关系
    """
    use_model_func = global_config["llm_model_func"]
    kw_prompt = _get_query_keywords_prompt(query, global_config)
    result = await use_model_func(kw_prompt)
    try:
        entity_keywords, relation_keywords = _parse_query_keywords(
            result, kw_prompt, need_relation_keywords=True
        )
    except json.JSONDecodeError:
        print(f"JSON parsing error: {result}")
        return PROMPTS["fail_response"]

    # 只处理二元关系
    def filter_pairwise_edges(edges):
        return [e for e in edges if isinstance(e.get("id_set"), (list, tuple)) and len(e["id_set"]) == 2]

    # 获取所有相关的二元关系
    relation_context = None
    if relation_keywords:
        results = await relationships_vdb.query(relation_keywords, top_k=query_param.top_k)
        if not len(results):
            return PROMPTS["fail_response"]
        edge_datas = await asyncio.gather(
            *[knowledge_hypergraph_inst.get_hyperedge(r['id_set']) for r in results]
        )
        edge_degree = await asyncio.gather(
            *[knowledge_hypergraph_inst.hyperedge_degree(e['id_set']) for e in results]
        )
        edge_datas = [
            {"id_set": k["id_set"], "rank": d, **v}
            for k, v, d in zip(results, edge_datas, edge_degree)
            if v is not None
        ]
        # 只保留二元关系
        edge_datas = filter_pairwise_edges(edge_datas)
        edge_datas = sorted(
            edge_datas, key=lambda x: (x["rank"], x["weight"]), reverse=True
        )
        edge_datas = truncate_list_by_token_size(
            edge_datas,
            key=lambda x: x["description"],
            max_token_size=query_param.max_token_for_relation_context,
        )
        # 相关实体
        entity_names = set()
        for e in edge_datas:
            for f in e["id_set"]:
                if await knowledge_hypergraph_inst.has_vertex(f):
                    entity_names.add(f)
        node_datas = await asyncio.gather(
            *[knowledge_hypergraph_inst.get_vertex(entity_name) for entity_name in entity_names]
        )
        node_degrees = await asyncio.gather(
            *[knowledge_hypergraph_inst.vertex_degree(entity_name) for entity_name in entity_names]
        )
        node_datas = [
            {**n, "entity_name": k, "rank": d}
            for k, n, d in zip(entity_names, node_datas, node_degrees)
            if n is not None
        ]
        node_datas = truncate_list_by_token_size(
            node_datas,
            key=lambda x: x["description"],
            max_token_size=query_param.max_token_for_entity_context,
        )
        # 相关文本
        text_units = [
            split_string_by_multi_markers(dp["source_id"], [GRAPH_FIELD_SEP])
            for dp in edge_datas
        ]
        all_text_units_lookup = {}
        for index, unit_list in enumerate(text_units):
            for c_id in unit_list:
                if c_id not in all_text_units_lookup:
                    all_text_units_lookup[c_id] = {
                        "data": await text_chunks_db.get_by_id(c_id),
                        "order": index,
                    }
        all_text_units = [
            {"id": k, **v} for k, v in all_text_units_lookup.items() if v is not None and v["data"] is not None
        ]
        all_text_units = sorted(all_text_units, key=lambda x: x["order"])
        all_text_units = truncate_list_by_token_size(
            all_text_units,
            key=lambda x: x["data"]["content"],
            max_token_size=query_param.max_token_for_text_unit,
        )
        all_text_units = [t["data"] for t in all_text_units]
        # 格式化 context
        relations_section_list = [
            ["id", "entity set", "description", "keywords", "weight", "rank"]
        ]
        for i, e in enumerate(edge_datas):
            relations_section_list.append(
                [
                    i,
                    e["id_set"],
                    e["description"],
                    e["keywords"],
                    e["weight"],
                    e["rank"],
                ]
            )
        relations_context = list_of_list_to_csv(relations_section_list)
        entites_section_list = [["id", "entity", "type", "description", "additional properties", "rank"]]
        for i, n in enumerate(node_datas):
            entites_section_list.append(
                [
                    i,
                    n["entity_name"],
                    n.get("entity_type", "UNKNOWN"),
                    n.get("description", "UNKNOWN"),
                    n.get("additional_properties", "UNKNOWN"),
                    n["rank"],
                ]
            )
        entities_context = list_of_list_to_csv(entites_section_list)
        text_units_section_list = [["id", "content"]]
        for i, t in enumerate(all_text_units):
            text_units_section_list.append([i, t["content"]])
        text_units_context = list_of_list_to_csv(text_units_section_list)
        context_string = f"""
-----Entities-----
```csv
{entities_context}
```
-----Relationships-----
```csv
{relations_context}
```
-----Sources-----
```csv
{text_units_context}
```
"""
        contextJson = {
            "context": context_string,
            "entities": [
                {
                    "id": i,
                    "entity_name": n["entity_name"],
                    "entity_type": n.get("entity_type", "UNKNOWN"),
                    "description": n.get("description", "UNKNOWN"),
                    "additional_properties": n.get("additional_properties", "UNKNOWN"),
                    "rank": n["rank"]
                }
                for i, n in enumerate(node_datas)
            ],
            "hyperedges": [
                {
                    "id": i,
                    "entity_set": e["id_set"],
                    "description": e["description"],
                    "keywords": e["keywords"],
                    "weight": e["weight"],
                    "rank": e["rank"]
                }
                for i, e in enumerate(edge_datas)
            ],
            "text_units": [
                {
                    "id": i,
                    "content": t["content"]
                }
                for i, t in enumerate(all_text_units)
            ]
        }
        if query_param.only_need_context:
            return context_string
        if context_string is None:
            return PROMPTS["fail_response"]
        define_str = ""
        if entity_keywords or relation_keywords:
            entity_keywords = entity_keywords if entity_keywords else ""
            relation_keywords = relation_keywords if relation_keywords else ""
            define_str = PROMPTS["rag_define"]
            define_str = define_str.format(ll_keywords=entity_keywords,hl_keywords=relation_keywords)
        sys_prompt_temp = PROMPTS["rag_response"]
        sys_prompt = sys_prompt_temp.format(
            context_data=context_string, response_type=query_param.response_type
        )
        response = await use_model_func(
            query + define_str,
            system_prompt=sys_prompt,
        )
        if len(response) > len(sys_prompt):
            response = (
                response.replace(sys_prompt, "")
                .replace("user", "")
                .replace("model", "")
                .replace(query, "")
                .replace("<system>", "")
                .replace("</system>", "")
                .strip()
            )
        if query_param.return_type == "json":
            contextJson["response"] = response
            response = contextJson
        return response
    else:
        return PROMPTS["fail_response"]


def combine_contexts(relation_context, entity_context):
    # Function to extract entities, relationships, and sources from context strings

    def extract_sections(context):
        entities_match = re.search(
            r"-----Entities-----\s*```csv\s*(.*?)\s*```", context, re.DOTALL
        )
        relationships_match = re.search(
            r"-----Relationships-----\s*```csv\s*(.*?)\s*```", context, re.DOTALL
        )
        sources_match = re.search(
            r"-----Sources-----\s*```csv\s*(.*?)\s*```", context, re.DOTALL
        )

        entities = entities_match.group(1) if entities_match else ""
        relationships = relationships_match.group(1) if relationships_match else ""
        sources = sources_match.group(1) if sources_match else ""

        return entities, relationships, sources

    # Extract sections from both contexts

    if relation_context is None:
        warnings.warn(
            "High Level context is None. Return empty High_Level entity/relationship/source"
        )
        hl_entities, hl_relationships, hl_sources = "", "", ""
    else:
        hl_entities, hl_relationships, hl_sources = extract_sections(relation_context)

    if entity_context is None:
        warnings.warn(
            "Low Level context is None. Return empty Low_Level entity/relationship/source"
        )
        ll_entities, ll_relationships, ll_sources = "", "", ""
    else:
        ll_entities, ll_relationships, ll_sources = extract_sections(entity_context)

    # Combine and deduplicate the entities
    combined_entities = process_combine_contexts(hl_entities, ll_entities)

    # Combine and deduplicate the relationships
    combined_relationships = process_combine_contexts(
        hl_relationships, ll_relationships
    )

    # Combine and deduplicate the sources
    combined_sources = process_combine_contexts(hl_sources, ll_sources)

    # Format the combined context
    return f"""
-----Entities-----
```csv
{combined_entities}
```
-----Relationships-----
```csv
{combined_relationships}
```
-----Sources-----
```csv
{combined_sources}
```
"""

def remove_after_sources(input_string: str) -> str:
    """
    删除字符串中 '-----Sources-----' 及其之后的所有内容。
    """
    # 找到 '-----Sources-----' 的起始位置
    index = input_string.find("-----Sources-----")
    if index != -1:  # 如果找到了该字符串
        return input_string[:index]  # 返回该位置之前的内容
    return input_string  # 如果没有找到，返回原始字符串

async def naive_query(
    query,
    chunks_vdb: BaseVectorStorage,
    text_chunks_db: BaseKVStorage[TextChunkSchema],
    query_param: QueryParam,
    global_config: dict,
):
    use_model_func = global_config["llm_model_func"]
    results = await chunks_vdb.query(query, top_k=query_param.top_k)
    if not len(results):
        return PROMPTS["fail_response"]
    chunks_ids = [r["id"] for r in results]
    chunks = await text_chunks_db.get_by_ids(chunks_ids)

    maybe_trun_chunks = truncate_list_by_token_size(
        chunks,
        key=lambda x: x["content"],
        max_token_size=query_param.max_token_for_text_unit,
    )
    logger.info(f"Truncate {len(chunks)} to {len(maybe_trun_chunks)} chunks")
    section = "--New Chunk--\n".join([c["content"] for c in maybe_trun_chunks])
    if query_param.only_need_context:
        return section
    sys_prompt_temp = PROMPTS["naive_rag_response"]
    sys_prompt = sys_prompt_temp.format(
        content_data=section, response_type=query_param.response_type
    )
    response = await use_model_func(
        query,
        system_prompt=sys_prompt,
    )

    if len(response) > len(sys_prompt):
        response = (
            response[len(sys_prompt) :]
            .replace(sys_prompt, "")
            .replace("user", "")
            .replace("model", "")
            .replace(query, "")
            .replace("<system>", "")
            .replace("</system>", "")
            .strip()
        )
    if query_param.return_type == "json":
        response = {
            "response": response,
        }
    return response


async def llm_query(
    query,
    query_param: QueryParam,
    global_config: dict,
):
    """
    只调用 LLM，不进行任何数据查询。
    """
    use_model_func = global_config["llm_model_func"]
    sys_prompt_temp = PROMPTS["rag_response"]
    sys_prompt = sys_prompt_temp.format(
        context_data="", response_type=query_param.response_type
    )
    response = await use_model_func(
        query,
        system_prompt=sys_prompt,
    )
    if len(response) > len(sys_prompt):
        response = (
            response.replace(sys_prompt, "")
            .replace("user", "")
            .replace("model", "")
            .replace(query, "")
            .replace("<system>", "")
            .replace("</system>", "")
            .strip()
        )
    if query_param.return_type == "json":
        response = {
            "response": response,
        }
    return response

# =========================
# Streaming versions (END)
# =========================

async def hyper_query_lite_stream(
    query,
    knowledge_hypergraph_inst: BaseHypergraphStorage,
    entities_vdb: BaseVectorStorage,
    text_chunks_db: BaseKVStorage[TextChunkSchema],
    query_param: QueryParam,
    global_config: dict,
):
    """
    hyper_query_lite 的流式版本：逻辑与 hyper_query_lite 相同，只把最后一步 LLM 生成改成 yield token
    """
    entity_context = None
    use_model_func = global_config["llm_model_func"]
    use_model_stream_func = global_config.get("llm_model_stream_func", None)
    if use_model_stream_func is None:
        raise AttributeError("llm_model_stream_func not found; streaming is unavailable.")

    kw_prompt = _get_query_keywords_prompt(query, global_config)

    result = await use_model_func(kw_prompt)

    try:
        entity_keywords, _ = _parse_query_keywords(
            result, kw_prompt, need_relation_keywords=False
        )
    except json.JSONDecodeError:
        yield PROMPTS["fail_response"]
        return

    if entity_keywords:
        entity_context = await _build_entity_query_context(
            entity_keywords,
            knowledge_hypergraph_inst,
            entities_vdb,
            text_chunks_db,
            query_param,
        )

    context = entity_context.get("context") if entity_context else None

    if query_param.only_need_context:
        yield context or ""
        return

    if context is None:
        yield PROMPTS["fail_response"]
        return

    define_str = ""
    if entity_keywords:
        define_str = PROMPTS["rag_define"].format(ll_keywords=entity_keywords, hl_keywords="")

    sys_prompt = PROMPTS["rag_response"].format(
        context_data=context,
        response_type=query_param.response_type,
    )

    if query_param.return_type == "json":
        raise ValueError("Streaming does not support return_type='json'. Use return_type='text'.")

    async for tok in use_model_stream_func(
        query + define_str,
        system_prompt=sys_prompt,
    ):
        if tok:
            yield tok
    return


async def naive_query_stream(
    query,
    chunks_vdb: BaseVectorStorage,
    text_chunks_db: BaseKVStorage[TextChunkSchema],
    query_param: QueryParam,
    global_config: dict,
):
    """
    naive_query 的流式版本：先做 chunk 检索拿到 section，然后用 LLM stream 输出答案
    """
    use_model_func = global_config["llm_model_func"]
    use_model_stream_func = global_config.get("llm_model_stream_func", None)
    if use_model_stream_func is None:
        raise AttributeError("llm_model_stream_func not found; streaming is unavailable.")

    results = await chunks_vdb.query(query, top_k=query_param.top_k)
    if not len(results):
        yield PROMPTS["fail_response"]
        return

    chunks_ids = [r["id"] for r in results]
    chunks = await text_chunks_db.get_by_ids(chunks_ids)

    maybe_trun_chunks = truncate_list_by_token_size(
        chunks,
        key=lambda x: x["content"],
        max_token_size=query_param.max_token_for_text_unit,
    )

    section = "--New Chunk--\n".join([c["content"] for c in maybe_trun_chunks])

    if query_param.only_need_context:
        yield section or ""
        return

    sys_prompt = PROMPTS["naive_rag_response"].format(
        content_data=section,
        response_type=query_param.response_type,
    )

    if query_param.return_type == "json":
        raise ValueError("Streaming does not support return_type='json'. Use return_type='text'.")

    async for tok in use_model_stream_func(
        query,
        system_prompt=sys_prompt,
    ):
        if tok:
            yield tok
    return


async def llm_query_stream(
    query,
    query_param: QueryParam,
    global_config: dict,
):
    """
    llm_query 的流式版本：不检索，直接按 rag_response（空 context）走流式输出
    """
    use_model_stream_func = global_config.get("llm_model_stream_func", None)
    if use_model_stream_func is None:
        raise AttributeError("llm_model_stream_func not found; streaming is unavailable.")

    sys_prompt = PROMPTS["rag_response"].format(
        context_data="",
        response_type=query_param.response_type,
    )

    if query_param.return_type == "json":
        raise ValueError("Streaming does not support return_type='json'. Use return_type='text'.")

    async for tok in use_model_stream_func(
        query,
        system_prompt=sys_prompt,
    ):
        if tok:
            yield tok
    return

