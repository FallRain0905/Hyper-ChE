"""Rule-based parser for common chemical conditions and metrics."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import re

from .text_normalizer import normalize_text


@dataclass
class ParsedQuantity:
    raw: str
    quantity_type: str
    operator: str
    value: float | None = None
    min_value: float | None = None
    max_value: float | None = None
    unit: str | None = None
    confidence: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


class UnitParser:
    """Parse numeric values, ranges, comparisons, and common units."""

    UNIT_PATTERNS: list[tuple[str, str, str]] = [
        ("current_density", r"mA\s*(?:/| )\s*cm(?:-?2|2)", "mA/cm2"),
        ("temperature", r"(?:°C|C|K)\b", None),
        ("concentration", r"(?:mol/L|M|g/L|mg/L|mM|μM)\b", None),
        ("time", r"(?:min|h|hr|hour|hours|s)\b", None),
        ("pH", r"pH\b", "pH"),
        ("ultrasonic_frequency", r"kHz\b", "kHz"),
        ("power_density", r"W\s*/\s*cm2", "W/cm2"),
        ("efficiency", r"%", "%"),
        ("removal_rate", r"%", "%"),
        ("defluorination_rate", r"%", "%"),
    ]

    NUMBER = r"[-+]?\d+(?:\.\d+)?"

    def parse(self, text: str, *, hint: str | None = None) -> ParsedQuantity | None:
        raw = str(text or "")
        if not raw.strip():
            return None
        value = normalize_text(raw)
        quantity_type, unit = self._detect_quantity(value, hint)
        if not quantity_type:
            return None

        operator = "="
        op_match = re.search(r"(>=|<=|>|<|≥|≤|≈|~|about|approximately)", value, flags=re.IGNORECASE)
        if op_match:
            token = op_match.group(1).lower()
            operator = {">=": ">=", "≥": ">=", "<=": "<=", "≤": "<=", "≈": "approx", "~": "approx"}.get(token, token)
            if token in {"about", "approximately"}:
                operator = "approx"

        range_match = re.search(rf"({self.NUMBER})\s*(?:-|to|~)\s*({self.NUMBER})", value, flags=re.IGNORECASE)
        if range_match:
            min_value = float(range_match.group(1))
            max_value = float(range_match.group(2))
            if min_value > max_value:
                min_value, max_value = max_value, min_value
            return ParsedQuantity(raw=raw, quantity_type=quantity_type, operator="range", min_value=min_value, max_value=max_value, unit=unit, confidence=0.9)

        number_match = re.search(self.NUMBER, value)
        if not number_match and quantity_type == "pH":
            number_match = re.search(r"pH\s*[:=]?\s*(" + self.NUMBER + ")", value, flags=re.IGNORECASE)
        if not number_match:
            return None

        return ParsedQuantity(raw=raw, quantity_type=quantity_type, operator=operator, value=float(number_match.group(0)), unit=unit, confidence=0.85)

    def parse_dict(self, text: str, *, hint: str | None = None) -> dict | None:
        parsed = self.parse(text, hint=hint)
        return parsed.to_dict() if parsed else None

    def _detect_quantity(self, text: str, hint: str | None = None) -> tuple[str | None, str | None]:
        hint_text = (hint or "").lower()
        combined = f"{hint_text} {text}".lower()
        if "current density" in combined:
            return "current_density", "mA/cm2"
        if "temperature" in combined or re.search(r"°c|\bk\b", combined):
            unit = "K" if re.search(r"\bK\b", text) else "°C"
            return "temperature", unit
        if "concentration" in combined or re.search(r"\b(mol/L|M|g/L|mg/L|mM|μM)\b", text):
            match = re.search(r"\b(mol/L|M|g/L|mg/L|mM|μM)\b", text)
            return "concentration", match.group(1) if match else None
        if "time" in combined or re.search(r"\b(min|h|hr|hour|hours|s)\b", combined):
            match = re.search(r"\b(min|h|hr|hour|hours|s)\b", text, flags=re.IGNORECASE)
            return "time", match.group(1) if match else None
        if "ph" in combined:
            return "pH", "pH"
        if "frequency" in combined or "ultrasound" in combined or "kHz" in text:
            return "ultrasonic_frequency", "kHz"
        if "power density" in combined:
            return "power_density", "W/cm2"
        if "defluorination" in combined:
            return "defluorination_rate", "%"
        if "removal" in combined or "degradation efficiency" in combined:
            return "removal_rate", "%"
        if any(term in combined for term in ["ce", "ve", "ee", "efficiency", "toc", "yield"]) and "%" in text:
            return "efficiency", "%"
        for quantity_type, pattern, normalized_unit in self.UNIT_PATTERNS:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                return quantity_type, normalized_unit or match.group(0)
        return None, None
