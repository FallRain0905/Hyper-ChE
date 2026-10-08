# -*- coding: utf-8 -*-
"""Resolve unified channels/model_profiles into the legacy provider-candidate shape.

The LLM pool in ``main.py`` (semaphores, health records, cooldown, failover)
already works well. Rather than rewrite it, this module adapts the new registry
into the exact candidate dict that pool consumes::

    {
      "provider": {name, baseUrl, modelName, apiKeys, enabled, maxAsync,
                   perKeyMaxAsync, priority, index},
      "key": <plaintext key>, "key_index": int, "key_total": int,
      "provider_id": str, "key_id": str,
    }

Secrets are decrypted here and nowhere else, and are never logged.
"""

from __future__ import annotations

import hashlib
from typing import Any

from auth import auth_store

MODEL_ROLES = ("extraction", "answer", "judge", "embedding", "reranker")

# Roles that describe a chat-completion model (as opposed to an embedding model).
LLM_ROLES = ("extraction", "answer", "judge", "reranker")


def _split_keys(value: str | None) -> list[str]:
    if not value:
        return []
    result: list[str] = []
    for chunk in str(value).replace(";", "\n").replace(",", "\n").split("\n"):
        chunk = chunk.strip()
        if chunk:
            result.append(chunk)
    return result


def _fingerprint(key: str | None) -> str:
    if not key:
        return "nokey"
    return hashlib.sha256(key.encode("utf-8", errors="ignore")).hexdigest()[:12]


def _provider_id(provider: dict) -> str:
    return "|".join(
        [
            str(provider.get("name", "")),
            str(provider.get("baseUrl", "")),
            str(provider.get("modelName", "")),
        ]
    )


def _profile_to_provider(profile: dict, index: int) -> dict[str, Any] | None:
    """Turn one model_profile row into a legacy provider dict."""
    channel = profile.get("channel") or {}
    channel_id = channel.get("id") or profile.get("channel_id")
    base_url = (channel.get("base_url") or "").strip()
    model_name = (profile.get("model_name") or "").strip()
    if not base_url or not model_name or not channel_id:
        return None

    secret = auth_store.get_channel_secret(channel_id)
    keys = _split_keys(secret)
    scope = channel.get("scope") or "platform"
    provider_name = channel.get("provider_name") or f"channel-{index + 1}"
    if scope == "user":
        provider_name = f"user:{provider_name}"

    per_key = profile.get("per_key_max_concurrency")
    max_async = profile.get("max_concurrency") or 4
    return {
        "name": provider_name,
        "baseUrl": base_url,
        "modelName": model_name,
        "apiKeys": keys,
        "enabled": True,
        "maxAsync": max(1, int(max_async)),
        "perKeyMaxAsync": max(1, int(per_key)) if per_key else None,
        "priority": int(profile.get("priority") or 100),
        "index": index,
        "protocol": channel.get("protocol") or "openai",
        "scope": scope,
        "timeout_seconds": profile.get("timeout_seconds"),
        "profile_id": profile.get("id"),
        "channel_id": channel_id,
        # Embedding-only metadata; unused by the chat pool but useful to callers.
        "embeddingDim": profile.get("embedding_dim"),
    }


def resolve_role_providers(
    role: str,
    *,
    current_user_id: str | None = None,
) -> list[dict[str, Any]]:
    """Return enabled provider dicts for a model role.

    The caller's own channels are included so a personal key takes precedence;
    callers decide the ordering between user and platform providers.
    """
    profiles = auth_store.list_model_profiles_for_role(role, include_user_id=current_user_id)
    providers: list[dict[str, Any]] = []
    for index, profile in enumerate(profiles):
        provider = _profile_to_provider(profile, index)
        if provider and provider["apiKeys"]:
            providers.append(provider)
    return providers


def build_candidates(
    providers: list[dict[str, Any]],
    *,
    key_state: dict[str, Any] | None = None,
    cursor: int = 0,
    now: float | None = None,
) -> list[dict[str, Any]]:
    """Expand providers into the per-key candidate list the LLM pool expects.

    ``key_state`` is the pool's ``LLM_PROVIDER_POOL_STATE["keys"]`` mapping so
    existing health/cooldown records still apply across restarts.
    """
    import time as _time

    moment = _time.monotonic() if now is None else now
    key_state = key_state or {}
    candidates: list[dict[str, Any]] = []

    ordered = sorted(providers, key=lambda item: (item.get("priority", 100), item.get("index", 0)))
    for provider_pos, provider in enumerate(ordered, start=1):
        keys = provider.get("apiKeys") or [None]
        key_total = len(keys)
        for key_index, key in enumerate(keys, start=1):
            provider_id = _provider_id(provider)
            key_id = f"{provider_id}|{key_index}|{_fingerprint(key)}"
            health = key_state.get(key_id) or {}
            if health.get("disabled"):
                continue
            if health.get("cooldown_until", 0.0) > moment:
                continue
            candidates.append(
                {
                    "provider": provider,
                    "provider_index": provider_pos,
                    "provider_total": len(ordered),
                    "key": key,
                    "key_index": key_index,
                    "key_total": key_total,
                    "provider_id": provider_id,
                    "key_id": key_id,
                }
            )

    if not candidates:
        return []
    start = cursor % len(candidates) if cursor else 0
    return candidates[start:] + candidates[:start]


def summarize_role(role: str, *, current_user_id: str | None = None) -> dict[str, Any]:
    """Secret-free summary of the providers configured for a role."""
    profiles = auth_store.list_model_profiles_for_role(role, include_user_id=current_user_id)
    entries = []
    for profile in profiles:
        channel = profile.get("channel") or {}
        entries.append(
            {
                "role": profile.get("role"),
                "model_name": profile.get("model_name"),
                "embedding_dim": profile.get("embedding_dim"),
                "max_concurrency": profile.get("max_concurrency"),
                "priority": profile.get("priority"),
                "provider_name": channel.get("provider_name"),
                "scope": channel.get("scope"),
                "protocol": channel.get("protocol"),
                "base_url": channel.get("base_url"),
                "has_secret": bool(auth_store.get_channel_secret(channel.get("id") or "")),
            }
        )
    return {"role": role, "count": len(entries), "providers": entries}


def embedding_profile(*, current_user_id: str | None = None) -> dict[str, Any] | None:
    """Return the highest-priority embedding profile, preferring the user's own."""
    profiles = auth_store.list_model_profiles_for_role("embedding", include_user_id=current_user_id)
    for profile in profiles:
        channel = profile.get("channel") or {}
        if channel.get("scope") == "user":
            return profile
    return profiles[0] if profiles else None


__all__ = [
    "LLM_ROLES",
    "MODEL_ROLES",
    "build_candidates",
    "embedding_profile",
    "resolve_role_providers",
    "summarize_role",
]
