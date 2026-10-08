# -*- coding: utf-8 -*-
"""Idempotent startup migrations for the unified provider and prompt registries.

Two one-time imports run here:

1. Built-in ``hyperrag/domains/<domain>`` directories are imported as
   read-only ``system`` prompt packs, each with a single published version.
2. Legacy model configuration is imported into ``channels`` / ``model_profiles``:
   ``settings.json`` providers and embedding settings become ``platform``
   channels, and each ``user_api_keys`` row becomes a ``user`` channel.

Every import is idempotent. It is skipped once a row carrying the matching
``migrated_from`` marker exists, so restarting the service never duplicates
data and never overwrites later edits.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from auth import auth_store, utcnow

PROMPT_TEMPLATE_NAMES = (
    "entity_extraction",
    "one_pass_extraction",
    "low_order_extraction",
    "high_order_extraction",
    "relationship_extraction",
    "query_keywords",
)
# Answer and judge prompts do not ship as domain files today. They are stored
# as empty strings so the Studio can populate them without a schema change.
ANSWER_PROMPT_KEY = "answer"
JUDGE_PROMPT_KEY = "judge"

MIGRATION_MARKER_SETTINGS = "settings.json"
MIGRATION_MARKER_USER_KEYS = "user_api_keys"
SEED_MARKER = "builtin-domains"


def _repo_root() -> Path:
    # The checkout keeps this module under web-ui/backend; the production image
    # flattens it into /app alongside hyperrag. Resolve both layouts by content.
    module_path = Path(__file__).resolve()
    for candidate in module_path.parents:
        if (candidate / "hyperrag" / "domains").is_dir():
            return candidate
    return module_path.parent


def _domains_dir() -> Path:
    return _repo_root() / "hyperrag" / "domains"


def _log(message: str) -> None:
    print(f"[migrations] {message}", file=sys.stderr)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _split_api_keys(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if not value:
        return []
    text = str(value)
    parts: list[str] = []
    for chunk in text.replace(";", "\n").replace(",", "\n").split("\n"):
        chunk = chunk.strip()
        if chunk:
            parts.append(chunk)
    return parts


def _strip_endpoint_suffix(url: str) -> str:
    cleaned = (url or "").strip().rstrip("/")
    for suffix in ("/chat/completions", "/embeddings", "/completions"):
        if cleaned.endswith(suffix):
            cleaned = cleaned[: -len(suffix)]
    return cleaned


# ---------------------------------------------------------------------------
# Built-in domain seed
# ---------------------------------------------------------------------------

def seed_builtin_domain_packs() -> int:
    """Import ``hyperrag/domains`` as read-only system prompt packs."""
    existing = {pack["domain_id"] for pack in auth_store.list_prompt_packs(include_system=True) if pack["scope"] == "system"}
    domains_dir = _domains_dir()
    if not domains_dir.exists():
        return 0

    created = 0
    for domain_path in sorted(domains_dir.iterdir()):
        if not domain_path.is_dir():
            continue
        config_path = domain_path / "config.json"
        if not config_path.exists():
            continue
        domain_id = domain_path.name
        if domain_id in existing:
            continue

        config = _read_json(config_path)
        prompts: dict[str, str] = {}
        for template_name in PROMPT_TEMPLATE_NAMES:
            template_path = domain_path / f"{template_name}.txt"
            prompts[template_name] = template_path.read_text(encoding="utf-8") if template_path.exists() else ""
        prompts.setdefault(ANSWER_PROMPT_KEY, "")
        prompts.setdefault(JUDGE_PROMPT_KEY, "")

        pack = auth_store.create_prompt_pack(
            domain_id=domain_id,
            name=config.get("domain_name") or domain_id,
            description=config.get("domain_description") or "Built-in domain imported from hyperrag/domains.",
            scope="system",
            owner_user_id=None,
            status="published",
        )
        version = auth_store.create_prompt_version(
            pack_id=pack["id"],
            config=config,
            prompts=prompts,
            changelog=f"Imported from hyperrag/domains/{domain_id}",
            created_by=None,
            status="published",
        )
        auth_store.publish_prompt_version(pack["id"], version["id"])
        created += 1

    if created:
        _log(f"seeded {created} built-in domain prompt pack(s)")
    return created


# ---------------------------------------------------------------------------
# Legacy model configuration import
# ---------------------------------------------------------------------------

def _import_settings_channels(settings: dict[str, Any]) -> int:
    """Import settings.json providers plus embedding config as platform channels."""
    if auth_store.count_channels("platform") > 0:
        return 0

    created = 0
    providers = settings.get("llmProviders")
    if not isinstance(providers, list):
        providers = []

    fallback_base = _strip_endpoint_suffix(str(settings.get("baseUrl") or ""))
    fallback_model = str(settings.get("modelName") or "")
    fallback_keys = _split_api_keys(settings.get("apiKey"))

    normalized: list[dict[str, Any]] = []
    for index, provider in enumerate(providers):
        if not isinstance(provider, dict):
            continue
        keys = _split_api_keys(provider.get("apiKeys"))
        if not keys:
            keys = fallback_keys
        normalized.append(
            {
                "name": provider.get("name") or f"provider-{index + 1}",
                "protocol": str(settings.get("modelProvider") or "openai"),
                "base_url": _strip_endpoint_suffix(str(provider.get("baseUrl") or fallback_base)),
                "keys": keys,
                "model": str(provider.get("modelName") or fallback_model),
                "enabled": bool(provider.get("enabled", True)),
                "max_async": int(provider.get("maxAsync") or settings.get("llmPerKeyMaxAsync") or 4),
                "per_key_max_async": provider.get("perKeyMaxAsync"),
                "priority": int(provider.get("priority") or (index + 1) * 10),
            }
        )

    if not normalized and (fallback_base or fallback_keys):
        normalized.append(
            {
                "name": "legacy-llm",
                "protocol": str(settings.get("modelProvider") or "openai"),
                "base_url": fallback_base,
                "keys": fallback_keys,
                "model": fallback_model,
                "enabled": True,
                "max_async": int(settings.get("llmPerKeyMaxAsync") or 4),
                "per_key_max_async": settings.get("llmPerKeyMaxAsync"),
                "priority": 10,
            }
        )

    for provider in normalized:
        channel = auth_store.create_channel(
            scope="platform",
            owner_user_id=None,
            provider_name=provider["name"],
            protocol=provider["protocol"],
            base_url=provider["base_url"],
            secret="\n".join(provider["keys"]),
            status="active" if provider["enabled"] else "disabled",
            migrated_from=MIGRATION_MARKER_SETTINGS,
        )
        created += 1
        for role in ("extraction", "answer"):
            auth_store.create_model_profile(
                channel_id=channel["id"],
                role=role,
                model_name=provider["model"],
                max_concurrency=provider["max_async"],
                per_key_max_concurrency=provider["per_key_max_async"],
                timeout_seconds=int(settings.get("llmTimeout") or 600),
                priority=provider["priority"],
            )

    embedding_model = str(settings.get("embeddingModel") or "")
    embedding_dim = settings.get("embeddingDim")
    embedding_keys = _split_api_keys(settings.get("embeddingApiKey")) or fallback_keys
    embedding_base = _strip_endpoint_suffix(str(settings.get("embeddingBaseUrl") or fallback_base))
    if embedding_model or embedding_keys:
        channel = auth_store.create_channel(
            scope="platform",
            owner_user_id=None,
            provider_name="legacy-embedding",
            protocol="openai",
            base_url=embedding_base,
            secret="\n".join(embedding_keys),
            status="active",
            migrated_from=MIGRATION_MARKER_SETTINGS,
        )
        created += 1
        auth_store.create_model_profile(
            channel_id=channel["id"],
            role="embedding",
            model_name=embedding_model,
            embedding_dim=int(embedding_dim) if embedding_dim else None,
            max_concurrency=int(settings.get("embeddingMaxAsync") or 4),
            timeout_seconds=int(settings.get("embeddingTimeout") or 600),
            priority=10,
        )

    if created:
        _log(f"imported {created} platform channel(s) from settings.json")
    return created


def _import_user_api_keys() -> int:
    """Import each user_api_keys row as a user-scoped channel."""
    existing_owners = {
        (channel["owner_user_id"], channel["id"])
        for channel in auth_store.list_channels(scope="user")
    }
    if auth_store.list_channels(scope="user") and any(
        channel.get("migrated_from") == MIGRATION_MARKER_USER_KEYS
        for channel in auth_store.list_channels(scope="user")
    ):
        return 0

    from sqlalchemy import select

    from auth import _fernet, _split_api_keys as split_keys, user_api_keys

    created = 0
    try:
        users = auth_store.list_users()
    except Exception:
        users = []

    with auth_store.engine.begin() as conn:
        rows = conn.execute(select(user_api_keys)).mappings().all()

    for row in rows:
        if (row["user_id"], row["id"]) in existing_owners:
            continue
        try:
            secret = _fernet().decrypt(row["api_key_encrypted"].encode("utf-8")).decode("utf-8")
        except Exception:
            continue
        keys = split_keys(secret)
        if not keys:
            continue
        role = "embedding" if row["provider_type"] == "embedding" else "answer"
        channel = auth_store.create_channel(
            scope="user",
            owner_user_id=row["user_id"],
            provider_name=f"personal-{row['provider_type']}",
            protocol="openai",
            base_url=_strip_endpoint_suffix(row["base_url"] or ""),
            secret="\n".join(keys),
            status="active" if row["enabled"] else "disabled",
            migrated_from=MIGRATION_MARKER_USER_KEYS,
        )
        created += 1
        auth_store.create_model_profile(
            channel_id=channel["id"],
            role=role,
            model_name=row["model_name"] or "",
            priority=5,
        )
        if role == "answer":
            auth_store.create_model_profile(
                channel_id=channel["id"],
                role="extraction",
                model_name=row["model_name"] or "",
                priority=5,
            )

    if created:
        _log(f"imported {created} user channel(s) from user_api_keys")
    return created


def scrub_plaintext_settings_secrets(settings_file: str | Path | None = None) -> bool:
    """Remove platform API keys from settings.json once they live in the registry.

    Platform keys were historically stored as plaintext JSON. After they are
    migrated into the encrypted ``channels`` table, the plaintext copies are
    blanked so the file on disk no longer carries credentials. The migration
    only runs when at least one platform channel exists, so a failed import can
    never destroy the only copy of a key.
    """
    if auth_store.count_channels("platform") <= 0:
        return False

    settings_path = Path(settings_file) if settings_file else Path(os.getenv("HYPERCHE_SETTINGS_FILE") or "settings.json")
    original = _read_json(settings_path)
    if not original:
        return False
    data = json.loads(json.dumps(original))  # deep copy so the backup keeps the originals

    changed = False
    for key in ("apiKey", "embeddingApiKey"):
        if data.get(key):
            data[key] = ""
            changed = True
    providers = data.get("llmProviders")
    if isinstance(providers, list):
        for provider in providers:
            if isinstance(provider, dict) and provider.get("apiKeys"):
                provider["apiKeys"] = []
                changed = True

    if not changed:
        return False

    try:
        # Keep a one-time backup so an operator can recover if a channel import
        # was incomplete; the backup itself still contains secrets and should be
        # removed once the migration is confirmed.
        backup = settings_path.with_suffix(".json.secrets-backup")
        if not backup.exists():
            backup.write_text(json.dumps(original, ensure_ascii=False, indent=2), encoding="utf-8")
        settings_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        _log(f"scrubbed plaintext platform secrets from {settings_path.name} (backup: {backup.name})")
        return True
    except Exception as exc:  # pragma: no cover - defensive
        _log(f"failed to scrub plaintext secrets: {exc}")
        return False


def run_startup_migrations(settings_file: str | Path | None = None) -> dict[str, int]:
    """Run every idempotent migration. Safe to call on each process start."""
    summary = {"seed_packs": 0, "platform_channels": 0, "user_channels": 0, "secrets_scrubbed": 0}

    try:
        summary["seed_packs"] = seed_builtin_domain_packs()
    except Exception as exc:  # pragma: no cover - defensive
        _log(f"domain seed failed: {exc}")

    settings_path = Path(settings_file) if settings_file else Path(os.getenv("HYPERCHE_SETTINGS_FILE") or "settings.json")
    try:
        summary["platform_channels"] = _import_settings_channels(_read_json(settings_path))
    except Exception as exc:  # pragma: no cover - defensive
        _log(f"settings channel import failed: {exc}")

    try:
        summary["user_channels"] = _import_user_api_keys()
    except Exception as exc:  # pragma: no cover - defensive
        _log(f"user key import failed: {exc}")

    # Only after keys are safely in the encrypted registry.
    try:
        summary["secrets_scrubbed"] = 1 if scrub_plaintext_settings_secrets(settings_path) else 0
    except Exception as exc:  # pragma: no cover - defensive
        _log(f"secret scrub failed: {exc}")

    return summary
