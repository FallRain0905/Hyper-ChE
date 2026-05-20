# -*- coding: utf-8 -*-
import sys
import io
import re
import logging  # Import logging early for SafeLogFilter class definition
import traceback
import hashlib
import contextvars
from logging.handlers import RotatingFileHandler

# Safe string conversion function for Windows encoding
def safe_str(obj):
    """Convert object to string with safe encoding for Windows gbk"""
    try:
        # First try to convert to string
        s = str(obj)

        if sys.platform == 'win32':
            # Use a more comprehensive approach to handle all problematic Unicode characters
            safe_chars = []
            for char in s:
                try:
                    # Test if the character can be encoded in gbk
                    char.encode('gbk')
                    safe_chars.append(char)
                except (UnicodeEncodeError, UnicodeDecodeError):
                    # If it fails, replace with a safe representation
                    safe_chars.append(f'[U+{ord(char):04X}]')

            s = ''.join(safe_chars)

        return s
    except Exception as e:
        # If conversion fails completely, return a generic error message
        return f"[ENCODING ERROR: {type(e).__name__}]"

# Safe print function for Windows encoding
def safe_print(*args, **kwargs):
    """Print function that handles Unicode encoding issues safely"""
    try:
        # Convert all arguments to safe strings
        safe_args = [safe_str(arg) for arg in args]
        print(*safe_args, **kwargs)
    except Exception as e:
        # If printing fails, try a basic fallback
        try:
            print(f"[PRINT ERROR: {safe_str(e)}]")
        except Exception:
            # Ultimate fallback
            print("[UNABLE TO PRINT MESSAGE DUE TO ENCODING ERROR]")

def redact_text_for_log(text: str) -> str:
    """Mask common API key/token patterns in free-form log strings."""
    try:
        text = re.sub(r"sk-[A-Za-z0-9_\-]{8,}", "sk-[REDACTED]", text)
        text = re.sub(
            r"(?i)(api[_-]?key|apikey|embeddingApiKey|authorization|token|secret)(\s*[:=]\s*)(['\"]?)[^,'\"\s}]+",
            r"\1\2\3[REDACTED]",
            text,
        )
    except Exception:
        pass
    return text

# Safe log filter for Windows encoding
class SafeLogFilter(logging.Filter):
    """Log filter that handles Unicode encoding issues"""

    def filter(self, record):
        try:
            # Safe-ify the fully formatted log message and remove args to avoid double interpolation.
            try:
                message = record.getMessage()
            except Exception:
                message = str(record.msg)
            record.msg = redact_text_for_log(safe_str(message))
            record.args = ()
        except Exception:
            # If filtering fails, at least don't break the logging
            pass
        return True

def extract_user_friendly_error(error_message: str) -> str:
    """提取用户友好的错误信息"""
    error_lower = error_message.lower()

    if "insufficient" in error_lower or "balance" in error_lower or "余额" in error_message:
        return "API账户余额不足，请充值或更换可用的嵌入模型 API Key"
    elif "permissiondenied" in error_lower or "permission denied" in error_lower or "403" in error_message:
        return "API权限不足或账户不可用，请检查嵌入模型权限、账户余额和 API Key"
    elif "401" in error_message or "unauthorized" in error_lower:
        return "API密钥无效或未授权，请检查设置"
    elif "500" in error_message:
        return "API服务器暂时不可用，请稍后重试"
    elif "502" in error_message or "503" in error_message:
        return "API服务暂时过载，请等待片刻后重试"
    elif "rate" in error_lower or "limit" in error_lower:
        return "API请求过于频繁，请等待一段时间后重试"
    elif "timeout" in error_lower:
        return "请求超时，请检查网络连接或减少文件大小"
    elif "authentication" in error_lower or "key" in error_lower:
        return "API密钥配置错误，请检查设置"
    elif "quota" in error_lower:
        return "API配额已用完，请检查账户状态"
    elif "embeddings" in error_lower and "error" in error_lower:
        return "文本嵌入服务暂时不可用，请稍后重试"
    elif "invalid_request" in error_lower:
        return "请求格式错误，请检查文件内容"
    elif "connection" in error_lower:
        return "网络连接问题，请检查网络设置"
    else:
        # 提取错误的核心信息
        if "error" in error_lower:
            # 尝试提取第一个错误信息
            try:
                error_start = error_lower.index("error")
                error_part = error_message[error_start:error_start + 200]
                return f"处理失败: {error_part}..."
            except ValueError:
                pass
        return f"处理失败: {error_message[:100]}..."

def extract_detailed_exception_message(error: Exception) -> str:
    """从 RetryError/OpenAI 异常中提取真实底层错误，避免日志只显示 RetryError。"""
    messages = [safe_str(error)]

    try:
        last_attempt = getattr(error, "last_attempt", None)
        inner_error = last_attempt.exception() if last_attempt else None
        if inner_error is not None:
            messages.append(f"{type(inner_error).__name__}: {safe_str(inner_error)}")
            body = getattr(inner_error, "body", None)
            if body:
                messages.append(f"body={safe_str(body)}")
            status_code = getattr(inner_error, "status_code", None)
            if status_code:
                messages.append(f"status_code={status_code}")
            code = getattr(inner_error, "code", None)
            if code:
                messages.append(f"code={code}")
    except Exception:
        pass

    for chain_attr in ("__cause__", "__context__"):
        try:
            chained = getattr(error, chain_attr, None)
            if chained is not None:
                messages.append(f"{chain_attr}={type(chained).__name__}: {safe_str(chained)}")
                body = getattr(chained, "body", None)
                if body:
                    messages.append(f"{chain_attr}.body={safe_str(body)}")
                status_code = getattr(chained, "status_code", None)
                if status_code:
                    messages.append(f"{chain_attr}.status_code={status_code}")
                code = getattr(chained, "code", None)
                if code:
                    messages.append(f"{chain_attr}.code={code}")
        except Exception:
            pass

    return redact_text_for_log(" | ".join(dict.fromkeys(messages)))

SENSITIVE_LOG_KEYS = {
    "api_key",
    "apikey",
    "apiKey",
    "embeddingApiKey",
    "embedding_api_key",
    "authorization",
    "token",
    "secret",
}

