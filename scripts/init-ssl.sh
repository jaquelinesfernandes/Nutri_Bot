#!/usr/bin/env bash
# init-ssl.sh — Emite certificados SSL pela primeira vez com Let's Encrypt.
# Execute ANTES de subir o docker-compose.prod.yml completo.
#
# Uso:
#   chmod +x scripts/init-ssl.sh
#   ./scripts/init-ssl.sh seudominio.com seu-email@exemplo.com
#
# Pré-requisitos:
#   - Docker + Docker Compose instalados
#   - Domínios seudominio.com, www.seudominio.com e app.seudominio.com apontando para este VPS
#   - Portas 80 e 443 abertas no firewall

set -euo pipefail

DOMAIN="${1:-}"
EMAIL="${2:-}"
APP_SUBDOMAIN="app.${DOMAIN}"

if [[ -z "$DOMAIN" || -z "$EMAIL" ]]; then
    echo "Uso: $0 <dominio> <email>"
    echo "Ex:  $0 seudominio.com admin@seudominio.com"
    exit 1
fi

echo "==> Substituindo domínio nos configs do Nginx..."
sed -i "s/seudominio\.com/${DOMAIN}/g" nginx/conf.d/website.conf
sed -i "s/app\.seudominio\.com/${APP_SUBDOMAIN}/g" nginx/conf.d/app.conf

echo "==> Subindo Nginx em modo HTTP-only para desafio ACME..."
# Nginx temporário que só responde na porta 80
docker compose -f docker-compose.prod.yml up -d nginx

echo "==> Aguardando Nginx iniciar..."
sleep 5

echo "==> Emitindo certificado para ${DOMAIN} e www.${DOMAIN}..."
docker compose -f docker-compose.prod.yml --profile ssl run --rm certbot \
    certonly --webroot -w /var/www/certbot \
    --email "$EMAIL" --agree-tos --no-eff-email \
    -d "$DOMAIN" -d "www.${DOMAIN}"

echo "==> Emitindo certificado para ${APP_SUBDOMAIN}..."
docker compose -f docker-compose.prod.yml --profile ssl run --rm certbot \
    certonly --webroot -w /var/www/certbot \
    --email "$EMAIL" --agree-tos --no-eff-email \
    -d "$APP_SUBDOMAIN"

echo "==> Reiniciando Nginx com HTTPS..."
docker compose -f docker-compose.prod.yml restart nginx

echo ""
echo "✓ SSL emitido com sucesso!"
echo "  Adicione ao crontab do host para renovação automática:"
echo "  0 3 * * * cd $(pwd) && docker compose -f docker-compose.prod.yml --profile ssl run --rm certbot renew --quiet && docker compose -f docker-compose.prod.yml exec nginx nginx -s reload"
