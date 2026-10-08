"""CLI for fully automatic offline post-hoc entity normalization."""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "web-ui" / "backend"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from hyperche.normalization import posthoc_cache as core

LOGGER = logging.getLogger("hyper_rag.posthoc_normalization.cli")


def _paths() -> tuple[list[Path], list[Path]]:
    config_dir = REPO_ROOT / "configs" / "normalization"
    registry_names = (
        "alias_registry.yaml",
        "canonical_equivalence_map.yaml",
        "common_chem.yaml",
        "flow_battery.yaml",
        "generic_terms.yaml",
        "pfas.yaml",
    )
    registry = [config_dir / name for name in registry_names if (config_dir / name).exists()]
    negative = [
        config_dir / "negative_pairs.yaml",
        config_dir / "high_risk_rules.yaml",
    ]
    return registry, [path for path in negative if path.exists()]


def _keys(kind: str) -> list[str]:
    return core._api_keys(kind) or core._api_keys("EMB" if kind == "LLM" else "LLM")


def _llm_endpoints(value: str | None) -> list[core.LLMEndpoint]:
    """Parse ``base_url|key`` entries separated by semicolons/newlines."""
    endpoints: list[core.LLMEndpoint] = []
    for item in re.split(r"[;\r\n]+", value or ""):
        item = item.strip()
        if not item or "|" not in item:
            continue
        base_url, api_key = item.split("|", 1)
        base_url, api_key = base_url.strip(), api_key.strip()
        if base_url and api_key:
            endpoints.append(core.LLMEndpoint(base_url=base_url, api_key=api_key))
    return endpoints


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-cache", type=Path, required=True)
    parser.add_argument("--target-cache", type=Path, required=True)
    parser.add_argument("--stage", choices=("all", "candidates", "judge", "rewrite", "embed", "validate"), default="all")
    parser.add_argument("--resume", dest="resume", action="store_true", default=True)
    parser.add_argument("--no-resume", dest="resume", action="store_false", help="Refuse to reuse an existing .work directory")
    parser.add_argument("--merge-confidence", type=float, default=0.90)
    parser.add_argument("--candidate-top-k", type=int, default=8)
    parser.add_argument(
        "--llm-max-async",
        type=int,
        default=5,
        help="Maximum concurrent LLM judgements (default: 5 to avoid provider throttling)",
    )
    parser.add_argument(
        "--llm-attempts-per-pair",
        type=int,
        default=2,
        help="API attempts for one candidate in a single resumable pass (default: 2)",
    )
    parser.add_argument("--embedding-max-async", type=int, default=15)
    parser.add_argument("--embedding-batch-num", type=int, default=16)
    parser.add_argument("--llm-timeout", type=float, default=3600.0)
    parser.add_argument("--embedding-timeout", type=float, default=600.0)
    parser.add_argument(
        "--llm-model",
        default=os.getenv("LLM_MODEL", "Pro/moonshotai/Kimi-K2.6"),
        help="LLM used for entity-pair judgement (default: Pro/moonshotai/Kimi-K2.6)",
    )
    parser.add_argument("--llm-base-url", default=os.getenv("LLM_BASE_URL", "https://api.siliconflow.cn/v1"))
    parser.add_argument(
        "--llm-endpoints",
        default=os.getenv("LLM_ENDPOINTS", ""),
        help="Optional semicolon-separated base_url|api_key entries for multi-provider judge runs",
    )
    parser.add_argument("--embedding-model", default=os.getenv("EMB_MODEL", "Qwen/Qwen3-Embedding-4B"))
    parser.add_argument("--embedding-base-url", default=os.getenv("EMB_BASE_URL", "https://api.siliconflow.cn/v1"))
    parser.add_argument("--embedding-dim", type=int, default=int(os.getenv("EMB_DIM", "2560")))
    parser.add_argument("--expected-docs", type=int, default=60)
    parser.add_argument("--expected-chunks", type=int, default=1328)
    return parser