def redact_for_log(value):
    """递归脱敏日志上下文，避免 API Key 写入日志文件。"""
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            if key in SENSITIVE_LOG_KEYS or any(s in key.lower() for s in ("key", "token", "secret", "authorization")):
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = redact_for_log(item)
        return redacted
    if isinstance(value, list):
        return [redact_for_log(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_for_log(item) for item in value)
    if isinstance(value, str):
        return redact_text_for_log(value)
    return value

def log_detailed_exception(logger: logging.Logger, title: str, error: Exception, context=None) -> str:
    """记录带上下文、底层异常和 traceback 的详细错误日志。"""
    detailed_error = extract_detailed_exception_message(error)
    logger.error(f"{title}: {detailed_error}")

    if context:
        try:
            logger.error(
                f"{title} context: "
                f"{json.dumps(redact_for_log(context), ensure_ascii=False, default=safe_str)}"
            )
        except Exception:
            logger.error(f"{title} context: {safe_str(redact_for_log(context))}")

    try:
        logger.error(
            f"{title} traceback:\n"
            f"{''.join(traceback.format_exception(type(error), error, error.__traceback__))}"
        )
    except Exception:
        logger.error(f"{title} traceback: <failed to format traceback>")

    return detailed_error

# Fix Windows encoding issue (only if not running under uvicorn)
# Check if we're running under uvicorn to avoid conflicts with its logging system
if sys.platform == 'win32' and 'uvicorn' not in sys.modules:
    try:
        # Only wrap if they're not already wrapped
        if not isinstance(sys.stdout, io.TextIOWrapper):
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        if not isinstance(sys.stderr, io.TextIOWrapper):
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except Exception as e:
        # If wrapping fails, continue without it - better to have encoding issues than crash
        pass

from fastapi import FastAPI, UploadFile, File, HTTPException, WebSocket, WebSocketDisconnect, Form, Request, Response, Depends
from fastapi.middleware.cors import CORSMiddleware
from auth import AUTH_COOKIE_NAME, auth_store, create_token
from db import get_hypergraph, getFrequentVertices, get_vertices, get_hyperedges, get_vertice, get_vertice_neighbor, get_hyperedge_neighbor_server, add_vertex, add_hyperedge, delete_vertex, delete_hyperedge, update_vertex, update_hyperedge, get_hyperedge_detail, db_manager, get_theme_hypergraph, get_theme_vertices, get_theme_hyperedges, get_theme_vertex_neighbor
from file_manager import file_manager
from kb_manager import KnowledgeBaseManager
import json
import os
import gc
import time
import asyncio
import numpy as np
import importlib.util
from pathlib import Path
from pydantic import BaseModel, Field
from typing import List, Optional, Any, Dict
from io import StringIO
from datetime import datetime

# 添加 HyperRAG 相关导入
# 若尚不可导入，则向上逐级查找含有 hyperrag 包的目录，并把“其父目录”加到 sys.path
if importlib.util.find_spec("hyperrag") is None:
    for parent in Path(__file__).resolve().parents:
        if (parent / "hyperrag" / "__init__.py").exists():
            sys.path.insert(0, str(parent))  # 注意是父目录，不是 …/hyperrag
            break

try:
    from hyperrag import HyperRAG, QueryParam
    from hyperrag.utils import EmbeddingFunc
    from hyperrag.llm import openai_embedding, openai_complete_if_cache
    HYPERRAG_AVAILABLE = True
except ImportError as e:
    print(f"HyperRAG not available: {e}")
    HYPERRAG_AVAILABLE = False

# 添加Cog-RAG导入
# 向上查找Hyper-RAG根目录并添加到sys.path，使cog-rag/cograg可以被导入
if importlib.util.find_spec("cograg") is None:
    for parent in Path(__file__).resolve().parents:
        # 检查是否是Hyper-RAG根目录（包含hyperrag和cog-rag子目录）
        if (parent / "hyperrag" / "__init__.py").exists() and (parent / "cog-rag" / "cograg" / "__init__.py").exists():
            if str(parent) not in sys.path:
                sys.path.insert(0, str(parent))
                print(f"已添加路径到sys.path: {parent}")
            # 添加cog-rag目录到sys.path以便导入
            cog_rag_path = parent / "cog-rag"
            if str(cog_rag_path) not in sys.path:
                sys.path.insert(0, str(cog_rag_path))
                print(f"已添加cog-rag路径到sys.path: {cog_rag_path}")
            break

try:
    # 尝试从cograg导入
    import importlib
    spec = importlib.util.find_spec("cograg")
    if spec:
        from cograg import CogRAG as CogRAGClass, QueryParam as CogQueryParam
        from cograg.utils import EmbeddingFunc
        COGRAG_AVAILABLE = True
        print("Cog-RAG 模块加载成功")
    else:
        raise ImportError("cograg module spec not found")
except ImportError as e:
    print(f"Cog-RAG not available: {e}")
    COGRAG_AVAILABLE = False
    print("Cog-RAG 模块不可用")


# 设置文件路径
SETTINGS_FILE = "settings.json"
API_KEY_POOL_STATE = {
    "llm": {"cursor": 0, "disabled": set()},
    "embedding": {"cursor": 0, "disabled": set()},
}
CURRENT_USER_ID = contextvars.ContextVar("hyperche_current_user_id", default=None)
LLM_PROVIDER_POOL_STATE = {
    "cursor": 0,
    "keys": {},
    "providers": {},
}

def get_runtime_settings_context() -> dict:
    """返回可安全写入日志的运行配置摘要。"""
    try:
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            settings = json.load(f)
        return {
            "model": settings.get("modelName"),
            "base_url": settings.get("baseUrl"),
            "embedding_model": settings.get("embeddingModel"),
            "embedding_base_url": settings.get("embeddingBaseUrl"),
            "embedding_dim": settings.get("embeddingDim"),
            "hyperrag_domain": settings.get("hyperrag_domain", "default"),
        }
    except Exception as e:
        return {"settings_error": safe_str(e)}

def split_api_keys(value: str | None) -> list[str]:
    """支持在同一个设置字段内用换行、逗号或分号配置多个 API Key。"""
    if not value:
        return []
    return [item.strip() for item in re.split(r"[\n,;]+", value) if item.strip()]

def mask_api_keys_for_settings(value: str | None) -> str:
    """Return one masked line per configured key so the settings UI preserves key count."""
    keys = split_api_keys(value)
    return "\n".join("***" for _ in keys)

def resolve_masked_api_key_text(new_value: str | None, existing_value: str | None) -> str:
    """Restore masked API key placeholders when saving settings.

    The frontend receives existing keys as one "***" per key. When saving, unchanged
    masked entries are restored from the previous settings while newly typed entries
    are kept. This also lets users add/remove individual keys in a multiline field.
    """
    new_keys = split_api_keys(new_value)
    if not new_keys:
        return ""

    existing_keys = split_api_keys(existing_value)
    if all(key == "***" for key in new_keys):
        if len(new_keys) == len(existing_keys):
            return "\n".join(existing_keys)

    resolved = []
    for index, key in enumerate(new_keys):
        if key == "***":
            if index < len(existing_keys):
                resolved.append(existing_keys[index])
        else:
            resolved.append(key)
    return "\n".join(resolved)

def get_api_key_candidates(pool_name: str, primary: str | None, fallback: str | None = None) -> list[tuple[int, int, str]]:
    keys = split_api_keys(primary)
    if not keys:
        keys = split_api_keys(fallback)
    if not keys:
        return []

    state = API_KEY_POOL_STATE.setdefault(pool_name, {"cursor": 0, "disabled": set()})
    enabled = [(idx, key) for idx, key in enumerate(keys) if key not in state["disabled"]]
    candidates = enabled or list(enumerate(keys))
    start = state["cursor"] % len(candidates)
    state["cursor"] += 1
    ordered = candidates[start:] + candidates[:start]
    return [(idx + 1, len(keys), key) for idx, key in ordered]

def mark_api_key_unhealthy(pool_name: str, key: str, error_message: str) -> None:
    error_lower = error_message.lower()
    if (
        "permissiondenied" in error_lower
        or "permission denied" in error_lower
        or "insufficient" in error_lower
        or "balance" in error_lower
        or "quota" in error_lower
        or "401" in error_message
        or "403" in error_message
    ):
        API_KEY_POOL_STATE.setdefault(pool_name, {"cursor": 0, "disabled": set()})["disabled"].add(key)

def reset_api_key_pool_health(pool_name: str | None = None) -> None:
    pools = [pool_name] if pool_name else list(API_KEY_POOL_STATE.keys())
    for pool in pools:
        API_KEY_POOL_STATE.setdefault(pool, {"cursor": 0, "disabled": set()})["disabled"].clear()

def summarize_key_pool(pool_name: str, primary: str | None, fallback: str | None = None) -> dict:
    keys = split_api_keys(primary) or split_api_keys(fallback)
    disabled = API_KEY_POOL_STATE.setdefault(pool_name, {"cursor": 0, "disabled": set()})["disabled"]
    return {
        "pool": pool_name,
        "total_keys": len(keys),
        "disabled_keys": sum(1 for key in keys if key in disabled),
        "enabled_keys": sum(1 for key in keys if key not in disabled),
    }

def _coerce_positive_int(value: Any, default: int, minimum: int = 1) -> int:
    try:
        parsed = int(value)
        return parsed if parsed >= minimum else default
    except Exception:
        return default

def _fingerprint_key(key: str | None) -> str:
    if not key:
        return "nokey"
    return hashlib.sha256(key.encode("utf-8", errors="ignore")).hexdigest()[:12]

def _provider_id(provider: dict) -> str:
    return "|".join(
        [
            safe_str(provider.get("name", "")),
            safe_str(provider.get("baseUrl", "")),
            safe_str(provider.get("modelName", "")),
        ]
    )

def _llm_key_id(provider: dict, key_index: int, key: str | None) -> str:
    return f"{_provider_id(provider)}|{key_index}|{_fingerprint_key(key)}"

def normalize_llm_providers(settings: dict) -> list[dict]:
    """Build enabled OpenAI-compatible LLM provider configs with legacy fallback."""
    per_key_default = _coerce_positive_int(settings.get("llmPerKeyMaxAsync", 1), 1)
    global_default = _coerce_positive_int(
        settings.get("llmGlobalMaxAsync", settings.get("llmModelMaxAsync", 4)),
        4,
    )

    raw_providers = settings.get("llmProviders")
    providers: list[dict] = []
    if isinstance(raw_providers, list):
        for idx, raw in enumerate(raw_providers):
            if not isinstance(raw, dict):
                continue
            api_keys = raw.get("apiKeys", [])
            if isinstance(api_keys, str):
                api_keys = split_api_keys(api_keys)
            elif isinstance(api_keys, list):
                api_keys = [safe_str(key).strip() for key in api_keys if safe_str(key).strip()]
            else:
                api_keys = []

            provider = {
                "name": raw.get("name") or f"llm-provider-{idx + 1}",
                "baseUrl": raw.get("baseUrl") or settings.get("baseUrl"),
                "modelName": raw.get("modelName") or settings.get("modelName", "gpt-5-mini"),
                "apiKeys": api_keys,
                "enabled": raw.get("enabled", True) is not False,
                "maxAsync": _coerce_positive_int(raw.get("maxAsync"), max(1, len(api_keys) * per_key_default)),
                "perKeyMaxAsync": _coerce_positive_int(raw.get("perKeyMaxAsync", per_key_default), per_key_default),
                "priority": _coerce_positive_int(raw.get("priority", 100), 100, minimum=0),
                "index": idx,
            }
            if provider["enabled"] and provider["baseUrl"] and provider["modelName"]:
                providers.append(provider)

    if not providers:
        legacy_keys = split_api_keys(settings.get("apiKey"))
        providers.append(
            {
                "name": "legacy-llm",
                "baseUrl": settings.get("baseUrl"),
                "modelName": settings.get("modelName", "gpt-5-mini"),
                "apiKeys": legacy_keys,
                "enabled": True,
                "maxAsync": max(1, min(global_default, max(1, len(legacy_keys) * per_key_default))),
                "perKeyMaxAsync": per_key_default,
                "priority": 100,
                "index": 0,
            }
        )

    return providers

def _pool_record(bucket: str, item_id: str, limit: int) -> dict:
    records = LLM_PROVIDER_POOL_STATE.setdefault(bucket, {})
    record = records.get(item_id)
    if record is None or record.get("limit") != limit:
        # Recreate only the limiter metadata; health state lives in the key record.
        record = {
            "limit": limit,
            "semaphore": asyncio.Semaphore(max(1, limit)),
            "active": 0,
        }
        records[item_id] = record
    return record

def _key_health_record(candidate: dict) -> dict:
    records = LLM_PROVIDER_POOL_STATE.setdefault("keys", {})
    item_id = candidate["key_id"]
    return records.setdefault(
        item_id,
        {
            "disabled": False,
            "cooldown_until": 0.0,
            "last_error": "",
            "success_count": 0,
            "failure_count": 0,
            "timeout_count": 0,
            "avg_latency": 0.0,
        },
    )

def classify_llm_pool_error(error_message: str) -> str:
    error_lower = error_message.lower()
    if (
        "permissiondenied" in error_lower
        or "permission denied" in error_lower
        or "insufficient" in error_lower
        or "balance" in error_lower
        or "quota" in error_lower
        or "unauthorized" in error_lower
        or "authentication" in error_lower
        or "401" in error_message
        or "403" in error_message
    ):
        return "disable"
    if "429" in error_message or "rate" in error_lower or "limit" in error_lower:
        return "cooldown"
    if (
        "connection" in error_lower
        or "network" in error_lower
        or "500" in error_message
        or "502" in error_message
        or "503" in error_message
        or "504" in error_message
    ):
        return "cooldown"
    return "fail"

def summarize_llm_provider_pool(settings: dict) -> dict:
    providers = normalize_llm_providers(settings)
    total_keys = 0
    enabled_keys = 0
    disabled_keys = 0
    cooldown_keys = 0
    now = time.monotonic()
    details = []
    for provider in providers:
        keys = provider.get("apiKeys") or [None]
        provider_total = len(keys)
        provider_enabled = 0
        provider_disabled = 0
        provider_cooldown = 0
        for key_index, key in enumerate(keys, start=1):
            candidate = {
                "provider": provider,
                "key_index": key_index,
                "key_id": _llm_key_id(provider, key_index, key),
            }
            health = _key_health_record(candidate)
            total_keys += 1
            if health.get("disabled"):
                disabled_keys += 1
                provider_disabled += 1
            elif health.get("cooldown_until", 0.0) > now:
                cooldown_keys += 1
                provider_cooldown += 1
            else:
                enabled_keys += 1
                provider_enabled += 1
        details.append(
            {
                "name": provider.get("name"),
                "model": provider.get("modelName"),
                "base_url": provider.get("baseUrl"),
                "total_keys": provider_total,
                "enabled_keys": provider_enabled,
                "disabled_keys": provider_disabled,
                "cooldown_keys": provider_cooldown,
                "max_async": provider.get("maxAsync"),
                "per_key_max_async": provider.get("perKeyMaxAsync"),
                "priority": provider.get("priority"),
            }
        )
    return {
        "pool": "llm_providers",
        "providers": len(providers),
        "total_keys": total_keys,
        "enabled_keys": enabled_keys,
        "disabled_keys": disabled_keys,
        "cooldown_keys": cooldown_keys,
        "details": details,
    }

def get_llm_provider_candidates(settings: dict) -> list[dict]:
    providers = sorted(normalize_llm_providers(settings), key=lambda item: (item.get("priority", 100), item.get("index", 0)))
    now = time.monotonic()
    candidates: list[dict] = []
    for provider_pos, provider in enumerate(providers, start=1):
        keys = provider.get("apiKeys") or [None]
        key_total = len(keys)
        for key_index, key in enumerate(keys, start=1):
            candidate = {
                "provider": provider,
                "provider_index": provider_pos,
                "provider_total": len(providers),
                "key": key,
                "key_index": key_index,
                "key_total": key_total,
                "provider_id": _provider_id(provider),
                "key_id": _llm_key_id(provider, key_index, key),
            }
            health = _key_health_record(candidate)
            if health.get("disabled"):
                continue
            if health.get("cooldown_until", 0.0) > now:
                continue
            candidates.append(candidate)

    if not candidates:
        return []
    start = LLM_PROVIDER_POOL_STATE.get("cursor", 0) % len(candidates)
    LLM_PROVIDER_POOL_STATE["cursor"] = LLM_PROVIDER_POOL_STATE.get("cursor", 0) + 1
    return candidates[start:] + candidates[:start]

async def acquire_llm_provider_slot(candidate: dict):
    provider = candidate["provider"]
    provider_record = _pool_record("providers", candidate["provider_id"], provider.get("maxAsync", 1))
    key_record = _pool_record("key_slots", candidate["key_id"], provider.get("perKeyMaxAsync", 1))
    await provider_record["semaphore"].acquire()
    provider_record["active"] += 1
    try:
        await key_record["semaphore"].acquire()
        key_record["active"] += 1
    except Exception:
        provider_record["active"] -= 1
        provider_record["semaphore"].release()
        raise

    def release():
        try:
            key_record["active"] = max(0, key_record["active"] - 1)
            key_record["semaphore"].release()
        finally:
            provider_record["active"] = max(0, provider_record["active"] - 1)
            provider_record["semaphore"].release()

    return release, provider_record, key_record

def record_llm_provider_result(candidate: dict, status: str, duration: float | None = None, error_message: str | None = None, cooldown_seconds: int = 60) -> str:
    health = _key_health_record(candidate)
    action = "none"
    if status == "success":
        health["success_count"] += 1
        if duration is not None:
            previous = float(health.get("avg_latency", 0.0) or 0.0)
            health["avg_latency"] = duration if previous <= 0 else previous * 0.8 + duration * 0.2
        health["last_error"] = ""
        action = "healthy"
    elif status == "timeout":
        health["timeout_count"] += 1
        health["last_error"] = error_message or "timeout"
        action = "record_timeout"
    else:
        health["failure_count"] += 1
        health["last_error"] = error_message or status
        action = classify_llm_pool_error(error_message or "")
        if action == "disable":
            health["disabled"] = True
        elif action == "cooldown":
            health["cooldown_until"] = time.monotonic() + max(1, cooldown_seconds)
    return action

def reset_llm_provider_pool_health() -> None:
    for record in LLM_PROVIDER_POOL_STATE.setdefault("keys", {}).values():
        record["disabled"] = False
        record["cooldown_until"] = 0.0
        record["last_error"] = ""

enable_api_docs = os.getenv("HYPERCHE_ENABLE_API_DOCS", "false").lower() in {"1", "true", "yes"}
app = FastAPI(
    docs_url="/docs" if enable_api_docs else None,
    redoc_url="/redoc" if enable_api_docs else None,
    openapi_url="/openapi.json" if enable_api_docs else None,
)

def _cors_origins() -> list[str]:
    configured = os.getenv("CORS_ORIGINS", "")
    if configured:
        return [origin.strip() for origin in configured.split(",") if origin.strip()]
    return [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5000",
        "http://127.0.0.1:5000",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def log_http_requests(request: Request, call_next):
    start = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        duration_ms = (time.perf_counter() - start) * 1000
        path = request.url.path
        if path.startswith(("/files", "/auth", "/quota", "/settings", "/hyperrag")):
            log_line = (
                f"HTTP {request.method} {path} status={status_code} "
                f"duration_ms={duration_ms:.1f}"
            )
            if status_code >= 400:
                main_logger.warning(log_line)
            else:
                main_logger.info(log_line)

@app.get("/")
async def root():
    return {"message": "HyperChE"}


class AuthRegisterRequest(BaseModel):
    email: str
    password: str
    display_name: str = ""


class AuthLoginRequest(BaseModel):
    email: str
    password: str


class QuotaConfigRequest(BaseModel):
    trial_docs_limit: int = 3
    trial_llm_calls_limit: int = 50
    trial_embedding_calls_limit: int = 200


class UserApiKeyRequest(BaseModel):
    provider_type: str
    base_url: str
    model_name: str
    api_key: str
    enabled: bool = True


def public_user(user: dict) -> dict:
    return {
        "id": user.get("id"),
        "email": user.get("email"),
        "display_name": user.get("display_name"),
        "role": user.get("role", "user"),
    }


def _set_auth_cookie(response: Response, token: str) -> None:
    secure_cookie = os.getenv("COOKIE_SECURE", "false").lower() == "true"
    response.set_cookie(
        AUTH_COOKIE_NAME,
        token,
        httponly=True,
        secure=secure_cookie,
        samesite="lax",
        max_age=14 * 24 * 3600,
        path="/",
    )


def _extract_auth_token(request: Request) -> str | None:
    cookie_token = request.cookies.get(AUTH_COOKIE_NAME)
    if cookie_token:
        return cookie_token
    auth_header = request.headers.get("Authorization", "")
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    return None


async def get_current_user(request: Request) -> dict | None:
    user = auth_store.user_from_token(_extract_auth_token(request))
    if user:
        CURRENT_USER_ID.set(user["id"])
    else:
        CURRENT_USER_ID.set(None)
    return user


async def require_current_user(request: Request) -> dict:
    user = await get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录 HyperChE")
    return user


async def require_admin_user(user: dict = Depends(require_current_user)) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


def _user_db_prefix(user: dict) -> str:
    user_id = (user or {}).get("id") or "anonymous"
    return f"u_{user_id[:12]}__"


def namespace_database_name(database_name: str | None, user: dict) -> str:
    clean_name = file_manager.sanitize_database_name(database_name or "default")
    prefix = _user_db_prefix(user)
    if clean_name.startswith(prefix):
        return clean_name
    return f"{prefix}{clean_name}"


def user_can_access_database(user: dict, database_name: str | None, include_legacy: bool = True) -> bool:
    if not database_name:
        return True
    if user.get("role") == "admin":
        return True
    if database_name.startswith(_user_db_prefix(user)):
        return True

    user_id = user.get("id")
    for kb in getattr(kb_manager, "_load_metadata", lambda: {})().values():
        if kb.get("database_name") == database_name:
            owner = kb.get("owner_user_id")
            return owner == user_id or (include_legacy and not owner)
    for file_info in file_manager.get_all_files(owner_user_id=user_id, include_legacy=include_legacy):
        if file_info.get("database_name") == database_name:
            return True
    return include_legacy and not database_name.startswith("u_")


def require_database_access(database_name: str | None, user: dict) -> str | None:
    if not database_name:
        return None
    clean_name = file_manager.sanitize_database_name(database_name)
    if not user_can_access_database(user, clean_name):
        raise HTTPException(status_code=403, detail="鏃犳潈璁块棶璇ョ煡璇嗗簱")
    return clean_name


def database_display_name(database_name: str, user: dict) -> str:
    prefix = _user_db_prefix(user)
    if database_name and database_name.startswith(prefix):
        return database_name[len(prefix):]
    return database_name


def has_personal_provider(user_id: str | None, provider_type: str) -> bool:
    return bool(auth_store.get_enabled_providers(user_id, provider_type))


def get_user_llm_provider_candidates(user_id: str | None, settings: dict) -> list[dict]:
    user_providers = auth_store.get_enabled_providers(user_id, "llm")
    if not user_providers:
        return []

    per_key_default = _coerce_positive_int(settings.get("llmPerKeyMaxAsync", 1), 1)
    providers = []
    for idx, user_provider in enumerate(user_providers):
        api_keys = user_provider.get("apiKeys") or split_api_keys(user_provider.get("apiKey"))
        if not api_keys:
            continue
        providers.append(
            {
                "name": f"user-llm-{idx + 1}",
                "baseUrl": user_provider["baseUrl"],
                "modelName": user_provider["modelName"],
                "apiKeys": api_keys,
                "enabled": True,
                "maxAsync": max(1, len(api_keys) * per_key_default),
                "perKeyMaxAsync": per_key_default,
                "priority": idx,
                "index": idx,
            }
        )
    if not providers:
        return []

    user_settings = dict(settings)
    user_settings["llmProviders"] = providers
    return get_llm_provider_candidates(user_settings)


def summarize_user_provider_pool(user_id: str | None, provider_type: str) -> dict:
    providers = auth_store.get_enabled_providers(user_id, provider_type)
    return {
        "pool": f"user_{provider_type}",
        "providers": len(providers),
        "total_keys": sum(len(provider.get("apiKeys") or []) for provider in providers),
    }


def get_user_embedding_candidates(user_id: str | None, settings: dict) -> list[dict]:
    user_providers = auth_store.get_enabled_providers(user_id, "embedding")
    candidates = []
    for provider_index, provider in enumerate(user_providers, start=1):
        key_candidates = get_api_key_candidates(
            f"embedding:user:{provider.get('id', provider_index)}",
            "\n".join(provider.get("apiKeys") or []),
        )
        for key_index, key_total, candidate_key in key_candidates:
            candidates.append(
                {
                    "provider_index": provider_index,
                    "provider_total": len(user_providers),
                    "key_index": key_index,
                    "key_total": key_total,
                    "key": candidate_key,
                    "model": provider["modelName"],
                    "base_url": provider["baseUrl"],
                }
            )
    return candidates


def consume_platform_quota(user_id: str | None, provider_type: str, amount: int = 1) -> None:
    if not user_id:
        return
    if has_personal_provider(user_id, provider_type):
        return
    quota_type = "llm" if provider_type == "llm" else "embedding"
    try:
        auth_store.consume_quota(user_id, quota_type, amount)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=safe_str(e))


def consume_document_quota_if_needed(user: dict, file_count: int) -> None:
    user_id = user.get("id")
    if user_id and not has_personal_provider(user_id, "embedding"):
        try:
            auth_store.consume_quota(user_id, "docs", file_count)
        except PermissionError as e:
            raise HTTPException(status_code=403, detail=safe_str(e))


@app.post("/auth/register")
async def auth_register(payload: AuthRegisterRequest, response: Response):
    try:
        user = auth_store.create_user(payload.email, payload.password, payload.display_name)
        token = create_token(user["id"], user.get("role", "user"))
        _set_auth_cookie(response, token)
        CURRENT_USER_ID.set(user["id"])
        return {"success": True, "user": public_user(user), "quota": auth_store.get_quota(user["id"])}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=safe_str(e))


@app.post("/auth/login")
async def auth_login(payload: AuthLoginRequest, response: Response):
    user = auth_store.authenticate(payload.email, payload.password)
    if not user:
        raise HTTPException(status_code=401, detail="邮箱或密码错误")
    token = create_token(user["id"], user.get("role", "user"))
    _set_auth_cookie(response, token)
    CURRENT_USER_ID.set(user["id"])
    return {"success": True, "user": public_user(user), "quota": auth_store.get_quota(user["id"])}


@app.post("/auth/logout")
async def auth_logout(response: Response):
    secure_cookie = os.getenv("COOKIE_SECURE", "false").lower() == "true"
    response.delete_cookie(AUTH_COOKIE_NAME, path="/", secure=secure_cookie, httponly=True, samesite="lax")
    CURRENT_USER_ID.set(None)
    return {"success": True}


@app.get("/auth/me")
async def auth_me(user: dict = Depends(require_current_user)):
    return {"success": True, "user": public_user(user), "quota": auth_store.get_quota(user["id"])}


@app.get("/quota/me")
async def quota_me(user: dict = Depends(require_current_user)):
    return {"success": True, "quota": auth_store.get_quota(user["id"])}


@app.get("/admin/quota-config")
async def get_admin_quota_config(user: dict = Depends(require_admin_user)):
    return {"success": True, "quota_config": auth_store.get_quota_limits()}


@app.post("/admin/quota-config")
async def save_admin_quota_config(payload: QuotaConfigRequest, user: dict = Depends(require_admin_user)):
    limits = auth_store.set_quota_limits(
        payload.trial_docs_limit,
        payload.trial_llm_calls_limit,
        payload.trial_embedding_calls_limit,
    )
    return {"success": True, "quota_config": limits}


@app.get("/user-api-keys")
async def list_user_api_keys(user: dict = Depends(require_current_user)):
    return {"success": True, "keys": auth_store.list_api_keys(user["id"])}


@app.post("/user-api-keys")
async def create_user_api_key(payload: UserApiKeyRequest, user: dict = Depends(require_current_user)):
    try:
        key = auth_store.add_api_key(
            user["id"],
            payload.provider_type,
            payload.base_url,
            payload.model_name,
            payload.api_key,
            payload.enabled,
        )
        return {"success": True, "key": key}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=safe_str(e))


@app.delete("/user-api-keys/{key_id}")
async def delete_user_api_key(key_id: str, user: dict = Depends(require_current_user)):
    deleted = auth_store.delete_api_key(user["id"], key_id)
    return {"success": deleted}


# ============ Knowledge Base Management ============

kb_manager = KnowledgeBaseManager()

class KBCreateRequest(BaseModel):
    name: str
    description: str = ""
    rag_system: str = "hyperrag"
    domain: str = "default"
    chunk_size: int = 1000
    chunk_overlap: int = 200

class KBUpdateRequest(BaseModel):
    description: Optional[str] = None
    rag_system: Optional[str] = None
    domain: Optional[str] = None
    chunk_size: Optional[int] = None
    chunk_overlap: Optional[int] = None
    name: Optional[str] = None

@app.post("/kb")
async def create_kb(req: KBCreateRequest, user: dict = Depends(require_current_user)):
    """创建知识库"""
    try:
        kb = await kb_manager.create_kb(
            name=req.name,
            description=req.description,
            rag_system=req.rag_system,
            domain=req.domain,
            chunk_size=req.chunk_size,
            chunk_overlap=req.chunk_overlap,
            database_name=namespace_database_name(req.name, user),
            owner_user_id=user.get("id"),
        )
        return {"success": True, "data": kb}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=safe_str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=safe_str(e))

