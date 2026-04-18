#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
#  dev-up.sh — levanta el stack de desarrollo
# ───────────────────────────────────────────────────────────────
#  Ejecutá desde la raíz del repo:
#      ./scripts/dev-up.sh
#
#  Levanta:
#    - postgres (pgvector) en localhost:5433
#    - api (uvicorn --reload) en localhost:8000
#
#  Requiere:
#    envs/.env.dev (copia de envs/env.dev.example con tus secrets)
# ═══════════════════════════════════════════════════════════════
set -euo pipefail

# Ubicar la raíz del repo sin asumir cwd
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

ENV_FILE="envs/.env.dev"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERROR: $ENV_FILE no existe."
  echo "  → cp envs/env.dev.example $ENV_FILE"
  echo "  → editá GROQ_API_KEY y OPENAI_API_KEY"
  exit 1
fi

echo ">> Levantando stack DEV..."
docker compose \
  -f docker/compose.yml \
  -f docker/compose.dev.yml \
  up -d --build

echo ""
echo ">> Esperando a que el API esté saludable..."
for i in {1..30}; do
  if docker compose -f docker/compose.yml -f docker/compose.dev.yml ps api \
     | grep -q "healthy\|Up"; then
    break
  fi
  sleep 1
done

echo ""
echo "✓ Stack DEV arriba"
echo "  API:      http://localhost:8000"
echo "  Health:   http://localhost:8000/health"
echo "  Docs:     http://localhost:8000/docs"
echo "  Postgres: localhost:5433 (user: postgres)"
echo ""
echo "  Logs:     docker compose -f docker/compose.yml -f docker/compose.dev.yml logs -f api"
echo "  Stop:     docker compose -f docker/compose.yml -f docker/compose.dev.yml down"
