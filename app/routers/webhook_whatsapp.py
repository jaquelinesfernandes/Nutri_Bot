import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request
from sqlalchemy import select

from app.config import settings
from app.db.session import AsyncSessionLocal
from app.models.user import User
from app.schemas.whatsapp import ZApiWebhookPayload

logger = logging.getLogger(__name__)
router = APIRouter(tags=["whatsapp"])


async def _send_whatsapp_message(phone: str, text: str) -> None:
    if not settings.zapi_instance_id or not settings.zapi_token:
        logger.debug(f"[WA] Z-API não configurado — mensagem não enviada: {text[:60]}")
        return
    url = f"https://api.z-api.io/instances/{settings.zapi_instance_id}/token/{settings.zapi_token}/send-text"
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            await client.post(url, json={"phone": phone, "message": text})
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


async def _process_whatsapp(payload: ZApiWebhookPayload) -> None:
    if payload.fromMe:
        return

    phone = payload.phone
    channel_id = f"wa:{phone}"
    text = payload.text.message if payload.text else None

    if not text:
        logger.debug(f"[WA] Mensagem sem texto de {phone} — ignorada")
        return

    try:
        async with AsyncSessionLocal() as db:
            user = await _get_or_create_user(db, channel_id, None)

            from app.services.conversation import conversation_service

            text_stripped = text.strip()
            if text_stripped.startswith("/"):
                parts = text_stripped.split(maxsplit=1)
                cmd = parts[0].lstrip("/")
                args = parts[1] if len(parts) > 1 else None
                response = await conversation_service.handle_command(user, cmd, args, db)
            else:
                response = await conversation_service.handle_message(user, "text", text_stripped, db=db)

            user.last_active_at = datetime.now(ZoneInfo("UTC"))
            await db.commit()

        # Remove Markdown antes de enviar (WhatsApp usa formato diferente)
        clean = response.replace("*", "").replace("_", "").replace("`", "")
        await _send_whatsapp_message(phone, clean)

    except Exception:
        logger.exception(f"[WA] Erro ao processar mensagem de {phone}")


@router.post("/webhook/whatsapp")
async def webhook_whatsapp(
    request: Request,
    background_tasks: BackgroundTasks,
    authorization: str | None = Header(default=None),
):
    expected = f"Bearer {settings.zapi_webhook_secret}"
    if settings.zapi_webhook_secret and authorization != expected:
        raise HTTPException(status_code=403, detail="Invalid token")

    body = await request.json()
    payload = ZApiWebhookPayload.model_validate(body)
    background_tasks.add_task(_process_whatsapp, payload)
    return {}