@app.get("/kb")
async def list_kbs(user: dict = Depends(require_current_user)):
    """列出所有知识库（含统计）"""
    try:
        kbs = await kb_manager.list_kbs(owner_user_id=user.get("id"), include_legacy=True)
        result = []
        for kb in kbs:
            stats = await kb_manager.get_kb_stats(kb["database_name"], file_manager, owner_user_id=user.get("id"), include_legacy=True)
            result.append({**kb, "display_database_name": database_display_name(kb["database_name"], user), "stats": stats})
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=safe_str(e))

@app.get("/kb/{kb_name}")
async def get_kb(kb_name: str, user: dict = Depends(require_current_user)):
    """获取知识库详情"""
    try:
        kb = await kb_manager.get_kb(kb_name, owner_user_id=user.get("id"), include_legacy=True)
        if not kb:
            raise HTTPException(status_code=404, detail="知识库不存在")
        stats = await kb_manager.get_kb_stats(kb["database_name"], file_manager, owner_user_id=user.get("id"), include_legacy=True)
        return {**kb, "display_database_name": database_display_name(kb["database_name"], user), "stats": stats}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=safe_str(e))

@app.put("/kb/{kb_name}")
async def update_kb(kb_name: str, req: KBUpdateRequest, user: dict = Depends(require_current_user)):
    """更新知识库设置"""
    try:
        updates = {k: v for k, v in req.dict().items() if v is not None}
        kb = await kb_manager.update_kb(kb_name, owner_user_id=user.get("id"), include_legacy=True, **updates)
        if not kb:
            raise HTTPException(status_code=404, detail="知识库不存在")
        return {"success": True, "data": kb}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=safe_str(e))

@app.delete("/kb/{kb_name}")
async def delete_kb(kb_name: str, user: dict = Depends(require_current_user)):
    """删除知识库及其文件和数据库"""
    try:
        kb = await kb_manager.get_kb(kb_name, owner_user_id=user.get("id"), include_legacy=True)
        if not kb:
            raise HTTPException(status_code=404, detail="知识库不存在")

        database_name = kb["database_name"]

        # 删除关联文件
        all_files = file_manager.get_all_files(owner_user_id=user.get("id"), include_legacy=True)
        kb_files = [f for f in all_files if f.get("kb_name") == database_name]
        for f in kb_files:
            try:
                file_manager.delete_file(f["file_id"])
            except Exception:
                pass

        # 删除数据库
        try:
            db_manager.delete_database(database_name)
        except Exception:
            pass

        # 删除KB元数据
        await kb_manager.delete_kb(kb_name, owner_user_id=user.get("id"), include_legacy=True)

        return {"success": True, "message": f"知识库 '{kb_name}' 已删除"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=safe_str(e))


@app.get("/db")
async def db(database: str = None, user: dict = Depends(require_current_user)):
    """
    获取全部数据json
    """
    try:
        database = require_database_access(database, user)
        data = get_hypergraph(database)
        return data
    except Exception as e:
        return {"error": safe_str(e)}

@app.get("/db/vertices")
async def get_vertices_function(database: str = None, page: int = None, page_size: int = None, user: dict = Depends(require_current_user)):
    """
    获取vertices列表
    """
    try:
        database = require_database_access(database, user)
        data = getFrequentVertices(database, page, page_size)
        return data
    except Exception as e:
        return {"error": safe_str(e)}

@app.get("/db/hyperedges")
async def get_hypergraph_function(database: str = None, page: int = None, page_size: int = None, user: dict = Depends(require_current_user)):
    """
    获取hyperedges列表
    """
    try:
        database = require_database_access(database, user)
        data = get_hyperedges(database, page, page_size)
        return data
    except Exception as e:
        return {"error": safe_str(e)}

@app.get("/db/hyperedges/{hyperedge_id}")
async def get_hyperedge(hyperedge_id: str, database: str = None, user: dict = Depends(require_current_user)):
    """
    获取指定hyperedge的详情
    """
    try:
        hyperedge_id = hyperedge_id.replace("%20", " ")
        vertices = hyperedge_id.split("|*|")
        database = require_database_access(database, user)
        data = get_hyperedge_detail(vertices, database)
        return data
    except Exception as e:
        return {"error": safe_str(e)}

@app.get("/db/vertices/{vertex_id}")
async def get_vertex(vertex_id: str, database: str = None, user: dict = Depends(require_current_user)):
    """
    获取指定vertex的json
    """
    vertex_id = vertex_id.replace("%20", " ")
    try:
        database = require_database_access(database, user)
        data = get_vertice(vertex_id, database)
        return data
    except Exception as e:
        return {"error": safe_str(e)}

@app.get("/db/vertices_neighbor/{vertex_id}")
async def get_vertex_neighbor(vertex_id: str, database: str = None, user: dict = Depends(require_current_user)):
    """
    获取指定vertex的neighbor
    """
    vertex_id = vertex_id.replace("%20", " ")
    try:
        database = require_database_access(database, user)
        data = get_vertice_neighbor(vertex_id, database)
        return data
    except Exception as e:
        return {"error": safe_str(e)}

@app.get("/db/hyperedge_neighbor/{hyperedge_id}")
async def get_hyperedge_neighbor(hyperedge_id: str, database: str = None, user: dict = Depends(require_current_user)):
    """
    获取指定hyperedge的neighbor
    """
    hyperedge_id = hyperedge_id.replace("%20", " ")
    hyperedge_id = hyperedge_id.replace("*", "#")
    print(hyperedge_id)
    try:
        database = require_database_access(database, user)
        data = get_hyperedge_neighbor_server(hyperedge_id, database)
        return data
    except Exception as e:
        return {"error": safe_str(e)}

class VertexModel(BaseModel):
    vertex_id: str
    entity_name: str = ""
    entity_type: str = ""
    description: str = ""
    additional_properties: str = ""
    database: str = None

class HyperedgeModel(BaseModel):
    vertices: list
    keywords: str = ""
    summary: str = ""
    database: str = None

class VertexUpdateModel(BaseModel):
    entity_name: str = ""
    entity_type: str = ""
    description: str = ""
    additional_properties: str = ""
    database: str = None

class HyperedgeUpdateModel(BaseModel):
    keywords: str = ""
    summary: str = ""
    database: str = None

@app.post("/db/vertices")
async def create_vertex(vertex: VertexModel, user: dict = Depends(require_current_user)):
    """
    创建新的vertex
    """
    try:
        vertex.database = require_database_access(vertex.database, user)
        result = add_vertex(vertex.vertex_id, {
            "entity_name": vertex.entity_name,
            "entity_type": vertex.entity_type,
            "description": vertex.description,
            "additional_properties": vertex.additional_properties
        }, vertex.database)
        return {"success": True, "message": "Vertex created successfully", "data": result}
    except Exception as e:
        return {"success": False, "message": safe_str(e)}

@app.post("/db/hyperedges")
async def create_hyperedge(hyperedge: HyperedgeModel, user: dict = Depends(require_current_user)):
    """
    创建新的hyperedge
    """
    try:
        hyperedge.database = require_database_access(hyperedge.database, user)
        result = add_hyperedge(hyperedge.vertices, {
            "keywords": hyperedge.keywords,
            "summary": hyperedge.summary
        }, hyperedge.database)
        return {"success": True, "message": "Hyperedge created successfully", "data": result}
    except Exception as e:
        return {"success": False, "message": safe_str(e)}

@app.put("/db/vertices/{vertex_id}")
async def update_vertex_endpoint(vertex_id: str, vertex: VertexUpdateModel, user: dict = Depends(require_current_user)):
    """
    更新vertex信息
    """
    try:
        vertex_id = vertex_id.replace("%20", " ")
        vertex.database = require_database_access(vertex.database, user)
        result = update_vertex(vertex_id, {
            "entity_name": vertex.entity_name,
            "entity_type": vertex.entity_type,
            "description": vertex.description,
            "additional_properties": vertex.additional_properties
        }, vertex.database)
        return {"success": True, "message": "Vertex updated successfully", "data": result}
    except Exception as e:
        return {"success": False, "message": safe_str(e)}

@app.put("/db/hyperedges/{hyperedge_id}")
async def update_hyperedge_endpoint(hyperedge_id: str, hyperedge: HyperedgeUpdateModel, user: dict = Depends(require_current_user)):
    """
    更新hyperedge信息
    """
    try:
        hyperedge_id = hyperedge_id.replace("%20", " ")
        vertices = hyperedge_id.split("|*|")
        hyperedge.database = require_database_access(hyperedge.database, user)
        result = update_hyperedge(vertices, {
            "keywords": hyperedge.keywords,
            "summary": hyperedge.summary
        }, hyperedge.database)
        return {"success": True, "message": "Hyperedge updated successfully", "data": result}
    except Exception as e:
        return {"success": False, "message": safe_str(e)}

@app.delete("/db/vertices/{vertex_id}")
async def delete_vertex_endpoint(vertex_id: str, database: str = None, user: dict = Depends(require_current_user)):
    """
    删除vertex
    """
    try:
        vertex_id = vertex_id.replace("%20", " ")
        database = require_database_access(database, user)
        result = delete_vertex(vertex_id, database)
        return {"success": True, "message": "Vertex deleted successfully"}
    except Exception as e:
        return {"success": False, "message": safe_str(e)}

@app.delete("/db/hyperedges/{hyperedge_id}")
async def delete_hyperedge_endpoint(hyperedge_id: str, database: str = None, user: dict = Depends(require_current_user)):
    """
    删除hyperedge
    """
    try:
        hyperedge_id = hyperedge_id.replace("%20", " ")
        vertices = hyperedge_id.split("|*|")
        database = require_database_access(database, user)
        result = delete_hyperedge(vertices, database)
        return {"success": True, "message": "Hyperedge deleted successfully"}
    except Exception as e:
        return {"success": False, "message": safe_str(e)}

# ========== 主题超图相关API端点 ==========

@app.get("/db/theme_hypergraph")
async def get_theme_hypergraph_endpoint(database: str = None, user: dict = Depends(require_current_user)):
    """获取主题超图全部数据"""
    try:
        database = require_database_access(database, user)
        data = get_theme_hypergraph(database)
        return data
    except Exception as e:
        return {"error": safe_str(e)}

@app.get("/db/theme_vertices")
async def get_theme_vertices_endpoint(database: str = None, page: int = None, page_size: int = None, user: dict = Depends(require_current_user)):
    """获取主题超图顶点列表"""
    try:
        database = require_database_access(database, user)
        data = get_theme_vertices(database, page, page_size)
        return data
    except Exception as e:
        return {"error": safe_str(e)}

@app.get("/db/theme_hyperedges")
async def get_theme_hyperedges_endpoint(database: str = None, page: int = None, page_size: int = None, user: dict = Depends(require_current_user)):
    """获取主题超图超边列表"""
    try:
        database = require_database_access(database, user)
        data = get_theme_hyperedges(database, page, page_size)
        return data
    except Exception as e:
        return {"error": safe_str(e)}

@app.get("/db/theme_vertices_neighbor/{vertex_id}")
async def get_theme_vertex_neighbor_endpoint(vertex_id: str, database: str = None, user: dict = Depends(require_current_user)):
    """获取主题超图中顶点的邻居"""
    try:
        vertex_id = vertex_id.replace("%20", " ")
        database = require_database_access(database, user)
        data = get_theme_vertex_neighbor(vertex_id, database)
        return data
    except Exception as e:
        return {"error": safe_str(e)}

# 设置相关的API接口

class LLMProviderModel(BaseModel):
    name: str = ""
    baseUrl: str = ""
    modelName: str = ""
    apiKeys: List[str] = Field(default_factory=list)
    enabled: bool = True
    maxAsync: int = 1
    perKeyMaxAsync: Optional[int] = None
    priority: int = 100

class SettingsModel(BaseModel):
    apiKey: str = ""
    modelProvider: str = "openai"
    modelName: str = "gpt-5-mini"
    baseUrl: str = "https://api.openai.com/v1"
    selectedDatabase: str = ""
    maxTokens: int = 2000
    temperature: float = 0.7
    llmTimeout: float = 600
    llmModelMaxAsync: int = 16
    llmGlobalMaxAsync: int = 16
    llmPerKeyMaxAsync: int = 4
    llmMaxRetries: int = 1
    llmProviderStrategy: str = "priority_round_robin"
    llmProviders: List[LLMProviderModel] = Field(default_factory=list)
    # HyperRAG 嵌入模型设置
    embeddingModel: str = "text-embedding-3-small"
    embeddingDim: int = 1536
    embeddingBaseUrl: str = ""  # 嵌入模型的API地址
    embeddingApiKey: str = ""  # 嵌入模型的API密钥
    # Cog-RAG相关设置
    enableCogRAG: bool = True  # 启用/禁用Cog-RAG功能
    # Hyper-RAG 领域配置
    hyperrag_domain: str = "default"  # "default", "flow_battery", or custom domains

class APITestModel(BaseModel):
    apiKey: str
    baseUrl: str
    modelName: str
    modelProvider: str

class DatabaseTestModel(BaseModel):
    database: str

@app.get("/settings")
async def get_settings(user: dict = Depends(require_current_user)):
    """
    获取系统设置
    """
    try:
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                    if not content:
                        main_logger.error(f"设置文件为空: {SETTINGS_FILE}")
                        return {
                            "success": False,
                            "message": "设置文件为空，请重新配置"
                        }
                    settings = json.loads(content)
            except json.JSONDecodeError as e:
                main_logger.error(f"设置文件JSON解析错误: {SETTINGS_FILE}, 错误: {e}")
                return {
                    "success": False,
                    "message": f"设置文件格式错误: {str(e)}"
                }
            # 不返回敏感信息如API Key
            settings_safe = settings.copy()
            if 'apiKey' in settings_safe:
                settings_safe['apiKey'] = '***' if settings_safe['apiKey'] else ''
            if 'embeddingApiKey' in settings_safe:
                settings_safe['embeddingApiKey'] = mask_api_keys_for_settings(settings_safe.get('embeddingApiKey'))
            if isinstance(settings_safe.get('llmProviders'), list):
                safe_providers = []
                for provider in settings_safe.get('llmProviders', []):
                    if not isinstance(provider, dict):
                        continue
                    safe_provider = provider.copy()
                    keys = safe_provider.get('apiKeys') or []
                    if isinstance(keys, str):
                        keys = split_api_keys(keys)
                    safe_provider['apiKeys'] = ['***' for key in keys if key]
                    safe_providers.append(safe_provider)
                settings_safe['llmProviders'] = safe_providers
            settings_safe["is_admin"] = user.get("role") == "admin"
            if user.get("role") != "admin":
                settings_safe["apiKey"] = ""
                settings_safe["embeddingApiKey"] = ""
                settings_safe["llmProviders"] = []
            return settings_safe
        else:
            # 返回默认设置
            return {
                "apiKey": "",
                "modelProvider": "openai",
                "modelName": "gpt-4o-mini",
                "baseUrl": "https://api.openai.com/v1",
                "selectedDatabase": "",
                "maxTokens": 2000,
                "temperature": 0.7,
                "llmTimeout": 600,
                "llmModelMaxAsync": 16,
                "llmGlobalMaxAsync": 16,
                "llmPerKeyMaxAsync": 4,
                "llmMaxRetries": 1,
                "llmProviderStrategy": "priority_round_robin",
                "llmProviders": [],
                "embeddingModel": "text-embedding-3-small",
                "embeddingDim": 1536,
                "embeddingBaseUrl": "",
                "embeddingApiKey": ""
            }
    except Exception as e:
        return {"success": False, "message": safe_str(e)}

@app.post("/settings")
async def save_settings(settings: SettingsModel, user: dict = Depends(require_admin_user)):
    """
    保存系统设置
    """
    try:
        settings_dict = settings.dict()
        existing_settings = {}
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                    existing_settings = json.load(f)
            except Exception:
                existing_settings = {}

        # 添加调试日志
        main_logger.info(
            f"🔍 [Settings] 接收到的设置: "
            f"{json.dumps(redact_for_log(settings_dict), ensure_ascii=False, indent=2)}"
        )

        # 如果apiKey是***，则保持原有的apiKey不变
        if settings_dict.get('apiKey') == '***':
            # 读取现有设置中的apiKey
            if os.path.exists(SETTINGS_FILE):
                with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                    existing_settings = json.load(f)
                # 保持原有的apiKey
                settings_dict['apiKey'] = existing_settings.get('apiKey', '')
            else:
                # 如果没有现有设置文件，则设为空字符串
                settings_dict['apiKey'] = ''

        # embeddingApiKey supports multiple keys separated by newline/comma/semicolon.
        # Preserve masked rows returned by GET /settings while allowing users to add/remove keys.
        settings_dict['embeddingApiKey'] = resolve_masked_api_key_text(
            settings_dict.get('embeddingApiKey'),
            existing_settings.get('embeddingApiKey', ''),
        )

        # 确保embedding相关字段被保存
        if 'embeddingBaseUrl' not in settings_dict:
            settings_dict['embeddingBaseUrl'] = ''

        existing_providers = existing_settings.get('llmProviders') or []
        if isinstance(settings_dict.get('llmProviders'), list):
            resolved_providers = []
            for provider_index, provider in enumerate(settings_dict.get('llmProviders', [])):
                if not isinstance(provider, dict):
                    continue
                existing_provider = None
                for old_provider in existing_providers:
                    if not isinstance(old_provider, dict):
                        continue
                    if (
                        old_provider.get('name') == provider.get('name')
                        and old_provider.get('baseUrl') == provider.get('baseUrl')
                        and old_provider.get('modelName') == provider.get('modelName')
                    ):
                        existing_provider = old_provider
                        break
                if existing_provider is None and provider_index < len(existing_providers):
                    existing_provider = existing_providers[provider_index]

                existing_keys = []
                if isinstance(existing_provider, dict):
                    existing_keys = existing_provider.get('apiKeys') or []
                    if isinstance(existing_keys, str):
                        existing_keys = split_api_keys(existing_keys)

                new_keys = provider.get('apiKeys') or []
                if isinstance(new_keys, str):
                    new_keys = split_api_keys(new_keys)
                resolved_keys = []
                for key_index, key in enumerate(new_keys):
                    key_text = safe_str(key).strip()
                    if key_text == '***':
                        if key_index < len(existing_keys):
                            resolved_keys.append(existing_keys[key_index])
                    elif key_text:
                        resolved_keys.append(key_text)
                provider['apiKeys'] = resolved_keys
                resolved_providers.append(provider)
            settings_dict['llmProviders'] = resolved_providers
            reset_llm_provider_pool_health()

        main_logger.info(
            f"💾 [Settings] 准备保存的设置: "
            f"{json.dumps(redact_for_log(settings_dict), ensure_ascii=False, indent=2)}"
        )

        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(settings_dict, f, ensure_ascii=False, indent=2)
        return {"success": True, "message": "设置保存成功"}
    except Exception as e:
        main_logger.error(f"[ERROR] [Settings] 保存设置失败: {safe_str(e)}")
        return {"success": False, "message": safe_str(e)}

