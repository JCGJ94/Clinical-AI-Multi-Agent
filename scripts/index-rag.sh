#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
#  index-rag.sh — ejecuta el indexador RAG (one-shot)
# ───────────────────────────────────────────────────────────────
#  Lee docs/ → genera embeddings OpenAI → escribe en pgvector.
#
#  Requiere:
#    - Stack arriba (postgres corriendo)
#    - OPENAI_API_KEY seteada en envs/.env.{dev|prod}
#
#  Uso:
#      ./scripts/index-rag.sh          # usa dev por defecto
#      ./scripts/index-rag.sh prod     # usa prod
# ═══════════════════════════════════════════════════════════════
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

MODE="${1:-dev}"

case "$MODE" in
  dev)
    OVERRIDE="docker/compose.dev.yml"
    ENV_FILE="envs/.env.dev"
    ;;
  prod)
    OVERRIDE="docker/compose.prod.yml"
    ENV_FILE="envs/.env.prod"
    ;;
  *)
    echo "ERROR: modo inválido '$MODE'. Usá 'dev' o 'prod'."
    exit 1
    ;;
esac

if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERROR: $ENV_FILE no existe."
  exit 1
fi

# Chequear que OPENAI_API_KEY esté seteada — el indexer la necesita
if ! grep -E "^OPENAI_API_KEY=.+" "$ENV_FILE" | grep -vE "OPENAI_API_KEY=(CHANGE_ME|$)" > /dev/null; then
  echo "ERROR: OPENAI_API_KEY vacía o placeholder en $ENV_FILE"
  echo "  → editá el archivo y seteá una key real"
  exit 1
fi

echo ">> Corriendo indexer RAG ($MODE)..."
docker compose \
  -f docker/compose.yml \
  -f "$OVERRIDE" \
  --profile tools \
  run --rm --build indexer

echo ""
echo "✓ Indexación completada"
