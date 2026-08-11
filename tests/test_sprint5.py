"""
Testes Sprint 5: onboarding polish, novos comandos (/agua, /silenciar, /desfazer),
timeout de estado, /start para usuário retornando, /ajuda contextual.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from app.services.conversation import ConversationService


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_user(
    plan: str = "free",
    first_name: str = "Ana",
    onboarding_complete: bool = True,
    alerts_enabled: bool = True,
    channel_type: str = "telegram",
    channel_id: str = "tg:55555",
    timezone: str = "America/Sao_Paulo",
    daily_calorie_goal: int | None = 2000,
    goal_type: str | None = "manter",
    conversation_state: str = "IDLE",
    state_expires_at: datetime | None = None,
    report_frequency: str = "weekly",
) -> MagicMock:
    user = MagicMock()
    user.id = uuid.uuid4()
    user.channel_id = channel_id
    user.channel_type = channel_type
    user.timezone = timezone
    user.daily_calorie_goal = daily_calorie_goal
    user.goal_type = goal_type
    user.plan = plan
    user.plan_expires_at = None
    user.first_name = first_name
    user.is_premium = plan != "free"
    user.alerts_enabled = alerts_enabled
    user.alerts_paused_until = None
    user.onboarding_complete = onboarding_complete
    user.report_frequency = report_frequency
    user.conversation_state = conversation_state
    user.state_data = None
    user.state_expires_at = state_expires_at
    user.created_at = datetime(2026, 6, 1, tzinfo=ZoneInfo("UTC"))
    user.lgpd_consent_at = datetime(2026, 6, 1, tzinfo=ZoneInfo("UTC"))
    return user


def _make_db() -> AsyncMock:
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()
    db.delete = AsyncMock()
    return db


def _make_meal_log(meal_type: str = "lunch", kcal: float = 600.0) -> MagicMock:
    log = MagicMock()
    log.id = uuid.uuid4()
    log.meal_type = meal_type
    log.total_calories_kcal = kcal
    log.total_protein_g = 30.0
    log.total_carb_g = 70.0
    log.total_fat_g = 15.0
    log.logged_at = datetime(2026, 6, 26, 12, 0, tzinfo=ZoneInfo("UTC"))
    return log


@pytest.fixture
def svc() -> ConversationService:
    return ConversationService()


# ── Estado expirado ───────────────────────────────────────────────────────────

class TestStateTimeout:
    @pytest.mark.asyncio
    async def test_expired_confirming_resets_to_idle(self, svc):
        expired = datetime.now(ZoneInfo("UTC")) - timedelta(minutes=15)
        user = _make_user(conversation_state="CONFIRMING", state_expires_at=expired)
        db = _make_db()

        with patch("app.config.settings") as mock_s:
            mock_s.maintenance_mode = False
            result = await svc.handle_message(user, "text", "sim", db=db)

        assert "expirou" in result.lower()
        assert user.conversation_state == "IDLE"
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_non_expired_confirming_proceeds(self, svc):
        not_expired = datetime.now(ZoneInfo("UTC")) + timedelta(minutes=5)
        user = _make_user(conversation_state="CONFIRMING", state_expires_at=not_expired)
        user.state_data = None
        db = _make_db()

        with patch("app.config.settings") as mock_s:
            mock_s.maintenance_mode = False
            result = await svc.handle_message(user, "text", "sim", db=db)

        assert "expirou" not in result.lower()

    @pytest.mark.asyncio
    async def test_no_expires_at_does_not_reset(self, svc):
        user = _make_user(conversation_state="CONFIRMING", state_expires_at=None)
        user.state_data = None
        db = _make_db()

        with patch("app.config.settings") as mock_s:
            mock_s.maintenance_mode = False
            result = await svc.handle_message(user, "text", "sim", db=db)

        assert "expirou" not in result.lower()


# ── /start para usuário retornando ────────────────────────────────────────────

class TestCmdStartReturning:
    @pytest.mark.asyncio
    async def test_start_returning_sem_refeicoes_hoje(self, svc):
        user = _make_user(onboarding_complete=True)
        db = _make_db()

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        db.execute.return_value = mock_result

        result = await svc._cmd_start(user, None, db)

        assert "Olá de novo" in result
        assert "Ana" in result
        assert "Nenhuma" in result or "comeu" in result.lower()

    @pytest.mark.asyncio
    async def test_start_returning_com_refeicoes_hoje(self, svc):
        user = _make_user(onboarding_complete=True)
        db = _make_db()

        log = _make_meal_log(kcal=600.0)
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [log]
        db.execute.return_value = mock_result

        result = await svc._cmd_start(user, None, db)

        assert "Olá de novo" in result
        assert "600" in result
        assert "Hoje" in result or "hoje" in result

    @pytest.mark.asyncio
    async def test_start_returning_mostra_barra_de_meta(self, svc):
        user = _make_user(onboarding_complete=True, daily_calorie_goal=2000)
        db = _make_db()

        log = _make_meal_log(kcal=1000.0)
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [log]
        db.execute.return_value = mock_result

        result = await svc._cmd_start(user, None, db)

        assert "%" in result
        assert "50" in result  # 1000/2000 = 50%

    @pytest.mark.asyncio
    async def test_start_novo_usuario_inicia_onboarding(self, svc):
        user = _make_user(onboarding_complete=False)
        db = _make_db()

        result = await svc._cmd_start(user, None, db)

        assert "NutriBot" in result
        assert "nome" in result.lower()
        db.commit.assert_called_once()


# ── /ajuda contextual ─────────────────────────────────────────────────────────

class TestCmdAjuda:
    @pytest.mark.asyncio
    async def test_ajuda_free_mostra_upgrade(self, svc):
        user = _make_user(plan="free")
        result = await svc._cmd_ajuda(user, None, None)
        assert "/premium" in result
        assert "foto" in result.lower() or "Premium" in result

    @pytest.mark.asyncio
    async def test_ajuda_premium_sem_upgrade_hint(self, svc):
        user = _make_user(plan="premium")
        result = await svc._cmd_ajuda(user, None, None)
        # Premium version doesn't need the upgrade CTA
        assert "/relatorio" in result
        assert "/frequencia" in result

    @pytest.mark.asyncio
    async def test_ajuda_contem_comandos_basicos(self, svc):
        user = _make_user(plan="free")
        result = await svc._cmd_ajuda(user, None, None)
        assert "/hoje" in result
        assert "/historico" in result
        assert "/meta" in result
        assert "/cancelar" in result
        assert "/agua" in result
        assert "/desfazer" in result
        assert "/silenciar" in result

    @pytest.mark.asyncio
    async def test_ajuda_premium_contem_relatorios(self, svc):
        user = _make_user(plan="premium")
        result = await svc._cmd_ajuda(user, None, None)
        assert "/relatorios" in result
        assert "/frequencia" in result


# ── /agua ─────────────────────────────────────────────────────────────────────

class TestCmdAgua:
    @pytest.mark.asyncio
    async def test_agua_default_250ml(self, svc):
        user = _make_user()
        db = _make_db()

        total_result = MagicMock()
        total_result.scalar_one_or_none.return_value = 250.0
        db.execute.return_value = total_result

        result = await svc._cmd_agua(user, None, db)

        assert "250" in result
        assert "💧" in result
        db.add.assert_called_once()
        db.flush.assert_called_once()
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_agua_com_quantidade_informada(self, svc):
        user = _make_user()
        db = _make_db()

        total_result = MagicMock()
        total_result.scalar_one_or_none.return_value = 500.0
        db.execute.return_value = total_result

        result = await svc._cmd_agua(user, "500", db)

        assert "500" in result

    @pytest.mark.asyncio
    async def test_agua_limita_5000ml(self, svc):
        user = _make_user()
        db = _make_db()

        total_result = MagicMock()
        total_result.scalar_one_or_none.return_value = 5000.0
        db.execute.return_value = total_result

        # Tentar registrar 9999ml deve ser limitado a 5000ml
        result = await svc._cmd_agua(user, "9999", db)
        added = db.add.call_args[0][0]
        assert added.volume_ml == 5000.0

    @pytest.mark.asyncio
    async def test_agua_sem_resultado_anterior_usa_ml_atual(self, svc):
        user = _make_user()
        db = _make_db()

        total_result = MagicMock()
        total_result.scalar_one_or_none.return_value = None  # sem registros anteriores
        db.execute.return_value = total_result

        result = await svc._cmd_agua(user, "300", db)

        assert "300" in result
        assert "💧" in result


# ── /silenciar ────────────────────────────────────────────────────────────────

class TestCmdSilenciar:
    @pytest.mark.asyncio
    async def test_silenciar_default_8h(self, svc):
        user = _make_user()
        db = _make_db()

        result = await svc._cmd_silenciar(user, None, db)

        assert "8h" in result
        assert "🔕" in result
        assert user.alerts_paused_until is not None
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_silenciar_com_horas_informadas(self, svc):
        user = _make_user()
        db = _make_db()

        result = await svc._cmd_silenciar(user, "2", db)

        assert "2h" in result

    @pytest.mark.asyncio
    async def test_silenciar_limita_72h(self, svc):
        user = _make_user()
        db = _make_db()

        await svc._cmd_silenciar(user, "999", db)

        # Deve estar 72h no futuro (com margem de 1 min)
        now_utc = datetime.now(ZoneInfo("UTC"))
        diff = user.alerts_paused_until - now_utc
        assert diff.total_seconds() <= 72 * 3600 + 60

    @pytest.mark.asyncio
    async def test_silenciar_mostra_horario_retomada(self, svc):
        user = _make_user()
        db = _make_db()

        result = await svc._cmd_silenciar(user, "4", db)

        assert ":" in result  # horário no formato HH:MM


# ── /desfazer ────────────────────────────────────────────────────────────────

class TestCmdDesfazer:
    @pytest.mark.asyncio
    async def test_desfazer_sem_refeicoes_hoje(self, svc):
        user = _make_user()
        db = _make_db()

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        db.execute.return_value = mock_result

        result = await svc._cmd_desfazer(user, None, db)

        assert "Não há" in result or "nenhuma" in result.lower()
        db.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_desfazer_apaga_ultima_refeicao(self, svc):
        user = _make_user()
        db = _make_db()

        log = _make_meal_log(meal_type="lunch", kcal=650.0)
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [log]
        db.execute.return_value = mock_result

        with patch("app.services.analytics.meal_deleted"):
            result = await svc._cmd_desfazer(user, None, db)

        db.delete.assert_called_once_with(log)
        db.commit.assert_called_once()
        assert "650" in result
        assert "↩️" in result

    @pytest.mark.asyncio
    async def test_desfazer_apaga_a_ultima_de_multiplas(self, svc):
        user = _make_user()
        db = _make_db()

        log1 = _make_meal_log(meal_type="breakfast", kcal=400.0)
        log2 = _make_meal_log(meal_type="lunch", kcal=700.0)
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [log1, log2]
        db.execute.return_value = mock_result

        with patch("app.services.analytics.meal_deleted"):
            result = await svc._cmd_desfazer(user, None, db)

        # Deve ter deletado o último (lunch)
        db.delete.assert_called_once_with(log2)
        assert "700" in result

    @pytest.mark.asyncio
    async def test_desfazer_dispara_analytics(self, svc):
        user = _make_user()
        db = _make_db()

        log = _make_meal_log()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [log]
        db.execute.return_value = mock_result

        with patch("app.services.analytics.meal_deleted") as mock_analytics:
            await svc._cmd_desfazer(user, None, db)

        mock_analytics.assert_called_once_with(user.channel_id)


# ── _set_timed_state ──────────────────────────────────────────────────────────

class TestSetTimedState:
    def test_confirming_tem_10_min(self, svc):
        user = _make_user()
        svc._set_timed_state(user, "CONFIRMING")

        assert user.conversation_state == "CONFIRMING"
        now = datetime.now(ZoneInfo("UTC"))
        diff = user.state_expires_at - now
        assert 9 * 60 < diff.total_seconds() <= 10 * 60 + 5

    def test_correcting_tem_5_min(self, svc):
        user = _make_user()
        svc._set_timed_state(user, "CORRECTING")

        assert user.conversation_state == "CORRECTING"
        now = datetime.now(ZoneInfo("UTC"))
        diff = user.state_expires_at - now
        assert 4 * 60 < diff.total_seconds() <= 5 * 60 + 5

    def test_deleting_tem_5_min(self, svc):
        user = _make_user()
        svc._set_timed_state(user, "DELETING")

        now = datetime.now(ZoneInfo("UTC"))
        diff = user.state_expires_at - now
        assert 4 * 60 < diff.total_seconds() <= 5 * 60 + 5

    def test_idle_sem_expires(self, svc):
        user = _make_user()
        svc._set_timed_state(user, "IDLE")

        assert user.conversation_state == "IDLE"
        assert user.state_expires_at is None


# ── Onboarding completion ─────────────────────────────────────────────────────

class TestOnboardingCompletion:
    @pytest.mark.asyncio
    async def test_completion_message_has_momento_uau(self, svc):
        user = _make_user(onboarding_complete=False, conversation_state="ONBOARDING")
        user.state_data = {
            "step": 2,
            "name": "Carlos",
            "goal_type": "manter",
            "goal_label": "manter o peso",
            "suggested_kcal": 2000,
        }
        db = _make_db()

        with patch("app.services.analytics.onboarding_completed"):
            result = await svc._handle_onboarding(user, "ok", db)

        assert "🎊" in result
        assert "Carlos" in result
        assert "2000" in result
        assert "✅" in result
        assert "09:30" in result  # alertas mostrados

    @pytest.mark.asyncio
    async def test_completion_message_shows_example(self, svc):
        user = _make_user(onboarding_complete=False, conversation_state="ONBOARDING")
        user.state_data = {
            "step": 2,
            "name": "Maria",
            "goal_type": "perder_peso",
            "goal_label": "perder peso",
            "suggested_kcal": 1500,
        }
        db = _make_db()

        with patch("app.services.analytics.onboarding_completed"):
            result = await svc._handle_onboarding(user, "1500", db)

        assert "arroz" in result.lower() or "refeição" in result.lower()
        assert "/ajuda" in result


# ── /handle_confirming — mensagem de erro melhorada ──────────────────────────

class TestConfirmingFallback:
    @pytest.mark.asyncio
    async def test_confirming_resposta_ambigua_orienta(self, svc):
        user = _make_user(conversation_state="CONFIRMING")
        user.state_data = {
            "pending_action": "confirm_meal",
            "meal_type": "lunch",
            "total_calories_kcal": 500.0,
            "total_protein_g": 20.0,
            "total_carb_g": 60.0,
            "total_fat_g": 10.0,
            "total_fiber_g": 5.0,
            "food_items": [],
        }
        db = _make_db()

        result = await svc._handle_confirming(user, "talvez", db)

        assert "sim" in result.lower()
        assert "não" in result.lower()
        assert "/cancelar" in result
