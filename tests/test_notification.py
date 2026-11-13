"""
Testes do NotificationService.

Cobre:
  - send_text: Telegram, WhatsApp, canal desconhecido, exceção silenciosa
  - send_document: Telegram, WhatsApp (upload + send), falha upload
  - _send_telegram: sem token, HTTP 200, HTTP 4xx
  - _send_telegram_document: com e sem caption
  - _send_whatsapp: sem credenciais, HTTP 200, HTTP 4xx, exceção
  - _send_whatsapp_document: upload OK + send OK, upload falha
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_user(channel_type: str = "telegram", channel_id: str = "tg:123456") -> MagicMock:
    u = MagicMock()
    u.channel_type = channel_type
    u.channel_id = channel_id
    return u


def _mock_response(status_code: int = 200, json_data: dict | None = None) -> MagicMock:
    r = MagicMock()
    r.status_code = status_code
    r.text = "mock response"
    r.json.return_value = json_data or {}
    return r


# ── send_text ─────────────────────────────────────────────────────────────────

class TestSendText:

    @pytest.mark.asyncio
    async def test_telegram_sucesso(self, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "telegram_bot_token", "123:TOKEN")

        from app.services.notification import NotificationService
        svc = NotificationService()

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock,
                   return_value=_mock_response(200)):
            result = await svc.send_text(_make_user("telegram", "tg:999"), "Olá!")

        assert result is True

    @pytest.mark.asyncio
    async def test_telegram_falha_http(self, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "telegram_bot_token", "123:TOKEN")

        from app.services.notification import NotificationService
        svc = NotificationService()

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock,
                   return_value=_mock_response(400)):
            result = await svc.send_text(_make_user("telegram", "tg:999"), "Olá!")

        assert result is False

    @pytest.mark.asyncio
    async def test_telegram_sem_token_retorna_false(self, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "telegram_bot_token", "")

        from app.services.notification import NotificationService
        svc = NotificationService()
        result = await svc.send_text(_make_user("telegram", "tg:123"), "Olá!")
        assert result is False

    @pytest.mark.asyncio
    async def test_whatsapp_sucesso(self, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "whatsapp_access_token", "TOKEN")
        monkeypatch.setattr(settings, "whatsapp_phone_number_id", "111")

        from app.services.notification import NotificationService
        svc = NotificationService()

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock,
                   return_value=_mock_response(200)):
            result = await svc.send_text(
                _make_user("whatsapp", "wa:5511999999999"), "Olá!"
            )

        assert result is True

    @pytest.mark.asyncio
    async def test_whatsapp_sem_credenciais_retorna_false(self, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "whatsapp_access_token", "")
        monkeypatch.setattr(settings, "whatsapp_phone_number_id", "")

        from app.services.notification import NotificationService
        svc = NotificationService()
        result = await svc.send_text(
            _make_user("whatsapp", "wa:5511999999999"), "Olá!"
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_canal_desconhecido_retorna_false(self):
        from app.services.notification import NotificationService
        svc = NotificationService()
        result = await svc.send_text(_make_user("web", "web:123"), "Olá!")
        assert result is False

    @pytest.mark.asyncio
    async def test_excecao_silenciosa_retorna_false(self, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "telegram_bot_token", "123:TOKEN")

        from app.services.notification import NotificationService
        svc = NotificationService()

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock,
                   side_effect=Exception("rede caiu")):
            result = await svc.send_text(_make_user("telegram", "tg:123"), "Olá!")

        assert result is False


# ── _send_telegram ────────────────────────────────────────────────────────────

class TestSendTelegram:

    @pytest.mark.asyncio
    async def test_extrai_chat_id_do_channel_id(self, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "telegram_bot_token", "123:TOKEN")

        from app.services.notification import NotificationService
        svc = NotificationService()

        captured = {}

        async def mock_post(self, url, **kwargs):
            captured["json"] = kwargs.get("json", {})
            return _mock_response(200)

        with patch("httpx.AsyncClient.post", new=mock_post):
            await svc._send_telegram("tg:987654321", "teste")

        assert captured["json"]["chat_id"] == "987654321"

    @pytest.mark.asyncio
    async def test_channel_id_sem_prefixo(self, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "telegram_bot_token", "123:TOKEN")

        from app.services.notification import NotificationService
        svc = NotificationService()

        captured = {}

        async def mock_post(self, url, **kwargs):
            captured["json"] = kwargs.get("json", {})
            return _mock_response(200)

        with patch("httpx.AsyncClient.post", new=mock_post):
            await svc._send_telegram("987654321", "teste")

        assert captured["json"]["chat_id"] == "987654321"

    @pytest.mark.asyncio
    async def test_usa_parse_mode_markdown(self, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "telegram_bot_token", "123:TOKEN")

        from app.services.notification import NotificationService
        svc = NotificationService()

        captured = {}

        async def mock_post(self, url, **kwargs):
            captured["json"] = kwargs.get("json", {})
            return _mock_response(200)

        with patch("httpx.AsyncClient.post", new=mock_post):
            await svc._send_telegram("tg:123", "**bold**")

        assert captured["json"]["parse_mode"] == "Markdown"


# ── _send_telegram_document ───────────────────────────────────────────────────

class TestSendTelegramDocument:

    @pytest.mark.asyncio
    async def test_envia_documento_com_sucesso(self, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "telegram_bot_token", "123:TOKEN")

        from app.services.notification import NotificationService
        svc = NotificationService()

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock,
                   return_value=_mock_response(200)):
            result = await svc._send_telegram_document(
                "tg:123456", b"PDF_BYTES", "relatorio.pdf", "Seu relatório!"
            )

        assert result is True

    @pytest.mark.asyncio
    async def test_sem_token_retorna_false(self, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "telegram_bot_token", "")

        from app.services.notification import NotificationService
        svc = NotificationService()
        result = await svc._send_telegram_document("tg:123", b"PDF", "f.pdf", None)
        assert result is False

    @pytest.mark.asyncio
    async def test_envia_sem_caption(self, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "telegram_bot_token", "123:TOKEN")

        from app.services.notification import NotificationService
        svc = NotificationService()

        captured_data = {}

        async def mock_post(self, url, **kwargs):
            captured_data.update(kwargs.get("data", {}))
            return _mock_response(200)

        with patch("httpx.AsyncClient.post", new=mock_post):
            result = await svc._send_telegram_document("tg:123", b"PDF", "f.pdf", None)

        assert result is True
        assert "caption" not in captured_data


# ── _send_whatsapp ────────────────────────────────────────────────────────────

class TestSendWhatsapp:

    @pytest.mark.asyncio
    async def test_extrai_numero_do_channel_id(self, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "whatsapp_access_token", "TOKEN")
        monkeypatch.setattr(settings, "whatsapp_phone_number_id", "111")

        from app.services.notification import NotificationService
        svc = NotificationService()

        captured = {}

        async def mock_post(self, url, **kwargs):
            captured["json"] = kwargs.get("json", {})
            return _mock_response(200)

        with patch("httpx.AsyncClient.post", new=mock_post):
            await svc._send_whatsapp("wa:5511999999999", "Olá!")

        assert captured["json"]["to"] == "5511999999999"

    @pytest.mark.asyncio
    async def test_inclui_bearer_token_no_header(self, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "whatsapp_access_token", "MEU_TOKEN")
        monkeypatch.setattr(settings, "whatsapp_phone_number_id", "111")

        from app.services.notification import NotificationService
        svc = NotificationService()

        captured = {}

        async def mock_post(self, url, **kwargs):
            captured["headers"] = kwargs.get("headers", {})
            return _mock_response(200)

        with patch("httpx.AsyncClient.post", new=mock_post):
            await svc._send_whatsapp("wa:5511", "Olá!")

        assert captured["headers"].get("Authorization") == "Bearer MEU_TOKEN"

    @pytest.mark.asyncio
    async def test_retorna_false_em_excecao(self, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "whatsapp_access_token", "TOKEN")
        monkeypatch.setattr(settings, "whatsapp_phone_number_id", "111")

        from app.services.notification import NotificationService
        svc = NotificationService()

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock,
                   side_effect=Exception("timeout")):
            # send_text tem o try/except externo; _send_whatsapp propaga
            result = await svc.send_text(_make_user("whatsapp", "wa:5511"), "Olá!")

        assert result is False


# ── _send_whatsapp_document ───────────────────────────────────────────────────

class TestSendWhatsappDocument:

    @pytest.mark.asyncio
    async def test_upload_e_send_com_sucesso(self, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "whatsapp_access_token", "TOKEN")
        monkeypatch.setattr(settings, "whatsapp_phone_number_id", "111")

        from app.services.notification import NotificationService
        svc = NotificationService()

        upload_response = _mock_response(200, {"id": "MEDIA_ID_123"})
        send_response = _mock_response(200)

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock,
                   side_effect=[upload_response, send_response]):
            result = await svc._send_whatsapp_document(
                "wa:5511999999999", b"PDF", "relatorio.pdf", "Seu relatório"
            )

        assert result is True

    @pytest.mark.asyncio
    async def test_retorna_false_se_upload_falhar(self, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "whatsapp_access_token", "TOKEN")
        monkeypatch.setattr(settings, "whatsapp_phone_number_id", "111")

        from app.services.notification import NotificationService
        svc = NotificationService()

        upload_fail = _mock_response(500)

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock,
                   return_value=upload_fail):
            result = await svc._send_whatsapp_document(
                "wa:5511", b"PDF", "f.pdf", None
            )

        assert result is False

    @pytest.mark.asyncio
    async def test_retorna_false_sem_credenciais(self, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "whatsapp_access_token", "")
        monkeypatch.setattr(settings, "whatsapp_phone_number_id", "")

        from app.services.notification import NotificationService
        svc = NotificationService()
        result = await svc._send_whatsapp_document("wa:5511", b"PDF", "f.pdf", None)
        assert result is False

    @pytest.mark.asyncio
    async def test_send_document_delega_para_canal_correto(self):
        from app.services.notification import NotificationService
        svc = NotificationService()

        with patch.object(svc, "_send_telegram_document", new_callable=AsyncMock,
                          return_value=True) as mock_tg:
            result = await svc.send_document(
                _make_user("telegram", "tg:123"), b"PDF", "f.pdf", "caption"
            )
            mock_tg.assert_called_once()
        assert result is True

        with patch.object(svc, "_send_whatsapp_document", new_callable=AsyncMock,
                          return_value=True) as mock_wa:
            result = await svc.send_document(
                _make_user("whatsapp", "wa:5511"), b"PDF", "f.pdf", None
            )
            mock_wa.assert_called_once()
        assert result is True

    @pytest.mark.asyncio
    async def test_send_document_excecao_retorna_false(self):
        from app.services.notification import NotificationService
        svc = NotificationService()

        with patch.object(svc, "_send_telegram_document", new_callable=AsyncMock,
                          side_effect=Exception("rede")):
            result = await svc.send_document(
                _make_user("telegram", "tg:123"), b"PDF", "f.pdf", None
            )
        assert result is False