@app.get("/llm-provider-pool/status")
async def get_llm_provider_pool_status(user: dict = Depends(require_admin_user)):
    try:
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            settings = json.load(f)
        return {"success": True, "data": summarize_llm_provider_pool(settings)}
    except Exception as e:
        return {"success": False, "message": safe_str(e)}

@app.post("/llm-provider-pool/reset")
async def reset_llm_provider_pool_status(user: dict = Depends(require_admin_user)):
    try:
        reset_llm_provider_pool_health()
        return {"success": True, "message": "LLM provider pool health reset"}
    except Exception as e:
        return {"success": False, "message": safe_str(e)}

@app.get("/domains")
async def get_domains():
    """获取可用领域列表"""
    try:
        from hyperrag.domains.domain_manager import domain_manager
        domains = domain_manager.get_available_domains()
        result = []
        for domain_name in domains:
            try:
                config = domain_manager.load_domain_config(domain_name)
                result.append({
                    "name": domain_name,
                    "description": config.get("domain_description", ""),
                    "output_format": config.get("output_format", "delimiter"),
                })
            except Exception:
                result.append({
                    "name": domain_name,
                    "description": "",
                    "output_format": "delimiter",
                })
        return {"domains": result}
    except Exception as e:
        main_logger.error(f"获取领域列表失败: {safe_str(e)}")
        return {"domains": [{"name": "default", "description": "通用领域", "output_format": "delimiter"}]}

@app.get("/databases")
async def get_databases(user: dict = Depends(require_current_user)):
    """
    获取可用数据库列表
    """
    try:
        databases = []

        # 使用db_manager获取数据库列表
        database_files = db_manager.list_databases()

        for db_info in database_files:
            # db_info 现在是字典格式，包含 'name', 'description', 'system' 字段
            if isinstance(db_info, dict):
                databases.append(db_info)
            else:
                # 向后兼容：如果是旧格式（字符串），则转换为字典
                databases.append({
                    "name": db_info,
                    "description": f"{db_info.replace('.hgdb', '')}超图",
                    "system": "hyperrag"  # 默认为 HyperRAG
                })

        # 如果没有找到数据库文件，返回默认列表
        databases = [
            {**db, "display_name": database_display_name(db.get("name", ""), user)}
            for db in databases
            if user_can_access_database(user, db.get("name"), include_legacy=True)
        ]

        if not databases:
            databases = []

        return databases
    except Exception as e:
        return {"success": False, "message": safe_str(e), "data": []}

@app.post("/test/embedding")
async def test_embedding(user: dict = Depends(require_current_user)):
    """
    测试嵌入API连接
    """
    try:
        main_logger.info("开始测试嵌入API连接...")

        # 从设置文件读取配置
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            settings = json.load(f)

        embedding_model = settings.get("embeddingModel", "text-embedding-3-small")
        api_key = settings.get("embeddingApiKey", settings.get("apiKey"))
        base_url = settings.get("embeddingBaseUrl", settings.get("baseUrl"))
        user_embedding_provider = auth_store.get_enabled_provider(user["id"], "embedding")
        if user_embedding_provider:
            embedding_model = user_embedding_provider["modelName"]
            api_key = user_embedding_provider["apiKey"]
            base_url = user_embedding_provider["baseUrl"]
            key_candidates = get_api_key_candidates(f"embedding:user:{user['id']}", api_key)
        else:
            key_candidates = get_api_key_candidates("embedding", api_key, settings.get("apiKey"))

        main_logger.info(
            f"测试嵌入模型: {embedding_model}, "
            f"Embedding Key池: {summarize_key_pool('embedding', api_key, settings.get('apiKey'))}"
        )

        # 使用简单的测试文本
        test_texts = ["This is a test for embedding API connectivity."]

        if not key_candidates:
            key_candidates = [(0, 0, None)]

        embeddings = None
        errors = []
        for key_index, key_total, candidate_key in key_candidates:
            try:
                if candidate_key:
                    main_logger.info(f"Embedding测试使用Key池候选: {key_index}/{key_total}")
                embeddings = await openai_embedding(
                    test_texts,
                    model=embedding_model,
                    api_key=candidate_key,
                    base_url=base_url,
                )
                break
            except Exception as e:
                detailed_error = extract_detailed_exception_message(e)
                errors.append(detailed_error)
                if candidate_key:
                    mark_api_key_unhealthy("embedding", candidate_key, detailed_error)
                main_logger.error(
                    f"Embedding测试Key候选失败: {key_index}/{key_total}, 错误: {detailed_error}"
                )
        if embeddings is None:
            raise RuntimeError("所有 Embedding API Key 均测试失败: " + " || ".join(errors))

        main_logger.info(f"嵌入测试成功，维度: {embeddings.shape}")

        return {
            "success": True,
            "message": "嵌入API连接正常",
            "details": {
                "model": embedding_model,
                "embedding_dim": embeddings.shape[1] if len(embeddings.shape) > 1 else embeddings.shape[0],
                "test_text_length": len(test_texts[0])
            }
        }
    except Exception as e:
        error_msg = log_detailed_exception(
            main_logger,
            "嵌入API测试失败",
            e,
            {
                "embedding_model": locals().get("embedding_model"),
                "embedding_base_url": locals().get("base_url"),
                "test_text_count": 1,
                "test_text_total_chars": len(test_texts[0]) if "test_texts" in locals() else None,
            },
        )

        # 提供用户友好的错误信息
        user_friendly_error = extract_user_friendly_error(error_msg)

        return {
            "success": False,
            "message": user_friendly_error,
            "detailed_error": error_msg[:500]
        }

@app.post("/test-api")
async def test_api_connection(api_test: APITestModel, user: dict = Depends(require_current_user)):
    """
    测试API连接
    """
    try:
        from openai import OpenAI
        
        # 根据不同的模型提供商进行测试
        if api_test.modelProvider == "openai":
            client = OpenAI(
                api_key=api_test.apiKey,
                base_url=api_test.baseUrl
            )
            
            # 发送一个简单的测试请求
            response = client.chat.completions.create(
                model=api_test.modelName,
                messages=[{"role": "user", "content": "Hello"}],
                max_tokens=10
            )
            
            return {"success": True, "message": "API连接测试成功"}
            
        elif api_test.modelProvider == "anthropic":
            # 对于Anthropic，可以添加相应的测试逻辑
            return {"success": True, "message": "Anthropic API连接测试成功"}
            
        else:
            # 对于其他提供商，进行通用测试
            return {"success": True, "message": "API连接测试成功"}
            
    except Exception as e:
        return {"success": False, "message": f"API连接测试失败: {safe_str(e)}"}

@app.post("/test-database")
async def test_database_connection(db_test: DatabaseTestModel):
    """
    测试数据库连接
    """
    try:
        # 使用db_manager测试数据库连接
        db = db_manager.get_database(db_test.database)
        
        # 尝试获取数据库的基本信息来验证连接
        vertices_count = len(db.all_v)
        edges_count = len(db.all_e)
        
        return {
            "success": True, 
            "message": "数据库连接测试成功",
            "info": {
                "vertices_count": vertices_count,
                "edges_count": edges_count,
                "database": db_test.database
            }
        }
        
    except Exception as e:
        return {"success": False, "message": f"数据库连接测试失败: {safe_str(e)}"}


# 全局 HyperRAG 实例 - 改为字典来支持多数据库
hyperrag_instances = {}
hyperrag_working_dir = "hyperrag_cache"

# 全局 Cog-RAG 实例 - 支持多数据库
cograg_instances = {}
cograg_working_dir = "cograg_cache"

async def get_hyperrag_llm_func(prompt, system_prompt=None, history_messages=[], **kwargs) -> str:
    """
    HyperRAG 专用的 LLM 函数，使用异步版本
    """
    try:
        main_logger.info(f"开始LLM调用，prompt长度: {len(prompt)} 字符")
        if system_prompt:
            main_logger.info(f"系统提示词长度: {len(system_prompt)} 字符")

        # 清理历史消息，移除空的assistant消息
        cleaned_history = []
        if history_messages:
            for msg in history_messages:
                # 保留非空的assistant消息
                if msg.get('role') != 'assistant' or msg.get('content', '').strip():
                    cleaned_history.append(msg)

        # 从设置文件读取配置
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            settings = json.load(f)

        model_name = settings.get("modelName", "gpt-5-mini")
        api_key = settings.get("apiKey")
        base_url = settings.get("baseUrl")

        key_candidates = get_api_key_candidates("llm", api_key)
        main_logger.info(
            f"使用模型: {model_name}, API地址: {base_url}, "
            f"LLM Key池: {summarize_key_pool('llm', api_key)}"
        )
        main_logger.info(f"历史消息数量: {len(cleaned_history)} (原始: {len(history_messages)})")

        # 设置超时参数（默认600秒，适应Moonshot慢速响应）
        timeout = float(settings.get("llmTimeout", kwargs.get('timeout', 600.0)))
        deadline = time.monotonic() + timeout
        main_logger.info(f"超时设置: {timeout} 秒")

        errors = []
        if not key_candidates:
            key_candidates = [(0, 0, None)]

        for attempt_pos, (key_index, key_total, candidate_key) in enumerate(key_candidates, start=1):
            try:
                if candidate_key:
                    main_logger.info(f"LLM调用使用Key池候选: {key_index}/{key_total}")
                remaining_timeout = deadline - time.monotonic()
                if remaining_timeout <= 0:
                    raise asyncio.TimeoutError(f"LLM total timeout exceeded after {timeout:.1f}s")
                attempt_timeout = max(1.0, min(timeout, remaining_timeout))
                response = await asyncio.wait_for(
                    openai_complete_if_cache(
                        model_name,
                        prompt,
                        system_prompt=system_prompt,
                        history_messages=cleaned_history,
                        api_key=candidate_key,
                        base_url=base_url,
                        timeout=attempt_timeout,
                        **kwargs,
                    ),
                    timeout=attempt_timeout + 5.0,
                )
                main_logger.info(f"LLM调用完成，响应长度: {len(response)} 字符")
                return response
            except (asyncio.TimeoutError, asyncio.CancelledError):
                error_msg = f"LLM call cancelled/timed out after total_timeout={timeout:.1f}s, key={key_index}/{key_total}"
                errors.append(error_msg)
                main_logger.warning(error_msg)
                break
            except Exception as e:
                error_msg = extract_detailed_exception_message(e)
                errors.append(error_msg)
                if candidate_key:
                    mark_api_key_unhealthy("llm", candidate_key, error_msg)
                    main_logger.error(f"LLM Key候选失败: {key_index}/{key_total}, 错误: {error_msg}")
                if attempt_pos >= len(key_candidates):
                    raise
                main_logger.warning(f"切换到下一个 LLM API Key 继续尝试")

        if errors and all("timed out" in err.lower() or "timeout" in err.lower() for err in errors):
            raise RuntimeError("LLM total timeout exceeded: " + " || ".join(errors))
        raise RuntimeError("所有 LLM API Key 均调用失败: " + " || ".join(errors))

    except Exception as e:
        log_detailed_exception(
            main_logger,
            "LLM调用失败",
            e,
            {
                "model": locals().get("model_name"),
                "base_url": locals().get("base_url"),
                "prompt_chars": len(prompt) if prompt is not None else 0,
                "system_prompt_chars": len(system_prompt) if system_prompt else 0,
                "history_count": len(cleaned_history) if "cleaned_history" in locals() else len(history_messages),
                "timeout": locals().get("timeout"),
            },
        )
        raise

async def get_hyperrag_embedding_func(texts: list[str]) -> np.ndarray:
    """
    HyperRAG 专用的嵌入函数，带重试机制
    """
    max_retries = 3
    base_delay = 1  # 基础延迟时间（秒）

    for attempt in range(max_retries):
        try:
            main_logger.info(f"开始文本嵌入 (尝试 {attempt + 1}/{max_retries})，文本数量: {len(texts)}")
            main_logger.info(f"文本总长度: {sum(len(text) for text in texts)} 字符")

            # 从设置文件读取配置
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                settings = json.load(f)

            embedding_model = settings.get("embeddingModel", "text-embedding-3-small")
            api_key = settings.get("embeddingApiKey", settings.get("apiKey"))
            base_url = settings.get("embeddingBaseUrl", settings.get("baseUrl"))
            current_user_id = CURRENT_USER_ID.get()
            user_embedding_provider = auth_store.get_enabled_provider(current_user_id, "embedding")
            if user_embedding_provider:
                embedding_model = user_embedding_provider["modelName"]
                api_key = user_embedding_provider["apiKey"]
                base_url = user_embedding_provider["baseUrl"]
                key_candidates = get_api_key_candidates(f"embedding:user:{current_user_id}", api_key)
            else:
                consume_platform_quota(current_user_id, "embedding", 1)
                key_candidates = get_api_key_candidates("embedding", api_key, settings.get("apiKey"))

            main_logger.info(
                f"使用嵌入模型: {embedding_model}, "
                f"provider={'user' if user_embedding_provider else 'platform'}, "
                f"Embedding Key池: {summarize_key_pool('embedding', api_key, settings.get('apiKey'))}"
            )

            if not key_candidates:
                key_candidates = [(0, 0, None)]

            last_error = None
            for attempt_pos, (key_index, key_total, candidate_key) in enumerate(key_candidates, start=1):
                try:
                    if candidate_key:
                        main_logger.info(f"Embedding调用使用Key池候选: {key_index}/{key_total}")
                    embeddings = await openai_embedding(
                        texts,
                        model=embedding_model,
                        api_key=candidate_key,
                        base_url=base_url,
                    )
                    main_logger.info(f"文本嵌入完成，嵌入维度: {embeddings.shape}")
                    return embeddings
                except Exception as e:
                    last_error = e
                    error_msg = extract_detailed_exception_message(e)
                    if candidate_key:
                        mark_api_key_unhealthy("embedding", candidate_key, error_msg)
                        main_logger.error(f"Embedding Key候选失败: {key_index}/{key_total}, 错误: {error_msg}")
                    if attempt_pos >= len(key_candidates):
                        raise
                    main_logger.warning("切换到下一个 Embedding API Key 继续尝试")

            if last_error:
                raise last_error

        except Exception as e:
            text_lengths = [len(text) for text in texts]
            error_msg = log_detailed_exception(
                main_logger,
                f"文本嵌入失败 (尝试 {attempt + 1}/{max_retries})",
                e,
                {
                    "attempt": attempt + 1,
                    "max_retries": max_retries,
                    "texts_count": len(texts),
                    "texts_total_chars": sum(text_lengths),
                    "texts_min_chars": min(text_lengths) if text_lengths else 0,
                    "texts_max_chars": max(text_lengths) if text_lengths else 0,
                    "embedding_model": locals().get("embedding_model"),
                    "embedding_base_url": locals().get("base_url"),
                },
            )

            # 检查是否是可重试的错误
            is_retryable = False
            if "500" in error_msg or "502" in error_msg or "503" in error_msg or "504" in error_msg:
                is_retryable = True
                main_logger.warning(f"服务器错误，将进行重试...")
            elif "rate" in error_msg.lower() or "limit" in error_msg.lower():
                is_retryable = True
                main_logger.warning(f"速率限制错误，将进行重试...")
            elif "timeout" in error_msg.lower() or "connection" in error_msg.lower():
                is_retryable = True
                main_logger.warning(f"网络错误，将进行重试...")

            if attempt < max_retries - 1 and is_retryable:
                # 指数退避
                delay = base_delay * (2 ** attempt)
                main_logger.info(f"等待 {delay} 秒后重试...")
                await asyncio.sleep(delay)
            else:
                # 不可重试错误或已达到最大重试次数
                main_logger.error(f"文本嵌入最终失败: {error_msg}")
                raise

