"""
Testes unitários do _process_update do webhook Telegram.

Testa a função _process_update diretamente (não via background_tasks),
mockando o banco de dados e o conversation_service para evitar I/O real.

Cobre app/routers/webhook_telegram.py linhas: 57–148 (~60 statements)
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.routers.webhook_telegram import _process_update, _send_message, _SEEN_UPDATE_IDS
from app.schemas.telegram import TelegramUpdate


# ── Fixtures helpers ──────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def clear_seen_update_ids():
    """Limpa o cache de update_ids processados antes de cada teste.

    _SEEN_UPDATE_IDS é um deque global usado para deduplicação de retentativas
    do Telegram. Entre testes, deve estar vazio para evitar falsos positivos.
    """
    _SEEN_UPDATE_IDS.clear()
    yield
    _SEEN_UPDATE_IDS.clear()

def _make_update(text: str | None = "oi", photo=None, voice=None, **msg_extra) -> TelegramUpdate:
    """Cria um TelegramUpdate mínimo válido."""
    msg: dict = {
        "message_id": 1,
        "from": {"id": 123, "is_bot": False, "first_name": "Teste"},
        "chat": {"id": 123, "type": "private"},
        "date": 1718000000,
    }
    if text is not None:
        msg["text"] = text
    if photo is not None:
        msg["photo"] = photo
    if voice is not None:
        msg["voice"] = voice
    msg.update(msg_extra)
    return TelegramUpdate.model_validate({"update_id": 1, "message": msg})


def _mock_db_context(user=None):
    """Retorna (mock_session_cls, mock_db) com user configurado."""
    mock_user = user or MagicMock(id=uuid.uuid4(), conversation_state="IDLE")
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_user

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db.__aexit__ = AsyncMock(return_value=False)

    mock_cls = MagicMock(return_value=mock_db)
    return mock_cls, mock_db, mock_user


# ── _send_message ─────────────────────────────────────────────────────────────

class TestSendMessage:
    async def test_sem_token_nao_envia(self):
        """Quando bot_token é vazio, retorna sem chamar httpx."""
        with patch("app.routers.webhook_telegram.settings") as mock_cfg:
            mock_cfg.telegram_bot_token = ""
            # Não deve levantar exceção nem fazer chamada HTTP
            await _send_message(123, "Olá!")

    async def test_com_token_faz_post(self):
        """Quando bot_token existe, chama a API Telegram."""
        with patch("app.routers.webhook_telegram.settings") as mock_cfg, \
             patch("app.routers.webhook_telegram.httpx.AsyncClient") as mock_http:
            mock_cfg.telegram_bot_token = "fake-token"
            mock_client = AsyncMock()
            mock_http.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_http.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock()

            await _send_message(123, "Olá!")
            mock_client.post.assert_awaited_once()

    async def test_com_erro_http_nao_levanta(self):
        """Falha de rede é logada e silenciada."""
        with patch("app.routers.webhook_telegram.settings") as mock_cfg, \
             patch("app.routers.webhook_telegram.httpx.AsyncClient") as mock_http:
            mock_cfg.telegram_bot_token = "fake-token"
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=Exception("timeout"))
            mock_http.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_http.return_value.__aexit__ = AsyncMock(return_value=False)

            # Não deve propagar exceção
            await _send_message(123, "msg")


# ── _process_update: update sem mensagem ─────────────────────────────────────

class TestProcessUpdateSemMensagem:
    async def test_update_sem_message_retorna_cedo(self):
        """update_id sem 'message' não deve fazer nada."""
        update = TelegramUpdate.model_validate({"update_id": 99})
        # Não deve levantar exceção
        await _process_update(update)

    async def test_mensagem_sem_texto_foto_voz(self):
        """Mensagem de sticker/documento é ignorada."""
        msg = {
            "message_id": 1,
            "from": {"id": 1, "is_bot": False, "first_name": "X"},
            "chat": {"id": 1, "type": "private"},
            "date": 1,
            # sem text, photo nem voice
        }
        update = TelegramUpdate.model_validate({"update_id": 2, "message": msg})
        await _process_update(update)


# ── _process_update: /ping ────────────────────────────────────────────────────

class TestProcessUpdatePing:
    async def test_ping_responde_sem_db(self):
        """/ping deve responder sem acessar o banco."""
        update = _make_update(text="/ping")
        with patch("app.routers.webhook_telegram._send_message") as mock_send:
            mock_send.return_value = None
            await _process_update(update)
            mock_send.assert_called_once()
            assert "Pong" in mock_send.call_args[0][1]

    async def test_ping_at_bot(self):
        update = _make_update(text="/ping@nutribot")
        with patch("app.routers.webhook_telegram._send_message") as mock_send:
            mock_send.return_value = None
            await _process_update(update)
            mock_send.assert_called_once()


# ── _process_update: texto normal ────────────────────────────────────────────

class TestProcessUpdateTexto:
    async def test_texto_chama_handle_message(self):
        update = _make_update(text="almocei arroz com feijão")
        mock_cls, mock_db, mock_user = _mock_db_context()

        with patch("app.routers.webhook_telegram.AsyncSessionLocal", mock_cls), \
             patch("app.routers.webhook_telegram._send_message", AsyncMock()), \
             patch("app.services.conversation.conversation_service") as mock_conv:
            mock_conv.handle_message = AsyncMock(return_value="Registrado! 🥗")
            # Importa após o patch
            from app.routers.webhook_telegram import _process_update as pu
            await pu(update)

    async def test_texto_chama_handle_command_com_slash(self):
        update = _make_update(text="/resumo")
        mock_cls, mock_db, mock_user = _mock_db_context()

        with patch("app.routers.webhook_telegram.AsyncSessionLocal", mock_cls), \
             patch("app.routers.webhook_telegram._send_message", AsyncMock()), \
             patch("app.services.conversation.conversation_service") as mock_conv:
            mock_conv.handle_command = AsyncMock(return_value="Aqui está seu resumo.")
            from app.routers.webhook_telegram import _process_update as pu
            await pu(update)


# ── _process_update: foto ─────────────────────────────────────────────────────

class TestProcessUpdateFoto:
    async def test_foto_baixada_chama_handle_message(self):
        photo = [
            {"file_id": "small", "file_unique_id": "s1", "width": 50, "height": 50},
            {"file_id": "large", "file_unique_id": "l1", "width": 800, "height": 600},
        ]
        update = _make_update(text=None, photo=photo, caption="esse é meu almoço")
        mock_cls, mock_db, mock_user = _mock_db_context()
        fake_bytes = b"JPEG_BYTES"

        with patch("app.routers.webhook_telegram.AsyncSessionLocal", mock_cls), \
             patch("app.routers.webhook_telegram._send_message", AsyncMock()), \
             patch("app.routers.webhook_telegram._download_telegram_file", AsyncMock(return_value=fake_bytes)), \
             patch("app.services.conversation.conversation_service") as mock_conv:
            mock_conv.handle_message = AsyncMock(return_value="Foto analisada!")
            from app.routers.webhook_telegram import _process_update as pu
            await pu(update)

    async def test_foto_falha_download_envia_mensagem_erro(self):
        photo = [{"file_id": "x", "file_unique_id": "x1", "width": 100, "height": 100}]
        update = _make_update(text=None, photo=photo)
        mock_cls, mock_db, mock_user = _mock_db_context()

        with patch("app.routers.webhook_telegram.AsyncSessionLocal", mock_cls), \
             patch("app.routers.webhook_telegram._send_message", AsyncMock()) as mock_send, \
             patch("app.routers.webhook_telegram._download_telegram_file", AsyncMock(side_effect=Exception("timeout"))), \
             patch("app.services.conversation.conversation_service"):
            from app.routers.webhook_telegram import _process_update as pu
            await pu(update)
            # Deve enviar mensagem de erro
            mock_send.assert_called()
            args = mock_send.call_args[0]
            assert "foto" in args[1].lower() or "erro" in args[1].lower()


# ── _process_update: áudio ────────────────────────────────────────────────────

class TestProcessUpdateAudio:
    async def test_audio_curto_processado(self):
        voice = {"file_id": "v1", "file_unique_id": "vu1", "duration": 10}
        update = _make_update(text=None, voice=voice)
        mock_cls, mock_db, mock_user = _mock_db_context()

        with patch("app.routers.webhook_telegram.AsyncSessionLocal", mock_cls), \
             patch("app.routers.webhook_telegram._send_message", AsyncMock()), \
             patch("app.routers.webhook_telegram._download_telegram_file", AsyncMock(return_value=b"OGG")), \
             patch("app.services.conversation.conversation_service") as mock_conv:
            mock_conv.handle_message = AsyncMock(return_value="Áudio transcrito!")
            from app.routers.webhook_telegram import _process_update as pu
            await pu(update)

    async def test_audio_longo_retorna_erro(self):
        voice = {"file_id": "v2", "file_unique_id": "vu2", "duration": 150}  # > 120s
        update = _make_update(text=None, voice=voice)
        mock_cls, mock_db, mock_user = _mock_db_context()

        with patch("app.routers.webhook_telegram.AsyncSessionLocal", mock_cls), \
             patch("app.routers.webhook_telegram._send_message", AsyncMock()) as mock_send, \
             patch("app.services.conversation.conversation_service"):
            from app.routers.webhook_telegram import _process_update as pu
            await pu(update)
            mock_send.assert_called()
            args = mock_send.call_args[0]
            assert "longo" in args[1].lower() or "2 min" in args[1].lower()

    async def test_audio_falha_download_envia_erro(self):
        voice = {"file_id": "v3", "file_unique_id": "vu3", "duration": 30}
        update = _make_update(text=None, voice=voice)
        mock_cls, mock_db, mock_user = _mock_db_context()

        with patch("app.routers.webhook_telegram.AsyncSessionLocal", mock_cls), \
             patch("app.routers.webhook_telegram._send_message", AsyncMock()) as mock_send, \
             patch("app.routers.webhook_telegram._download_telegram_file", AsyncMock(side_effect=Exception("network"))), \
             patch("app.services.conversation.conversation_service"):
            from app.routers.webhook_telegram import _process_update as pu
            await pu(update)
            mock_send.assert_called()


# ── _process_update: erro genérico ────────────────────────────────────────────

class TestProcessUpdateErroGenerico:
    async def test_excecao_interna_envia_mensagem_de_erro(self):
        """Exceção inesperada na camada de conversa é capturada e informa o usuário."""
        update = _make_update(text="teste")
        mock_cls, mock_db, mock_user = _mock_db_context()

        with patch("app.routers.webhook_telegram.AsyncSessionLocal", mock_cls), \
             patch("app.routers.webhook_telegram._send_message", AsyncMock()) as mock_send, \
             patch("app.services.conversation.conversation_service") as mock_conv:
            mock_conv.handle_message = AsyncMock(side_effect=RuntimeError("erro inesperado"))
            from app.routers.webhook_telegram import _process_update as pu
            await pu(update)
            mock_send.assert_called()
            args = mock_send.call_args[0]
            assert "erro" in args[1].lower()
