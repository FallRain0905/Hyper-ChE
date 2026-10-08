#!/bin/sh
# Restore already-built application images while retaining all data volumes.
set -eu
repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
release=${1:-}
env_file=${2:-/opt/hyperche/shared/.env}
case "$release" in
    ""|*[!0-9a-f]*) echo "Usage: $0 PREVIOUS_COMMIT_SHA [PRIVATE_ENV_FILE]" >&2; exit 1 ;;
esac
if [ ! -f "$env_file" ]; then
    echo "Private environment file is missing." >&2
    exit 1
fi
docker image inspect "hyperche/backend:$release" >/dev/null
docker image inspect "hyperche/frontend:$release" >/dev/null
cd "$repo_dir"
HYPERCHE_RELEASE=$release
export HYPERCHE_RELEASE
docker compose -p hyperche --env-file "$env_file" -f docker-compose.hyperche.yml config --quiet
docker compose -p hyperche --env-file "$env_file" -f docker-compose.hyperche.yml up -d --no-build --wait --wait-timeout 180
echo "Restored HyperChE application images for $release; data volumes were retained."
