"""
Roda o bot Telegram em modo polling local — sem precisar de ngrok ou webhook.
Ideal para desenvolvimento e testes. Em produção, usar webhook via uvicorn.

Uso:
    python scripts/run_bot_polling.py
"""

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("nutribot.polling")

import httpx
from app.config import settings
from app.schemas.telegram import TelegramUpdate
from app.services.nutrition import nutrition_service

_TG = f"https://api.telegram.org/bot{settings.telegram_bot_token}"


async def _get_updates(offset: int | None, timeout: int = 30) -> list[dict]:
    params = {"timeout": timeout, "allowed_updates": ["message"]}
    if offset is not None:
        params["offset"] = offset
    async with httpx.AsyncClient(timeout=timeout + 5) as client:
        r = await client.get(f"{_TG}/getUpdates", params=params)
        r.raise_for_status()
        data = r.json()
        return data.get("result", [])


async def _delete_webhook():
    """Remove webhook existente para não conflitar com polling."""
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(f"{_TG}/deleteWebhook", json={"drop_pending_updates": False})
        if r.status_code == 200:
            logger.info("Webhook removido (modo polling ativo)")
        else:
            logger.warning(f"Não foi possível remover webhook: {r.text}")


async def run():
    if not settings.telegram_bot_token:
        print("ERRO: TELEGRAM_BOT_TOKEN não configurado no .env")
        sys.exit(1)

    nutrition_service.load_data()
    logger.info("Base nutricional carregada")

    await _delete_webhook()

    # Importar após carregar dados
    from app.routers.webhook_telegram import _process_update

    logger.info("=" * 50)
    logger.info("NutriBot rodando em modo POLLING")
    logger.info("Envie mensagens no Telegram para testar")
    logger.info("Ctrl+C para encerrar")
    logger.info("=" * 50)

    offset = None
    while True:
        try:
            updates = await _get_updates(offset)
            for raw in updates:
                offset = raw["update_id"] + 1
                try:
                    update = TelegramUpdate.model_validate(raw)
                    await _process_update(update)
                except Exception as e:
                    logger.error(f"Erro ao processar update {raw.get('update_id')}: {e}")
        except httpx.ReadTimeout:
            pass  # normal em long polling
        except httpx.HTTPError as e:
            logger.warning(f"Erro HTTP: {e} — aguardando 5s...")
            await asyncio.sleep(5)
        except KeyboardInterrupt:
            logger.info("Encerrando...")
            break
        except Exception as e:
            logger.error(f"Erro inesperado: {e}")
            await asyncio.sleep(3)


if __name__ == "__main__":
    asyncio.run(run())
