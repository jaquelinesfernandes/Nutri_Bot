"""
Testes do webhook WhatsApp (Meta Cloud API).

Cobre:
  - GET  /webhook/whatsapp  — verificação do hub challenge
  - POST /webhook/whatsapp  — recebimento de mensagens (texto, imagem, áudio)
  - Validação HMAC-SHA256
  - Deduplicação de mensagens (_SEEN_MESSAGE_IDS)
  - Comportamento sem credenciais configuradas
"""
from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


# ── fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def client():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture(autouse=True)
def configure_whatsapp(monkeypatch):
    """Garante que WhatsApp esteja configurado para todos os testes."""
    monkeypatch.setattr(settings, "whatsapp_verify_token", "test_verify_token")
    monkeypatch.setattr(settings, "whatsapp_access_token", "test_access_token")
    monkeypatch.setattr(settings, "whatsapp_phone_number_id", "111222333444")
    monkeypatch.setattr(settings, "whatsapp_app_secret", "test_app_secret")


@pytest.fixture(autouse=True)
def reset_seen_ids():
    """Limpa deque de IDs vistos antes de cada teste."""
    from app.routers.webhook_whatsapp import _SEEN_MESSAGE_IDS
    _SEEN_MESSAGE_IDS.clear()
    yield
    _SEEN_MESSAGE_IDS.clear()


def _make_hmac_header(body: bytes, secret: str = "test_app_secret") -> str:
    """Gera header X-Hub-Signature-256 válido."""
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={sig}"


def _text_payload(msg_id: str = "wamid.001", text: str = "arroz com feijão") -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "ENTRY_ID",
            "changes": [{
                "field": "messages",
                "value": {
                    "messaging_product": "whatsapp",
                    "contacts": [{"profile": {"name": "Ana Teste"}, "wa_id": "5511999999999"}],
                    "messages": [{
                        "id": msg_id,
                        "from": "5511999999999",
                        "timestamp": "1700000000",
                        "type": "text",
                        "text": {"body": text}
                    }]
                }
            }]
        }]
    }


# ── GET /webhook/whatsapp ─────────────────────────────────────────────────────

class TestVerifyWebhook:

    def test_responde_com_challenge_correto(self, client):
        r = client.get(
            "/webhook/whatsapp",
            params={
                "hub.mode": "subscribe",
                "hub.challenge": "987654",
                "hub.verify_token": "test_verify_token",
            }
        )
        assert r.status_code == 200
        assert r.json() == 987654

    def test_rejeita_verify_token_errado(self, client):
        r = client.get(
            "/webhook/whatsapp",
            params={
                "hub.mode": "subscribe",
                "hub.challenge": "12345",
                "hub.verify_token": "token_errado",
            }
        )
        assert r.status_code == 403

    def test_rejeita_modo_diferente_de_subscribe(self, client):
        r = client.get(
            "/webhook/whatsapp",
            params={
                "hub.mode": "unsubscribe",
                "hub.challenge": "12345",
                "hub.verify_token": "test_verify_token",
            }
        )
        assert r.status_code == 403

    def test_sem_verify_token_configurado_retorna_503(self, client, monkeypatch):
        monkeypatch.setattr(settings, "whatsapp_verify_token", "")
        r = client.get(
            "/webhook/whatsapp",
            params={
                "hub.mode": "subscribe",
                "hub.challenge": "123",
                "hub.verify_token": "",
            }
        )
        assert r.status_code == 503

    def test_challenge_numerico_retorna_inteiro(self, client):
        r = client.get(
            "/webhook/whatsapp",
            params={
                "hub.mode": "subscribe",
                "hub.challenge": "42",
                "hub.verify_token": "test_verify_token",
            }
        )
        assert r.status_code == 200
        assert r.json() == 42


# ── POST /webhook/whatsapp — HMAC ─────────────────────────────────────────────

