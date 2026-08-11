"""NotificationService — envio de mensagens via Telegram e WhatsApp."""

from __future__ import annotations

import logging

import httpx

from app.models.user import User

logger = logging.getLogger(__name__)


class NotificationService:
    async def send_text(self, user: User, text: str) -> bool:
        """Envia mensagem de texto. Retorna True se enviou com sucesso."""
        try:
            if user.channel_type == "telegram":
                return await self._send_telegram(user.channel_id, text)
            elif user.channel_type == "whatsapp":
                return await self._send_whatsapp(user.channel_id, text)
        except Exception as e:
            logger.warning(f"[NOTIF] Falha ao enviar para {user.channel_id}: {e}")
        return False

    async def send_document(
        self,
        user: User,
        document_bytes: bytes,
        filename: str,
        caption: str | None = None,
    ) -> bool:
        try:
            if user.channel_type == "telegram":
                return await self._send_telegram_document(
                    user.channel_id, document_bytes, filename, caption
                )
        except Exception as e:
            logger.warning(f"[NOTIF DOC] Falha ao enviar para {user.channel_id}: {e}")
        return False

    # ── Telegram ─────────────────────────────────────────────────────────────

    async def _send_telegram(self, channel_id: str, text: str) -> bool:
        from app.config import settings

        if not settings.telegram_bot_token:
            logger.debug("[TG] Bot token não configurado")
            return False

        # channel_id formato: "tg:123456789"
        chat_id = channel_id.split(":", 1)[1] if ":" in channel_id else channel_id
        url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"

        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(url, json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
            })
            if r.status_code == 200:
                return True
            logger.warning(f"[TG] sendMessage {r.status_code}: {r.text[:200]}")
            return False

    async def _send_telegram_document(
        self, channel_id: str, document: bytes, filename: str, caption: str | None
    ) -> bool:
        from app.config import settings

        if not settings.telegram_bot_token:
            return False

        chat_id = channel_id.split(":", 1)[1] if ":" in channel_id else channel_id
        url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendDocument"

        async with httpx.AsyncClient(timeout=30) as client:
            files = {"document": (filename, document, "application/pdf")}
            data = {"chat_id": chat_id}
            if caption:
                data["caption"] = caption
            r = await client.post(url, data=data, files=files)
            return r.status_code == 200

    # ── WhatsApp ──────────────────────────────────────────────────────────────

    async def _send_whatsapp(self, channel_id: str, text: str) -> bool:
        from app.config import settings

        if not settings.zapi_instance_id or not settings.zapi_token:
            logger.debug("[WA] Z-API não configurado")
            return False

        phone = channel_id.split(":", 1)[1] if ":" in channel_id else channel_id
        url = (
            f"https://api.z-api.io/instances/{settings.zapi_instance_id}"
            f"/token/{settings.zapi_token}/send-text"
        )
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(url, json={"phone": phone, "message": text})
            return r.status_code == 200


notification_service = NotificationService()
