#!/usr/bin/env python
"""
Testa o bot do Telegram ponta a ponta:
  1. Verifica status do webhook
  2. Verifica se o Render está respondendo em /health
  3. Envia uma mensagem de teste via sendMessage (requer TELEGRAM_TEST_CHAT_ID no .env)

Uso:
    python scripts/test_telegram_bot.py

Variáveis de ambiente (.env):
    TELEGRAM_BOT_TOKEN      — obrigatória
    WEBHOOK_BASE_URL        — obrigatória
    TELEGRAM_TEST_CHAT_ID   — opcional; se ausente, pula o envio de mensagem
                              (encontre o seu em https://t.me/userinfobot)
"""
from __future__ import annotations

import os
import sys

import httpx
from dotenv import load_dotenv

load_dotenv()

token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
base_url = os.environ.get("WEBHOOK_BASE_URL", "").rstrip("/")
chat_id = os.environ.get("TELEGRAM_TEST_CHAT_ID", "")

OK = "✅"
FAIL = "❌"
SKIP = "⏭️"


def check(label: str, ok: bool, detail: str = "") -> bool:
    mark = OK if ok else FAIL
    print(f"  {mark}  {label}" + (f" — {detail}" if detail else ""))
    return ok


def main() -> int:
    errors = 0

    # ── 1. Pré-requisitos ────────────────────────────────────────────────────
    print("\n🔍 Verificando pré-requisitos...")
    if not check("TELEGRAM_BOT_TOKEN definido", bool(token)):
        errors += 1
    if not check("WEBHOOK_BASE_URL definido", bool(base_url)):
        errors += 1
    if errors:
        print("\nDefina as variáveis faltantes no .env e tente novamente.")
        return 1

    # ── 2. Health check do Render ────────────────────────────────────────────
    print("\n🌐 Verificando Render /health ...")
    try:
        r = httpx.get(f"{base_url}/health", timeout=15, follow_redirects=True)
        ok = r.status_code == 200
        check("/health retornou 200", ok, f"status={r.status_code}")
        if not ok:
            errors += 1
    except Exception as e:
        check("/health acessível", False, str(e))
        errors += 1

    # ── 3. Status do webhook ─────────────────────────────────────────────────
    print("\n📡 Verificando webhook do Telegram...")
    try:
        r = httpx.get(
            f"https://api.telegram.org/bot{token}/getWebhookInfo",
            timeout=10,
        )
        info = r.json().get("result", {})
        webhook_url = info.get("url", "")
        pending = info.get("pending_update_count", 0)
        last_error = info.get("last_error_message", "")
        last_error_date = info.get("last_error_date", 0)

        expected = f"{base_url}/webhook/telegram"
        url_ok = webhook_url == expected
        check("URL do webhook correta", url_ok, webhook_url or "(vazia)")
        check("Sem pending updates", pending == 0, f"{pending} pendentes")
        check(
            "Sem erros recentes",
            not last_error,
            last_error or "nenhum",
        )
        if not url_ok:
            errors += 1
            print(f"\n     💡 Esperado: {expected}")
            print(f"        Execute: python scripts/register_telegram_webhook.py")
    except Exception as e:
        check("getWebhookInfo acessível", False, str(e))
        errors += 1

    # ── 4. Envio de mensagem de teste ────────────────────────────────────────
    print("\n💬 Envio de mensagem de teste...")
    if not chat_id:
        print(f"  {SKIP}  TELEGRAM_TEST_CHAT_ID não definido — pulando")
        print("       Para habilitar: adicione TELEGRAM_TEST_CHAT_ID=<seu_id> no .env")
        print("       Descubra seu ID em: https://t.me/userinfobot")
    else:
        try:
            r = httpx.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": (
                        "🤖 *NutriBot — teste de conectividade*\n\n"
                        "✅ Deploy no Render funcionando\n"
                        "✅ Webhook registrado\n\n"
                        "Responda qualquer coisa para testar o fluxo completo!"
                    ),
                    "parse_mode": "Markdown",
                },
                timeout=10,
            )
            data = r.json()
            ok = data.get("ok", False)
            check("Mensagem enviada com sucesso", ok, data.get("description", ""))
            if not ok:
                errors += 1
        except Exception as e:
            check("sendMessage acessível", False, str(e))
            errors += 1

    # ── Resumo ───────────────────────────────────────────────────────────────
    print()
    if errors == 0:
        print(f"{OK} Tudo certo! Abra o Telegram e envie uma mensagem para o bot.")
    else:
        print(f"{FAIL} {errors} verificação(ões) falharam. Veja os detalhes acima.")

    return errors


if __name__ == "__main__":
    sys.exit(main())
