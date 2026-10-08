"""Deterministic query normalization and controlled expansion.

The functions in this module are deliberately model-free.  They only normalize
formatting and add a small, auditable set of chemistry abbreviations.  Callers
must record the returned variants in the run protocol; the module never uses a
gold answer or source document metadata.
"""

from __future__ import annotations

import re
import unicodedata


_SPACE_RE = re.compile(r"\s+")
_SLASH_RE = re.compile(r"\s*/\s*")
_DASH_RE = re.compile(r"\s*[-–—−]\s*")

_ABBREVIATIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bcoulombic efficiency\b", re.I), "CE"),
    (re.compile(r"\bvoltage efficiency\b|\bvoltaic efficiency\b", re.I), "VE"),
    (re.compile(r"\benergy efficiency\b", re.I), "EE"),
    (re.compile(r"\bion exchange capacity\b", re.I), "IEC"),
    (re.compile(r"\bvanadium redox flow battery\b", re.I), "VRFB"),
    (re.compile(r"\biron[- ]chromium redox flow battery\b", re.I), "ICRFB"),
)


def normalize_query(value: str) -> str:
    """Normalize Unicode/unit formatting without dropping query words."""

    text = unicodedata.normalize("NFKC", str(value or ""))
    replacements = {
        "μ": "u",
        "µ": "u",
        "×": "x",
        "℃": " C",
        "°C": " C",
        "° C": " C",
        "⁻": "-",
        "²": "2",
        "³": "3",
        " ": " ",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    text = _DASH_RE.sub("-", text)
    text = _SLASH_RE.sub("/", text)
    text = _SPACE_RE.sub(" ", text).strip()
    return text


def classify_query(value: str) -> str:
    """Return a stable routing label used only for diagnostics and templates."""

    text = normalize_query(value).lower()
    if any(token in text for token in ("compare", "comparison", "versus", " vs ", "higher", "lower")):
        return "comparison"
    if any(token in text for token in ("why", "mechanism", "because", "cause")):
        return "mechanism explanation"
    if any(token in text for token in ("degradation", "fade", "crossover", "dendrite")):
        return "degradation analysis"
    if any(token in text for token in ("at ", "under ", "condition", "temperature", "current density", "cycle")):
        return "condition-constrained retrieval"
    if any(token in text for token in ("optimal", "recommend", "trade-off", "synthesis", "simultaneously")):
        return "multi-condition synthesis"
    return "direct retrieval"


def _abbreviation_variant(text: str) -> str:
    variant = text
    for pattern, replacement in _ABBREVIATIONS:
        variant = pattern.sub(replacement, variant)
    return normalize_query(variant)


def query_variants(value: str, *, max_variants: int = 2) -> list[str]:
    """Return at most ``max_variants`` deterministic surface/canonical queries.

    The first variant is always the normalized user query.  The optional second
    variant replaces common long chemistry metric names with their abbreviations.
    No generated variant is allowed to be empty or duplicated.
    """

    if max_variants <= 0:
        raise ValueError("max_variants must be positive")
    original = normalize_query(value)
    variants: list[str] = []
    for candidate in (original, _abbreviation_variant(original)):
        if candidate and candidate not in variants:
            variants.append(candidate)
        if len(variants) >= max_variants:
            break
    return variants
