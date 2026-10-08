"""Configuration and health checks for the single public demo instance."""

from pathlib import Path
from typing import Any
import os

PUBLIC_DEMO_ID = "flow-battery"
PUBLIC_DEMO_NAME = "液流电池公开知识库"
PUBLIC_DEMO_DOMAIN = "flow_battery"
DEFAULT_PUBLIC_DEMO_DATABASE = "case1"

REQUIRED_CACHE_FILES = (
    "hypergraph_chunk_entity_relation.hgdb",
    "kv_store_full_docs.json",
    "kv_store_text_chunks.json",
    "vdb_chunks.json",
    "vdb_entities.json",
    "vdb_relationships.json",
)
OPTIONAL_CACHE_FILES = ("kv_store_llm_response_cache.json",)
LFS_POINTER_HEADER = b"version https://git-lfs.github.com/spec/v1"


def _is_lfs_pointer(path: Path) -> bool:
    try:
        with path.open("rb") as file:
            return file.read(len(LFS_POINTER_HEADER)) == LFS_POINTER_HEADER
    except OSError:
        return False


def inspect_public_demo_cache(cache_root: str | Path, database: str) -> dict[str, Any]:
    """Return a safe, API-ready health report for the configured demo cache."""
    final_path = final_cache_path(cache_root, database)
    if final_path is not None:
        from hyperche.retrieval.runtime import inspect_final_cache
        status = inspect_final_cache(final_path)
        return {**status, "ready": status["cache_ready"], "database": database,
                "cache_exists": final_path.is_dir(), "optional_missing_files": [], "retrieval_profile": "f1"}
    database_dir = Path(cache_root) / database
    missing_files: list[str] = []
    lfs_pointer_files: list[str] = []

    for filename in REQUIRED_CACHE_FILES:
        path = database_dir / filename
        if not path.is_file():
            missing_files.append(filename)
        elif _is_lfs_pointer(path):
            lfs_pointer_files.append(filename)

    optional_missing_files = [
        filename for filename in OPTIONAL_CACHE_FILES
        if not (database_dir / filename).is_file()
    ]

    return {
        "ready": database_dir.is_dir() and not missing_files and not lfs_pointer_files,
        "database": database,
        "cache_exists": database_dir.is_dir(),
        "missing_files": missing_files,
        "lfs_pointer_files": lfs_pointer_files,
        "optional_missing_files": optional_missing_files,
        "cache_ready": database_dir.is_dir() and not missing_files and not lfs_pointer_files,
        "retrieval_profile": "legacy", "read_only": False,
    }


def final_cache_path(cache_root: str | Path, database: str) -> Path | None:
    """Bind the explicit read-only mount, or detect a server-published final KB.

    A mode setting alone never upgrades a user-built/legacy database to F1.
    Presence of final metadata means it must validate before it may be queried.
    """
    name = str(database or "").removesuffix(".hgdb")
    configured = os.getenv("HYPERCHE_FINAL_CACHE_DIR", "").strip()
    alias = os.getenv("HYPERCHE_FINAL_CACHE_DATABASE", "hyper_final_posthoc_v1").strip()
    if configured and name == alias:
        return Path(configured)
    candidate = Path(cache_root) / name
    if (candidate / "final_validation.json").is_file():
        return candidate
    return None


def public_demo_metadata(database: str) -> dict[str, str]:
    return {
        "id": PUBLIC_DEMO_ID,
        "name": PUBLIC_DEMO_NAME,
        "database_name": database,
        "domain": PUBLIC_DEMO_DOMAIN,
        "rag_system": "hyperrag",
    }
