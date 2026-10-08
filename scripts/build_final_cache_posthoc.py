"""Create the agreed final cache without repeating extraction or judgement."""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "web-ui" / "backend"))

from hyperche.normalization import posthoc_cache as core
from hyperche.normalization import final_cache as final


def close_file_handlers() -> None:
    for handler in list(logging.getLogger().handlers):
        if isinstance(handler, logging.FileHandler):
            logging.getLogger().removeHandler(handler)
            handler.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-cache", type=Path, required=True)
    parser.add_argument("--normalized-cache", type=Path, required=True)
    parser.add_argument("--target-cache", type=Path, required=True)
    parser.add_argument("--chunk-map", type=Path, required=True)
    parser.add_argument("--embedding-endpoints-file", type=Path)
    parser.add_argument("--stage", choices=("all", "prepare", "embed", "validate"), default="all")
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--timeout", type=float, default=120)
    args = parser.parse_args()
    if args.concurrency < 1 or args.batch_size < 1:
        parser.error("concurrency and batch size must be positive")
    source, normalized, target = args.source_cache.resolve(), args.normalized_cache.resolve(), args.target_cache.resolve()
    if target in (source, normalized):
        parser.error("choose a new target distinct from both input caches")
    with core.TargetCacheLock(target):
        work, state = core.prepare_work(source, target, resume=True)
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", force=True,
                            handlers=[logging.FileHandler(work / "final_build.log", encoding="utf-8"), logging.StreamHandler()])
        # Provider requests contain credentials; retain status in our own logger.
        logging.getLogger("httpx").setLevel(logging.WARNING)
        phase = "prepare"
        try:
            input_signature = {"version": final.VERSION,
                               "normalized_graph": core.file_sha256(normalized / core.GRAPH_FILE),
                               "canonical_map": core.file_sha256(normalized / "canonical_entity_map.json"),
                               "chunk_map": core.file_sha256(args.chunk_map), "model": final.MODEL}
            signature_path = work / "final_input_signature.json"
            if signature_path.exists() and core._load_json_dict(signature_path) != input_signature:
                raise ValueError("final cache input signature changed; use a new target")
            core.write_json(signature_path, input_signature)
            stages = state.get("stages", {})
            if args.stage in ("all", "prepare") and stages.get("prepare", {}).get("status") != "completed":
                core.update_state(work, "prepare", "running")
                details = final.prepare_final(source, normalized, work, args.chunk_map)
                core.update_state(work, "prepare", "completed", details)
                final.LOGGER.info("prepare completed: %s", details)
            if args.stage == "prepare":
                return
            if core._load_json_dict(work / "normalization_state.json")["stages"].get("prepare", {}).get("status") != "completed":
                raise ValueError("prepare stage must complete first")
            phase = "embed"
            if args.stage in ("all", "embed"):
                if not args.embedding_endpoints_file:
                    parser.error("--embedding-endpoints-file is required for embedding")
                endpoints = []
                for line in args.embedding_endpoints_file.read_text(encoding="utf-8-sig").splitlines():
                    if "|" in line:
                        url, key = line.strip().split("|", 1)
                        endpoints.append((url.strip(), key.strip()))
                endpoints = list(dict.fromkeys(endpoints))
                if len(endpoints) != 5 or any(url != "https://api.siliconflow.cn/v1" or not key for url, key in endpoints):
                    raise ValueError("expected the five active SiliconFlow endpoints")
                core.update_state(work, "embed", "running", {"keys": len(endpoints), "concurrency": args.concurrency})
                details = asyncio.run(final.embed_final(work, endpoints, concurrency=args.concurrency,
                                                       batch_size=args.batch_size, timeout=args.timeout))
                core.update_state(work, "embed", "completed", details)
            if args.stage == "embed":
                return
            phase = "validate"
            core.update_state(work, "validate", "running")
            details = final.validate_final(source, normalized, work)
            core.update_state(work, "validate", "completed", details)
            phase = "publish"
            core.update_state(work, "publish", "running")
            close_file_handlers()
            core.publish_work(work, target)
            core.update_state(target, "publish", "completed", {"target_cache": str(target)})
            print(f"Published {target}; validation passed.", flush=True)
        except BaseException as exc:
            if work.exists():
                core.update_state(work, phase, "failed", {"error_type": type(exc).__name__, "message": str(exc)})
            logging.getLogger(__name__).exception("final build failed in %s", phase)
            raise
        finally:
            close_file_handlers()


if __name__ == "__main__":
    main()