async def preflight_hyperrag_api_services() -> None:
    """在正式嵌入前轻量检查 LLM 与 embedding API，避免跑到 chunk 中途才失败。"""
    if not HYPERRAG_AVAILABLE:
        raise RuntimeError("HyperRAG is not available")

    with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
        settings = json.load(f)

    llm_model = settings.get("modelName", "gpt-5-mini")
    llm_api_key = settings.get("apiKey")
    llm_base_url = settings.get("baseUrl")
    embedding_model = settings.get("embeddingModel", "text-embedding-3-small")
    embedding_api_key = settings.get("embeddingApiKey", settings.get("apiKey"))
    embedding_base_url = settings.get("embeddingBaseUrl", settings.get("baseUrl"))
    llm_provider_candidates = get_llm_provider_candidates(settings)
    llm_key_candidates = get_api_key_candidates("llm", llm_api_key)
    embedding_key_candidates = get_api_key_candidates("embedding", embedding_api_key, llm_api_key)

    main_logger.info(
        "开始HyperRAG API预检: "
        f"llm_model={llm_model}, llm_base_url={llm_base_url}, "
        f"embedding_model={embedding_model}, embedding_base_url={embedding_base_url}, "
        f"llm_provider_pool={summarize_llm_provider_pool(settings)}, "
        f"embedding_key_pool={summarize_key_pool('embedding', embedding_api_key, llm_api_key)}"
    )

    if not embedding_key_candidates:
        embedding_key_candidates = [(0, 0, None)]
    embedding_errors = []
    embedding_ok = False
    for key_index, key_total, candidate_key in embedding_key_candidates:
        try:
            await openai_embedding(
                ["HyperRAG embedding preflight"],
                model=embedding_model,
                api_key=candidate_key,
                base_url=embedding_base_url,
                timeout=30.0,
            )
            embedding_ok = True
            main_logger.info(f"HyperRAG API预检: embedding 服务正常，Key候选 {key_index}/{key_total}")
            break
        except Exception as e:
            detailed_error = log_detailed_exception(
                main_logger,
                "HyperRAG API预检失败 - embedding",
                e,
                {
                    "key_index": key_index,
                    "key_total": key_total,
                    "embedding_model": embedding_model,
                    "embedding_base_url": embedding_base_url,
                    "runtime_settings": get_runtime_settings_context(),
                },
            )
            embedding_errors.append(detailed_error)
            if candidate_key:
                mark_api_key_unhealthy("embedding", candidate_key, detailed_error)
    if not embedding_ok:
        detail = " || ".join(embedding_errors)
        suggestion = extract_user_friendly_error(detail)
        raise RuntimeError(f"嵌入服务预检失败: {detail}。建议: {suggestion}")

    if not llm_key_candidates:
        llm_key_candidates = [(0, 0, None)]
    llm_errors = []
    llm_ok = False
    for key_index, key_total, candidate_key in llm_key_candidates:
        try:
            await openai_complete_if_cache(
                llm_model,
                "Reply exactly: OK",
                api_key=candidate_key,
                base_url=llm_base_url,
                timeout=30.0,
                max_tokens=8,
            )
            llm_ok = True
            main_logger.info(f"HyperRAG API预检: LLM 服务正常，Key候选 {key_index}/{key_total}")
            break
        except Exception as e:
            detailed_error = log_detailed_exception(
                main_logger,
                "HyperRAG API预检失败 - LLM",
                e,
                {
                    "key_index": key_index,
                    "key_total": key_total,
                    "model": llm_model,
                    "base_url": llm_base_url,
                    "runtime_settings": get_runtime_settings_context(),
                },
            )
            llm_errors.append(detailed_error)
            if candidate_key:
                mark_api_key_unhealthy("llm", candidate_key, detailed_error)
    if not llm_ok:
        detail = " || ".join(llm_errors)
        suggestion = extract_user_friendly_error(detail)
        raise RuntimeError(f"LLM服务预检失败: {detail}。建议: {suggestion}")

async def get_hyperrag_llm_func(prompt, system_prompt=None, history_messages=[], **kwargs) -> str:
    """HyperRAG LLM function backed by the multi-provider API key pool."""
    cleaned_history = []
    model_name = None
    base_url = None
    timeout = None
    provider_name = None
    try:
        main_logger.info(f"LLM call queued: prompt_chars={len(prompt) if prompt is not None else 0}")
        if system_prompt:
            main_logger.info(f"LLM system prompt chars: {len(system_prompt)}")

        if history_messages:
            for msg in history_messages:
                if msg.get('role') != 'assistant' or msg.get('content', '').strip():
                    cleaned_history.append(msg)

        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            settings = json.load(f)

        timeout = float(settings.get("llmTimeout", kwargs.get('timeout', 600.0)))
        max_retries = _coerce_positive_int(settings.get("llmMaxRetries", 1), 1, minimum=0)
        max_attempts = max(1, max_retries + 1)
        current_user_id = CURRENT_USER_ID.get()
        user_llm_candidates = get_user_llm_provider_candidates(current_user_id, settings)
        if user_llm_candidates:
            provider_candidates = user_llm_candidates
        else:
            consume_platform_quota(current_user_id, "llm", 1)
            provider_candidates = get_llm_provider_candidates(settings)
        main_logger.info(
            "LLM provider pool: "
            f"{json.dumps(redact_for_log(summarize_user_provider_pool(current_user_id, 'llm')), ensure_ascii=False) if user_llm_candidates else json.dumps(redact_for_log(summarize_llm_provider_pool(settings)), ensure_ascii=False)}"
        )
        main_logger.info(f"LLM history messages: {len(cleaned_history)} (raw: {len(history_messages)})")

        if not provider_candidates:
            raise RuntimeError("No healthy LLM provider/key candidates are available")

        errors = []
        for attempt_pos, candidate in enumerate(provider_candidates[:max_attempts], start=1):
            provider = candidate["provider"]
            provider_name = provider.get("name")
            model_name = provider.get("modelName")
            base_url = provider.get("baseUrl")
            candidate_key = candidate.get("key")
            release_slot = None
            started_at = time.monotonic()
            try:
                release_slot, provider_record, key_record = await acquire_llm_provider_slot(candidate)
                main_logger.info(
                    "LLM request start: "
                    f"provider={provider_name}, model={model_name}, base_url={base_url}, "
                    f"key={candidate['key_index']}/{candidate['key_total']}, "
                    f"prompt_chars={len(prompt) if prompt else 0}, timeout={timeout}, "
                    f"provider_active={provider_record['active']}/{provider_record['limit']}, "
                    f"key_active={key_record['active']}/{key_record['limit']}, "
                    f"attempt={attempt_pos}/{max_attempts}"
                )
                response = await asyncio.wait_for(
                    openai_complete_if_cache(
                        model_name,
                        prompt,
                        system_prompt=system_prompt,
                        history_messages=cleaned_history,
                        api_key=candidate_key,
                        base_url=base_url,
                        timeout=timeout,
                        **kwargs,
                    ),
                    timeout=timeout + 5.0,
                )
                duration = time.monotonic() - started_at
                record_llm_provider_result(candidate, "success", duration=duration)
                main_logger.info(
                    "LLM request done: "
                    f"provider={provider_name}, key={candidate['key_index']}/{candidate['key_total']}, "
                    f"duration={duration:.1f}s, response_chars={len(response)}, status=success"
                )
                return response
            except (asyncio.TimeoutError, asyncio.CancelledError):
                duration = time.monotonic() - started_at
                error_msg = (
                    f"LLM call cancelled/timed out after timeout={timeout:.1f}s, "
                    f"provider={provider_name}, key={candidate['key_index']}/{candidate['key_total']}"
                )
                errors.append(error_msg)
                action = record_llm_provider_result(candidate, "timeout", duration=duration, error_message=error_msg)
                main_logger.warning(
                    "LLM request failed: "
                    f"provider={provider_name}, key={candidate['key_index']}/{candidate['key_total']}, "
                    f"duration={duration:.1f}s, error_type=timeout, action={action}, fallback=next_provider"
                )
            except Exception as e:
                duration = time.monotonic() - started_at
                error_msg = extract_detailed_exception_message(e)
                errors.append(error_msg)
                action = record_llm_provider_result(
                    candidate,
                    "fail",
                    duration=duration,
                    error_message=error_msg,
                    cooldown_seconds=_coerce_positive_int(settings.get("llmKeyCooldownSeconds", 60), 60),
                )
                main_logger.error(
                    "LLM request failed: "
                    f"provider={provider_name}, key={candidate['key_index']}/{candidate['key_total']}, "
                    f"duration={duration:.1f}s, error_type={action}, action={action}, "
                    f"fallback=next_provider, error={error_msg}"
                )
                if attempt_pos >= max_attempts:
                    raise
            finally:
                if release_slot:
                    release_slot()

        if errors and all("timed out" in err.lower() or "timeout" in err.lower() for err in errors):
            raise RuntimeError("LLM total timeout exceeded: " + " || ".join(errors))
        raise RuntimeError("All LLM provider/key candidates failed: " + " || ".join(errors))

    except Exception as e:
        log_detailed_exception(
            main_logger,
            "LLM调用失败",
            e,
            {
                "provider": provider_name,
                "model": model_name,
                "base_url": base_url,
                "prompt_chars": len(prompt) if prompt is not None else 0,
                "system_prompt_chars": len(system_prompt) if system_prompt else 0,
                "history_count": len(cleaned_history) if "cleaned_history" in locals() else len(history_messages),
                "timeout": timeout,
            },
        )
        raise

async def preflight_hyperrag_api_services() -> None:
    """Preflight embedding plus the multi-provider LLM pool."""
    if not HYPERRAG_AVAILABLE:
        raise RuntimeError("HyperRAG is not available")

    with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
        settings = json.load(f)

    embedding_model = settings.get("embeddingModel", "text-embedding-3-small")
    embedding_api_key = settings.get("embeddingApiKey", settings.get("apiKey"))
    embedding_base_url = settings.get("embeddingBaseUrl", settings.get("baseUrl"))
    current_user_id = CURRENT_USER_ID.get()
    user_embedding_provider = auth_store.get_enabled_provider(current_user_id, "embedding")
    if user_embedding_provider:
        embedding_model = user_embedding_provider["modelName"]
        embedding_api_key = user_embedding_provider["apiKey"]
        embedding_base_url = user_embedding_provider["baseUrl"]
        embedding_key_candidates = get_api_key_candidates(f"embedding:user:{current_user_id}", embedding_api_key)
    else:
        embedding_key_candidates = get_api_key_candidates("embedding", embedding_api_key, settings.get("apiKey"))
    if not embedding_key_candidates:
        embedding_key_candidates = [(0, 0, None)]

    main_logger.info(
        "HyperRAG API preflight start: "
        f"embedding_model={embedding_model}, embedding_base_url={embedding_base_url}, "
        f"llm_provider_pool={summarize_llm_provider_pool(settings)}, "
        f"embedding_key_pool={summarize_key_pool('embedding', embedding_api_key, settings.get('apiKey'))}"
    )

    embedding_errors = []
    embedding_ok = False
    for key_index, key_total, candidate_key in embedding_key_candidates:
        try:
            await openai_embedding(
                ["HyperRAG embedding preflight"],
                model=embedding_model,
                api_key=candidate_key,
                base_url=embedding_base_url,
                timeout=30.0,
            )
            embedding_ok = True
            main_logger.info(f"HyperRAG API preflight: embedding OK, key={key_index}/{key_total}")
            break
        except Exception as e:
            detailed_error = log_detailed_exception(
                main_logger,
                "HyperRAG API preflight failed - embedding",
                e,
                {
                    "key_index": key_index,
                    "key_total": key_total,
                    "embedding_model": embedding_model,
                    "embedding_base_url": embedding_base_url,
                    "runtime_settings": get_runtime_settings_context(),
                },
            )
            embedding_errors.append(detailed_error)
            if candidate_key:
                mark_api_key_unhealthy("embedding", candidate_key, detailed_error)
    if not embedding_ok:
        detail = " || ".join(embedding_errors)
        suggestion = extract_user_friendly_error(detail)
        raise RuntimeError(f"Embedding service preflight failed: {detail}. Suggestion: {suggestion}")

    user_llm_candidates = get_user_llm_provider_candidates(current_user_id, settings)
    if user_llm_candidates:
        llm_candidates = user_llm_candidates
    else:
        llm_candidates = get_llm_provider_candidates(settings)
    if not llm_candidates:
        raise RuntimeError("LLM service preflight failed: no healthy provider/key candidates")
    llm_errors = []
    llm_ok = False
    for candidate in llm_candidates:
        provider = candidate["provider"]
        try:
            await openai_complete_if_cache(
                provider.get("modelName"),
                "Reply exactly: OK",
                api_key=candidate.get("key"),
                base_url=provider.get("baseUrl"),
                timeout=30.0,
                max_tokens=8,
            )
            llm_ok = True
            main_logger.info(
                "HyperRAG API preflight: LLM OK, "
                f"provider={provider.get('name')}, key={candidate['key_index']}/{candidate['key_total']}"
            )
            break
        except Exception as e:
            detailed_error = log_detailed_exception(
                main_logger,
                "HyperRAG API preflight failed - LLM",
                e,
                {
                    "provider": provider.get("name"),
                    "key_index": candidate["key_index"],
                    "key_total": candidate["key_total"],
                    "model": provider.get("modelName"),
                    "base_url": provider.get("baseUrl"),
                    "runtime_settings": get_runtime_settings_context(),
                },
            )
            llm_errors.append(detailed_error)
            record_llm_provider_result(
                candidate,
                "fail",
                error_message=detailed_error,
                cooldown_seconds=_coerce_positive_int(settings.get("llmKeyCooldownSeconds", 60), 60),
            )
    if not llm_ok:
        detail = " || ".join(llm_errors)
        suggestion = extract_user_friendly_error(detail)
        raise RuntimeError(f"LLM service preflight failed: {detail}. Suggestion: {suggestion}")

def get_or_create_hyperrag(database: str = None, chunk_size: int = None, chunk_overlap: int = None):
    """
    获取或创建指定数据库的 HyperRAG 实例
    """
    global hyperrag_instances
    
    if not HYPERRAG_AVAILABLE:
        main_logger.error("HyperRAG 不可用")
        raise RuntimeError("HyperRAG is not available")
    
    # 如果没有指定数据库，使用默认数据库
    if database is None:
        database = db_manager.default_database
        main_logger.info(f"使用默认数据库: {database}")
    
    # 检查是否已存在该数据库的实例
    requested_chunk_size = int(chunk_size) if chunk_size else None
    requested_chunk_overlap = int(chunk_overlap) if chunk_overlap is not None else None

    if database not in hyperrag_instances:
        main_logger.info(f"创建新的HyperRAG实例，数据库: {database}")
        
        # 使用数据库名作为工作目录（去掉.hgdb后缀）
        if database.endswith('.hgdb'):
            db_dir_name = database.replace('.hgdb', '')
        else:
            db_dir_name = database
            
        # HyperRAG 工作目录直接使用 hyperrag_cache 下的数据库文件夹
        db_working_dir = os.path.join(hyperrag_working_dir, db_dir_name)
        Path(db_working_dir).mkdir(parents=True, exist_ok=True)
        
        main_logger.info(f"HyperRAG工作目录: {db_working_dir}")
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            settings = json.load(f)

        embedding_dim = settings.get("embeddingDim")

        # 获取领域配置
        current_domain = settings.get("hyperrag_domain", "default")
        main_logger.info(f"使用Hyper-RAG领域: {current_domain}")

        # 如果是特定领域，设置领域管理器
        if current_domain != "default":
            try:
                from hyperrag.prompt import set_domain
                set_domain(current_domain)
                main_logger.info(f"领域已设置为: {current_domain}")
            except Exception as e:
                main_logger.warning(f"设置领域失败，使用默认领域: {safe_str(e)}")
                current_domain = "default"

        # 获取领域特定的实体类型（如果支持）
        entity_types = None
        if current_domain != "default":
            try:
                from hyperrag.prompt import get_entity_types
                entity_types = get_entity_types(current_domain)
                main_logger.info(f"领域实体类型: {entity_types}")
            except Exception as e:
                main_logger.warning(f"获取领域实体类型失败: {safe_str(e)}")

        # 初始化 HyperRAG 实例
        hyperrag_kwargs = {
            "working_dir": db_working_dir,
            "llm_model_func": get_hyperrag_llm_func,
            "llm_model_max_async": int(settings.get("llmGlobalMaxAsync", settings.get("llmModelMaxAsync", 4))),
            "embedding_func": EmbeddingFunc(
                embedding_dim=embedding_dim,  # text-embedding-3-small 的维度
                max_token_size=8192,
                func=get_hyperrag_embedding_func
            ),
        }

        if requested_chunk_size:
            hyperrag_kwargs["chunk_token_size"] = requested_chunk_size
        if requested_chunk_overlap is not None:
            hyperrag_kwargs["chunk_overlap_token_size"] = requested_chunk_overlap

        hyperrag_instances[database] = HyperRAG(**hyperrag_kwargs)

        # 传递领域配置到 HyperRAG 实例
        if current_domain != "default":
            hyperrag_instances[database].domain = current_domain
        main_logger.info(
            f"HyperRAG effective config: database={database}, domain={hyperrag_instances[database].domain}, "
            f"chunk_token_size={hyperrag_instances[database].chunk_token_size}, "
            f"chunk_overlap_token_size={hyperrag_instances[database].chunk_overlap_token_size}, "
            f"llm_model_max_async={hyperrag_instances[database].llm_model_max_async}, "
            f"embedding_batch_num={hyperrag_instances[database].embedding_batch_num}"
        )
        
        main_logger.info(f"HyperRAG实例创建完成，数据库: {database}")
    else:
        main_logger.info(f"使用现有HyperRAG实例，数据库: {database}")
    
    instance = hyperrag_instances[database]
    try:
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            settings = json.load(f)
        instance.domain = settings.get("hyperrag_domain", getattr(instance, "domain", "default"))
    except Exception as e:
        main_logger.warning(f"刷新HyperRAG领域配置失败: {safe_str(e)}")
    if requested_chunk_size:
        instance.chunk_token_size = requested_chunk_size
    if requested_chunk_overlap is not None:
        instance.chunk_overlap_token_size = requested_chunk_overlap
    main_logger.info(
        f"HyperRAG active config: database={database}, domain={getattr(instance, 'domain', 'default')}, "
        f"chunk_token_size={instance.chunk_token_size}, "
        f"chunk_overlap_token_size={instance.chunk_overlap_token_size}, "
        f"llm_model_max_async={instance.llm_model_max_async}, "
        f"embedding_batch_num={instance.embedding_batch_num}"
    )
    return instance


