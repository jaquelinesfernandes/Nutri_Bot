"""
Testes para app/services/conversation/_handlers_b2b.py — convite nutricionista e revogação LGPD.
Usa ConversationService diretamente, sem DB real (AsyncMock).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from app.services.conversation import ConversationService


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_user(
    state: str = "IDLE",
    state_data: dict | None = None,
    state_expires_at: datetime | None = None,
) -> MagicMock:
    u = MagicMock()
    u.id = uuid.uuid4()
    u.channel_id = "tg:77777"
    u.channel_type = "telegram"
    u.first_name = "Maria"
    u.plan = "free"
    u.is_premium = False
    u.alerts_enabled = True
    u.alerts_paused_until = None
    u.onboarding_complete = True
    u.daily_calorie_goal = 2000
    u.goal_type = "manter"
    u.report_frequency = "weekly"
    u.conversation_state = state
    u.state_data = state_data
    u.state_expires_at = state_expires_at
    u.plan_expires_at = None
    u.created_at = datetime(2026, 1, 1, tzinfo=ZoneInfo("UTC"))
    u.lgpd_consent_at = datetime(2026, 1, 1, tzinfo=ZoneInfo("UTC"))
    return u


def _make_db() -> AsyncMock:
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.add = MagicMock()
    db.delete = AsyncMock()
    return db


def _db_returning(obj) -> AsyncMock:
    """DB que retorna `obj` no primeiro scalar_one_or_none."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = obj
    result.scalars.return_value.all.return_value = []
    db = _make_db()
    db.execute = AsyncMock(return_value=result)
    return db


@pytest.fixture
def svc() -> ConversationService:
    return ConversationService()


# ── _iniciar_convite ──────────────────────────────────────────────────────────

class TestIniciarConvite:
    @pytest.mark.asyncio
    async def test_token_invalido_retorna_erro(self, svc):
        user = _make_user()
        db = _db_returning(None)  # NutritionistPatient não encontrado

        result = await svc._iniciar_convite(user, "token-invalido", db)

        assert "inválido" in result or "expirado" in result

    @pytest.mark.asyncio
    async def test_convite_ja_aceito_retorna_mensagem(self, svc):
        link = MagicMock()
        link.status = "active"
        db = _db_returning(link)

        result = await svc._iniciar_convite(_make_user(), "tok", db)

        assert "aceito" in result.lower()

    @pytest.mark.asyncio
    async def test_convite_expirado_marca_status(self, svc):
        link = MagicMock()
        link.status = "pending"
        link.expires_at = datetime(2020, 1, 1, tzinfo=timezone.utc)

        db = _make_db()
        call_count = 0

        async def _execute(query, *args, **kwargs):
            nonlocal call_count
            result = MagicMock()
            result.scalar_one_or_none.return_value = link if call_count == 0 else None
            call_count += 1
            return result

        db.execute = _execute
        user = _make_user()

        result = await svc._iniciar_convite(user, "tok", db)

        assert "expirou" in result.lower()
        assert link.status == "expired"

    @pytest.mark.asyncio
    async def test_convite_valido_seta_estado_invite_pending(self, svc):
        link = MagicMock()
        link.status = "pending"
        link.expires_at = datetime.now(timezone.utc) + timedelta(days=3)
        link.nutritionist_id = uuid.uuid4()

        nutri = MagicMock()
        nutri.first_name = "Dra. Paula"
        nutri.state_data = {"crn": "CRN-12345"}

        call_count = 0

        async def _execute(query, *args, **kwargs):
            nonlocal call_count
            result = MagicMock()
            if call_count == 0:
                result.scalar_one_or_none.return_value = link
            else:
                result.scalar_one_or_none.return_value = nutri
            call_count += 1
            return result

        db = _make_db()
        db.execute = _execute

        user = _make_user()
        result = await svc._iniciar_convite(user, "tok-valido", db)

        assert "Dra. Paula" in result
        assert user.conversation_state == "INVITE_PENDING"


# ── _handle_invite_pending ────────────────────────────────────────────────────