def _configure_logging(work: Path) -> None:
    work.mkdir(parents=True, exist_ok=True)
    LOGGER_ROOT = logging.getLogger()
    LOGGER_ROOT.setLevel(logging.INFO)
    for handler in list(LOGGER_ROOT.handlers):
        LOGGER_ROOT.removeHandler(handler)
        handler.close()
    formatter = logging.Formatter("%(asctime)s %(levelname)s:%(name)s:%(message)s")
    file_handler = logging.FileHandler(work / "normalization_run.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    LOGGER_ROOT.addHandler(file_handler)
    LOGGER_ROOT.addHandler(console_handler)


def _merge_api_stats(work: Path, **updates: Any) -> None:
    path = work / "normalization_state.json"
    state = core._load_json_dict(path)
    stats = dict(state.get("api_statistics") or {})
    for key, value in updates.items():
        if isinstance(value, dict):
            stats[key] = value
        else:
            stats[key] = value
    state["api_statistics"] = stats
    core.write_json(path, state)


def _stage_done(work: Path, stage: str, resume: bool) -> bool:
    if not resume:
        return False
    state = core._load_json_dict(work / "normalization_state.json")
    return (state.get("stages") or {}).get(stage, {}).get("status") == "completed"


def _mark(work: Path, stage: str, status: str, details: dict[str, Any] | None = None) -> None:
    core.update_state(work, stage, status, details)
    LOGGER.info("stage=%s status=%s", stage, status)


def _candidate_stage(source: Path, work: Path, args: argparse.Namespace, registry: list[Path], negative: list[Path]) -> dict[str, Any]:
    output = work / "normalization_candidates.jsonl"
    state_path = work / "normalization_state.json"
    state = core._load_json_dict(state_path)
    candidate_state = (state.get("stages") or {}).get("candidates") or {}
    candidate_details = candidate_state.get("details") or {}
    can_resume = (
        args.resume
        and candidate_state.get("status") == "completed"
        and output.exists()
        and candidate_details.get("candidate_version") == core.CANDIDATE_VERSION
        and int(candidate_details.get("candidate_top_k", -1)) == args.candidate_top_k
    )
    if can_resume:
        rows = core.read_jsonl(output)
        LOGGER.info("resume candidates: %s rows", len(rows))
        return {
            "candidate_pairs": len(rows),
            "candidate_top_k": args.candidate_top_k,
            "candidate_version": core.CANDIDATE_VERSION,
            "resume": True,
        }

    if args.resume and candidate_state:
        LOGGER.info(
            "candidate configuration changed; rebuilding candidates "
            "(stored_version=%s current_version=%s stored_top_k=%s current_top_k=%s)",
            candidate_details.get("candidate_version"),
            core.CANDIDATE_VERSION,
            candidate_details.get("candidate_top_k"),
            args.candidate_top_k,
        )
        stages = state.setdefault("stages", {})
        for downstream_stage in ("judge", "rewrite", "embed", "validate", "publish"):
            stages.pop(downstream_stage, None)
        core.write_json(state_path, state)

    _mark(work, "candidates", "running")
    rows = core.generate_candidates(source, top_k=args.candidate_top_k, registry_paths=registry, negative_paths=negative)
    core.write_jsonl(output, rows)
    details = {
        "candidate_pairs": len(rows),
        "candidate_top_k": args.candidate_top_k,
        "candidate_version": core.CANDIDATE_VERSION,
    }
    _mark(work, "candidates", "completed", details)
    return details


async def _judge_stage(work: Path, args: argparse.Namespace) -> dict[str, Any]:
    _mark(work, "judge", "running")
    endpoints = _llm_endpoints(getattr(args, "llm_endpoints", ""))
    keys = _keys("LLM")
    if endpoints:
        keys = [endpoint.api_key for endpoint in endpoints]
    if not keys and not endpoints:
        raise RuntimeError("No LLM keys or endpoints. Set LLM_API_KEY(S) or LLM_ENDPOINTS; secrets are never written to output.")
    result = await core.judge_candidates(
        work,
        llm_model=args.llm_model,
        llm_base_url=args.llm_base_url,
        llm_keys=keys,
        llm_endpoints=endpoints or None,
        max_async=args.llm_max_async,
        timeout=args.llm_timeout,
        attempts_per_pair=getattr(args, "llm_attempts_per_pair", 2),
        resume=args.resume,
    )
    _merge_api_stats(work, llm=result)
    _mark(work, "judge", "completed", result)
    return result


async def _rewrite_stage(source: Path, work: Path, args: argparse.Namespace, registry: list[Path], negative: list[Path]) -> dict[str, Any]:
    if _stage_done(work, "rewrite", args.resume) and (work / "canonical_entity_map.json").exists() and (work / core.GRAPH_FILE).exists():
        result = core._load_json_dict(work / "normalization_rewrite_summary.json")
        LOGGER.info("resume rewrite: %s canonical vertices", result.get("canonical_vertices"))
        return result
    _mark(work, "rewrite", "running")
    endpoints = _llm_endpoints(getattr(args, "llm_endpoints", ""))
    keys = _keys("LLM")
    if endpoints:
        keys = [endpoint.api_key for endpoint in endpoints]
    canonical_map = await core.build_canonical_map(
        source,
        work,
        merge_confidence=args.merge_confidence,
        registry_paths=registry,
        negative_paths=negative,
        llm_model=args.llm_model,
        llm_base_url=args.llm_base_url,
        llm_keys=keys,
        llm_endpoints=endpoints or None,
        max_async=args.llm_max_async,
        llm_timeout=args.llm_timeout,
        resume=args.resume,
    )
    cluster_audit_stats = (canonical_map.get("metadata") or {}).get("cluster_audit_api_statistics") or {}
    if cluster_audit_stats:
        _merge_api_stats(work, cluster_audit=cluster_audit_stats)
    rewrite = core.rewrite_graph(source, work, canonical_map)
    details = {"canonical_entities": len(canonical_map.get("clusters") or []), **rewrite}
    _mark(work, "rewrite", "completed", details)
    return details


async def _embed_stage(work: Path, args: argparse.Namespace) -> dict[str, Any]:
    if _stage_done(work, "embed", args.resume) and (work / "vdb_entities.json").exists() and (work / "vdb_relationships.json").exists():
        LOGGER.info("resume embed: vector files already completed")
        return {"resume": True}
    _mark(work, "embed", "running")
    keys = _keys("EMB")
    if not keys:
        raise RuntimeError("No embedding keys. Set EMB_API_KEY or EMB_API_KEYS; keys are never written to output.")
    result = await core.rebuild_vectors(
        work,
        embedding_model=args.embedding_model,
        embedding_base_url=args.embedding_base_url,
        embedding_keys=keys,
        embedding_dim=args.embedding_dim,
        max_async=args.embedding_max_async,
        batch_num=args.embedding_batch_num,
        timeout=args.embedding_timeout,
        resume=args.resume,
    )
    _merge_api_stats(work, embedding=result.get("api_statistics", {}))
    _mark(work, "embed", "completed", result)
    return result


def _validate_stage(source: Path, work: Path, args: argparse.Namespace, negative: list[Path]) -> dict[str, Any]:
    if _stage_done(work, "validate", args.resume) and (work / "normalization_summary.json").exists():
        return core._load_json_dict(work / "normalization_summary.json")
    _mark(work, "validate", "running")
    result = core.validate_cache(
        source,
        work,
        merge_confidence=args.merge_confidence,
        negative_paths=negative,
        expected_docs=args.expected_docs,
        expected_chunks=args.expected_chunks,
    )
    _mark(work, "validate", "completed", result)
    return result


async def _run(args: argparse.Namespace) -> None:
    source = args.source_cache.resolve()
    target = args.target_cache.resolve()
    work, _ = core.prepare_work(source, target, resume=args.resume)
    _configure_logging(work)
    registry, negative = _paths()
    LOGGER.info("source=%s", source)
    LOGGER.info("target=%s", target)
    LOGGER.info("work=%s", work)
    LOGGER.info("model llm=%s embedding=%s", args.llm_model, args.embedding_model)
    LOGGER.info(
        "judge concurrency=%s attempts_per_pair=%s timeout=%ss",
        args.llm_max_async,
        getattr(args, "llm_attempts_per_pair", 2),
        args.llm_timeout,
    )
    LOGGER.info("stages are resumable; source cache is read-only")

    stage = args.stage
    run_all = stage == "all"
    if run_all or stage == "candidates":
        _candidate_stage(source, work, args, registry, negative)
    if stage == "candidates":
        return
    if run_all or stage == "judge":
        await _judge_stage(work, args)
    if stage == "judge":
        return
    if run_all or stage == "rewrite":
        await _rewrite_stage(source, work, args, registry, negative)
    if stage == "rewrite":
        return
    if run_all or stage == "embed":
        await _embed_stage(work, args)
    if stage == "embed":
        return
    if run_all or stage == "validate":
        result = _validate_stage(source, work, args, negative)
        core.update_run_config(source, work, merge_confidence=args.merge_confidence, llm_model=args.llm_model, embedding_model=args.embedding_model, candidate_top_k=args.candidate_top_k, source_hashes=core.source_checksums(source))
        if not result.get("validation_passed", False):
            raise RuntimeError("Validation did not pass; target was not published")
        _mark(work, "publish", "running")
        # Windows cannot rename a directory while its log file is open.
        root_logger = logging.getLogger()
        for handler in list(root_logger.handlers):
            if isinstance(handler, logging.FileHandler):
                root_logger.removeHandler(handler)
                handler.close()
        try:
            core.publish_work(work, target)
        except Exception:
            _configure_logging(work)
            raise
        _configure_logging(target)
        core.update_state(target, "publish", "completed", {"target_cache": str(target)})
        LOGGER.info("published target cache: %s", target)


def main() -> None:
    args = _parser().parse_args()
    try:
        with core.TargetCacheLock(args.target_cache.resolve()):
            asyncio.run(_run(args))
    except Exception:
        logging.exception("post-hoc normalization failed")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
