"""Webhook WhatsApp — Meta Cloud API (Graph API v19.0)."""

from __future__ import annotations

import hashlib
import hmac
import logging
from collections import deque
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from sqlalchemy import select

from app.config import settings
from app.db.session import AsyncSessionLocal
from app.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter(tags=["whatsapp"])

_SEEN_MESSAGE_IDS: deque[str] = deque(maxlen=500)
_GRAPH_BASE = "https://graph.facebook.com/v19.0"


# ── Verificação do webhook (GET) ──────────────────────────────────────────────

@router.get("/webhook/whatsapp")
async def verify_webhook(
    hub_mode: str = Query(alias="hub.mode", default=""),
    hub_challenge: str = Query(alias="hub.challenge", default=""),
    hub_verify_token: str = Query(alias="hub.verify_token", default=""),
):
    """Meta verifica o endpoint na configuração do app — responde com o challenge."""
    if not settings.whatsapp_verify_token:
        raise HTTPException(status_code=503, detail="WhatsApp not configured")
    if hub_mode == "subscribe" and hub_verify_token == settings.whatsapp_verify_token:
        return int(hub_challenge)
    raise HTTPException(status_code=403, detail="Verification failed")


# ── Recebimento de mensagens (POST) ───────────────────────────────────────────

@router.post("/webhook/whatsapp")
async def webhook_whatsapp(request: Request, background_tasks: BackgroundTasks):
    """Recebe eventos do WhatsApp Business Cloud API."""
    body = await request.body()

    if settings.whatsapp_app_secret:
        sig_header = request.headers.get("X-Hub-Signature-256", "")
        expected = "sha256=" + hmac.new(
            settings.whatsapp_app_secret.encode(),
            body,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(sig_header, expected):
            logger.warning("[WA] Webhook rejeitado: assinatura HMAC inválida")
            raise HTTPException(status_code=403, detail="Invalid signature")

    payload = await request.json()
    background_tasks.add_task(_process_payload, payload)
    return {}


# ── Processamento ─────────────────────────────────────────────────────────────

async def _process_payload(payload: dict) -> None:
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            if change.get("field") != "messages":
                continue
            value = change.get("value", {})
            contacts = value.get("contacts", [])
            for msg in value.get("messages", []):
                await _process_message(msg, contacts)


async def _process_message(msg: dict, contacts: list[dict]) -> None:
    msg_id = msg.get("id", "")
    if msg_id in _SEEN_MESSAGE_IDS:
        logger.warning(f"[WA] Mensagem {msg_id} já processada — ignorando.")
        return
    _SEEN_MESSAGE_IDS.append(msg_id)

    from_number = msg.get("from", "")  # E.164 sem +, ex: "5511999999999"
    msg_type = msg.get("type", "")

    # Ignora status updates e tipos não suportados
    if not from_number or msg_type not in ("text", "image", "audio"):
        return

    channel_id = f"wa:{from_number}"
    first_name = _extract_name(contacts, from_number)

    try:
        async with AsyncSessionLocal() as db:
            user = await _get_or_create_user(db, channel_id, first_name)

            from app.services.conversation import conversation_service
            from app.services.notification import notification_service

            if msg_type == "image":
                media_id = msg.get("image", {}).get("id")
                caption = msg.get("image", {}).get("caption")
                image_bytes = await _download_media(media_id) if media_id else None
                if image_bytes:
                    response = await conversation_service.handle_message(
                        user, "photo", image_bytes, caption=caption, db=db
                    )
                else:
                    response = (
                        "Não consegui baixar a foto 😔\n"
                        "Tente novamente ou descreva a refeição em texto."
                    )

            elif msg_type == "audio":
                media_id = msg.get("audio", {}).get("id")
                audio_bytes = await _download_media(media_id) if media_id else None
                if audio_bytes:
                    response = await conversation_service.handle_message(
                        user, "audio", audio_bytes, db=db
                    )
                else:
                    response = (
                        "Não consegui baixar o áudio 😔\n"
                        "Tente novamente ou descreva a refeição em texto."
                    )

            else:  # text
                text = msg.get("text", {}).get("body", "").strip()
                if not text:
                    return
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
            await notification_service.send_text(user, response)

    except Exception:
        logger.exception(f"[WA] Erro ao processar mensagem {msg_id}")
        await _send_whatsapp_text(from_number, "Ocorreu um erro inesperado 😔 Tente novamente em instantes.")


def _extract_name(contacts: list[dict], wa_id: str) -> str | None:
    for c in contacts:
        if c.get("wa_id") == wa_id:
            return c.get("profile", {}).get("name")
    return None


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
        logger.info(f"[WA] Novo usuário criado: {channel_id} nome={first_name!r}")
    elif first_name and not user.first_name:
        user.first_name = first_name
        logger.info(f"[WA] Nome atualizado: {channel_id} → {first_name!r}")
    return user


async def _download_media(media_id: str) -> bytes | None:
    """Baixa mídia (foto/áudio) do Media Store da Meta em dois passos:
    1. Obtém a URL temporária pelo media_id
    2. Baixa o conteúdo com o token de autorização
    """
    token = settings.whatsapp_access_token
    if not token:
        return None
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            r = await client.get(f"{_GRAPH_BASE}/{media_id}", headers=headers)
            r.raise_for_status()
            media_url = r.json().get("url")
            if not media_url:
                return None
            r2 = await client.get(media_url, headers=headers)
            r2.raise_for_status()
            return r2.content
        except Exception as e:
            logger.warning(f"[WA] Falha ao baixar mídia {media_id}: {e}")
            return None


async def _send_whatsapp_text(to: str, text: str) -> bool:
    """Envia mensagem de texto diretamente (sem depender de NotificationService)."""
    token = settings.whatsapp_access_token
    phone_id = settings.whatsapp_phone_number_id
    if not token or not phone_id:
        logger.debug("[WA] Credenciais não configuradas — mensagem não enviada")
        return False
    url = f"{_GRAPH_BASE}/{phone_id}/messages"
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            r = await client.post(
                url,
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "messaging_product": "whatsapp",
                    "to": to,
                    "type": "text",
                    "text": {"body": text, "preview_url": False},
                },
            )
            if r.status_code == 200:
                return True
            logger.warning(f"[WA] sendMessage {r.status_code}: {r.text[:200]}")
            return False
        except Exception as e:
            logger.warning(f"[WA] Falha ao enviar para {to}: {e}")
            return False