class TestHandleInvitePending:
    def _make_pending_user(self, token: str = "tok") -> MagicMock:
        future = datetime.now(ZoneInfo("UTC")) + timedelta(minutes=10)
        return _make_user(
            state="INVITE_PENDING",
            state_data={"invite_token": token, "nutri_name": "Dra. Paula"},
            state_expires_at=future,
        )

    @pytest.mark.asyncio
    async def test_aceitar_sim_ativa_link(self, svc):
        link = MagicMock()
        link.status = "pending"
        link.expires_at = datetime.now(timezone.utc) + timedelta(days=1)

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = link
        db = _make_db()
        db.execute = AsyncMock(return_value=result_mock)

        with patch("app.config.settings") as ms:
            ms.maintenance_mode = False
            result = await svc.handle_message(
                self._make_pending_user(), "text", "sim", db=db
            )

        assert link.status == "active"
        assert "Pronto" in result or "agora pode" in result

    @pytest.mark.asyncio
    async def test_recusar_nao_declina_link(self, svc):
        link = MagicMock()
        link.status = "pending"
        link.expires_at = datetime.now(timezone.utc) + timedelta(days=1)

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = link
        db = _make_db()
        db.execute = AsyncMock(return_value=result_mock)

        with patch("app.config.settings") as ms:
            ms.maintenance_mode = False
            result = await svc.handle_message(
                self._make_pending_user(), "text", "não", db=db
            )

        assert link.status == "declined"
        assert "recusado" in result.lower()

    @pytest.mark.asyncio
    async def test_resposta_invalida_mantem_estado(self, svc):
        user = self._make_pending_user()
        db = _make_db()

        with patch("app.config.settings") as ms:
            ms.maintenance_mode = False
            result = await svc.handle_message(user, "text", "talvez", db=db)

        assert user.conversation_state == "INVITE_PENDING"
        assert "SIM" in result or "NÃO" in result


# ── _handle_revoking ──────────────────────────────────────────────────────────

class TestHandleRevoking:
    def _make_revoking_user(self) -> MagicMock:
        link_id = str(uuid.uuid4())
        future = datetime.now(ZoneInfo("UTC")) + timedelta(minutes=10)
        return _make_user(
            state="REVOKING",
            state_data={"link_id": link_id, "nutri_name": "Dra. Paula"},
            state_expires_at=future,
        )

    @pytest.mark.asyncio
    async def test_confirmar_revoga_link(self, svc):
        user = self._make_revoking_user()
        link = MagicMock()
        link.status = "active"

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = link
        db = _make_db()
        db.execute = AsyncMock(return_value=result_mock)

        with patch("app.config.settings") as ms:
            ms.maintenance_mode = False
            result = await svc.handle_message(user, "text", "sim", db=db)

        assert link.status == "revoked"
        assert link.revoked_at is not None
        assert "revogado" in result.lower()
        assert user.conversation_state == "IDLE"

    @pytest.mark.asyncio
    async def test_cancelar_nao_revoga(self, svc):
        user = self._make_revoking_user()
        db = _make_db()

        with patch("app.config.settings") as ms:
            ms.maintenance_mode = False
            result = await svc.handle_message(user, "text", "não", db=db)

        assert user.conversation_state == "IDLE"
        assert "cancelado" in result.lower()

    @pytest.mark.asyncio
    async def test_link_nao_encontrado_retorna_erro(self, svc):
        user = self._make_revoking_user()

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        db = _make_db()
        db.execute = AsyncMock(return_value=result_mock)

        with patch("app.config.settings") as ms:
            ms.maintenance_mode = False
            result = await svc.handle_message(user, "text", "sim", db=db)

        assert "não está mais ativo" in result or "revogado" in result.lower()

    @pytest.mark.asyncio
    async def test_resposta_invalida_mantem_revoking(self, svc):
        user = self._make_revoking_user()
        db = _make_db()

        with patch("app.config.settings") as ms:
            ms.maintenance_mode = False
            result = await svc.handle_message(user, "text", "quem sabe", db=db)

        assert user.conversation_state == "REVOKING"
        assert "SIM" in result or "NÃO" in result
