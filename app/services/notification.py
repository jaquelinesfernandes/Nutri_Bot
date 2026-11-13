"""NotificationService — envio de mensagens via Telegram e WhatsApp (Meta Cloud API)."""

from __future__ import annotations

import logging

import httpx

from app.models.user import User

logger = logging.getLogger(__name__)

_GRAPH_BASE = "https://graph.facebook.com/v19.0"


class NotificationService:
    async def send_text(self, user: User, text: str) -> bool:
        """Envia mensagem de texto. Retorna True se enviou com sucesso."""
        try:
            if user.channel_type == "telegram":
                return await self._send_telegram(user.channel_id, text)
            elif user.channel_type == "whatsapp":
                return await self._send_whatsapp(user.channel_id, text)
            else:
                logger.warning(f"[NOTIF] Canal não suportado: {user.channel_type}")
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
            elif user.channel_type == "whatsapp":
                return await self._send_whatsapp_document(
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

    # ── WhatsApp (Meta Cloud API) ─────────────────────────────────────────────

    async def _send_whatsapp(self, channel_id: str, text: str) -> bool:
        from app.config import settings

        token = settings.whatsapp_access_token
        phone_id = settings.whatsapp_phone_number_id
        if not token or not phone_id:
            logger.debug("[WA] Credenciais não configuradas — mensagem não enviada")
            return False

        to = channel_id.split(":", 1)[1] if ":" in channel_id else channel_id
        url = f"{_GRAPH_BASE}/{phone_id}/messages"

        async with httpx.AsyncClient(timeout=10) as client:
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

    async def _send_whatsapp_document(
        self, channel_id: str, document: bytes, filename: str, caption: str | None
    ) -> bool:
        """Envia PDF via WhatsApp em dois passos: upload do arquivo → envio da mensagem."""
        from app.config import settings

        token = settings.whatsapp_access_token
        phone_id = settings.whatsapp_phone_number_id
        if not token or not phone_id:
            return False

        to = channel_id.split(":", 1)[1] if ":" in channel_id else channel_id

        async with httpx.AsyncClient(timeout=60) as client:
            # Passo 1: faz upload do PDF para o Media Store da Meta
            upload_r = await client.post(
                f"{_GRAPH_BASE}/{phone_id}/media",
                headers={"Authorization": f"Bearer {token}"},
                files={"file": (filename, document, "application/pdf")},
                data={"messaging_product": "whatsapp"},
            )
            if upload_r.status_code != 200:
                logger.warning(f"[WA] Upload de mídia falhou {upload_r.status_code}: {upload_r.text[:200]}")
                return False
            media_id = upload_r.json().get("id")

            # Passo 2: envia a mensagem referenciando o media_id
            send_r = await client.post(
                f"{_GRAPH_BASE}/{phone_id}/messages",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "messaging_product": "whatsapp",
                    "to": to,
                    "type": "document",
                    "document": {
                        "id": media_id,
                        "filename": filename,
                        "caption": caption or "",
                    },
                },
            )
            if send_r.status_code == 200:
                return True
            logger.warning(f"[WA] sendDocument {send_r.status_code}: {send_r.text[:200]}")
            return False


notification_service = NotificationService()
