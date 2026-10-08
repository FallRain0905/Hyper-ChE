"""Remove historical duplicate relationship vectors without re-running LLM extraction.

The graph store uses a hyperedge's vertex set as its key, while older builds
included the mutable relation_type in the relationship-vector ID. This left
historical vector rows behind when an edge was merged with new evidence.

Default mode is a read-only audit. Pass ``--apply`` only after the builder is
stopped and the dry-run counts have been reviewed. Applying creates a backup
next to the original file and replaces the JSON atomically.
"""

from __future__ import annotations

import argparse
import base64
import copy
import json
import os
import sys
import shutil
import tempfile
from collections import OrderedDict
from datetime import datetime
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hyperrag.utils import relationship_vector_id


def _vertex_key(id_set) -> tuple[str, ...]:
    if not isinstance(id_set, (list, tuple, set)):
        raise ValueError(f"relationship row has invalid id_set: {id_set!r}")
    return tuple(sorted(str(item) for item in id_set))


def _decode_matrix(matrix_value: str, *, rows: int, dim: int) -> np.ndarray:
    matrix = np.frombuffer(base64.b64decode(matrix_value), dtype=np.float32)
    expected = rows * dim
    if matrix.size != expected:
        raise ValueError(
            f"matrix has {matrix.size} float32 values; expected {expected} "
            f"for {rows} rows x {dim} dimensions"
        )
    return matrix.reshape(rows, dim)


def _load(path: Path) -> tuple[dict, list[dict], np.ndarray]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("data")
    dim = int(payload.get("embedding_dim", 0))
    if not isinstance(rows, list) or not dim:
        raise ValueError(f"invalid vector DB header/data in {path}")
    if not isinstance(payload.get("matrix"), str):
        raise ValueError(f"missing base64 matrix in {path}")
    matrix = _decode_matrix(payload["matrix"], rows=len(rows), dim=dim)
    return payload, rows, matrix


def _select_rows(rows: list[dict], matrix: np.ndarray):
    selected: OrderedDict[tuple[str, ...], tuple[int, dict]] = OrderedDict()
    duplicate_rows = 0
    for index, row in enumerate(rows):
        key = _vertex_key(row.get("id_set"))
        if key in selected:
            duplicate_rows += 1
        # Rows are appended when the graph edge is merged again. The last row
        # therefore carries the latest merged relation metadata and embedding.
        selected[key] = (index, row)

    output_rows: list[dict] = []
    output_vectors: list[np.ndarray] = []
    seen_ids: dict[str, tuple[str, ...]] = {}
    for key, (index, row) in selected.items():
        stable_id = relationship_vector_id(key)
        previous = seen_ids.get(stable_id)
        if previous is not None and previous != key:
            raise ValueError(f"stable ID collision: {stable_id}: {previous!r} vs {key!r}")
        seen_ids[stable_id] = key
        new_row = copy.deepcopy(row)
        new_row["__id__"] = stable_id
        output_rows.append(new_row)
        output_vectors.append(matrix[index])

    return output_rows, np.asarray(output_vectors, dtype=np.float32), duplicate_rows


def _write_atomic(path: Path, payload: dict) -> None:
    fd, temp_name = tempfile.mkstemp(prefix=f"{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def migrate(path: Path, *, apply: bool) -> dict:
    payload, rows, matrix = _load(path)
    output_rows, output_matrix, duplicate_rows = _select_rows(rows, matrix)
    output = dict(payload)
    output["data"] = output_rows
    output["matrix"] = base64.b64encode(output_matrix.tobytes()).decode("ascii")
    report = {
        "path": str(path),
        "input_rows": len(rows),
        "unique_vertex_sets": len(output_rows),
        "duplicate_rows_removed": duplicate_rows,
        "output_rows": len(output_rows),
        "embedding_dim": int(payload["embedding_dim"]),
        "matrix_rows": int(output_matrix.shape[0]),
        "applied": False,
    }
    if apply:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = path.with_name(f"{path.stem}.pre_stable_id_backup_{timestamp}{path.suffix}")
        shutil.copy2(path, backup)
        _write_atomic(path, output)
        report["backup"] = str(backup)
        report["applied"] = True
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", required=True, type=Path)
    parser.add_argument("--apply", action="store_true", help="backup and atomically replace vdb_relationships.json")
    args = parser.parse_args()
    path = args.cache_dir / "vdb_relationships.json"
    if not path.is_file():
        raise SystemExit(f"missing relationship vector DB: {path}")
    if args.apply:
        print("WARNING: ensure no builder or retrieval process is writing this cache.")
    report = migrate(path, apply=args.apply)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
