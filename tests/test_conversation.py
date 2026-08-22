"""
Testes unitários do ConversationService — Sprint 1.
Usa mocks para DB e serviços externos (AI, nutrition).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.conversation import ConversationService, CONFIRM_WORDS, DENY_WORDS


# ── Fixtures ───────────────────────────────────────────────────────────────────

def _make_user(
    state: str = "IDLE",
    state_data: dict | None = None,
    onboarding_complete: bool = True,
    daily_calorie_goal: int | None = None,
    plan: str = "free",
    first_name: str | None = "Teste",
) -> MagicMock:
    user = MagicMock()
    user.id = uuid.uuid4()
    user.channel_id = "tg:12345"
    user.channel_type = "telegram"
    user.conversation_state = state
    user.state_data = state_data
    user.onboarding_complete = onboarding_complete
    user.daily_calorie_goal = daily_calorie_goal
    user.first_name = first_name
    user.plan = plan
    user.plan_expires_at = None
    user.timezone = "America/Sao_Paulo"
    user.is_premium = plan != "free"
    return user


def _make_db() -> AsyncMock:
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()
    return db


@pytest.fixture
def svc() -> ConversationService:
    return ConversationService()


# ── Testes de comandos simples ─────────────────────────────────────────────────

class TestCmdAjuda:
    @pytest.mark.asyncio
    async def test_ajuda_free_user(self, svc):
        user = _make_user(plan="free")
        result = await svc._cmd_ajuda(user, None, None)
        assert "/hoje" in result
        assert "/premium" in result

    @pytest.mark.asyncio
    async def test_ajuda_premium_user(self, svc):
        user = _make_user(plan="premium")
        user.is_premium = True
        result = await svc._cmd_ajuda(user, None, None)
        assert "/hoje" in result
        assert "/premium" not in result


class TestCmdPlano:
    @pytest.mark.asyncio
    async def test_plano_free(self, svc):
        user = _make_user(plan="free")
        result = await svc._cmd_plano(user, None, None)
        assert "Gratuito" in result

    @pytest.mark.asyncio
    async def test_plano_premium_sem_validade(self, svc):
        user = _make_user(plan="premium")
        user.is_premium = True
        result = await svc._cmd_plano(user, None, None)
        assert "Premium" in result


class TestCmdPrivacidade:
    @pytest.mark.asyncio
    async def test_privacidade_menciona_lgpd(self, svc):
        user = _make_user()
        result = await svc._cmd_privacidade(user, None, None)
        assert "LGPD" in result
        assert "deletar" in result.lower() or "Deletar" in result


class TestCmdFeedback:
    @pytest.mark.asyncio
    async def test_sem_args_pede_texto(self, svc):
        user = _make_user()
        result = await svc._cmd_feedback(user, None, None)
        assert "feedback" in result.lower()

    @pytest.mark.asyncio
    async def test_com_args_agradece(self, svc):
        user = _make_user()
        result = await svc._cmd_feedback(user, "Bot muito bom!", None)
        assert "Obrigado" in result or "feedback" in result.lower()


class TestCmdMeta:
    @pytest.mark.asyncio
    async def test_set_meta_valid(self, svc):
        user = _make_user()
        db = _make_db()
        result = await svc._cmd_meta(user, "1800", db)
        assert "1800" in result
        assert user.daily_calorie_goal == 1800
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_meta_invalido(self, svc):
        user = _make_user()
        result = await svc._cmd_meta(user, "abc", None)
        assert "kcal" in result.lower()

    @pytest.mark.asyncio
    async def test_set_meta_fora_do_range(self, svc):
        user = _make_user()
        result = await svc._cmd_meta(user, "100", None)
        assert "500" in result

    @pytest.mark.asyncio
    async def test_get_meta_existente(self, svc):
        user = _make_user(daily_calorie_goal=2000)
        result = await svc._cmd_meta(user, None, None)
        assert "2000" in result

    @pytest.mark.asyncio
    async def test_get_meta_nao_definida(self, svc):
        user = _make_user(daily_calorie_goal=None)
        result = await svc._cmd_meta(user, None, None)
        assert "não tem" in result.lower() or "Meta" in result


class TestCmdCancelar:
    @pytest.mark.asyncio
    async def test_cancela_estado_ativo(self, svc):
        user = _make_user(state="CONFIRMING", state_data={"foo": "bar"})
        db = _make_db()
        result = await svc._cmd_cancelar(user, None, db)
        assert user.conversation_state == "IDLE"
        assert user.state_data is None
        assert "cancelada" in result.lower() or "Ação" in result

    @pytest.mark.asyncio
    async def test_cancela_idle(self, svc):
        user = _make_user(state="IDLE")
        db = _make_db()
        result = await svc._cmd_cancelar(user, None, db)
        assert "nenhuma" in result.lower() or "Não" in result


# ── Onboarding ─────────────────────────────────────────────────────────────────

class TestOnboarding:
    @pytest.mark.asyncio
    async def test_start_inicia_onboarding(self, svc):
        user = _make_user(onboarding_complete=False)
        db = _make_db()
        result = await svc._cmd_start(user, None, db)
        assert user.conversation_state == "ONBOARDING"
        assert "nome" in result.lower()
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_usuario_existente(self, svc):
        user = _make_user(onboarding_complete=True)
        db = _make_db()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        db.execute.return_value = mock_result

        result = await svc._cmd_start(user, None, db)
        assert user.conversation_state == "IDLE"
        assert "Olá" in result or "olá" in result.lower()

    @pytest.mark.asyncio
    async def test_onboarding_step0_salva_nome(self, svc):
        user = _make_user(state="ONBOARDING", state_data={"step": 0}, onboarding_complete=False)
        db = _make_db()
        result = await svc._handle_onboarding(user, "João", db)
        assert user.state_data["step"] == 1
        assert user.state_data["name"] == "João"
        assert "objetivo" in result.lower()
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_onboarding_step1_perder_peso(self, svc):
        user = _make_user(
            state="ONBOARDING",
            state_data={"step": 1, "name": "Ana"},
            onboarding_complete=False,
        )
        db = _make_db()
        result = await svc._handle_onboarding(user, "1", db)
        assert user.state_data["step"] == 2
        assert user.state_data["goal_type"] == "perder_peso"
        assert "1500" in result
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_onboarding_step1_ganhar_massa(self, svc):
        user = _make_user(
            state="ONBOARDING",
            state_data={"step": 1, "name": "Carlos"},
            onboarding_complete=False,
        )
        db = _make_db()
        result = await svc._handle_onboarding(user, "ganhar massa", db)
        assert user.state_data["goal_type"] == "ganhar_massa"
        assert "2500" in result

    @pytest.mark.asyncio
    async def test_onboarding_step2_confirma_sugestao(self, svc):
        user = _make_user(
            state="ONBOARDING",
            state_data={"step": 2, "name": "Maria", "goal_type": "manter", "goal_label": "manter o peso", "suggested_kcal": 2000},
            onboarding_complete=False,
        )
        db = _make_db()
        result = await svc._handle_onboarding(user, "ok", db)
        assert user.onboarding_complete is True
        assert user.daily_calorie_goal == 2000
        assert user.lgpd_consent_at is not None
        assert user.conversation_state == "IDLE"
        assert "pronto" in result.lower() or "Tudo" in result

    @pytest.mark.asyncio
    async def test_onboarding_step2_meta_customizada(self, svc):
        user = _make_user(
            state="ONBOARDING",
            state_data={"step": 2, "name": "Pedro", "goal_type": "perder_peso", "goal_label": "perder peso", "suggested_kcal": 1500},
            onboarding_complete=False,
        )
        db = _make_db()
        result = await svc._handle_onboarding(user, "1800", db)
        assert user.daily_calorie_goal == 1800
        assert user.onboarding_complete is True


# ── Confirming / Correcting ────────────────────────────────────────────────────

class TestConfirming:
    def _pending_state(self) -> dict:
        return {
            "raw_input_encrypted": "abc",
            "meal_type": "lunch",
            "input_type": "text",
            "total_calories_kcal": 400.0,
            "total_protein_g": 30.0,
            "total_carb_g": 50.0,
            "total_fat_g": 8.0,
            "total_fiber_g": 5.0,
            "food_items": [
                {"name": "Arroz", "original_term": "arroz", "quantity_g": 180,
                 "calories_kcal": 230.0, "protein_g": 4.5, "carb_g": 50.6, "fat_g": 0.4,
                 "fiber_g": 2.9, "source": "taco_cache", "confidence_score": 0.95, "taco_code": "001"}
            ],
        }

    @pytest.mark.asyncio
    async def test_confirma_com_sim(self, svc):
        user = _make_user(state="CONFIRMING", state_data=self._pending_state())
        db = _make_db()
        # Mockar _get_today_total_kcal
        svc._get_today_total_kcal = AsyncMock(return_value=400.0)
        result = await svc._handle_confirming(user, "sim", db)
        assert "✅" in result
        assert user.conversation_state == "IDLE"

    @pytest.mark.asyncio
    async def test_confirma_com_ok(self, svc):
        user = _make_user(state="CONFIRMING", state_data=self._pending_state(), daily_calorie_goal=2000)
        db = _make_db()
        svc._get_today_total_kcal = AsyncMock(return_value=400.0)
        result = await svc._handle_confirming(user, "ok", db)
        assert "✅" in result

    @pytest.mark.asyncio
    async def test_rejeita_com_nao(self, svc):
        user = _make_user(state="CONFIRMING", state_data=self._pending_state())
        db = _make_db()
        result = await svc._handle_confirming(user, "não", db)
        assert user.conversation_state == "CORRECTING"
        assert "corrij" in result.lower() or "correção" in result.lower()

    @pytest.mark.asyncio
    async def test_resposta_ambigua(self, svc):
        user = _make_user(state="CONFIRMING", state_data=self._pending_state())
        db = _make_db()
        result = await svc._handle_confirming(user, "talvez", db)
        assert "sim" in result.lower() or "não" in result.lower()

    @pytest.mark.asyncio
    async def test_sem_pending_reseta(self, svc):
        user = _make_user(state="CONFIRMING", state_data=None)
        db = _make_db()
        result = await svc._handle_confirming(user, "sim", db)
        assert user.conversation_state == "IDLE"


# ── Deleting ───────────────────────────────────────────────────────────────────

class TestDeleting:
    @pytest.mark.asyncio
    async def test_cmd_deletar_inicia_fluxo(self, svc):
        user = _make_user()
        db = _make_db()
        result = await svc._cmd_deletar_dados(user, None, db)
        assert user.conversation_state == "DELETING"
        assert "DELETAR" in result
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_deleting_confirma(self, svc):
        user = _make_user(state="DELETING", state_data={})
        db = _make_db()
        result = await svc._handle_deleting(user, "DELETAR", db)
        assert user.deleted_at is not None
        assert user.conversation_state == "IDLE"
        assert "72 horas" in result or "exclu" in result.lower()

    @pytest.mark.asyncio
    async def test_handle_deleting_cancela(self, svc):
        user = _make_user(state="DELETING", state_data={})
        db = _make_db()
        result = await svc._handle_deleting(user, "nao quero", db)
        assert user.conversation_state == "IDLE"
        assert "cancel" in result.lower()


# ── handle_command routing ─────────────────────────────────────────────────────

class TestHandleCommand:
    @pytest.mark.asyncio
    async def test_comando_desconhecido(self, svc):
        user = _make_user()
        result = await svc.handle_command(user, "inexistente", None, None)
        assert "não reconhecido" in result.lower()

    @pytest.mark.asyncio
    async def test_maintenance_mode(self, svc):
        user = _make_user()
        with patch("app.config.settings") as mock_settings:
            mock_settings.maintenance_mode = True
            result = await svc.handle_message(user, "text", "arroz", db=None)
        assert "manutenção" in result.lower()

    @pytest.mark.asyncio
    async def test_audio_sem_premium(self, svc):
        user = _make_user(plan="free")
        user.is_premium = False
        result = await svc.handle_message(user, "audio", b"fake_audio", db=None)
        assert "Premium" in result or "premium" in result.lower()


# ── /historico ────────────────────────────────────────────────────────────────

def _make_meal_log(meal_type="lunch", kcal=600.0, protein=30.0, carb=70.0, fat=15.0,
                   days_ago=0, tz_str="America/Sao_Paulo") -> MagicMock:
    from datetime import timezone, timedelta
    from zoneinfo import ZoneInfo
    tz = ZoneInfo(tz_str)
    now = datetime.now(tz)
    logged = (now - timedelta(days=days_ago)).replace(hour=12, minute=0)
    log = MagicMock()
    log.meal_type = meal_type
    log.total_calories_kcal = kcal
    log.total_protein_g = protein
    log.total_carb_g = carb
    log.total_fat_g = fat
    log.logged_at = logged
    return log


def _db_with_logs(logs: list) -> AsyncMock:
    db = _make_db()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = logs
    db.execute.return_value = mock_result
    return db


class TestCmdHistorico:
    @pytest.mark.asyncio
    async def test_sem_registros_retorna_mensagem(self, svc):
        user = _make_user()
        db = _db_with_logs([])
        result = await svc._cmd_historico(user, None, db)
        assert "Nenhuma" in result

    @pytest.mark.asyncio
    async def test_um_dia_com_refeicoes(self, svc):
        user = _make_user()
        logs = [
            _make_meal_log("breakfast", kcal=400, days_ago=0),
            _make_meal_log("lunch", kcal=700, days_ago=0),
        ]
        db = _db_with_logs(logs)
        result = await svc._cmd_historico(user, None, db)
        assert "Café" in result
        assert "Almoço" in result
        assert "400" in result
        assert "700" in result

    @pytest.mark.asyncio
    async def test_multiplos_dias_agrupados(self, svc):
        user = _make_user()
        logs = [
            _make_meal_log("lunch", kcal=600, days_ago=0),
            _make_meal_log("lunch", kcal=550, days_ago=1),
            _make_meal_log("lunch", kcal=700, days_ago=2),
        ]
        db = _db_with_logs(logs)
        result = await svc._cmd_historico(user, None, db)
        assert "Média" in result
        assert "3" in result or "dias" in result.lower()

    @pytest.mark.asyncio
    async def test_mostra_barra_progresso_com_meta(self, svc):
        user = _make_user(daily_calorie_goal=2000)
        logs = [_make_meal_log("lunch", kcal=1000, days_ago=0)]
        db = _db_with_logs(logs)
        result = await svc._cmd_historico(user, None, db)
        assert "50%" in result
        assert "█" in result

    @pytest.mark.asyncio
    async def test_free_user_ve_upsell_premium(self, svc):
        user = _make_user(plan="free")
        logs = [_make_meal_log(days_ago=0)]
        db = _db_with_logs(logs)
        result = await svc._cmd_historico(user, None, db)
        assert "premium" in result.lower() or "Premium" in result

    @pytest.mark.asyncio
    async def test_premium_user_sem_upsell(self, svc):
        user = _make_user(plan="premium")
        user.is_premium = True
        logs = [_make_meal_log(days_ago=0)]
        db = _db_with_logs(logs)
        result = await svc._cmd_historico(user, None, db)
        assert "/premium" not in result

    @pytest.mark.asyncio
    async def test_args_limita_dias(self, svc):
        user = _make_user(plan="premium")
        user.is_premium = True
        logs = [_make_meal_log(days_ago=0)]
        db = _db_with_logs(logs)
        # Não deve lançar erro com arg numérico
        result = await svc._cmd_historico(user, "7", db)
        assert result  # retorna algo


# ── /deletar refeição ──────────────────────────────────────────────────────────

def _make_meal_log_with_id(meal_type="lunch", kcal=600.0, days_ago=0):
    import uuid
    log = _make_meal_log(meal_type, kcal=kcal, days_ago=days_ago)
    log.id = uuid.uuid4()
    return log


class TestCmdDeletarRefeicao:
    @pytest.mark.asyncio
    async def test_sem_refeicoes_hoje(self, svc):
        user = _make_user()
        db = _db_with_logs([])
        result = await svc._cmd_deletar_refeicao(user, None, db)
        assert "Nenhuma" in result

    @pytest.mark.asyncio
    async def test_uma_refeicao_pede_confirmacao(self, svc):
        user = _make_user()
        logs = [_make_meal_log_with_id("lunch", kcal=600)]
        db = _db_with_logs(logs)
        result = await svc._cmd_deletar_refeicao(user, None, db)
        assert "Confirma deletar" in result
        assert "600" in result
        assert user.conversation_state == "CONFIRMING"
        assert user.state_data["pending_action"] == "delete_meal"

    @pytest.mark.asyncio
    async def test_multiplas_lista_numerada(self, svc):
        user = _make_user()
        logs = [
            _make_meal_log_with_id("breakfast", kcal=400),
            _make_meal_log_with_id("lunch", kcal=700),
        ]
        db = _db_with_logs(logs)
        result = await svc._cmd_deletar_refeicao(user, None, db)
        assert "1." in result and "2." in result
        assert user.conversation_state == "CONFIRMING"
        assert user.state_data["pending_action"] == "delete_meal_pick"

    @pytest.mark.asyncio
    async def test_args_almoco_acha_direto(self, svc):
        user = _make_user()
        logs = [
            _make_meal_log_with_id("breakfast", kcal=400),
            _make_meal_log_with_id("lunch", kcal=700),
        ]
        db = _db_with_logs(logs)
        result = await svc._cmd_deletar_refeicao(user, "almoço", db)
        assert "Confirma deletar" in result
        assert "700" in result
        assert user.state_data["pending_action"] == "delete_meal"

    @pytest.mark.asyncio
    async def test_args_tipo_nao_encontrado(self, svc):
        user = _make_user()
        logs = [_make_meal_log_with_id("breakfast", kcal=400)]
        db = _db_with_logs(logs)
        result = await svc._cmd_deletar_refeicao(user, "jantar", db)
        assert "Não encontrei" in result

    @pytest.mark.asyncio
    async def test_pick_numero_valido(self, svc):
        import uuid
        user = _make_user(state="CONFIRMING")
        meal_id = str(uuid.uuid4())
        user.state_data = {
            "pending_action": "delete_meal_pick",
            "meals": [
                {"id": meal_id, "meal_type": "lunch", "kcal": 600.0,
                 "logged_at": "2026-06-16T12:00:00+00:00"},
            ],
        }
        db = _make_db()
        result = await svc._handle_delete_pick(user, "1", db, user.state_data)
        assert "Confirma deletar" in result
        assert user.state_data["pending_action"] == "delete_meal"
        assert user.state_data["meal_log_id"] == meal_id

    @pytest.mark.asyncio
    async def test_pick_numero_invalido(self, svc):
        user = _make_user(state="CONFIRMING")
        user.state_data = {
            "pending_action": "delete_meal_pick",
            "meals": [
                {"id": "abc", "meal_type": "lunch", "kcal": 600.0,
                 "logged_at": "2026-06-16T12:00:00+00:00"},
            ],
        }
        db = _make_db()
        result = await svc._handle_delete_pick(user, "5", db, user.state_data)
        assert "número" in result.lower()

    @pytest.mark.asyncio
    async def test_confirm_sim_deleta(self, svc):
        import uuid
        meal_id = uuid.uuid4()
        user = _make_user(state="CONFIRMING")
        user.state_data = {
            "pending_action": "delete_meal",
            "meal_log_id": str(meal_id),
            "meal_summary": "Almoço (12:00) — 600 kcal",
        }
        # Mock DB returning a MealLog
        db = _make_db()
        mock_meal = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_meal
        db.execute.return_value = mock_result
        db.delete = AsyncMock()

        result = await svc._handle_delete_confirm(user, "sim", db, user.state_data)
        assert "deletado" in result.lower()
        assert user.conversation_state == "IDLE"
        db.delete.assert_called_once_with(mock_meal)

    @pytest.mark.asyncio
    async def test_confirm_nao_cancela(self, svc):
        import uuid
        user = _make_user(state="CONFIRMING")
        user.state_data = {
            "pending_action": "delete_meal",
            "meal_log_id": str(uuid.uuid4()),
            "meal_summary": "Almoço — 600 kcal",
        }
        db = _make_db()
        result = await svc._handle_delete_confirm(user, "não", db, user.state_data)
        assert "cancelad" in result.lower() or "nada" in result.lower()
        assert user.conversation_state == "IDLE"


# ── /alertas ──────────────────────────────────────────────────────────────────

class TestCmdAlertas:
    @pytest.fixture
    def svc(self):
        return ConversationService()

    @pytest.mark.asyncio
    async def test_status_sem_args_ativado(self, svc):
        user = _make_user()
        user.alerts_enabled = True
        db = _make_db()
        result = await svc._cmd_alertas(user, None, db)
        assert "ativados" in result.lower() or "ativado" in result.lower()
        assert "09:30" in result

    @pytest.mark.asyncio
    async def test_status_sem_args_desativado(self, svc):
        user = _make_user()
        user.alerts_enabled = False
        db = _make_db()
        result = await svc._cmd_alertas(user, None, db)
        assert "desativado" in result.lower()

    @pytest.mark.asyncio
    async def test_desativar_alertas(self, svc):
        user = _make_user()
        user.alerts_enabled = True
        db = _make_db()
        result = await svc._cmd_alertas(user, "off", db)
        assert user.alerts_enabled is False
        assert "desativados" in result.lower()
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_ativar_alertas(self, svc):
        user = _make_user()
        user.alerts_enabled = False
        user.alerts_paused_until = None
        db = _make_db()
        result = await svc._cmd_alertas(user, "on", db)
        assert user.alerts_enabled is True
        assert "ativados" in result.lower()
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_desativar_sinonimos(self, svc):
        for arg in ("desativar", "pausar", "nao", "não"):
            user = _make_user()
            user.alerts_enabled = True
            db = _make_db()
            await svc._cmd_alertas(user, arg, db)
            assert user.alerts_enabled is False, f"arg={arg!r} deveria desativar"


# ── Registro Retroativo ────────────────────────────────────────────────────────

class TestDateLabel:
    """_date_label retorna rótulos legíveis para datas passadas."""

    def _tz(self):
        from zoneinfo import ZoneInfo
        return ZoneInfo("America/Sao_Paulo")

    def test_ontem(self, svc):
        tz = self._tz()
        today = datetime.now(tz).date()
        result = svc._date_label(today - timedelta(days=1), tz)
        assert "ontem" in result
        assert (today - timedelta(days=1)).strftime("%d/%m") in result

    def test_anteontem(self, svc):
        tz = self._tz()
        today = datetime.now(tz).date()
        result = svc._date_label(today - timedelta(days=2), tz)
        assert "anteontem" in result

    def test_dia_da_semana(self, svc):
        tz = self._tz()
        today = datetime.now(tz).date()
        resultado = svc._date_label(today - timedelta(days=5), tz)
        # Deve conter nome de dia da semana em português
        dias = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
        assert any(d in resultado for d in dias)


class TestParseDateFromArgs:
    """_parse_date_from_args converte texto livre em date."""

    def test_ontem(self, svc):
        user = _make_user()
        result = svc._parse_date_from_args("ontem", user)
        from zoneinfo import ZoneInfo
        today = datetime.now(ZoneInfo("America/Sao_Paulo")).date()
        assert result == today - timedelta(days=1)

    def test_anteontem(self, svc):
        user = _make_user()
        result = svc._parse_date_from_args("anteontem", user)
        from zoneinfo import ZoneInfo
        today = datetime.now(ZoneInfo("America/Sao_Paulo")).date()
        assert result == today - timedelta(days=2)

    def test_formato_dd_mm(self, svc):
        user = _make_user()
        from zoneinfo import ZoneInfo
        today = datetime.now(ZoneInfo("America/Sao_Paulo")).date()
        alvo = today - timedelta(days=3)
        result = svc._parse_date_from_args(alvo.strftime("%d/%m"), user)
        assert result == alvo

    def test_argumento_vazio(self, svc):
        user = _make_user()
        assert svc._parse_date_from_args(None, user) is None
        assert svc._parse_date_from_args("", user) is None

    def test_texto_invalido(self, svc):
        user = _make_user()
        assert svc._parse_date_from_args("amanhã", user) is None


class TestCheckBackdateLimit:
    """_check_backdate_limit aplica os limites por plano."""

    def test_ontem_free_ok(self, svc):
        user = _make_user(plan="free")
        from zoneinfo import ZoneInfo
        today = datetime.now(ZoneInfo("America/Sao_Paulo")).date()
        assert svc._check_backdate_limit(today - timedelta(days=1), user) is None

    def test_oito_dias_free_bloqueado(self, svc):
        user = _make_user(plan="free")
        from zoneinfo import ZoneInfo
        today = datetime.now(ZoneInfo("America/Sao_Paulo")).date()
        result = svc._check_backdate_limit(today - timedelta(days=8), user)
        assert result is not None
        assert "premium" in result.lower() or "Premium" in result

    def test_oito_dias_premium_ok(self, svc):
        user = _make_user(plan="premium")
        user.is_premium = True
        from zoneinfo import ZoneInfo
        today = datetime.now(ZoneInfo("America/Sao_Paulo")).date()
        assert svc._check_backdate_limit(today - timedelta(days=8), user) is None

    def test_31_dias_premium_bloqueado(self, svc):
        user = _make_user(plan="premium")
        user.is_premium = True
        from zoneinfo import ZoneInfo
        today = datetime.now(ZoneInfo("America/Sao_Paulo")).date()
        result = svc._check_backdate_limit(today - timedelta(days=31), user)
        assert result is not None

    def test_hoje_bloqueado(self, svc):
        user = _make_user()
        from zoneinfo import ZoneInfo
        today = datetime.now(ZoneInfo("America/Sao_Paulo")).date()
        result = svc._check_backdate_limit(today, user)
        assert result is not None


class TestCmdRegistrar:
    """Comando /registrar abre o fluxo BACKDATING."""

    @pytest.mark.asyncio
    async def test_sem_args_mostra_ajuda(self, svc):
        user = _make_user()
        result = await svc._cmd_registrar(user, None, _make_db())
        assert "/registrar ontem" in result
        assert "/registrar" in result

    @pytest.mark.asyncio
    async def test_ontem_abre_backdating(self, svc):
        user = _make_user()
        db = _make_db()
        result = await svc._cmd_registrar(user, "ontem", db)
        assert user.conversation_state == "BACKDATING"
        assert user.state_data is not None
        assert "target_date" in user.state_data
        from zoneinfo import ZoneInfo
        today = datetime.now(ZoneInfo("America/Sao_Paulo")).date()
        assert user.state_data["target_date"] == (today - timedelta(days=1)).isoformat()
        assert "ontem" in result.lower()

    @pytest.mark.asyncio
    async def test_data_fora_limite_free(self, svc):
        user = _make_user(plan="free")
        db = _make_db()
        from zoneinfo import ZoneInfo
        today = datetime.now(ZoneInfo("America/Sao_Paulo")).date()
        alvo = (today - timedelta(days=10)).strftime("%d/%m")
        result = await svc._cmd_registrar(user, alvo, db)
        assert user.conversation_state != "BACKDATING"
        assert "premium" in result.lower() or "Premium" in result

    @pytest.mark.asyncio
    async def test_data_futura_rejeitada(self, svc):
        user = _make_user()
        result = await svc._cmd_registrar(user, "hoje", _make_db())
        # "hoje" não é passado → rejeitado
        assert user.conversation_state != "BACKDATING"


class TestHandleBackdating:
    """Estado BACKDATING chama _run_meal_extraction com target_date."""

    @pytest.mark.asyncio
    async def test_sem_state_data_reseta(self, svc):
        user = _make_user(state="BACKDATING", state_data=None)
        db = _make_db()
        result = await svc._handle_backdating(user, "arroz", db)
        assert user.conversation_state == "IDLE"
        assert "errado" in result.lower() or "comeu" in result.lower()

    @pytest.mark.asyncio
    async def test_chama_extracao_com_target_date(self, svc):
        from zoneinfo import ZoneInfo
        today = datetime.now(ZoneInfo("America/Sao_Paulo")).date()
        yesterday = (today - timedelta(days=1)).isoformat()
        user = _make_user(state="BACKDATING", state_data={"target_date": yesterday})
        db = _make_db()

        mock_extraction = MagicMock()
        mock_extraction.foods = []  # retorna vazio para simplificar
        mock_extraction.date_offset = 0
        mock_extraction.date_explicit = None

        with patch(
            "app.services.ai_service.ai_service.extract_foods_from_text",
            new_callable=AsyncMock,
            return_value=mock_extraction,
        ):
            result = await svc._handle_backdating(user, "pão com ovo", db)
        # Sem foods → mensagem de fallback, mas não deve crashar
        assert isinstance(result, str)


class TestAjudaMencionaRegistrar:
    """O comando /ajuda menciona /registrar nos dois planos."""

    @pytest.mark.asyncio
    async def test_ajuda_free_menciona_registrar(self, svc):
        user = _make_user(plan="free")
        result = await svc._cmd_ajuda(user, None, None)
        assert "/registrar" in result

    @pytest.mark.asyncio
    async def test_ajuda_premium_menciona_registrar(self, svc):
        user = _make_user(plan="premium")
        user.is_premium = True
        result = await svc._cmd_ajuda(user, None, None)
        assert "/registrar" in result
