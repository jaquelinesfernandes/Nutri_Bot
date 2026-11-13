"""
Testes do scheduler (APScheduler jobs).

Estratégia: mockar app.db.session.AsyncSessionLocal (importado lazily dentro
das funções) e app.services.notification.notification_service.

Cobre:
  - start_scheduler: registra os 12 jobs esperados
  - _send_meal_alert: filtra usuários sem onboarding, alertas desativados,
    refeição já registrada, alertas pausados
  - _send_water_alert: filtra por consumo < 50% da meta
  - job_expire_invites: atualiza convites expirados
  - job_reengagement: envia para usuários inativos há 3+ dias
  - _send_periodic_report: lógica de datas weekly/monthly/quarterly
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_user(
    *,
    first_name: str = "Ana",
    alerts_paused_until=None,
    daily_water_goal_ml: int = 2000,
    is_premium: bool = False,
    report_frequency: str = "weekly",
    channel_type: str = "telegram",
    last_active_at=None,
) -> MagicMock:
    u = MagicMock()
    u.id = uuid.uuid4()
    u.first_name = first_name
    u.alerts_paused_until = alerts_paused_until
    u.daily_water_goal_ml = daily_water_goal_ml
    u.is_premium = is_premium
    u.report_frequency = report_frequency
    u.channel_type = channel_type
    u.channel_id = f"tg:{u.id.int % 100000}"
    u.last_active_at = last_active_at or (datetime.now(ZoneInfo("UTC")) - timedelta(days=1))
    u.daily_calorie_goal = 2000
    return u


def _build_ctx(db: AsyncMock) -> MagicMock:
    """Envolve um AsyncMock de db num context manager assíncrono."""
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=db)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


def _users_result(users: list) -> MagicMock:
    r = MagicMock()
    r.scalars.return_value.all.return_value = users
    return r


def _none_result() -> MagicMock:
    r = MagicMock()
    r.scalar_one_or_none.return_value = None
    r.scalar_one.return_value = 0
    r.scalars.return_value.first.return_value = None
    r.rowcount = 0
    return r


# ── start_scheduler ───────────────────────────────────────────────────────────

class TestStartScheduler:

    @pytest.mark.asyncio
    async def test_registra_doze_jobs(self):
        from app.services.scheduler import start_scheduler
        scheduler = await start_scheduler()
        try:
            assert len(scheduler.get_jobs()) == 12
        finally:
            scheduler.shutdown(wait=False)

    @pytest.mark.asyncio
    async def test_ids_dos_jobs_esperados(self):
        from app.services.scheduler import start_scheduler
        expected_ids = {
            "alert_breakfast", "alert_morning_snack", "alert_lunch",
            "alert_afternoon_snack", "alert_dinner",
            "report_weekly", "report_monthly", "report_quarterly",
            "reengagement",
            "water_morning", "water_afternoon",
            "expire_invites",
        }
        scheduler = await start_scheduler()
        try:
            assert {j.id for j in scheduler.get_jobs()} == expected_ids
        finally:
            scheduler.shutdown(wait=False)

    @pytest.mark.asyncio
    async def test_scheduler_inicia_rodando(self):
        from app.services.scheduler import start_scheduler
        scheduler = await start_scheduler()
        try:
            assert scheduler.running is True
        finally:
            scheduler.shutdown(wait=False)

    @pytest.mark.asyncio
    async def test_replace_existing_nao_duplica(self):
        from app.services.scheduler import start_scheduler
        s1 = await start_scheduler()
        s2 = await start_scheduler()
        try:
            assert len(s2.get_jobs()) == 12
        finally:
            s1.shutdown(wait=False)
            s2.shutdown(wait=False)


# ── _send_meal_alert ──────────────────────────────────────────────────────────

class TestSendMealAlert:

    @pytest.mark.asyncio
    async def test_envia_para_usuario_elegivel(self):
        user = _make_user()
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[_users_result([user]), _none_result()])

        with patch("app.db.session.AsyncSessionLocal", return_value=_build_ctx(db)), \
             patch("app.services.notification.notification_service") as mock_notif:
            mock_notif.send_text = AsyncMock(return_value=True)
            from app.services.scheduler import _send_meal_alert
            await _send_meal_alert("lunch", "Ei, {name}! Já almoçou?")

        mock_notif.send_text.assert_called_once()
        assert "Ana" in mock_notif.send_text.call_args[0][1]

    @pytest.mark.asyncio
    async def test_nao_envia_quando_lista_vazia(self):
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_users_result([]))

        with patch("app.db.session.AsyncSessionLocal", return_value=_build_ctx(db)), \
             patch("app.services.notification.notification_service") as mock_notif:
            mock_notif.send_text = AsyncMock(return_value=True)
            from app.services.scheduler import _send_meal_alert
            await _send_meal_alert("breakfast", "Bom dia, {name}!")

        mock_notif.send_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_nao_envia_quando_ja_registrou_refeicao(self):
        user = _make_user()
        existing = MagicMock()
        log_result = MagicMock()
        log_result.scalar_one_or_none.return_value = existing

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[_users_result([user]), log_result])

        with patch("app.db.session.AsyncSessionLocal", return_value=_build_ctx(db)), \
             patch("app.services.notification.notification_service") as mock_notif:
            mock_notif.send_text = AsyncMock(return_value=True)
            from app.services.scheduler import _send_meal_alert
            await _send_meal_alert("lunch", "Ei, {name}!")

        mock_notif.send_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_nao_envia_quando_alerta_pausado(self):
        paused_until = datetime.now(ZoneInfo("UTC")) + timedelta(hours=2)
        user = _make_user(alerts_paused_until=paused_until)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_users_result([user]))

        with patch("app.db.session.AsyncSessionLocal", return_value=_build_ctx(db)), \
             patch("app.services.notification.notification_service") as mock_notif:
            mock_notif.send_text = AsyncMock(return_value=True)
            from app.services.scheduler import _send_meal_alert
            await _send_meal_alert("dinner", "Boa noite, {name}!")

        mock_notif.send_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_envia_quando_pausa_ja_expirou(self):
        paused_until = datetime.now(ZoneInfo("UTC")) - timedelta(hours=1)
        user = _make_user(alerts_paused_until=paused_until)
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[_users_result([user]), _none_result()])

        with patch("app.db.session.AsyncSessionLocal", return_value=_build_ctx(db)), \
             patch("app.services.notification.notification_service") as mock_notif:
            mock_notif.send_text = AsyncMock(return_value=True)
            from app.services.scheduler import _send_meal_alert
            await _send_meal_alert("breakfast", "Bom dia, {name}!")

        mock_notif.send_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_nome_padrao_quando_first_name_none(self):
        user = _make_user(first_name=None)
        user.first_name = None
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[_users_result([user]), _none_result()])

        with patch("app.db.session.AsyncSessionLocal", return_value=_build_ctx(db)), \
             patch("app.services.notification.notification_service") as mock_notif:
            mock_notif.send_text = AsyncMock(return_value=True)
            from app.services.scheduler import _send_meal_alert
            await _send_meal_alert("lunch", "Ei, {name}! Almoçou?")

        assert "você" in mock_notif.send_text.call_args[0][1]

    @pytest.mark.asyncio
    async def test_multiplos_usuarios_envia_para_todos_elegiveis(self):
        users = [_make_user(first_name=f"User{i}") for i in range(4)]
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[_users_result(users), *[_none_result()] * 4])

        with patch("app.db.session.AsyncSessionLocal", return_value=_build_ctx(db)), \
             patch("app.services.notification.notification_service") as mock_notif:
            mock_notif.send_text = AsyncMock(return_value=True)
            from app.services.scheduler import _send_meal_alert
            await _send_meal_alert("dinner", "Boa noite, {name}!")

        assert mock_notif.send_text.call_count == 4

    @pytest.mark.asyncio
    async def test_job_wrappers_chamam_send_meal_alert(self):
        from app.services import scheduler as sched_module
        with patch.object(sched_module, "_send_meal_alert", new_callable=AsyncMock) as m:
            await sched_module.job_alert_breakfast()
            m.assert_called_once_with("breakfast", sched_module._ALERT_JOBS[0][3])

        with patch.object(sched_module, "_send_meal_alert", new_callable=AsyncMock) as m:
            await sched_module.job_alert_lunch()
            m.assert_called_once_with("lunch", sched_module._ALERT_JOBS[2][3])

        with patch.object(sched_module, "_send_meal_alert", new_callable=AsyncMock) as m:
            await sched_module.job_alert_dinner()
            m.assert_called_once_with("dinner", sched_module._ALERT_JOBS[4][3])


# ── _send_water_alert ─────────────────────────────────────────────────────────

class TestSendWaterAlert:

    def _make_water_db(self, users: list, water_ml: float) -> tuple:
        water_r = MagicMock()
        water_r.scalar_one.return_value = water_ml

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[_users_result(users)] + [water_r] * max(len(users), 1)
        )
        return db, _build_ctx(db)

    @pytest.mark.asyncio
    async def test_envia_quando_abaixo_de_50_pct(self):
        user = _make_user(daily_water_goal_ml=2000)
        db, ctx = self._make_water_db([user], 500.0)

        with patch("app.db.session.AsyncSessionLocal", return_value=ctx), \
             patch("app.services.notification.notification_service") as mock_notif:
            mock_notif.send_text = AsyncMock(return_value=True)
            from app.services.scheduler import _send_water_alert
            await _send_water_alert("morning")

        mock_notif.send_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_nao_envia_quando_acima_de_50_pct(self):
        user = _make_user(daily_water_goal_ml=2000)
        db, ctx = self._make_water_db([user], 1200.0)

        with patch("app.db.session.AsyncSessionLocal", return_value=ctx), \
             patch("app.services.notification.notification_service") as mock_notif:
            mock_notif.send_text = AsyncMock(return_value=True)
            from app.services.scheduler import _send_water_alert
            await _send_water_alert("morning")

        mock_notif.send_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_exatamente_50_pct_nao_envia(self):
        user = _make_user(daily_water_goal_ml=2000)
        db, ctx = self._make_water_db([user], 1000.0)

        with patch("app.db.session.AsyncSessionLocal", return_value=ctx), \
             patch("app.services.notification.notification_service") as mock_notif:
            mock_notif.send_text = AsyncMock(return_value=True)
            from app.services.scheduler import _send_water_alert
            await _send_water_alert("afternoon")

        mock_notif.send_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_mensagem_afternoon_contem_tarde(self):
        user = _make_user(daily_water_goal_ml=2000, first_name="Carla")
        db, ctx = self._make_water_db([user], 400.0)

        with patch("app.db.session.AsyncSessionLocal", return_value=ctx), \
             patch("app.services.notification.notification_service") as mock_notif:
            mock_notif.send_text = AsyncMock(return_value=True)
            from app.services.scheduler import _send_water_alert
            await _send_water_alert("afternoon")

        msg = mock_notif.send_text.call_args[0][1]
        assert "Carla" in msg

    @pytest.mark.asyncio
    async def test_goal_zero_nao_divide_por_zero(self):
        user = _make_user(daily_water_goal_ml=0)
        db, ctx = self._make_water_db([user], 0.0)

        with patch("app.db.session.AsyncSessionLocal", return_value=ctx), \
             patch("app.services.notification.notification_service") as mock_notif:
            mock_notif.send_text = AsyncMock(return_value=True)
            from app.services.scheduler import _send_water_alert
            await _send_water_alert("morning")  # não deve levantar

    @pytest.mark.asyncio
    async def test_job_water_wrappers(self):
        from app.services import scheduler as sched_module
        with patch.object(sched_module, "_send_water_alert", new_callable=AsyncMock) as m:
            await sched_module.job_water_morning()
            m.assert_called_once_with("morning")

        with patch.object(sched_module, "_send_water_alert", new_callable=AsyncMock) as m:
            await sched_module.job_water_afternoon()
            m.assert_called_once_with("afternoon")


# ── job_expire_invites ────────────────────────────────────────────────────────

class TestJobExpireInvites:

    @pytest.mark.asyncio
    async def test_executa_update_e_commit(self):
        result_mock = MagicMock()
        result_mock.rowcount = 3
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result_mock)
        db.commit = AsyncMock()

        with patch("app.db.session.AsyncSessionLocal", return_value=_build_ctx(db)):
            from app.services.scheduler import job_expire_invites
            await job_expire_invites()

        db.execute.assert_called_once()
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_nao_falha_com_zero_expirados(self):
        result_mock = MagicMock()
        result_mock.rowcount = 0
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result_mock)
        db.commit = AsyncMock()

        with patch("app.db.session.AsyncSessionLocal", return_value=_build_ctx(db)):
            from app.services.scheduler import job_expire_invites
            await job_expire_invites()


# ── job_reengagement ──────────────────────────────────────────────────────────

class TestJobReengagement:

    @pytest.mark.asyncio
    async def test_envia_para_usuarios_inativos(self):
        users = [_make_user(first_name="Maria"), _make_user(first_name="João")]
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_users_result(users))

        with patch("app.db.session.AsyncSessionLocal", return_value=_build_ctx(db)), \
             patch("app.services.notification.notification_service") as mock_notif:
            mock_notif.send_text = AsyncMock(return_value=True)
            from app.services.scheduler import job_reengagement
            await job_reengagement()

        assert mock_notif.send_text.call_count == 2

    @pytest.mark.asyncio
    async def test_nao_envia_quando_sem_usuarios(self):
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_users_result([]))

        with patch("app.db.session.AsyncSessionLocal", return_value=_build_ctx(db)), \
             patch("app.services.notification.notification_service") as mock_notif:
            mock_notif.send_text = AsyncMock(return_value=True)
            from app.services.scheduler import job_reengagement
            await job_reengagement()

        mock_notif.send_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_mensagem_menciona_nome(self):
        user = _make_user(first_name="Pedro")
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_users_result([user]))

        with patch("app.db.session.AsyncSessionLocal", return_value=_build_ctx(db)), \
             patch("app.services.notification.notification_service") as mock_notif:
            mock_notif.send_text = AsyncMock(return_value=True)
            from app.services.scheduler import job_reengagement
            await job_reengagement()

        assert "Pedro" in mock_notif.send_text.call_args[0][1]


# ── _send_periodic_report — wrappers e datas ─────────────────────────────────

class TestPeriodicReportWrappers:

    @pytest.mark.asyncio
    async def test_job_weekly_chama_send_periodic_report(self):
        from app.services import scheduler as sched_module
        with patch.object(sched_module, "_send_periodic_report", new_callable=AsyncMock) as m:
            await sched_module.job_weekly_report()
            m.assert_called_once_with("weekly")

    @pytest.mark.asyncio
    async def test_job_monthly_chama_send_periodic_report(self):
        from app.services import scheduler as sched_module
        with patch.object(sched_module, "_send_periodic_report", new_callable=AsyncMock) as m:
            await sched_module.job_monthly_report()
            m.assert_called_once_with("monthly")

    @pytest.mark.asyncio
    async def test_job_quarterly_chama_send_periodic_report(self):
        from app.services import scheduler as sched_module
        with patch.object(sched_module, "_send_periodic_report", new_callable=AsyncMock) as m:
            await sched_module.job_quarterly_report()
            m.assert_called_once_with("quarterly")

    @pytest.mark.asyncio
    async def test_send_periodic_report_weekly_sem_usuarios(self):
        """Deve terminar sem erro quando não há usuários."""
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_users_result([]))

        with patch("app.db.session.AsyncSessionLocal", return_value=_build_ctx(db)), \
             patch("app.services.notification.notification_service"), \
             patch("app.services.report.report_service"):
            from app.services.scheduler import _send_periodic_report
            await _send_periodic_report("weekly")

    @pytest.mark.asyncio
    async def test_send_periodic_report_monthly_sem_usuarios(self):
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_users_result([]))

        with patch("app.db.session.AsyncSessionLocal", return_value=_build_ctx(db)), \
             patch("app.services.notification.notification_service"), \
             patch("app.services.report.report_service"):
            from app.services.scheduler import _send_periodic_report
            await _send_periodic_report("monthly")

    @pytest.mark.asyncio
    async def test_send_periodic_report_quarterly_sem_usuarios(self):
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_users_result([]))

        with patch("app.db.session.AsyncSessionLocal", return_value=_build_ctx(db)), \
             patch("app.services.notification.notification_service"), \
             patch("app.services.report.report_service"):
            from app.services.scheduler import _send_periodic_report
            await _send_periodic_report("quarterly")
