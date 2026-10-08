#!/bin/sh
# Build and launch one committed release. Private environment and data remain
# outside the checkout; no other Compose project or host Nginx is modified.
set -eu
repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
env_file=${1:-/opt/hyperche/shared/.env}
cd "$repo_dir"
if [ ! -f "$env_file" ]; then
    echo "Private environment file is missing: $env_file" >&2
    exit 1
fi
if [ -n "$(git status --porcelain)" ]; then
    echo "Commit the release before deploying; this checkout has local changes." >&2
    exit 1
fi
HYPERCHE_RELEASE=$(git rev-parse --short=12 HEAD)
export HYPERCHE_RELEASE
docker compose -p hyperche --env-file "$env_file" -f docker-compose.hyperche.yml config --quiet
case "${HYPERCHE_PULL_BASE_IMAGES:-true}" in
    true) docker compose -p hyperche --env-file "$env_file" -f docker-compose.hyperche.yml build --pull ;;
    false) docker compose -p hyperche --env-file "$env_file" -f docker-compose.hyperche.yml build ;;
    *) echo "HYPERCHE_PULL_BASE_IMAGES must be true or false." >&2; exit 1 ;;
esac
docker compose -p hyperche --env-file "$env_file" -f docker-compose.hyperche.yml up -d --no-build --wait --wait-timeout 180
docker compose -p hyperche --env-file "$env_file" -f docker-compose.hyperche.yml ps
echo "HyperChE release $HYPERCHE_RELEASE is running on the configured loopback port."
