#!/usr/bin/env bash
# deploy.sh — Faz deploy ou atualização do NutriBot no VPS.
#
# Uso:
#   chmod +x scripts/deploy.sh
#   ./scripts/deploy.sh            # deploy normal
#   ./scripts/deploy.sh --build    # força rebuild da imagem
#
# Pré-requisitos:
#   - .env.prod preenchido na raiz do projeto
#   - SSL já emitido (scripts/init-ssl.sh)

set -euo pipefail

BUILD_FLAG=""
if [[ "${1:-}" == "--build" ]]; then
    BUILD_FLAG="--build"
fi

echo "==> NutriBot Deploy — $(date '+%Y-%m-%d %H:%M:%S')"

echo "==> Puxando últimas alterações do git..."
git pull origin main

echo "==> Subindo serviços..."
docker compose -f docker-compose.prod.yml up -d $BUILD_FLAG

echo "==> Aguardando app ficar saudável..."
MAX_WAIT=60
ELAPSED=0
until docker compose -f docker-compose.prod.yml exec app curl -sf http://localhost:8000/ping > /dev/null 2>&1; do
    if [[ $ELAPSED -ge $MAX_WAIT ]]; then
        echo "✗ App não respondeu em ${MAX_WAIT}s. Verificando logs..."
        docker compose -f docker-compose.prod.yml logs --tail=50 app
        exit 1
    fi
    sleep 3
    ELAPSED=$((ELAPSED + 3))
done

echo ""
echo "✓ Deploy concluído com sucesso!"
echo "  Status dos containers:"
docker compose -f docker-compose.prod.yml ps