def get_or_create_cograg(database: str = None):
    """
    获取或创建指定数据库的 Cog-RAG 实例
    """
    global cograg_instances

    if not COGRAG_AVAILABLE:
        main_logger.error("Cog-RAG 不可用")
        raise RuntimeError("Cog-RAG is not available")

    # 如果没有指定数据库，使用默认数据库
    if database is None:
        database = db_manager.default_database
        main_logger.info(f"使用默认数据库: {database}")

    # 检查是否已存在该数据库的实例
    if database not in cograg_instances:
        main_logger.info(f"创建新的Cog-RAG实例，数据库: {database}")

        # 使用数据库名作为工作目录（去掉.hgdb后缀）
        if database.endswith('.hgdb'):
            db_dir_name = database.replace('.hgdb', '')
        else:
            db_dir_name = database

        # Cog-RAG 工作目录
        db_working_dir = os.path.join(cograg_working_dir, db_dir_name)
        Path(db_working_dir).mkdir(parents=True, exist_ok=True)

        main_logger.info(f"Cog-RAG工作目录: {db_working_dir}")
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            settings = json.load(f)

        embedding_dim = settings.get("embeddingDim")

        # 初始化 Cog-RAG 实例，复用现有的LLM和嵌入函数
        cograg_instances[database] = CogRAGClass(
            working_dir=db_working_dir,
            llm_model_func=get_hyperrag_llm_func,
            embedding_func=EmbeddingFunc(
                embedding_dim=embedding_dim,
                max_token_size=8192,
                func=get_hyperrag_embedding_func
            ),
        )

        main_logger.info(f"Cog-RAG实例创建完成，数据库: {database}")
    else:
        main_logger.info(f"使用现有Cog-RAG实例，数据库: {database}")

    return cograg_instances[database]


class Message(BaseModel):
    message: str

@app.post("/process_message")
async def process_message(msg: Message, user: dict = Depends(require_current_user)):
    user_message = msg.message
    try:
        response_message = await get_hyperrag_llm_func(prompt=user_message)
    except Exception as e:
        return {"response": safe_str(e)} 
    return {"response": response_message}

# HyperRAG 问答相关接口

class DocumentModel(BaseModel):
    content: str
    retries: int = 3
    database: str = None  # 添加数据库参数

class QueryModel(BaseModel):
    question: str
    mode: str = "hyper"  # 支持: hyper, hyper-lite, naive, graph, llm, cog, cog-hybrid, cog-entity, cog-theme
    top_k: int = 60
    max_token_for_text_unit: int = 1600
    max_token_for_entity_context: int = 300
    max_token_for_relation_context: int = 1600
    only_need_context: bool = False
    response_type: str = "Multiple Paragraphs"
    database: str = None  # 添加数据库参数

@app.post("/hyperrag/insert")
async def insert_document(doc: DocumentModel, user: dict = Depends(require_current_user)):
    """
    向指定数据库的 HyperRAG 插入文档
    """
    if not HYPERRAG_AVAILABLE:
        return {"success": False, "message": "HyperRAG is not available"}
    
    try:
        consume_document_quota_if_needed(user, 1)
        doc.database = namespace_database_name(doc.database, user)
        rag = get_or_create_hyperrag(doc.database)
        
        # 重试机制
        for attempt in range(doc.retries):
            try:
                await rag.ainsert(doc.content)
                return {
                    "success": True, 
                    "message": "Document inserted successfully",
                    "database": doc.database or "default"
                }
            except Exception as e:
                if attempt == doc.retries - 1:
                    raise e
                print(f"Insert attempt {attempt + 1} failed: {e}. Retrying...")
                await asyncio.sleep(2)
                
    except Exception as e:
        return {"success": False, "message": f"Failed to insert document: {safe_str(e)}"}

@app.post("/hyperrag/query")
async def query_hyperrag(query: QueryModel, user: dict = Depends(require_current_user)):
    """
    统一的查询端点，支持HyperRAG和Cog-RAG模式
    """
    try:
        # 定义Cog-RAG模式
        cog_modes = ["cog", "cog-hybrid", "cog-entity", "cog-theme"]
        hyper_modes = ["hyper", "hyper-lite", "naive", "graph", "llm"]

        if query.mode in cog_modes:
            # 使用Cog-RAG
            if not COGRAG_AVAILABLE:
                return {"success": False, "message": "Cog-RAG is not available"}

            main_logger.info(f"使用Cog-RAG查询，模式: {query.mode}")
            query.database = require_database_access(query.database, user) if query.database else namespace_database_name("default", user)
            rag = get_or_create_cograg(query.database)

            # 创建Cog-RAG查询参数
            param = CogQueryParam(
                mode=query.mode,
                top_k=query.top_k,
                max_token_for_text_unit=query.max_token_for_text_unit,
                max_token_for_entity_context=query.max_token_for_entity_context,
                max_token_for_relation_context=query.max_token_for_relation_context,
                only_need_context=query.only_need_context,
                response_type=query.response_type,
            )

            # 执行查询
            result = await rag.aquery(query.question, param)

            # 处理Cog-RAG响应格式
            return {
                "success": True,
                "response": result.get("response", ""),
                "entities": result.get("entities", []),
                "themes": result.get("themes", []),  # Cog-RAG特有的主题信息
                "hyperedges": result.get("hyperedges", []),
                "text_units": result.get("text_units", []),
                "mode": query.mode,
                "rag_system": "cograg",  # 标识使用的系统
                "question": query.question,
                "database": query.database or "default"
            }

        elif query.mode in hyper_modes:
            # 使用现有的HyperRAG逻辑
            if not HYPERRAG_AVAILABLE:
                return {"success": False, "message": "HyperRAG is not available"}

            main_logger.info(f"使用HyperRAG查询，模式: {query.mode}")
            query.database = require_database_access(query.database, user) if query.database else namespace_database_name("default", user)
            rag = get_or_create_hyperrag(query.database)
            param = QueryParam(
                mode=query.mode,
                top_k=query.top_k,
                max_token_for_text_unit=query.max_token_for_text_unit,
                max_token_for_entity_context=query.max_token_for_entity_context,
                max_token_for_relation_context=query.max_token_for_relation_context,
                only_need_context=query.only_need_context,
                response_type=query.response_type,
                return_type='json'
            )

            result = await rag.aquery(query.question, param)

            return {
                "success": True,
                "response": result.get("response", ""),
                "entities": result.get("entities", []),
                "hyperedges": result.get("hyperedges", []),
                "text_units": result.get("text_units", []),
                "mode": query.mode,
                "rag_system": "hyperrag",
                "question": query.question,
                "database": query.database or "default"
            }
        else:
            return {"success": False, "message": f"Unknown query mode: {query.mode}"}

    except Exception as e:
        main_logger.error(f"查询失败: {safe_str(e)}")
        return {"success": False, "message": f"Query failed: {safe_str(e)}"}
        
    except Exception as e:
        return {"success": False, "message": f"Query failed: {safe_str(e)}"}

@app.get("/hyperrag/status")
async def get_hyperrag_status(database: str = None):
    """
    获取指定数据库的 HyperRAG 实例状态
    """
    try:
        status = {
            "available": HYPERRAG_AVAILABLE,
            "database": database or "default",
            "working_dir": hyperrag_working_dir,
            "instances": list(hyperrag_instances.keys())
        }
        
        if database:
            # 获取特定数据库的状态
            if database in hyperrag_instances:
                instance = hyperrag_instances[database]
                status["initialized"] = True
                try:
                    status["details"] = {
                        "chunk_token_size": instance.chunk_token_size,
                        "llm_model_name": instance.llm_model_name,
                        "embedding_func_available": instance.embedding_func is not None,
                        "working_dir": os.path.join(hyperrag_working_dir, database.replace('.hgdb', ''))
                    }
                except Exception as e:
                    status["details"] = f"Error getting details: {safe_str(e)}"
            else:
                status["initialized"] = False
        else:
            # 获取所有实例的概览
            status["initialized"] = len(hyperrag_instances) > 0
            status["total_instances"] = len(hyperrag_instances)
        
        return status

    except Exception as e:
        return {"success": False, "message": f"Failed to get status: {safe_str(e)}"}

@app.post("/cograg/insert")
async def insert_cograg_document(doc: DocumentModel):
    """
    向指定数据库的 Cog-RAG 插入文档
    """
    if not COGRAG_AVAILABLE:
        return {"success": False, "message": "Cog-RAG is not available"}

    try:
        rag = get_or_create_cograg(doc.database)

        # 重试机制
        for attempt in range(doc.retries):
            try:
                await rag.ainsert(doc.content)
                main_logger.info(f"文档插入Cog-RAG成功，数据库: {doc.database}")
                return {
                    "success": True,
                    "message": "Document inserted into Cog-RAG successfully",
                    "database": doc.database or "default",
                    "rag_system": "cograg"
                }
            except Exception as e:
                if attempt == doc.retries - 1:
                    raise e
                main_logger.warning(f"插入尝试 {attempt + 1} 失败: {safe_str(e)}. 重试中...")
                await asyncio.sleep(2)

    except Exception as e:
        main_logger.error(f"插入Cog-RAG文档失败: {safe_str(e)}")
        return {"success": False, "message": f"Failed to insert document into Cog-RAG: {safe_str(e)}"}

@app.get("/cograg/status")
async def get_cograg_status(database: str = None):
    """
    获取Cog-RAG实例状态
    """
    try:
        status = {
            "available": COGRAG_AVAILABLE,
            "database": database or "default",
            "working_dir": cograg_working_dir,
            "instances": list(cograg_instances.keys())
        }

        if database and database in cograg_instances:
            instance = cograg_instances[database]
            status["initialized"] = True
            status["details"] = {
                "chunk_token_size": instance.chunk_token_size,
                "llm_model_name": instance.llm_model_name,
                "embedding_func_available": instance.embedding_func is not None,
                "working_dir": os.path.join(cograg_working_dir, database.replace('.hgdb', ''))
            }
        else:
            status["initialized"] = False

        return status
    except Exception as e:
        main_logger.error(f"获取Cog-RAG状态失败: {safe_str(e)}")
        return {"success": False, "message": f"Failed to get Cog-RAG status: {safe_str(e)}"}

@app.get("/systems/status")
async def get_systems_status():
    """
    获取所有RAG系统的状态
    """
    try:
        status = {
            "hyperrag": {
                "available": HYPERRAG_AVAILABLE,
                "instances": len(hyperrag_instances),
                "working_dir": hyperrag_working_dir
            },
            "cograg": {
                "available": COGRAG_AVAILABLE,
                "instances": len(cograg_instances),
                "working_dir": cograg_working_dir
            },
            "current_system": "hyperrag"  # 默认系统
        }
        return status
    except Exception as e:
        main_logger.error(f"获取系统状态失败: {safe_str(e)}")
        return {"success": False, "message": f"Failed to get systems status: {safe_str(e)}"}

@app.delete("/hyperrag/reset")
async def reset_hyperrag(database: str = None):
    """
    重置指定数据库的 HyperRAG 实例，或重置所有实例
    """
    global hyperrag_instances
    
    try:
        if database:
            # 重置特定数据库的实例
            if database in hyperrag_instances:
                del hyperrag_instances[database]
                return {
                    "success": True, 
                    "message": f"HyperRAG instance for database '{database}' reset successfully"
                }
            else:
                return {
                    "success": False, 
                    "message": f"No HyperRAG instance found for database '{database}'"
                }
        else:
            # 重置所有实例
            hyperrag_instances = {}
            return {"success": True, "message": "All HyperRAG instances reset successfully"}
            
    except Exception as e:
        return {"success": False, "message": f"Failed to reset: {safe_str(e)}"}

# 文件管理相关的API接口

class FileEmbedRequest(BaseModel):
    file_ids: List[str]
    chunk_size: int = 500  # 减小chunk_size避免超时
    chunk_overlap: int = 100  # 相应减小overlap
    rag_system: str = "hyperrag"  # 新增：选择RAG系统 (hyperrag 或 cograg)
    target_database: Optional[str] = None  # 目标数据库名称，None则使用文件关联的数据库
    update_file_database: bool = False  # 是否更新文件关联的数据库
    kb_name: Optional[str] = None  # 知识库名称，自动填充嵌入配置

@app.get("/files")
async def get_files(user: dict = Depends(require_current_user)):
    """
    获取所有上传的文件列表
    """
    try:
        files = file_manager.get_all_files(owner_user_id=user.get("id"), include_legacy=True)
        return {"files": files}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取文件列表失败: {safe_str(e)}")

@app.post("/files/upload")
async def upload_files(
    files: List[UploadFile] = File(...),
    target_database: str = Form(default=None),
    kb_name: str = Form(default=None),
    user: dict = Depends(require_current_user)
):
    """
    上传文件接口

    Args:
        files: 上传的文件列表
        target_database: 目标数据库名称（可选），如果指定则所有文件都关联到此数据库

    Returns:
        包含上传结果的字典
    """
    print(f"\n{'='*50}")
    print(f"开始文件上传，文件数量: {len(files)}")
    if target_database:
        print(f"目标数据库: {target_database}")
    print(f"{'='*50}")

    # 检查是否有文件
    if not files or len(files) == 0:
        print("[ERROR] 没有接收到文件")
        raise HTTPException(status_code=400, detail="没有接收到文件")

    results = []

    for i, file in enumerate(files):
        try:
            print(f"\n上传文件 {i+1}/{len(files)}: {file.filename}")
            print(f"文件大小: {file.size if hasattr(file, 'size') else '未知'} bytes")
            print(f"文件类型: {file.content_type}")

            # 检查文件大小
            if hasattr(file, 'size') and file.size and file.size > 50 * 1024 * 1024:  # 50MB
                raise ValueError("文件大小超过50MB限制")

            # 读取文件内容
            print("正在读取文件内容...")
            content = await file.read()
            print(f"[OK] 文件内容读取完成，实际大小: {len(content)} bytes")

            if len(content) == 0:
                raise ValueError("文件内容为空")

            # 保存文件 - 传入目标数据库
            print("正在保存文件到本地...")

            # 如果指定了kb_name，使用KB的数据库名
            effective_target_db = target_database
            if kb_name:
                kb = await kb_manager.get_kb(kb_name, owner_user_id=user.get("id"), include_legacy=True)
                if kb:
                    effective_target_db = kb["database_name"]
                else:
                    raise ValueError("知识库不存在或无权访问")
            elif effective_target_db:
                effective_target_db = namespace_database_name(effective_target_db, user)
            else:
                effective_target_db = namespace_database_name(Path(file.filename).stem, user)

            file_info = await file_manager.save_uploaded_file(
                content,
                file.filename,
                target_database=effective_target_db,
                owner_user_id=user.get("id"),
            )

            # 关联知识库
            if kb_name:
                file_manager.update_file_kb(file_info["file_id"], kb_name)

            file_info["status"] = "uploaded"
            file_info["size"] = len(content)
            print(f"[OK] 文件保存成功: {file_info['filename']}")
            print(f"  - 文件ID: {file_info['file_id']}")
            print(f"  - 保存路径: {file_info['file_path']}")
            print(f"  - 数据库: {file_info['database_name']}")

            results.append(file_info)

        except Exception as e:
            error_msg = f"文件上传失败: {file.filename if hasattr(file, 'filename') else '未知文件'}, 错误: {safe_str(e)}"
            print(f"[ERROR] {error_msg}")
            main_logger.error(error_msg)
            results.append({
                "filename": file.filename if hasattr(file, 'filename') else '未知文件',
                "status": "error",
                "error": safe_str(e)
            })

    print(f"\n文件上传完成，成功: {len([r for r in results if r.get('status') == 'uploaded'])}/{len(files)}")
    print(f"{'='*50}")

    return {"files": results}

@app.delete("/files/{file_id}")
async def delete_file(file_id: str, clean_database: bool = False, user: dict = Depends(require_current_user)):
    file_info_for_auth = file_manager.get_file_by_id(file_id, owner_user_id=user.get("id"), include_legacy=True)
    if not file_info_for_auth:
        raise HTTPException(status_code=404, detail="文件不存在或无权访问")
    """
    删除指定的文件

    Args:
        file_id: 文件ID
        clean_database: 是否同时清理数据库中的嵌入数据
    """
    try:
        # 获取当前活动的HyperRAG实例用于清理数据库
        rag_instance = None
        if clean_database:
            # 获取默认数据库的HyperRAG实例
            try:
                rag_instance = get_or_create_hyperrag()
                main_logger.info(f"准备清理文件 {file_id} 的数据库数据")
            except Exception as e:
                main_logger.warning(f"无法获取HyperRAG实例进行数据库清理: {safe_str(e)}")
                clean_database = False

        success = file_manager.delete_file(file_id, clean_database=clean_database, rag_instance=rag_instance)

        if success:
            message = "文件删除成功"
            if clean_database and rag_instance:
                message += "，数据库数据已清理"
            return {"success": True, "message": message}
        else:
            raise HTTPException(status_code=404, detail="文件不存在")
    except Exception as e:
        main_logger.error(f"删除文件失败: {safe_str(e)}")
        raise HTTPException(status_code=500, detail=f"文件删除失败: {safe_str(e)}")

