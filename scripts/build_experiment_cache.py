"""Build a Hyper-ChE experiment cache for one configured mode."""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from hyperrag import HyperRAG
from hyperrag.experiment import resolve_experiment_mode, write_run_config
from hyperrag.llm import openai_complete_if_cache, openai_embedding
from hyperrag.utils import EmbeddingFunc, logger


def text_hash(text: str) -> str:
    return hashlib.md5((text or "").encode("utf-8")).hexdigest()


def safe_id(value: str) -> str:
    text = re.sub(r"\s+", "_", str(value or "").strip())
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("._-")
    return text or "doc"


def extract_numeric_index(path: Path, fallback: int) -> int:
    match = re.search(r"(\d+)", path.stem)
    return int(match.group(1)) if match else fallback


def infer_title(text: str, file_path: Path) -> str:
    for line in (text or "").splitlines()[:40]:
        stripped = line.strip()
        if stripped.startswith("#"):
            stripped = stripped.lstrip("#").strip()
        if stripped and not stripped.lower().startswith("source file:"):
            return stripped[:240]
    return file_path.stem


def iter_text_files(path: Path) -> Iterable[Path]:
    for suffix in ("*.md", "*.markdown", "*.txt"):
        yield from path.rglob(suffix)


def read_input_documents(
    path: Path,
    *,
    doc_id_prefix: str,
    doc_start: int | None = None,
    doc_end: int | None = None,
) -> list[dict]:
    if path.is_file():
        text = path.read_text(encoding="utf-8-sig")
        doc_number = doc_start or extract_numeric_index(path, 1)
        doc_id = f"{safe_id(doc_id_prefix)}_{doc_number:03d}"
        return [
            {
                "doc_id": doc_id,
                "source_doc_id": doc_id,
                "source_file": path.name,
                "source_path": str(path.resolve()),
                "title": infer_title(text, path),
                "text_hash": text_hash(text),
                "content": text,
            }
        ]
    if not path.is_dir():
        raise FileNotFoundError(f"Input path not found: {path}")
    documents = []
    files = sorted(iter_text_files(path))
    for ordinal, file_path in enumerate(files, start=1):
        doc_number = extract_numeric_index(file_path, ordinal)
        if doc_start is not None and doc_number < doc_start:
            continue
        if doc_end is not None and doc_number > doc_end:
            continue
        text = file_path.read_text(encoding="utf-8-sig")
        content = f"# Source File: {file_path.name}\n\n{text}"
        doc_id = f"{safe_id(doc_id_prefix)}_{doc_number:03d}"
        documents.append(
            {
                "doc_id": doc_id,
                "source_doc_id": doc_id,
                "source_file": file_path.name,
                "source_path": str(file_path.resolve()),
                "title": infer_title(text, file_path),
                "text_hash": text_hash(text),
                "content": content,
            }
        )
    if not documents:
        raise FileNotFoundError(f"No .md/.txt files found under: {path}")
    return documents