class TestHmacValidation:

    @patch("app.routers.webhook_whatsapp._process_payload", new_callable=AsyncMock)
    def test_aceita_assinatura_hmac_valida(self, mock_proc, client):
        body = json.dumps(_text_payload()).encode()
        r = client.post(
            "/webhook/whatsapp",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": _make_hmac_header(body),
            }
        )
        assert r.status_code == 200

    @patch("app.routers.webhook_whatsapp._process_payload", new_callable=AsyncMock)
    def test_rejeita_assinatura_hmac_invalida(self, mock_proc, client):
        body = json.dumps(_text_payload()).encode()
        r = client.post(
            "/webhook/whatsapp",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": "sha256=invalido",
            }
        )
        assert r.status_code == 403

    @patch("app.routers.webhook_whatsapp._process_payload", new_callable=AsyncMock)
    def test_aceita_sem_assinatura_quando_app_secret_vazio(self, mock_proc, client, monkeypatch):
        monkeypatch.setattr(settings, "whatsapp_app_secret", "")
        body = json.dumps(_text_payload()).encode()
        r = client.post(
            "/webhook/whatsapp",
            content=body,
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 200

    @patch("app.routers.webhook_whatsapp._process_payload", new_callable=AsyncMock)
    def test_sem_header_assinatura_rejeita_quando_secret_configurado(self, mock_proc, client):
        body = json.dumps(_text_payload()).encode()
        r = client.post(
            "/webhook/whatsapp",
            content=body,
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 403

    @patch("app.routers.webhook_whatsapp._process_payload", new_callable=AsyncMock)
    def test_retorna_dict_vazio_em_sucesso(self, mock_proc, client):
        body = json.dumps(_text_payload()).encode()
        r = client.post(
            "/webhook/whatsapp",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": _make_hmac_header(body),
            }
        )
        assert r.json() == {}


# ── Processamento de mensagens ────────────────────────────────────────────────

class TestProcessMessage:

    @patch("app.routers.webhook_whatsapp.AsyncSessionLocal")
    @patch("app.routers.webhook_whatsapp._send_whatsapp_text", new_callable=AsyncMock)
    async def test_ignora_tipo_nao_suportado(self, mock_send, mock_db):
        from app.routers.webhook_whatsapp import _process_message
        msg = {"id": "wamid.X", "from": "5511999999999", "type": "sticker"}
        # Não deve chamar send nem levantar exceção
        await _process_message(msg, [])
        mock_send.assert_not_called()

    @patch("app.routers.webhook_whatsapp.AsyncSessionLocal")
    @patch("app.routers.webhook_whatsapp._send_whatsapp_text", new_callable=AsyncMock)
    async def test_ignora_from_vazio(self, mock_send, mock_db):
        from app.routers.webhook_whatsapp import _process_message
        msg = {"id": "wamid.Y", "from": "", "type": "text", "text": {"body": "oi"}}
        await _process_message(msg, [])
        mock_send.assert_not_called()

    async def test_deduplicacao_ignora_mensagem_repetida(self):
        from app.routers.webhook_whatsapp import _SEEN_MESSAGE_IDS, _process_message

        # Pré-carrega ID
        _SEEN_MESSAGE_IDS.append("wamid.DUP")

        with patch("app.routers.webhook_whatsapp.AsyncSessionLocal") as mock_db, \
             patch("app.routers.webhook_whatsapp._send_whatsapp_text", new_callable=AsyncMock) as mock_send:
            msg = {"id": "wamid.DUP", "from": "5511999999999", "type": "text", "text": {"body": "oi"}}
            await _process_message(msg, [])
            mock_db.assert_not_called()
            mock_send.assert_not_called()

    async def test_deduplicacao_registra_novo_id(self):
        from app.routers.webhook_whatsapp import _SEEN_MESSAGE_IDS

        assert "wamid.NEW" not in _SEEN_MESSAGE_IDS

        mock_db_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        mock_db_session.flush = AsyncMock()
        mock_db_session.commit = AsyncMock()
        mock_db_session.add = MagicMock()

        ctx_manager = MagicMock()
        ctx_manager.__aenter__ = AsyncMock(return_value=mock_db_session)
        ctx_manager.__aexit__ = AsyncMock(return_value=False)

        with patch("app.routers.webhook_whatsapp.AsyncSessionLocal", return_value=ctx_manager), \
             patch("app.routers.webhook_whatsapp._send_whatsapp_text", new_callable=AsyncMock), \
             patch("app.services.conversation.conversation_service") as mock_conv, \
             patch("app.services.notification.notification_service") as mock_notif:
            mock_conv.handle_message = AsyncMock(return_value="Registrado!")
            mock_notif.send_text = AsyncMock()

            from app.routers.webhook_whatsapp import _process_message
            msg = {"id": "wamid.NEW", "from": "5511999999999", "type": "text", "text": {"body": "oi"}}
            await _process_message(msg, [{"wa_id": "5511999999999", "profile": {"name": "Ana"}}])

        assert "wamid.NEW" in _SEEN_MESSAGE_IDS


# ── _process_payload ──────────────────────────────────────────────────────────

class TestProcessPayload:

    async def test_ignora_campo_diferente_de_messages(self):
        from app.routers.webhook_whatsapp import _process_payload
        payload = {
            "entry": [{
                "changes": [{"field": "statuses", "value": {}}]
            }]
        }
        # Não deve levantar, nem chamar _process_message
        with patch("app.routers.webhook_whatsapp._process_message", new_callable=AsyncMock) as mock_pm:
            await _process_payload(payload)
            mock_pm.assert_not_called()

    async def test_payload_vazio_nao_levanta(self):
        from app.routers.webhook_whatsapp import _process_payload
        await _process_payload({})  # deve ser silencioso


# ── _extract_name ─────────────────────────────────────────────────────────────

class TestExtractName:

    def test_extrai_nome_correto(self):
        from app.routers.webhook_whatsapp import _extract_name
        contacts = [
            {"wa_id": "5511111", "profile": {"name": "Maria"}},
            {"wa_id": "5522222", "profile": {"name": "João"}},
        ]
        assert _extract_name(contacts, "5522222") == "João"

    def test_retorna_none_quando_nao_encontrado(self):
        from app.routers.webhook_whatsapp import _extract_name
        assert _extract_name([], "5511111") is None

    def test_retorna_none_wa_id_errado(self):
        from app.routers.webhook_whatsapp import _extract_name
        contacts = [{"wa_id": "5511111", "profile": {"name": "Ana"}}]
        assert _extract_name(contacts, "5599999") is None


# ── _send_whatsapp_text ───────────────────────────────────────────────────────

class TestSendWhatsappText:

    async def test_retorna_false_sem_token(self, monkeypatch):
        monkeypatch.setattr(settings, "whatsapp_access_token", "")
        from app.routers.webhook_whatsapp import _send_whatsapp_text
        result = await _send_whatsapp_text("5511999999999", "teste")
        assert result is False

    async def test_retorna_false_sem_phone_id(self, monkeypatch):
        monkeypatch.setattr(settings, "whatsapp_phone_number_id", "")
        from app.routers.webhook_whatsapp import _send_whatsapp_text
        result = await _send_whatsapp_text("5511999999999", "teste")
        assert result is False

    async def test_retorna_true_em_resposta_200(self):
        from app.routers.webhook_whatsapp import _send_whatsapp_text
        import httpx

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
            result = await _send_whatsapp_text("5511999999999", "mensagem de teste")
            assert result is True

    async def test_retorna_false_em_erro_de_rede(self):
        from app.routers.webhook_whatsapp import _send_whatsapp_text

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, side_effect=Exception("rede")):
            result = await _send_whatsapp_text("5511999999999", "teste")
            assert result is False
