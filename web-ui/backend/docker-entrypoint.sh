#!/bin/sh
set -eu
cache_seed_dir="${HYPERCHE_CACHE_SEED_DIR:-/app/cache_seed/case1}"
cache_runtime_dir="${HYPERCHE_CACHE_RUNTIME_DIR:-/app/hyperrag_cache/case1}"
required_cache_file="hypergraph_chunk_entity_relation.hgdb"
mkdir -p "$cache_runtime_dir"
if [ ! -f "$cache_runtime_dir/$required_cache_file" ]; then
    if [ -f "$cache_seed_dir/$required_cache_file" ]; then
        echo "[INFO] Initializing writable case1 cache from mounted seed"
        cp -a "$cache_seed_dir/." "$cache_runtime_dir/"
    else
        echo "[INFO] No seed cache mounted; starting with an empty knowledge base"
    fi
fi
exec "$@"