@app.post("/database/clear")
async def clear_database(database: str = "default", user: dict = Depends(require_current_user)):
    database = require_database_access(database, user) or namespace_database_name("default", user)
    """
    清空指定数据库的所有数据

    Args:
        database: 数据库名称
    """
    try:
        main_logger.info(f"开始清空数据库: {database}")

        # 清空HyperRAG实例缓存
        if database in hyperrag_instances:
            del hyperrag_instances[database]
            main_logger.info(f"已清除数据库 {database} 的实例缓存")

        # 删除数据库文件（保留日志文件，避免文件占用错误）
        db_path = Path(hyperrag_working_dir) / database
        if db_path.exists():
            import shutil
            # 保留日志文件，只删除数据文件
            data_files_to_delete = []
            for item in db_path.iterdir():
                if item.is_file() and not item.name.endswith('.log'):
                    data_files_to_delete.append(item)
                elif item.is_dir():
                    # 删除子目录中的所有文件（除了.log文件）
                    for sub_item in item.rglob('*'):
                        if sub_item.is_file() and not sub_item.name.endswith('.log'):
                            try:
                                sub_item.unlink()
                            except Exception as e:
                                main_logger.warning(f"删除文件 {sub_item} 失败: {safe_str(e)}")

            # 删除数据文件
            for file in data_files_to_delete:
                try:
                    file.unlink()
                    main_logger.info(f"已删除数据文件: {file}")
                except Exception as e:
                    main_logger.warning(f"删除文件 {file} 失败: {safe_str(e)}")

            # 尝试删除空目录
            for item in db_path.iterdir():
                if item.is_dir():
                    try:
                        shutil.rmtree(item)
                    except Exception as e:
                        main_logger.warning(f"删除目录 {item} 失败: {safe_str(e)}")

            main_logger.info(f"已清空数据库数据: {db_path}")

        return {
            "success": True,
            "message": f"数据库 {database} 已清空",
            "database": database
        }
    except Exception as e:
        main_logger.error(f"清空数据库失败: {safe_str(e)}")
        raise HTTPException(status_code=500, detail=f"清空数据库失败: {safe_str(e)}")

@app.get("/database/status")
async def get_database_status(database: str = "default", user: dict = Depends(require_current_user)):
    database = require_database_access(database, user) or namespace_database_name("default", user)
    """
    获取数据库状态信息

    Args:
        database: 数据库名称
    """
    try:
        # 检查数据库是否存在
        db_path = Path(hyperrag_working_dir) / database
        db_exists = db_path.exists()

        # 获取数据库大小
        db_size = 0
        if db_exists:
            for file_path in db_path.rglob("*"):
                if file_path.is_file():
                    db_size += file_path.stat().st_size

        # 获取实例状态
        has_instance = database in hyperrag_instances

        return {
            "database": database,
            "exists": db_exists,
            "has_instance": has_instance,
            "size_bytes": db_size,
            "size_mb": round(db_size / (1024 * 1024), 2),
            "path": str(db_path)
        }
    except Exception as e:
        main_logger.error(f"获取数据库状态失败: {safe_str(e)}")
        raise HTTPException(status_code=500, detail=f"获取数据库状态失败: {safe_str(e)}")

@app.get("/databases/{database_name}/diagnose")
async def diagnose_database(database_name: str, user: dict = Depends(require_current_user)):
    database_name = require_database_access(database_name, user)
    """
    诊断数据库文件占用情况

    Args:
        database_name: 数据库名称

    Returns:
        诊断信息
    """
    try:
        import psutil
        import os

        diagnosis = {
            "database": database_name,
            "hyperrag": {"exists": False, "path": "", "files": [], "processes": []},
            "cograg": {"exists": False, "path": "", "files": [], "processes": []},
            "instances": {
                "hyperrag": database_name in hyperrag_instances,
                "cograg": database_name in cograg_instances,
                "db_manager_hyperrag": f"{database_name}_hyperrag" in db_manager.databases,
                "db_manager_cograg": f"{database_name}_cograg" in db_manager.databases,
                "theme_db": database_name in db_manager.theme_databases
            }
        }

        # 诊断 HyperRAG 数据库
        hyperrag_path = os.path.join(hyperrag_working_dir, database_name)
        if os.path.exists(hyperrag_path):
            diagnosis["hyperrag"]["exists"] = True
            diagnosis["hyperrag"]["path"] = hyperrag_path

            # 列出所有文件
            for root, dirs, files in os.walk(hyperrag_path):
                for file in files:
                    file_path = os.path.join(root, file)
                    file_info = {
                        "path": file_path,
                        "size": os.path.getsize(file_path),
                        "locked": False
                    }

                    # 尝试检测文件是否被锁定
                    try:
                        # 尝试以独占模式打开文件
                        with open(file_path, 'a') as f:
                            pass
                    except (IOError, PermissionError):
                        file_info["locked"] = True
                        # 尝试查找占用文件的进程
                        try:
                            for proc in psutil.process_iter(['pid', 'name', 'open_files']):
                                try:
                                    for item in proc.info['open_files'] or []:
                                        if file_path.lower() in item.path.lower():
                                            diagnosis["hyperrag"]["processes"].append({
                                                "pid": proc.info['pid'],
                                                "name": proc.info['name'],
                                                "path": item.path
                                            })
                                except (psutil.NoSuchProcess, psutil.AccessDenied):
                                    continue
                        except Exception:
                            pass

                    diagnosis["hyperrag"]["files"].append(file_info)

        # 诊断 Cog-RAG 数据库
        cograg_path = os.path.join(cograg_working_dir, database_name)
        if os.path.exists(cograg_path):
            diagnosis["cograg"]["exists"] = True
            diagnosis["cograg"]["path"] = cograg_path

            # 列出所有文件
            for root, dirs, files in os.walk(cograg_path):
                for file in files:
                    file_path = os.path.join(root, file)
                    file_info = {
                        "path": file_path,
                        "size": os.path.getsize(file_path),
                        "locked": False
                    }

                    # 尝试检测文件是否被锁定
                    try:
                        with open(file_path, 'a') as f:
                            pass
                    except (IOError, PermissionError):
                        file_info["locked"] = True
                        # 尝试查找占用文件的进程
                        try:
                            for proc in psutil.process_iter(['pid', 'name', 'open_files']):
                                try:
                                    for item in proc.info['open_files'] or []:
                                        if file_path.lower() in item.path.lower():
                                            diagnosis["cograg"]["processes"].append({
                                                "pid": proc.info['pid'],
                                                "name": proc.info['name'],
                                                "path": item.path
                                            })
                                except (psutil.NoSuchProcess, psutil.AccessDenied):
                                    continue
                        except Exception:
                            pass

                    diagnosis["cograg"]["files"].append(file_info)

        return diagnosis

    except ImportError:
        return {"error": "psutil module not installed", "message": "Install psutil to use this feature: pip install psutil"}
    except Exception as e:
        main_logger.error(f"诊断数据库失败: {database_name}, 错误: {safe_str(e)}")
        return {"error": safe_str(e), "message": f"诊断失败: {safe_str(e)}"}

@app.delete("/databases/{database_name}")
async def delete_database_endpoint(database_name: str, user: dict = Depends(require_current_user)):
    """
    删除指定数据库（支持HyperRAG和Cog-RAG双系统）

    Args:
        database_name: 数据库名称

    Returns:
        删除结果
    """
    import gc
    import time

    try:
        main_logger.info(f"[DELETE]  开始删除数据库: {database_name}")

        # 验证数据库名称安全性
        if not database_name or database_name in ['.', '..'] or '/' in database_name or '\\' in database_name:
            return {"success": False, "message": "Invalid database name"}

        # 第一步：清除所有RAG实例缓存
        print(f"📋 清除RAG实例缓存...")
        cleared_instances = []

        if database_name in hyperrag_instances:
            instance = hyperrag_instances[database_name]
            # 尝试调用实例的清理方法（如果存在）
            if hasattr(instance, '_cleanup'):
                try:
                    instance._cleanup()
                    print(f"   [OK] 调用HyperRAG实例清理方法")
                except Exception as e:
                    print(f"   [WARNING]  HyperRAG实例清理失败: {safe_str(e)}")

            del hyperrag_instances[database_name]
            cleared_instances.append(f"HyperRAG({database_name})")
            main_logger.info(f"已清除HyperRAG实例: {database_name}")
            print(f"   [OK] 已清除HyperRAG实例: {database_name}")

        if database_name in cograg_instances:
            instance = cograg_instances[database_name]
            # 尝试调用实例的清理方法（如果存在）
            if hasattr(instance, '_cleanup'):
                try:
                    instance._cleanup()
                    print(f"   [OK] 调用Cog-RAG实例清理方法")
                except Exception as e:
                    print(f"   [WARNING]  Cog-RAG实例清理失败: {safe_str(e)}")

            del cograg_instances[database_name]
            cleared_instances.append(f"Cog-RAG({database_name})")
            main_logger.info(f"已清除Cog-RAG实例: {database_name}")
            print(f"   [OK] 已清除Cog-RAG实例: {database_name}")

        # 强制垃圾回收
        gc.collect()
        time.sleep(0.5)  # 给系统时间释放资源

        if cleared_instances:
            print(f"   [INFO] 共清除 {len(cleared_instances)} 个实例: {', '.join(cleared_instances)}")

        # 第二步：调用数据库管理器删除数据库
        print(f"📂 调用数据库管理器删除数据库文件...")
        result = db_manager.delete_database(database_name)

        # 再次强制垃圾回收
        gc.collect()

        # 第三步：发送WebSocket通知
        try:
            await manager.broadcast_json({
                "type": "database_deleted",
                "database_name": database_name,
                "success": result.get("success", False),
                "timestamp": datetime.now().isoformat()
            })
            main_logger.info(f"已发送数据库删除通知: {database_name}")
            print(f"📢 已发送数据库删除通知")
        except Exception as e:
            main_logger.warning(f"发送WebSocket通知失败: {safe_str(e)}")
            print(f"[WARNING]  发送WebSocket通知失败: {safe_str(e)}")

        # 添加清理的实例信息到结果中
        result["cleared_instances"] = cleared_instances

        return result

    except Exception as e:
        main_logger.error(f"[ERROR] 删除数据库失败: {database_name}, 错误: {safe_str(e)}")
        print(f"[ERROR] 删除数据库失败: {database_name}, 错误: {safe_str(e)}")
        return {"success": False, "message": f"删除数据库失败: {safe_str(e)}"}

@app.post("/files/embed")
async def embed_files(request: FileEmbedRequest, user: dict = Depends(require_current_user)):
    """
    批量嵌入文档到HyperRAG
    """
    if not HYPERRAG_AVAILABLE:
        raise HTTPException(status_code=500, detail="HyperRAG is not available")
    
    print(f"\n{'='*50}")
    print(f"开始文档嵌入，文件数量: {len(request.file_ids)}")
    print(f"配置参数: chunk_size={request.chunk_size}, chunk_overlap={request.chunk_overlap}")
    print(f"{'='*50}")
    
    results = []
    
    try:
        database_name = require_database_access(database_name, user)
        consume_document_quota_if_needed(user, len(request.file_ids))
        await preflight_hyperrag_api_services()

        for i, file_id in enumerate(request.file_ids):
            file_info = None
            database_name = None
            content = None
            try:
                print(f"\n处理文件 {i+1}/{len(request.file_ids)}: {file_id}")
                
                # 更新文件状态为处理中
                print("更新文件状态为处理中...")
                file_manager.update_file_status(file_id, "processing")
                
                # 获取文件信息
                print("获取文件信息...")
                file_info = file_manager.get_file_by_id(file_id, owner_user_id=user.get("id"), include_legacy=True)
                if not file_info:
                    error_msg = f"文件不存在: {file_id}"
                    print(f"[ERROR] {error_msg}")
                    results.append({
                        "file_id": file_id,
                        "status": "error",
                        "error": "文件不存在"
                    })
                    continue
                
                print(f"[OK] 文件信息: {file_info['filename']} ({file_info['file_size']} bytes)")
                
                # 使用文件对应的数据库名
                database_name = file_info["database_name"]
                print(f"目标数据库: {database_name}")
                rag = get_or_create_hyperrag(
                    database_name,
                    chunk_size=request.chunk_size,
                    chunk_overlap=request.chunk_overlap,
                )
                
                # 读取文件内容
                print("读取文件内容...")
                content = await file_manager.read_file_content(file_info["file_path"])
                print(f"[OK] 内容长度: {len(content)} 字符")
                
                # 插入到HyperRAG
                print("开始文档嵌入...")
                await rag.ainsert(content)
                print("[OK] 文档嵌入完成")
                
                # 更新文件状态为已嵌入
                file_manager.update_file_status(file_id, "embedded")
                
                results.append({
                    "file_id": file_id,
                    "filename": file_info["filename"],
                    "database_name": database_name,
                    "status": "embedded"
                })
                
                print(f"[OK] 文件 {file_info['filename']} 嵌入成功")
                
            except Exception as e:
                # 更新文件状态为错误
                detailed_error = log_detailed_exception(
                    main_logger,
                    "文件嵌入失败",
                    e,
                    {
                        "file_id": file_id,
                        "filename": file_info.get("filename") if "file_info" in locals() and file_info else None,
                        "database_name": locals().get("database_name"),
                        "rag_system": request.rag_system,
                        "chunk_size": request.chunk_size,
                        "chunk_overlap": request.chunk_overlap,
                        "content_chars": len(content) if "content" in locals() else None,
                        "runtime_settings": get_runtime_settings_context(),
                    },
                )
                user_friendly_error = extract_user_friendly_error(detailed_error)
                error_msg = f"文件嵌入失败: {file_id}, 错误: {detailed_error}"
                print(f"[ERROR] {error_msg}")
                file_manager.update_file_status(file_id, "error", user_friendly_error)
                
                results.append({
                    "file_id": file_id,
                    "status": "error",
                    "error": user_friendly_error,
                    "detailed_error": detailed_error[:500]
                })
        
        successful = len([r for r in results if r.get('status') == 'embedded'])
        print(f"\n文档嵌入完成，成功: {successful}/{len(request.file_ids)}")
        print(f"{'='*50}")
        
        return {"embedded_files": results}

    except Exception as e:
        detailed_error = log_detailed_exception(
            main_logger,
            "批量嵌入失败",
            e,
            {
                "file_ids": request.file_ids,
                "rag_system": request.rag_system,
                "target_database": request.target_database,
                "chunk_size": request.chunk_size,
                "chunk_overlap": request.chunk_overlap,
                "runtime_settings": get_runtime_settings_context(),
            },
        )
        error_msg = f"批量嵌入失败: {detailed_error}"
        print(f"[ERROR] {error_msg}")
        raise HTTPException(status_code=500, detail=extract_user_friendly_error(detailed_error))

@app.post("/cache/clear")
async def clear_hyperrag_cache():
    """
    清除 HyperRAG 实例缓存，强制重新创建实例
    """
    global hyperrag_instances
    cleared_count = len(hyperrag_instances)
    hyperrag_instances = {}
    main_logger.info(f"已清除 {cleared_count} 个 HyperRAG 实例缓存")
    return {"success": True, "message": f"已清除 {cleared_count} 个实例缓存"}

# 自定义日志处理器，将日志通过WebSocket发送
class WebSocketLogHandler(logging.Handler):
    def __init__(self, connection_manager):
        super().__init__()
        self.connection_manager = connection_manager

    def emit(self, record):
        try:
            log_message = self.format(record)
            # 使用safe_str处理可能包含问题Unicode字符的日志消息
            safe_message = safe_str(log_message)
            # 异步发送日志消息
            loop = asyncio.get_running_loop()
            loop.create_task(self.connection_manager.send_log_message({
                "type": "log",
                "level": record.levelname,
                "message": safe_message,
                "timestamp": record.created,
                "logger_name": record.name
            }))
        except Exception:
            pass  # 避免日志处理器自身错误影响主程序

# 自定义流处理器，捕获print语句和其他输出
class WebSocketStreamHandler:
    def __init__(self, connection_manager, stream_type="stdout"):
        self.connection_manager = connection_manager
        self.stream_type = stream_type
        self.original_stream = sys.stdout if stream_type == "stdout" else sys.stderr
        
    def write(self, message):
        try:
            # 同时写入原始流
            self.original_stream.write(message)
            self.original_stream.flush()

            # 发送到WebSocket（去除空行）
            if message.strip():
                # 使用safe_str处理可能包含问题Unicode字符的消息
                safe_message = safe_str(message.strip())
                loop = asyncio.get_running_loop()
                loop.create_task(self.connection_manager.send_log_message({
                    "type": "console",
                    "level": "ERROR" if self.stream_type == "stderr" else "INFO",
                    "message": safe_message,
                    "timestamp": loop.time(),
                    "source": self.stream_type
                }))
        except Exception:
            # 如果写入失败，至少尝试继续执行
            pass
    
    def flush(self):
        self.original_stream.flush()

# WebSocket连接管理
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.logging_enabled = False
        self.original_stdout = None
        self.original_stderr = None

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        
        # 如果是第一个连接，启用日志重定向
        if len(self.active_connections) == 1 and not self.logging_enabled:
            self.enable_logging_redirect()

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        
        # 如果没有连接了，禁用日志重定向
        if len(self.active_connections) == 0 and self.logging_enabled:
            self.disable_logging_redirect()

    def enable_logging_redirect(self):
        """启用日志重定向"""
        if not self.logging_enabled:
            self.original_stdout = sys.stdout
            self.original_stderr = sys.stderr
            
            # 重定向标准输出和错误输出
            sys.stdout = WebSocketStreamHandler(self, "stdout")
            sys.stderr = WebSocketStreamHandler(self, "stderr")
            
            self.logging_enabled = True
            print("日志重定向已启用")

    def disable_logging_redirect(self):
        """禁用日志重定向"""
        if self.logging_enabled and self.original_stdout and self.original_stderr:
            sys.stdout = self.original_stdout
            sys.stderr = self.original_stderr
            self.logging_enabled = False
            print("日志重定向已禁用")

    async def send_personal_message(self, message: str, websocket: WebSocket):
        await websocket.send_text(message)

    async def broadcast(self, message: str):
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception:
                # 如果连接已断开，标记为移除
                disconnected.append(connection)

        # 移除断开的连接
        for conn in disconnected:
            self.disconnect(conn)

    async def broadcast_json(self, message: dict):
        """向所有连接的客户端广播JSON消息"""
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                # 如果连接已断开，标记为移除
                disconnected.append(connection)

        # 移除断开的连接
        for conn in disconnected:
            self.disconnect(conn)

    async def send_progress_update(self, progress_data: dict):
        """发送进度更新到所有连接的客户端"""
        message = json.dumps(progress_data)
        await self.broadcast(message)
    
    async def send_log_message(self, log_data: dict):
        """发送日志消息到所有连接的客户端"""
        message = json.dumps(log_data)
        await self.broadcast(message)

manager = ConnectionManager()

