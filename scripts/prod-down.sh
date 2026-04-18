#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
#  prod-down.sh — baja el stack de producción
# ───────────────────────────────────────────────────────────────
#  NO borra el volumen de postgres por defecto (tus datos persisten).
#  Pasá --wipe para borrar TODO incluyendo los datos:
#      ./scripts/prod-down.sh --wipe
# ═══════════════════════════════════════════════════════════════
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

WIPE=false
if [[ "${1:-}" == "--wipe" ]]; then
  WIPE=true
fi

echo ">> Bajando stack PROD..."

if $WIPE; then
  echo ">> --wipe activo: se borrará el volumen postgres_data"
  read -p "¿Confirmás? Esto ES DESTRUCTIVO (y/N): " -n 1 -r
  echo
  if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Cancelado."
    exit 0
  fi
  docker compose \
    -f docker/compose.yml \
    -f docker/compose.prod.yml \
    down --volumes
else
  docker compose \
    -f docker/compose.yml \
    -f docker/compose.prod.yml \
    down
fi

echo "✓ Stack bajado"
