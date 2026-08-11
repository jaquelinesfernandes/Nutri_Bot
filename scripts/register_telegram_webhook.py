#!/usr/bin/env python
"""
Registra o webhook do Telegram após o deploy.

Uso:
    python scripts/register_telegram_webhook.py https://seu-app.railway.app

Variáveis de ambiente necessárias (lidas do .env):
    TELEGRAM_BOT_TOKEN
    TELEGRAM_WEBHOOK_SECRET
"""
from __future__ import annotations

import os
import sys

import httpx
from dotenv import load_dotenv

load_dotenv()

token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
secret = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")

if not token:
    print("ERRO: TELEGRAM_BOT_TOKEN não definido")
    sys.exit(1)

if len(sys.argv) < 2:
    print("Uso: python scripts/register_telegram_webhook.py https://seu-app.railway.app")
    sys.exit(1)

app_url = sys.argv[1].rstrip("/")
webhook_url = f"{app_url}/webhook/telegram"

print(f"Registrando webhook: {webhook_url}")

resp = httpx.post(
    f"https://api.telegram.org/bot{token}/setWebhook",
    json={
        "url": webhook_url,
        "secret_token": secret or None,
        "allowed_updates": ["message", "callback_query"],
        "drop_pending_updates": True,
    },
    timeout=15,
)

data = resp.json()
if data.get("ok"):
    print(f"✅ Webhook registrado com sucesso: {data.get('description', 'OK')}")
else:
    print(f"❌ Falha: {data}")
    sys.exit(1)

# Confirma o registro
info = httpx.get(
    f"https://api.telegram.org/bot{token}/getWebhookInfo",
    timeout=10,
).json()
result = info.get("result", {})
print(f"\nStatus atual:")
print(f"  URL: {result.get('url')}")
print(f"  Pending updates: {result.get('pending_update_count', 0)}")
print(f"  Last error: {result.get('last_error_message', 'nenhum')}")
