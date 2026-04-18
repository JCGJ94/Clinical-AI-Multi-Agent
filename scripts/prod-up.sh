#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
#  prod-up.sh — levanta el stack de producción (local, para testing)
# ───────────────────────────────────────────────────────────────
#  Este script es para PROBAR LOCALMENTE la config de prod antes
#  de deployar al VPS. Simula la experiencia productiva:
#    - Non-root user
#    - Sin bind mounts (código dentro de la imagen)
#    - Resource limits
#    - Ports bindeados solo a 127.0.0.1
#    - restart: unless-stopped
#
#  Uso:
#      ./scripts/prod-up.sh
#
#  Para deploy real al VPS, copiá el repo al server y corré el mismo script.
# ═══════════════════════════════════════════════════════════════
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

ENV_FILE="envs/.env.prod"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERROR: $ENV_FILE no existe."
  echo "  → cp envs/env.prod.example $ENV_FILE"
  echo "  → reemplazá TODOS los placeholders CHANGE_ME_*"
  exit 1
fi

# Sanity check: que no queden placeholders sin reemplazar
if grep -q "CHANGE_ME" "$ENV_FILE"; then
  echo "ERROR: $ENV_FILE todavía contiene placeholders CHANGE_ME_*"
  echo "  → editá el archivo y reemplazá los secrets antes de continuar"
  exit 1
fi

echo ">> Levantando stack PROD (local testing)..."
docker compose \
  -f docker/compose.yml \
  -f docker/compose.prod.yml \
  up -d --build

echo ""
echo ">> Esperando healthcheck del API..."
for i in {1..60}; do
  STATUS=$(docker inspect --format='{{.State.Health.Status}}' clinical-ai-api 2>/dev/null || echo "starting")
  if [[ "$STATUS" == "healthy" ]]; then
    echo "✓ API healthy"
    break
  fi
  sleep 2
done

echo ""
echo "✓ Stack PROD arriba (modo local testing)"
echo "  API:      http://127.0.0.1:8000"
echo "  Health:   http://127.0.0.1:8000/health"
echo "  Postgres: 127.0.0.1:5433 (acceso solo local)"
echo ""
echo "  Logs:     docker compose -f docker/compose.yml -f docker/compose.prod.yml logs -f api"
echo "  Down:     ./scripts/prod-down.sh"
