#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/apps/clinical-ai"

: "${GIT_SHA:?GIT_SHA is required}"
: "${GHCR_USER:?GHCR_USER is required}"
: "${GHCR_TOKEN:?GHCR_TOKEN is required}"

cd "$APP_DIR"

git fetch origin main
git checkout main
git reset --hard origin/main

echo "$GHCR_TOKEN" | docker login ghcr.io -u "$GHCR_USER" --password-stdin

export IMAGE_TAG="sha-$GIT_SHA"

docker network inspect proxy >/dev/null 2>&1 || docker network create proxy

docker compose \
  -f docker/compose.yml \
  -f docker/compose.vps.yml \
  pull api indexer migrator

docker compose \
  -f docker/compose.yml \
  -f docker/compose.vps.yml \
  up -d postgres

docker compose \
  -f docker/compose.yml \
  -f docker/compose.vps.yml \
  --profile tools \
  run --rm migrator

docker compose \
  -f docker/compose.yml \
  -f docker/compose.vps.yml \
  up -d api

for _ in {1..30}; do
  STATUS=$(docker inspect --format='{{.State.Health.Status}}' clinical-ai-api 2>/dev/null || echo "starting")
  if [[ "$STATUS" == "healthy" ]]; then
    docker image prune -af --filter "until=168h"
    docker builder prune -af --filter "until=168h"
    docker container prune -f
    exit 0
  fi
  sleep 2
done

echo "ERROR: clinical-ai-api no quedó healthy" >&2
exit 1
