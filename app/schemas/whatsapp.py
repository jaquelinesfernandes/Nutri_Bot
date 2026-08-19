"""Schemas Pydantic para webhook da Evolution API (WhatsApp)."""
from __future__ import annotations

from pydantic import BaseModel


class EvolutionMessageKey(BaseModel):
    remoteJid: str          # ex: "5511999999999@s.whatsapp.net"
    fromMe: bool = False
    id: str = ""


class EvolutionMessageContent(BaseModel):
    """Conteúdo da mensagem — apenas os tipos que o NutriBot processa."""
    conversation: str | None = None           # texto simples
    extendedTextMessage: dict | None = None   # texto com link/preview
    imageMessage: dict | None = None          # foto
    audioMessage: dict | None = None          # áudio (PTT ou gravado)


class EvolutionMessageData(BaseModel):
    key: EvolutionMessageKey
    message: EvolutionMessageContent | None = None
    messageType: str = ""       # "conversation" | "imageMessage" | etc.
    pushName: str | None = None # nome exibido do remetente


class EvolutionWebhookPayload(BaseModel):
    event: str = ""             # "messages.upsert" | "connection.update" | etc.
    instance: str = ""
    data: EvolutionMessageData
