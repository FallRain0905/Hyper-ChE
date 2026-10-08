"""Materialize published prompt packs into loadable domain directories.

The HyperRAG core reads prompt templates from ``hyperrag/domains/<domain>`` on
disk via ``DomainManager``. Rather than change that read path, the Studio stores
prompt packs in SQL and renders the selected version onto disk as a synthetic
domain directory. ``DomainManager`` then treats it like any built-in domain.

Two properties matter:

* The directory name is derived from the pack id and the version's content
  hash, so a given ``pack@version`` always maps to a stable path and a changed
  version can never collide with a cached ``DomainManager`` config entry.
* Rendering is idempotent: existing files are only rewritten when their content
  differs, so repeated materialization does not churn the filesystem.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

# Template files DomainManager.get_prompt_template() looks up by name.
PROMPT_TEMPLATE_NAMES = (
    "entity_extraction",
    "one_pass_extraction",
    "low_order_extraction",
    "high_order_extraction",
    "relationship_extraction",
    "query_keywords",
)
# Non-file prompts. They are kept in the version body for the Studio and for
# answer-time prompt selection, but are not written as domain templates today.
VIRTUAL_PROMPT_NAMES = ("answer", "judge")

_DOMAIN_SAFE_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def materialized_root() -> Path:
    """Directory holding rendered prompt packs.

    Defaults to ``<repo>/web-ui/backend/runtime/prompt_domains``; override with
    ``HYPERCHE_PROMPT_DOMAINS_DIR`` when the backend is containerized.
    """
    configured = os.getenv("HYPERCHE_PROMPT_DOMAINS_DIR")
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[2] / "web-ui" / "backend" / "runtime" / "prompt_domains"


def domain_alias(pack_id: str, content_hash: str | None) -> str:
    """Build the synthetic domain directory name for a pack version."""
    safe_pack = _DOMAIN_SAFE_RE.sub("_", (pack_id or "")[:16]) or "pack"
    digest = (content_hash or "nohash")[:12]
    return f"pack_{safe_pack}_{digest}"


def render_domain_dir(
    *,
    pack_id: str,
    config: dict[str, Any],
    prompts: dict[str, Any],
    content_hash: str | None = None,
    root: Path | None = None,
) -> Path:
    """Write a pack version to disk and return the domain directory path."""
    target_root = root or materialized_root()
    domain_dir = target_root / domain_alias(pack_id, content_hash)
    domain_dir.mkdir(parents=True, exist_ok=True)

    config_path = domain_dir / "config.json"
    config_text = json.dumps(config or {}, ensure_ascii=False, indent=2)
    if not config_path.exists() or config_path.read_text(encoding="utf-8") != config_text:
        config_path.write_text(config_text, encoding="utf-8")

    for name in PROMPT_TEMPLATE_NAMES:
        template = prompts.get(name)
        template_path = domain_dir / f"{name}.txt"
        if template is None:
            # A missing template stays absent so DomainManager falls back to the
            # default domain or the built-in prompt, matching current behavior.
            if template_path.exists():
                template_path.unlink()
            continue
        text = str(template)
        if not template_path.exists() or template_path.read_text(encoding="utf-8") != text:
            template_path.write_text(text, encoding="utf-8")

    return domain_dir


def materialize_version(version: dict[str, Any]) -> Path:
    """Render a version dict (as returned by AuthStore) onto disk.

    ``version`` must include ``pack_id``, ``config``, ``prompts`` and ideally
    ``content_hash``. Use ``AuthStore.get_prompt_version(..., include_body=True)``.
    """
    return render_domain_dir(
        pack_id=version.get("pack_id", ""),
        config=version.get("config") or {},
        prompts=version.get("prompts") or {},
        content_hash=version.get("content_hash"),
    )


__all__ = [
    "PROMPT_TEMPLATE_NAMES",
    "VIRTUAL_PROMPT_NAMES",
    "domain_alias",
    "materialize_version",
    "materialized_root",
    "render_domain_dir",
]
