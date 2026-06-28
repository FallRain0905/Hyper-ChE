"""Experiment mode utilities for Hyper-ChE benchmarks."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

try:
    import yaml
except Exception:  # pragma: no cover
    yaml = None


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODES_PATH = REPO_ROOT / "configs" / "experiments" / "modes.yaml"
DEFAULT_EXPERIMENT_MODE = "hyper_final"
EXPERIMENT_SWITCHES = (
    "enable_entity_normalization",
    "enable_measurement_instances",
    "enable_efu_repair",
    "enable_hybrid_rerank",
)


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Experiment config not found: {path}")
    text = path.read_text(encoding="utf-8")
    if yaml is not None:
        data = yaml.safe_load(text) or {}
    else:
        data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(f"Experiment config must be an object: {path}")
    return data


def load_experiment_modes(path: str | Path | None = None) -> dict[str, dict[str, Any]]:
    data = _load_yaml(Path(path) if path else DEFAULT_MODES_PATH)
    modes = data.get("modes", data)
    if not isinstance(modes, dict):
        raise ValueError("Experiment modes config must contain a 'modes' mapping.")
    return {str(name): dict(config or {}) for name, config in modes.items()}


def resolve_prompt_domain(prompt_profile: str | None, domain: str | None = None) -> str:
    profile = (prompt_profile or "chemistry").strip()
    if profile == "generic_json":
        return "generic_json"
    if profile == "chemistry":
        return domain or "flow_battery"
    return domain or profile


def resolve_experiment_mode(
    mode: str | None = None,
    *,
    domain: str | None = "flow_battery",
    modes_path: str | Path | None = None,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    mode_name = mode or DEFAULT_EXPERIMENT_MODE
    modes = load_experiment_modes(modes_path)
    if mode_name not in modes:
        raise KeyError(f"Unknown experiment mode '{mode_name}'. Available modes: {', '.join(sorted(modes))}")

    config = dict(modes[mode_name])
    config.update(overrides or {})
    prompt_profile = config.get("prompt_profile", "chemistry")
    effective_domain = resolve_prompt_domain(prompt_profile, domain)

    resolved = {
        "experiment_mode": mode_name,
        "mode": mode_name,
        "query_mode": config.get("query_mode", "hyper"),
        "prompt_profile": prompt_profile,
        "domain": domain or "flow_battery",
        "effective_domain": effective_domain,
    }
    for key in EXPERIMENT_SWITCHES:
        resolved[key] = bool(config.get(key, True))
    return resolved


def write_run_config(
    cache_dir: str | Path,
    resolved_config: dict[str, Any],
    *,
    extra: dict[str, Any] | None = None,
) -> Path:
    path = Path(cache_dir)
    path.mkdir(parents=True, exist_ok=True)
    payload = {
        "experiment_mode": resolved_config.get("experiment_mode") or resolved_config.get("mode"),
        "query_mode": resolved_config.get("query_mode"),
        "prompt_profile": resolved_config.get("prompt_profile"),
        "domain": resolved_config.get("domain"),
        "effective_domain": resolved_config.get("effective_domain", resolved_config.get("domain")),
        "enable_entity_normalization": bool(resolved_config.get("enable_entity_normalization", True)),
        "enable_measurement_instances": bool(resolved_config.get("enable_measurement_instances", True)),
        "enable_efu_repair": bool(resolved_config.get("enable_efu_repair", True)),
        "enable_hybrid_rerank": bool(resolved_config.get("enable_hybrid_rerank", True)),
        "corpus_id": resolved_config.get("corpus_id") or path.name,
        "cache_dir": str(path.resolve()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if extra:
        payload.update(_redact_payload(extra))
    output = path / "run_config.json"
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return output


def _redact_payload(value: Any) -> Any:
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            lower = str(key).lower()
            if any(token in lower for token in ("key", "token", "secret", "password", "authorization")):
                result[key] = "[REDACTED]"
            else:
                result[key] = _redact_payload(item)
        return result
    if isinstance(value, list):
        return [_redact_payload(item) for item in value]
    return value
