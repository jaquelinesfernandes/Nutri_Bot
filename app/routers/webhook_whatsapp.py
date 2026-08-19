"""Webhook da Evolution API — canal WhatsApp do NutriBot."""
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request
from sqlalchemy import select

from app.config import settings
from app.db.session import AsyncSessionLocal
from app.models.user import User
from app.schemas.whatsapp import EvolutionWebhookPayload

logger = logging.getLogger(__name__)
router = APIRouter(tags=["whatsapp"])


async def _send_whatsapp_message(phone: str, text: str) -> None:
    """Envia mensagem de texto via Evolution API."""
    if not settings.evolution_api_url or not settings.evolution_api_instance:
        logger.debug(f"[WA] Evolution API não configurado — mensagem não enviada: {text[:60]}")
        return

    url = (
        f"{settings.evolution_api_url.rstrip('/')}"
        f"/message/sendText/{settings.evolution_api_instance}"
    )
    # Evolution API espera número no formato JID: "5511999999999@s.whatsapp.net"
    jid = f"{phone}@s.whatsapp.net" if "@" not in phone else phone
    headers = {"apikey": settings.evolution_api_key}

    async with httpx.AsyncClient(timeout=10) as client:
        try:
            await client.post(url, json={"number": jid, "text": text}, headers=headers)
        except Exception as e:
            logger.warning(f"[WA] Falha ao enviar para {phone}: {e}")


async def _get_or_create_user(db, channel_id: str, first_name: str | None) -> User:
    result = await db.execute(select(User).where(User.channel_id == channel_id))
    user = result.scalar_one_or_none()
    if not user:
        user = User(
            channel_id=channel_id,
            channel_type="whatsapp",
            first_name=first_name,
            conversation_state="IDLE",
        )
        db.add(user)
        await db.flush()
        logger.info(f"[WA] Novo usuário criado: {channel_id}")
    return user


def _extract_text(payload: EvolutionWebhookPayload) -> str | None:
    """Extrai o texto da mensagem, suportando os tipos mais comuns."""
    msg = payload.data.message
    if not msg:
        return None
    if msg.conversation:
        return msg.conversation
    if msg.extendedTextMessage:
        return msg.extendedTextMessage.get("text")
    return None


async def _process_whatsapp(payload: EvolutionWebhookPayload) -> None:
    # Ignora eventos que não sejam mensagens recebidas
    if payload.event != "messages.upsert":
        return
    if payload.data.key.fromMe:
        return

    # Extrai número limpo (sem sufixo @s.whatsapp.net)
    jid = payload.data.key.remoteJid
    phone = jid.split("@")[0]
    channel_id = f"wa:{phone}"

    text = _extract_text(payload)
    if not text:
        logger.debug(f"[WA] Mensagem sem texto de {phone} — ignorada")
        return

    first_name = payload.data.pushName

    try:
        async with AsyncSessionLocal() as db:
            user = await _get_or_create_user(db, channel_id, first_name)

            from app.services.conversation import conversation_service

            text_stripped = text.strip()
            if text_stripped.startswith("/"):
                parts = text_stripped.split(maxsplit=1)
                cmd = parts[0].lstrip("/")
                args = parts[1] if len(parts) > 1 else None
                response = await conversation_service.handle_command(user, cmd, args, db)
            else:
                response = await conversation_service.handle_message(
                    user, "text", text_stripped, db=db
                )

            user.last_active_at = datetime.now(ZoneInfo("UTC"))
            await db.commit()

        # Remove Markdown antes de enviar (WhatsApp usa formatação própria)
        clean = response.replace("*", "").replace("_", "").replace("`", "")
        await _send_whatsapp_message(phone, clean)

    except Exception:
        logger.exception(f"[WA] Erro ao processar mensagem de {phone}")


@router.post("/webhook/whatsapp")
async def webhook_whatsapp(
    request: Request,
    background_tasks: BackgroundTasks,
    apikey: str | None = Header(default=None),
):
    """
    Recebe eventos da Evolution API.
    A Evolution API envia o header 'apikey' com a chave configurada.
    """
    if settings.evolution_webhook_secret and apikey != settings.evolution_webhook_secret:
        raise HTTPException(status_code=403, detail="Invalid token")

    body = await request.json()
    payload = EvolutionWebhookPayload.model_validate(body)
    background_tasks.add_task(_process_whatsapp, payload)
    return {}
