"""String normalization for lightweight chemical entity matching."""

from __future__ import annotations

import re
import unicodedata

SUPERSCRIPT_MAP = str.maketrans(
    {
        "⁰": "0",
        "¹": "1",
        "²": "2",
        "³": "3",
        "⁴": "4",
        "⁵": "5",
        "⁶": "6",
        "⁷": "7",
        "⁸": "8",
        "⁹": "9",
        "⁺": "+",
        "⁻": "-",
    }
)

SUBSCRIPT_MAP = str.maketrans(
    {
        "₀": "0",
        "₁": "1",
        "₂": "2",
        "₃": "3",
        "₄": "4",
        "₅": "5",
        "₆": "6",
        "₇": "7",
        "₈": "8",
        "₉": "9",
        "₊": "+",
        "₋": "-",
    }
)

SYMBOL_REPLACEMENTS = {
    "−": "-",
    "–": "-",
    "—": "-",
    "‐": "-",
    "＋": "+",
    "≥": ">=",
    "≤": "<=",
    "＞": ">",
    "＜": "<",
    "／": "/",
    "•": "·",
    "∙": "·",
    "μ": "u",
    "µ": "u",
    "㎛": "um",
    "℃": "degc",
    "°C": "degc",
    "°c": "degc",
    "°": "",
}


def to_half_width(text: str) -> str:
    return unicodedata.normalize("NFKC", text or "")


def _preserve_high_risk_ion_notation(text: str) -> str:
    """Normalize high-risk ion notations without erasing valence distinctions."""

    value = text
    value = re.sub(r"\bVO\s*²\s*⁺", "VO^2+", value, flags=re.IGNORECASE)
    value = re.sub(r"\bVO\s*\^\s*2\s*\+", "VO^2+", value, flags=re.IGNORECASE)
    value = re.sub(r"\bVO\s*₂\s*⁺", "VO2+", value, flags=re.IGNORECASE)
    value = re.sub(r"\bVO\s*2\s*\+", "VO2+", value, flags=re.IGNORECASE)
    value = re.sub(r"\bV\s*\(\s*II\s*\)", "V(II)", value, flags=re.IGNORECASE)
    value = re.sub(r"\bV\s*\(\s*III\s*\)", "V(III)", value, flags=re.IGNORECASE)
    value = re.sub(r"\bV\s*\(\s*IV\s*\)", "V(IV)", value, flags=re.IGNORECASE)
    value = re.sub(r"\bV\s*\(\s*V\s*\)", "V(V)", value, flags=re.IGNORECASE)
    value = re.sub(r"\bV\s*4\s*\+", "V4+", value, flags=re.IGNORECASE)
    value = re.sub(r"\bCr\s*\(\s*II\s*\)", "Cr(II)", value, flags=re.IGNORECASE)
    value = re.sub(r"\bCr\s*\(\s*III\s*\)", "Cr(III)", value, flags=re.IGNORECASE)
    return value


def normalize_radical_name(text: str) -> str:
    value = text
    value = re.sub(r"(?:·|\.)\s*OH\b", "oh_radical", value, flags=re.IGNORECASE)
    value = re.sub(r"\bOH\s+radicals?\b", "oh_radical", value, flags=re.IGNORECASE)
    value = re.sub(r"\bhydroxyl\s+radicals?\b", "oh_radical", value, flags=re.IGNORECASE)
    value = re.sub(r"(?:·|\.)\s*O2\s*-?\b", "o2_radical", value, flags=re.IGNORECASE)
    value = re.sub(r"\bO2\s+radical\s+anion\b", "o2_radical", value, flags=re.IGNORECASE)
    value = re.sub(r"\bsuperoxide\s+radicals?\b", "o2_radical", value, flags=re.IGNORECASE)
    value = re.sub(r"\bSO4\s*(?:·|-?radical)?\s*-?\b", "so4_radical", value, flags=re.IGNORECASE)
    return value


def normalize_units_in_text(text: str) -> str:
    value = text
    value = re.sub(r"mA\s*(?:/|\s+)\s*cm\s*(?:\^?\s*-?\s*2|2)", "ma/cm2", value, flags=re.IGNORECASE)
    value = re.sub(r"W\s*(?:/|\s+)\s*cm\s*(?:\^?\s*-?\s*2|2)", "w/cm2", value, flags=re.IGNORECASE)
    value = re.sub(r"mg\s*(?:/|\s+)\s*L\s*(?:\^?\s*-?\s*1)?", "mg/l", value, flags=re.IGNORECASE)
    value = re.sub(r"g\s*(?:/|\s+)\s*L\s*(?:\^?\s*-?\s*1)?", "g/l", value, flags=re.IGNORECASE)
    value = re.sub(r"mol\s*(?:/|\s+)\s*L\s*(?:\^?\s*-?\s*1)?", "mol/l", value, flags=re.IGNORECASE)
    return value


def normalize_text(text: str, *, lowercase: bool = False) -> str:
    """Human-readable normalization used for display/report fields."""

    value = _preserve_high_risk_ion_notation(str(text or ""))
    value = to_half_width(value)
    for src, dst in SYMBOL_REPLACEMENTS.items():
        value = value.replace(src, dst)
    value = value.translate(SUPERSCRIPT_MAP).translate(SUBSCRIPT_MAP)
    value = normalize_radical_name(value)
    value = normalize_units_in_text(value)
    value = re.sub(r"\s+", " ", value)
    value = re.sub(r"\s*([/+(),;:])\s*", r"\1", value)
    value = re.sub(r"\s*-\s*", "-", value)
    value = value.strip(" \t\r\n\"'")
    return value.lower() if lowercase else value


def normalize_text_for_match(text: str) -> str:
    """Return a compact matching key; never use it as the displayed entity name."""

    value = normalize_text(text, lowercase=True)
    value = re.sub(r"\bba\s*ti\s*o\s*3\b", "batio3", value)
    value = re.sub(r"\bbi\s*fe\s*o\s*3\b", "bifeo3", value)
    value = re.sub(r"\s+", "", value)
    value = re.sub(r"[\"'`~!?,.;:()\[\]{}]", "", value)
    value = value.replace("_", "")
    return value


def normalize_formula_key(text: str) -> str:
    return normalize_text_for_match(text)