# 设置全面的日志配置
def setup_comprehensive_logging():
    """设置全面的日志配置"""
    # 设置根日志记录器
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    
    # 清除现有的处理器
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    log_dir = Path(__file__).resolve().parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    # 创建WebSocket处理器
    ws_handler = WebSocketLogHandler(manager)
    ws_handler.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    detailed_formatter = logging.Formatter(
        '%(asctime)s - %(process)d - %(threadName)s - %(name)s - %(levelname)s - %(message)s'
    )
    ws_handler.setFormatter(formatter)
    
    # 创建控制台处理器（保留控制台输出）
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    # 设置编码为UTF-8以支持特殊字符
    if hasattr(console_handler, 'stream') and hasattr(console_handler.stream, 'reconfigure'):
        try:
            console_handler.stream.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass  # 如果重新配置失败，继续使用默认编码

    # 创建文件日志处理器：backend.log 记录完整运行日志，error.log 只记录错误和 traceback
    backend_file_handler = RotatingFileHandler(
        log_dir / "backend.log",
        maxBytes=20 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    backend_file_handler.setLevel(logging.DEBUG)
    backend_file_handler.setFormatter(detailed_formatter)

    error_file_handler = RotatingFileHandler(
        log_dir / "error.log",
        maxBytes=20 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    error_file_handler.setLevel(logging.ERROR)
    error_file_handler.setFormatter(detailed_formatter)
    
    # 添加处理器到根日志记录器
    root_logger.addHandler(ws_handler)
    root_logger.addHandler(console_handler)
    root_logger.addHandler(backend_file_handler)
    root_logger.addHandler(error_file_handler)

    # 添加安全日志过滤器到根记录器
    safe_filter = SafeLogFilter()
    root_logger.addFilter(safe_filter)
    for handler in root_logger.handlers:
        handler.addFilter(safe_filter)
    
    # 设置特定模块的日志级别
    logging.getLogger('hyperrag').setLevel(logging.INFO)
    logging.getLogger('openai').setLevel(logging.INFO)
    logging.getLogger('httpx').setLevel(logging.WARNING)  # 减少HTTP请求日志
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    
    # 确保HyperRAG相关的所有子模块都能输出日志
    hyperrag_modules = [
        'hyperrag.base',
        'hyperrag.hyperrag',
        'hyperrag.llm',
        'hyperrag.operate',
        'hyperrag.prompt',
        'hyperrag.storage',
        'hyperrag.utils'
    ]

    for module_name in hyperrag_modules:
        module_logger = logging.getLogger(module_name)
        module_logger.setLevel(logging.INFO)
        # 确保模块日志也会传播到根记录器
        module_logger.propagate = True
        # 添加安全过滤器到每个模块
        module_logger.addFilter(safe_filter)

    root_logger.info(f"日志文件已启用: {log_dir / 'backend.log'}")
    root_logger.info(f"错误日志文件已启用: {log_dir / 'error.log'}")
    
    return root_logger

def configure_hyperrag_logging():
    """配置HyperRAG相关的详细日志输出"""
    try:
        # 如果HyperRAG可用，配置其内部日志
        if HYPERRAG_AVAILABLE:
            # 导入HyperRAG相关模块并设置日志
            try:
                import hyperrag
                import hyperrag.base
                import hyperrag.storage
                import hyperrag.llm
                import hyperrag.utils
                
                # 为HyperRAG的主要模块设置日志记录器
                modules_to_configure = [
                    hyperrag,
                    hyperrag.base,
                    hyperrag.storage, 
                    hyperrag.llm,
                    hyperrag.utils
                ]
                
                for module in modules_to_configure:
                    if hasattr(module, '__name__'):
                        logger = logging.getLogger(module.__name__)
                        logger.setLevel(logging.INFO)
                        logger.propagate = True
                        # 添加安全过滤器
                        safe_filter = SafeLogFilter()
                        logger.addFilter(safe_filter)
                        
                print("[OK] HyperRAG logging configuration completed")

            except ImportError as e:
                print(f"[WARNING] Failed to import HyperRAG module for logging configuration: {safe_str(e)}")

    except Exception as e:
        print(f"[WARNING] HyperRAG logging configuration failed: {safe_str(e)}")

# 初始化日志系统
main_logger = setup_comprehensive_logging()

# 配置HyperRAG日志
configure_hyperrag_logging()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            # 这里可以处理客户端发送的消息
            await manager.send_personal_message(f"Message received: {data}", websocket)
    except WebSocketDisconnect:
        manager.disconnect(websocket)

# 带实时进度通知的文档嵌入接口
@app.post("/files/embed-with-progress")
async def embed_files_with_progress(request: FileEmbedRequest, user: dict = Depends(require_current_user)):
    """
    批量嵌入文档到HyperRAG，带实时进度通知

    参数:
        file_ids: 文件ID列表
        chunk_size: 分块大小
        chunk_overlap: 分块重叠
        rag_system: RAG系统 (hyperrag/cograg)
        target_database: 目标数据库名称（可选），如果指定则所有文档嵌入到此数据库
        update_file_database: 是否更新文件关联的数据库
    """
    if not HYPERRAG_AVAILABLE:
        raise HTTPException(status_code=500, detail="HyperRAG is not available")

    # 如果指定了kb_name，从KB配置中读取默认参数
    if request.kb_name:
        kb = await kb_manager.get_kb(request.kb_name, owner_user_id=user.get("id"), include_legacy=True)
        if kb:
            if not request.target_database:
                request.target_database = kb["database_name"]
            request.rag_system = kb.get("rag_system", request.rag_system)
            request.chunk_size = kb.get("chunk_size", request.chunk_size)
            request.chunk_overlap = kb.get("chunk_overlap", request.chunk_overlap)
            request.update_file_database = True
            # 设置领域 - 直接更新设置文件中的 domain
            try:
                if os.path.exists(SETTINGS_FILE):
                    with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                        _settings = json.load(f)
                else:
                    _settings = {}
                _settings["hyperrag_domain"] = kb.get("domain", "default")
                with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
                    json.dump(_settings, f, ensure_ascii=False, indent=2)
            except Exception as e:
                main_logger.warning(f"更新领域设置失败: {safe_str(e)}")

    # 立即返回处理开始的响应
    if request.kb_name and not request.target_database:
        raise HTTPException(status_code=404, detail="知识库不存在或无权访问")

    if request.target_database:
        request.target_database = require_database_access(request.target_database, user)

    total_files = len(request.file_ids)
    consume_document_quota_if_needed(user, total_files)

    # 记录目标数据库信息
    if request.target_database:
        main_logger.info(f"目标数据库已指定: {request.target_database}")
        print(f"目标数据库: {request.target_database}")

    try:
        await preflight_hyperrag_api_services()
    except Exception as e:
        detailed_error = log_detailed_exception(
            main_logger,
            "文档嵌入启动前预检失败",
            e,
            {
                "file_ids": request.file_ids,
                "rag_system": request.rag_system,
                "target_database": request.target_database,
                "chunk_size": request.chunk_size,
                "chunk_overlap": request.chunk_overlap,
                "runtime_settings": get_runtime_settings_context(),
            },
        )
        user_friendly_error = extract_user_friendly_error(detailed_error)
        await manager.send_progress_update({
            "type": "error",
            "error": user_friendly_error,
            "detailed_error": detailed_error[:500],
            "total_files": total_files,
        })
        raise HTTPException(status_code=400, detail=user_friendly_error)
    
    # 异步处理文件嵌入
    asyncio.create_task(process_files_with_progress(request, total_files, user.get("id")))
    
    return {
        "message": "文档嵌入处理已开始",
        "total_files": total_files,
        "processing": True
    }

async def process_files_with_progress(request: FileEmbedRequest, total_files: int, owner_user_id: str | None = None):
    """异步处理文件嵌入并发送进度更新"""
    try:
        print(f"="*60)
        print(f"开始批量文件嵌入任务")
        print(f"文件总数: {total_files}")
        print(f"配置参数: chunk_size={request.chunk_size}, chunk_overlap={request.chunk_overlap}")
        print(f"="*60)
        
        main_logger.info(f"开始处理 {total_files} 个文件的嵌入任务")
        main_logger.info(f"配置参数: chunk_size={request.chunk_size}, chunk_overlap={request.chunk_overlap}")
        
        successful_files = 0
        failed_files = 0
        
        for i, file_id in enumerate(request.file_ids):
            file_info = None
            database_name = None
            content = None
            try:
                print(f"\n{'='*40}")
                print(f"处理文件 {i + 1}/{total_files}")
                print(f"文件ID: {file_id}")
                print(f"{'='*40}")
                
                # 发送进度更新
                await manager.send_progress_update({
                    "type": "progress",
                    "file_id": file_id,
                    "current": i + 1,
                    "total": total_files,
                    "percentage": ((i + 1) / total_files) * 100,
                    "status": "processing",
                    "message": f"正在处理文件 {i + 1}/{total_files}"
                })
                
                # 更新文件状态为处理中
                print("更新文件状态为处理中...")
                file_manager.update_file_status(file_id, "processing")
                
                # 获取文件信息
                print("正在获取文件信息...")
                main_logger.info(f"获取文件信息: {file_id}")
                file_info = file_manager.get_file_by_id(file_id, owner_user_id=owner_user_id, include_legacy=True)
                if not file_info:
                    error_msg = f"文件不存在: {file_id}"
                    print(f"[ERROR] 错误: {error_msg}")
                    main_logger.error(error_msg)
                    await manager.send_progress_update({
                        "type": "error",
                        "file_id": file_id,
                        "error": "文件不存在",
                        "current": i + 1,
                        "total": total_files
                    })
                    failed_files += 1
                    continue
                
                print(f"[OK] 文件信息获取成功:")
                print(f"  - 文件名: {file_info['filename']}")
                print(f"  - 文件大小: {file_info['file_size']} bytes")
                print(f"  - 上传时间: {file_info['upload_time']}")

                # 使用目标数据库（如果指定）或文件对应的数据库名
                if request.target_database:
                    database_name = file_manager.sanitize_database_name(request.target_database)
                    # 更新文件关联的数据库
                    if request.update_file_database:
                        file_manager.update_file_database(file_id, database_name)
                        print(f"  - 更新文件关联数据库为: {database_name}")
                else:
                    database_name = file_info["database_name"]
                print(f"  - 目标数据库: {database_name}")
                
                main_logger.info(f"开始处理文件: {file_info['filename']} ({file_info['file_size']} bytes)，使用数据库: {database_name}")
                
                # 为每个文件初始化对应的HyperRAG实例
                # 根据请求选择RAG系统
                if request.rag_system == "cograg":
                    if not COGRAG_AVAILABLE:
                        return {"success": False, "message": "Cog-RAG is not available"}
                    print(f"正在初始化 Cog-RAG 实例（{request.rag_system.upper()}系统）...")
                    main_logger.info(f"正在初始化 Cog-RAG 实例，数据库: {database_name}")
                    rag = get_or_create_cograg(database_name)
                    print(f"[OK] Cog-RAG 实例初始化完成")
                    main_logger.info(f"Cog-RAG 实例初始化完成，使用数据库: {database_name}")
                else:
                    if not HYPERRAG_AVAILABLE:
                        return {"success": False, "message": "HyperRAG is not available"}
                    print(f"正在初始化 HyperRAG 实例（{request.rag_system.upper()}系统）...")
                    main_logger.info(f"正在初始化 HyperRAG 实例，数据库: {database_name}")
                    rag = get_or_create_hyperrag(
                        database_name,
                        chunk_size=request.chunk_size,
                        chunk_overlap=request.chunk_overlap,
                    )
                    print(f"[OK] HyperRAG 实例初始化完成")
                    main_logger.info(f"HyperRAG 实例初始化完成，使用数据库: {database_name}")
                
                # 发送详细进度信息
                await manager.send_progress_update({
                    "type": "file_processing",
                    "file_id": file_id,
                    "filename": file_info["filename"],
                    "database_name": database_name,
                    "stage": "reading",
                    "message": f"正在读取文件: {file_info['filename']} (数据库: {database_name}, {request.rag_system.upper()}系统)",
                    "rag_system": request.rag_system  # 添加系统标识
                })
                
                # 读取文件内容
                print("正在读取文件内容...")
                main_logger.info(f"开始读取文件内容: {file_info['filename']}")
                content = await file_manager.read_file_content(file_info["file_path"])
                print(f"[OK] 文件读取完成，内容长度: {len(content)} 字符")
                main_logger.info(f"文件读取完成，内容长度: {len(content)} 字符")
                
                # 显示内容预览
                preview = content[:200] + "..." if len(content) > 200 else content
                print(f"内容预览: {preview}")
                
                # 发送嵌入阶段的进度
                await manager.send_progress_update({
                    "type": "file_processing",
                    "file_id": file_id,
                    "filename": file_info["filename"],
                    "database_name": database_name,
                    "stage": "embedding",
                    "message": f"正在嵌入文档: {file_info['filename']} (数据库: {database_name})"
                })
                
                # 插入到HyperRAG
                print("开始文档嵌入处理...")
                print("这个过程可能需要一些时间，请耐心等待...")
                main_logger.info(f"开始文档嵌入处理: {file_info['filename']}，数据库: {database_name}")
                main_logger.info("正在进行文档分块...")

                # 这里会触发HyperRAG的详细处理过程
                try:
                    await rag.ainsert(content)
                    print("[OK] 文档嵌入完成！")
                    main_logger.info(f"文档嵌入完成: {file_info['filename']}，数据库: {database_name}")
                except Exception as embed_error:
                    error_msg = log_detailed_exception(
                        main_logger,
                        "文档嵌入失败",
                        embed_error,
                        {
                            "file_id": file_id,
                            "filename": file_info.get("filename") if file_info else None,
                            "file_size": file_info.get("file_size") if file_info else None,
                            "file_path": file_info.get("file_path") if file_info else None,
                            "database_name": database_name,
                            "rag_system": request.rag_system,
                            "target_database": request.target_database,
                            "chunk_size": request.chunk_size,
                            "chunk_overlap": request.chunk_overlap,
                            "content_chars": len(content) if content is not None else None,
                            "runtime_settings": get_runtime_settings_context(),
                        },
                    )

                    # 提供更详细的错误信息和建议
                    main_logger.error(f"文档嵌入失败摘要: {error_msg}")

                    # 检查常见的错误类型并提供建议
                    suggestion = extract_user_friendly_error(error_msg)

                    # 抛出包含详细建议的错误
                    raise RuntimeError(f"{error_msg}。建议: {suggestion}") from embed_error
                
                # 更新文件状态为已嵌入
                file_manager.update_file_status(file_id, "embedded")
                
                # 发送成功完成的进度更新
                await manager.send_progress_update({
                    "type": "file_completed",
                    "file_id": file_id,
                    "filename": file_info["filename"],
                    "database_name": database_name,
                    "status": "completed",
                    "message": f"文件嵌入完成: {file_info['filename']} (数据库: {database_name})"
                })
                
                successful_files += 1
                print(f"[OK] 文件 {file_info['filename']} 处理成功！")
                
            except Exception as e:
                # 更新文件状态为错误
                error_msg = f"文件处理失败: {file_id}"
                detailed_error = log_detailed_exception(
                    main_logger,
                    error_msg,
                    e,
                    {
                        "file_id": file_id,
                        "filename": file_info.get("filename") if file_info else None,
                        "file_size": file_info.get("file_size") if file_info else None,
                        "file_path": file_info.get("file_path") if file_info else None,
                        "database_name": database_name,
                        "rag_system": request.rag_system,
                        "target_database": request.target_database,
                        "chunk_size": request.chunk_size,
                        "chunk_overlap": request.chunk_overlap,
                        "content_chars": len(content) if content is not None else None,
                        "runtime_settings": get_runtime_settings_context(),
                    },
                )
                print(f"[ERROR] {error_msg}")
                print(f"[ERROR] 详细错误: {detailed_error}")
                main_logger.error(f"{error_msg}, 详细错误摘要: {detailed_error}")

                # 提取有用的错误信息给用户
                user_friendly_error = extract_user_friendly_error(detailed_error)
                file_manager.update_file_status(file_id, "error", user_friendly_error)

                # 发送错误进度更新，使用用户友好的错误信息
                await manager.send_progress_update({
                    "type": "file_error",
                    "file_id": file_id,
                    "filename": file_info.get("filename", "未知文件"),
                    "error": user_friendly_error,
                    "detailed_error": detailed_error[:200],  # 限制详细错误长度
                    "current": i + 1,
                    "total": total_files
                })
                
                failed_files += 1
        
        # 发送整体完成的进度更新
        print(f"\n{'='*60}")
        print(f"批量文档处理完成！")
        print(f"总文件数: {total_files}")
        print(f"成功处理: {successful_files}")
        print(f"处理失败: {failed_files}")
        print(f"成功率: {(successful_files/total_files)*100:.1f}%")
        print(f"{'='*60}")
        
        main_logger.info(f"所有文档处理完成！总计: {total_files} 个文件，成功: {successful_files}，失败: {failed_files}")
        await manager.send_progress_update({
            "type": "all_completed",
            "message": f"所有文档处理完成 (成功: {successful_files}, 失败: {failed_files})",
            "total_files": total_files,
            "successful_files": successful_files,
            "failed_files": failed_files
        })
        
    except Exception as e:
        # 发送整体错误信息
        detailed_error = log_detailed_exception(
            main_logger,
            "批量嵌入失败",
            e,
            {
                "file_ids": request.file_ids,
                "total_files": total_files,
                "rag_system": request.rag_system,
                "target_database": request.target_database,
                "chunk_size": request.chunk_size,
                "chunk_overlap": request.chunk_overlap,
                "runtime_settings": get_runtime_settings_context(),
            },
        )
        error_msg = f"批量嵌入失败: {detailed_error}"
        print(f"[ERROR] {error_msg}")
        main_logger.error(error_msg)
        await manager.send_progress_update({
            "type": "error",
            "error": error_msg
        })