def append_jsonl(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def write_manifest(path: Path, documents: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for doc in documents:
            payload = {
                "doc_id": doc["doc_id"],
                "source_doc_id": doc["source_doc_id"],
                "source_file": doc.get("source_file", ""),
                "source_path": doc.get("source_path", ""),
                "title": doc.get("title", ""),
                "text_hash": doc.get("text_hash", ""),
                "chars": len(doc.get("content", "")),
            }
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def load_completed_doc_ids(cache_dir: Path, progress_path: Path) -> set[str]:
    completed = set()
    full_docs_path = cache_dir / "kv_store_full_docs.json"
    chunk_docs = set()
    if full_docs_path.exists():
        try:
            data = json.loads(full_docs_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                completed.update(str(key) for key in data.keys())
                for value in data.values():
                    if isinstance(value, dict) and value.get("doc_id"):
                        completed.add(str(value["doc_id"]))
        except Exception as exc:
            print(f"[BuildExperiment] warning: failed to read existing full docs: {exc}", flush=True)
    text_chunks_path = cache_dir / "kv_store_text_chunks.json"
    if text_chunks_path.exists():
        try:
            data = json.loads(text_chunks_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for value in data.values():
                    if isinstance(value, dict):
                        doc_id = value.get("source_doc_id") or value.get("doc_id")
                        if doc_id:
                            chunk_docs.add(str(doc_id))
        except Exception as exc:
            print(f"[BuildExperiment] warning: failed to read existing text chunks: {exc}", flush=True)
    completed.update(chunk_docs)

    progress_completed = set()
    if progress_path.exists():
        for line in progress_path.read_text(encoding="utf-8").splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if item.get("status") == "success" and item.get("doc_id"):
                progress_completed.add(str(item["doc_id"]))
    stale_progress = sorted(progress_completed - completed)
    if stale_progress:
        print(
            "[BuildExperiment] warning: ignoring progress-only completed docs not present in storage: "
            f"{stale_progress[:10]}{'...' if len(stale_progress) > 10 else ''}",
            flush=True,
        )
    return completed


def env_required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def split_key_pool(value: str) -> list[str]:
    return [part.strip() for part in re.split(r"[;,\r\n]+", value or "") if part.strip()]


def _split_provider_keys(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(part).strip() for part in value if str(part).strip()]
    return split_key_pool(str(value or ""))


def load_llm_provider_entries(*, default_model: str, default_base_url: str | None, default_api_keys: list[str]) -> list[dict]:
    """Load optional multi-provider LLM config from LLM_PROVIDER_CONFIG.

    The value is a JSON array/object. Each provider can use either snake_case or
    camelCase fields: name, base_url/baseUrl, model/modelName, api_keys/apiKeys/apiKey.
    """
    raw = os.getenv("LLM_PROVIDER_CONFIG")
    if not raw:
        return [
            {
                "provider": "default",
                "model": default_model,
                "base_url": default_base_url,
                "api_key": key,
                "key_index": index,
                "key_total": len(default_api_keys),
            }
            for index, key in enumerate(default_api_keys)
        ]

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"LLM_PROVIDER_CONFIG must be valid JSON: {exc}") from exc
    providers = data if isinstance(data, list) else data.get("providers", [])
    if not isinstance(providers, list):
        raise RuntimeError("LLM_PROVIDER_CONFIG must be a provider array or an object with providers=[...].")

    entries = []
    for provider_index, provider in enumerate(providers):
        if not isinstance(provider, dict) or provider.get("enabled", True) is False:
            continue
        name = str(provider.get("name") or f"provider_{provider_index + 1}")
        base_url = provider.get("base_url", provider.get("baseUrl", default_base_url))
        model = str(provider.get("model") or provider.get("modelName") or default_model)
        keys = _split_provider_keys(
            provider.get("api_keys", provider.get("apiKeys", provider.get("apiKey", "")))
        )
        for key_index, key in enumerate(keys):
            entries.append(
                {
                    "provider": name,
                    "model": model,
                    "base_url": base_url,
                    "api_key": key,
                    "key_index": key_index,
                    "key_total": len(keys),
                }
            )
    if not entries:
        raise RuntimeError("LLM_PROVIDER_CONFIG did not contain any enabled provider keys.")
    return entries


class AsyncKeyPool:
    def __init__(self, items: list[Any], *, name: str):
        if not items:
            raise RuntimeError(f"{name} key pool is empty")
        self.items = items
        self.name = name
        self._index = 0
        self._lock = asyncio.Lock()

    async def next(self) -> tuple[int, Any]:
        async with self._lock:
            idx = self._index % len(self.items)
            self._index += 1
            return idx, self.items[idx]


def positive_int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer, got {value!r}") from exc


def build_llm_func(*, model: str, base_url: str | None, api_keys: list[str], timeout: float):
    entries = load_llm_provider_entries(default_model=model, default_base_url=base_url, default_api_keys=api_keys)
    pool = AsyncKeyPool(entries, name="LLM provider pool")
    request_counter = 0

    def log_pool(message: str) -> None:
        print(message, flush=True)
        logger.info(message)

    async def llm_func(prompt: str, system_prompt=None, history_messages=None, **kwargs):
        nonlocal request_counter
        request_counter += 1
        request_id = request_counter
        attempts = max(1, min(len(entries), positive_int_env("LLM_KEY_ATTEMPTS", len(entries))))
        last_exc = None
        request_start = time.perf_counter()
        log_pool(
            f"[LLMPool] REQUEST START id={request_id} model={model} "
            f"prompt_chars={len(prompt or '')} pool_size={len(entries)} "
            f"max_attempts={attempts} timeout={timeout:.1f}s"
        )
        for attempt in range(attempts):
            entry_index, entry = await pool.next()
            attempt_start = time.perf_counter()
            provider = entry.get("provider") or "unknown"
            key_slot = entry.get("key_index", 0) + 1
            key_total = entry.get("key_total", "?")
            log_pool(
                f"[LLMPool] ATTEMPT START id={request_id} attempt={attempt + 1}/{attempts} "
                f"provider={provider} entry={entry_index + 1}/{len(entries)} "
                f"key_slot={key_slot}/{key_total} model={entry['model']}"
            )
            try:
                response = await openai_complete_if_cache(
                    entry["model"],
                    prompt,
                    system_prompt=system_prompt,
                    history_messages=history_messages or [],
                    base_url=entry.get("base_url"),
                    api_key=entry["api_key"],
                    timeout=timeout,
                    **kwargs,
                )
                log_pool(
                    f"[LLMPool] ATTEMPT DONE id={request_id} attempt={attempt + 1}/{attempts} "
                    f"provider={provider} entry={entry_index + 1}/{len(entries)} "
                    f"key_slot={key_slot}/{key_total} elapsed={time.perf_counter() - attempt_start:.2f}s "
                    f"response_chars={len(response) if isinstance(response, str) else 0}"
                )
                log_pool(
                    f"[LLMPool] REQUEST DONE id={request_id} "
                    f"elapsed={time.perf_counter() - request_start:.2f}s"
                )
                return response
            except Exception as exc:
                last_exc = exc
                log_pool(
                    f"[LLMPool] ATTEMPT FAILED id={request_id} attempt={attempt + 1}/{attempts} "
                    f"provider={provider} entry={entry_index + 1}/{len(entries)} "
                    f"key_slot={key_slot}/{key_total} elapsed={time.perf_counter() - attempt_start:.2f}s "
                    f"error={type(exc).__name__}: {exc}"
                )
        log_pool(
            f"[LLMPool] REQUEST FAILED id={request_id} "
            f"elapsed={time.perf_counter() - request_start:.2f}s attempts={attempts} "
            f"error={type(last_exc).__name__}: {last_exc}"
        )
        raise last_exc

    return llm_func


def build_embedding_func(*, model: str, base_url: str | None, api_keys: list[str], dim: int, timeout: float) -> EmbeddingFunc:
    pool = AsyncKeyPool(api_keys, name="EMB_API_KEY")

    async def embedding_func(texts: list[str]):
        attempts = max(1, min(len(api_keys), positive_int_env("EMB_KEY_ATTEMPTS", len(api_keys))))
        last_exc = None
        for attempt in range(attempts):
            key_index, api_key = await pool.next()
            try:
                return await openai_embedding(
                    texts,
                    model=model,
                    base_url=base_url,
                    api_key=api_key,
                    timeout=timeout,
                )
            except Exception as exc:
                last_exc = exc
                print(
                    f"[BuildExperiment] embedding call failed with key={key_index + 1}/{len(api_keys)} "
                    f"attempt={attempt + 1}/{attempts}: {type(exc).__name__}: {exc}",
                    flush=True,
                )
        raise last_exc

    return EmbeddingFunc(embedding_dim=dim, max_token_size=8192, func=embedding_func)


async def amain() -> None:
    parser = argparse.ArgumentParser(description="Build a Hyper-ChE experiment cache.")
    parser.add_argument("--input", required=True, type=Path, help="Input markdown/text file or directory.")
    parser.add_argument("--cache-dir", required=True, type=Path, help="Output HyperRAG cache directory.")
    parser.add_argument("--mode", default="hyper_final", help="Experiment mode from configs/experiments/modes.yaml.")
    parser.add_argument("--domain", default="flow_battery", help="Chemistry domain for chemistry prompt_profile.")
    parser.add_argument("--chunk-size", type=int, default=positive_int_env("CHUNK_SIZE", 1000))
    parser.add_argument("--chunk-overlap", type=int, default=None)
    parser.add_argument("--max-entities-per-chunk", type=int, default=positive_int_env("MAX_ENTITIES_PER_CHUNK", 40))
    parser.add_argument("--doc-id-prefix", default="DOC", help="Stable document ID prefix, e.g. RFB.")
    parser.add_argument("--doc-start", type=int, default=None, help="Only include files whose numeric index is >= this value.")
    parser.add_argument("--doc-end", type=int, default=None, help="Only include files whose numeric index is <= this value.")
    parser.add_argument("--resume", action="store_true", help="Skip documents already completed in this cache.")
    parser.add_argument("--manifest", type=Path, default=None, help="Optional corpus_manifest.jsonl output path.")
    parser.add_argument("--llm-timeout", type=float, default=float(os.getenv("LLM_TIMEOUT", "600")))
    parser.add_argument("--embedding-timeout", type=float, default=float(os.getenv("EMB_TIMEOUT", "120")))
    parser.add_argument("--llm-max-async", type=int, default=positive_int_env("LLM_MAX_ASYNC", 4))
    parser.add_argument("--embedding-max-async", type=int, default=positive_int_env("EMB_MAX_ASYNC", 8))
    parser.add_argument("--embedding-batch-num", type=int, default=positive_int_env("EMB_BATCH_NUM", 8))
    parser.add_argument("--entity-extract-max-gleaning", type=int, default=positive_int_env("ENTITY_EXTRACT_MAX_GLEANING", 0))
    parser.add_argument("--disable-one-pass-extraction", action="store_true", help="Use legacy JSON entity-then-relationship extraction.")
    args = parser.parse_args()

    llm_api_keys = split_key_pool(env_required("LLM_API_KEY"))
    llm_base_url = os.getenv("LLM_BASE_URL")
    llm_model = env_required("LLM_MODEL")
    emb_api_keys = split_key_pool(env_required("EMB_API_KEY"))
    emb_base_url = os.getenv("EMB_BASE_URL")
    emb_model = env_required("EMB_MODEL")
    emb_dim = positive_int_env("EMB_DIM", 2560)

    resolved = resolve_experiment_mode(args.mode, domain=args.domain)
    cache_dir = args.cache_dir
    cache_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = args.manifest or (cache_dir / "corpus_manifest.jsonl")
    progress_path = cache_dir / "build_progress.jsonl"
    extra = {
        "input": str(args.input.resolve()),
        "doc_id_prefix": args.doc_id_prefix,
        "doc_start": args.doc_start,
        "doc_end": args.doc_end,
        "resume": args.resume,
        "corpus_manifest_path": str(manifest_path.resolve()),
        "build_progress_path": str(progress_path.resolve()),
        "index_profile": resolved.get("index_profile"),
        "llm": {"model": llm_model, "base_url": llm_base_url, "api_key_count": len(llm_api_keys)},
        "embedding": {
            "model": emb_model,
            "base_url": emb_base_url,
            "api_key_count": len(emb_api_keys),
            "embedding_dim": emb_dim,
        },
        "chunk_size": args.chunk_size,
        "chunk_overlap": args.chunk_overlap,
        "max_entities_per_chunk": args.max_entities_per_chunk,
        "entity_extract_max_gleaning": args.entity_extract_max_gleaning,
        "enable_one_pass_extraction": not args.disable_one_pass_extraction,
    }
    run_config_path = write_run_config(cache_dir, resolved, extra=extra)
    print(f"[BuildExperiment] run_config written: {run_config_path}", flush=True)
    print(f"[BuildExperiment] resolved mode: {resolved}", flush=True)
    print(f"[BuildExperiment] key pools: llm={len(llm_api_keys)}, embedding={len(emb_api_keys)}", flush=True)

    documents = read_input_documents(
        args.input,
        doc_id_prefix=args.doc_id_prefix,
        doc_start=args.doc_start,
        doc_end=args.doc_end,
    )
    write_manifest(manifest_path, documents)
    print(
        f"[BuildExperiment] loaded input docs={len(documents)} "
        f"chars={sum(len(doc.get('content', '')) for doc in documents)}",
        flush=True,
    )
    print(f"[BuildExperiment] corpus_manifest written: {manifest_path}", flush=True)

    rag_kwargs = {
        "working_dir": str(cache_dir),
        "domain": resolved["effective_domain"],
        "experiment_mode": resolved["experiment_mode"],
        "query_mode": resolved["query_mode"],
        "prompt_profile": resolved["prompt_profile"],
        "enable_one_pass_extraction": not args.disable_one_pass_extraction,
        "enable_entity_normalization": resolved["enable_entity_normalization"],
        "enable_measurement_instances": resolved["enable_measurement_instances"],
        "enable_efu_repair": resolved["enable_efu_repair"],
        "enable_hybrid_rerank": resolved["enable_hybrid_rerank"],
        "index_profile": resolved.get("index_profile", "dual_concat"),
        "corpus_manifest_path": str(manifest_path.resolve()),
        "llm_model_func": build_llm_func(
            model=llm_model,
            base_url=llm_base_url,
            api_keys=llm_api_keys,
            timeout=args.llm_timeout,
        ),
        "llm_model_max_async": args.llm_max_async,
        "embedding_func": build_embedding_func(
            model=emb_model,
            base_url=emb_base_url,
            api_keys=emb_api_keys,
            dim=emb_dim,
            timeout=args.embedding_timeout,
        ),
        "embedding_func_max_async": args.embedding_max_async,
        "embedding_batch_num": args.embedding_batch_num,
        "max_entities_per_chunk": args.max_entities_per_chunk,
        "entity_extract_max_gleaning": args.entity_extract_max_gleaning,
    }
    if args.chunk_size is not None:
        rag_kwargs["chunk_token_size"] = args.chunk_size
    if args.chunk_overlap is not None:
        rag_kwargs["chunk_overlap_token_size"] = args.chunk_overlap

    rag = HyperRAG(**rag_kwargs)
    run_config_path = write_run_config(cache_dir, resolved, extra=extra)
    print(f"[BuildExperiment] run_config refreshed after HyperRAG init: {run_config_path}", flush=True)
    completed_doc_ids = load_completed_doc_ids(cache_dir, progress_path) if args.resume else set()
    if completed_doc_ids:
        print(f"[BuildExperiment] resume enabled; completed docs detected={len(completed_doc_ids)}", flush=True)

    total = len(documents)
    success_count = 0
    error_count = 0
    failed_doc_ids: list[str] = []
    for index, doc in enumerate(documents, start=1):
        doc_id = str(doc["doc_id"])
        if args.resume and doc_id in completed_doc_ids:
            print(f"[BuildExperiment] skip completed {index}/{total}: {doc_id} {doc.get('source_file', '')}", flush=True)
            append_jsonl(
                progress_path,
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "status": "skipped",
                    "doc_id": doc_id,
                    "source_file": doc.get("source_file", ""),
                    "reason": "resume_completed",
                },
            )
            continue
        print(f"[BuildExperiment] start {index}/{total}: {doc_id} {doc.get('source_file', '')}", flush=True)
        append_jsonl(
            progress_path,
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "status": "start",
                "doc_id": doc_id,
                "source_file": doc.get("source_file", ""),
                "text_hash": doc.get("text_hash", ""),
            },
        )
        try:
            await rag.ainsert(doc)
            append_jsonl(
                progress_path,
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "status": "success",
                    "doc_id": doc_id,
                    "source_file": doc.get("source_file", ""),
                    "text_hash": doc.get("text_hash", ""),
                },
            )
            print(f"[BuildExperiment] success {index}/{total}: {doc_id}", flush=True)
            success_count += 1
        except Exception as exc:
            error_count += 1
            failed_doc_ids.append(doc_id)
            append_jsonl(
                progress_path,
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "status": "error",
                    "doc_id": doc_id,
                    "source_file": doc.get("source_file", ""),
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
            )
            print(f"[BuildExperiment] error {index}/{total}: {doc_id}: {type(exc).__name__}: {exc}", flush=True)
            print(
                f"[BuildExperiment] continuing after failed document {doc_id}; "
                "it remains incomplete and will be retried by the next --resume run",
                flush=True,
            )
            continue
    print(
        f"[BuildExperiment] cache build pass complete: {cache_dir.resolve()} "
        f"success={success_count} errors={error_count} failed_docs={failed_doc_ids}",
        flush=True,
    )


def main() -> None:
    asyncio.run(amain())


if __name__ == "__main__":
    main()
