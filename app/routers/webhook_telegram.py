import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request
from sqlalchemy import select

from app.config import settings
from app.db.session import AsyncSessionLocal
from app.models.user import User
from app.schemas.telegram import TelegramUpdate

logger = logging.getLogger(__name__)
router = APIRouter(tags=["telegram"])

_TG_BASE = "https://api.telegram.org/bot{token}"


async def _send_message(chat_id: int, text: str) -> None:
    if not settings.telegram_bot_token:
        logger.debug(f"[TG] Bot token não configurado — mensagem não enviada: {text[:60]}")
        return
    url = _TG_BASE.format(token=settings.telegram_bot_token) + "/sendMessage"
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            await client.post(url, json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
            })
        except Exception as e:
            logger.warning(f"[TG] Falha ao enviar mensagem para {chat_id}: {e}")


async def _download_telegram_file(file_id: str, timeout: int = 30) -> bytes:
    """Baixa qualquer arquivo do Telegram (foto, áudio, documento) usando file_id."""
    token = settings.telegram_bot_token
    base = _TG_BASE.format(token=token)
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.get(f"{base}/getFile", params={"file_id": file_id})
        r.raise_for_status()
        file_path = r.json()["result"]["file_path"]
        r2 = await client.get(f"https://api.telegram.org/file/bot{token}/{file_path}")
        r2.raise_for_status()
        return r2.content


# Alias mantido para compatibilidade com código existente
async def _download_telegram_photo(file_id: str) -> bytes:
    return await _download_telegram_file(file_id)


async def _get_or_create_user(db, channel_id: str, first_name: str | None) -> User:
    result = await db.execute(select(User).where(User.channel_id == channel_id))
    user = result.scalar_one_or_none()
    if not user:
        user = User(
            channel_id=channel_id,
            channel_type="telegram",
            first_name=first_name,
            conversation_state="IDLE",
        )
        db.add(user)
        await db.flush()
        logger.info(f"[TG] Novo usuário criado: {channel_id}")
    return user


async def _process_update(update: TelegramUpdate) -> None:
    msg = update.message
    if not msg:
        return
    if not msg.text and not msg.photo and not msg.voice:
        return  # ignora stickers, documentos, etc.

    chat_id = msg.chat.id
    channel_id = f"tg:{chat_id}"
    first_name = msg.from_.first_name if msg.from_ else None

    try:
        async with AsyncSessionLocal() as db:
            user = await _get_or_create_user(db, channel_id, first_name)

            from app.services.conversation import conversation_service

            if msg.photo:
                # Telegram envia lista ordenada do menor para o maior — pega a maior resolução
                file_id = msg.photo[-1].file_id
                try:
                    image_bytes = await _download_telegram_file(file_id)
                except Exception as e:
                    logger.error(f"[TG] Falha ao baixar foto {file_id}: {e}")
                    image_bytes = None

                if image_bytes:
                    response = await conversation_service.handle_message(
                        user, "photo", image_bytes, caption=msg.caption, db=db
                    )
                else:
                    response = (
                        "Não consegui baixar a foto 😔\n"
                        "Tente novamente ou descreva a refeição em texto."
                    )

            elif msg.voice:
                duration = msg.voice.duration
                if duration > 120:
                    response = "Áudio muito longo (máx. 2 min). Tente dividir em partes menores!"
                else:
                    try:
                        audio_bytes = await _download_telegram_file(msg.voice.file_id, timeout=60)
                    except Exception as e:
                        logger.error(f"[TG] Falha ao baixar áudio {msg.voice.file_id}: {e}")
                        audio_bytes = None

                    if audio_bytes:
                        response = await conversation_service.handle_message(
                            user, "audio", audio_bytes, db=db
                        )
                    else:
                        response = (
                            "Não consegui baixar o áudio 😔\n"
                            "Tente novamente ou descreva a refeição em texto."
                        )

            else:
                text = msg.text.strip()
                if text.startswith("/"):
                    parts = text.split(maxsplit=1)
                    cmd = parts[0].lstrip("/").split("@")[0]
                    args = parts[1] if len(parts) > 1 else None
                    response = await conversation_service.handle_command(user, cmd, args, db)
                else:
                    response = await conversation_service.handle_message(user, "text", text, db=db)

            user.last_active_at = datetime.now(ZoneInfo("UTC"))
            await db.commit()

        if response:
            await _send_message(chat_id, response)

    except Exception:
        logger.exception(f"[TG] Erro ao processar update {update.update_id}")
        await _send_message(chat_id, "Ocorreu um erro inesperado 😔 Tente novamente em instantes.")


@router.post("/webhook/telegram")
async def webhook_telegram(
    request: Request,
    background_tasks: BackgroundTasks,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
):
    # Só valida o secret se estiver configurado; se vazio, aceita qualquer request
    # (evita 403 quando TELEGRAM_WEBHOOK_SECRET não foi definido no ambiente de deploy)
    if settings.telegram_webhook_secret and x_telegram_bot_api_secret_token != settings.telegram_webhook_secret:
        logger.warning(
            f"[TG] Webhook rejeitado: secret inválido "
            f"(recebido={x_telegram_bot_api_secret_token!r})"
        )
        raise HTTPException(status_code=403, detail="Invalid secret token")

    body = await request.json()
    update = TelegramUpdate.model_validate(body)
    background_tasks.add_task(_process_update, update)
    return {}
