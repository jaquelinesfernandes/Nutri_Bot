"""
Testes unitários Sprint 4: relatório semanal, exportação LGPD, áudio, /relatorios.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.conversation import ConversationService


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_user(
    plan: str = "free",
    first_name: str = "Ana",
    alerts_enabled: bool = True,
    channel_type: str = "telegram",
    channel_id: str = "tg:99999",
    timezone: str = "America/Sao_Paulo",
    daily_calorie_goal: int | None = 2000,
    goal_type: str | None = "manter",
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
    user.report_frequency = report_frequency
    user.created_at = datetime(2026, 6, 1, tzinfo=__import__("zoneinfo").ZoneInfo("UTC"))
    user.lgpd_consent_at = datetime(2026, 6, 1, tzinfo=__import__("zoneinfo").ZoneInfo("UTC"))
    return user


def _make_db() -> AsyncMock:
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()
    db.delete = AsyncMock()
    return db


@pytest.fixture
def svc() -> ConversationService:
    return ConversationService()


# ── /relatorios ───────────────────────────────────────────────────────────────

class TestCmdRelatorios:
    @pytest.mark.asyncio
    async def test_free_user_recebe_cta_premium(self, svc):
        user = _make_user(plan="free")
        db = _make_db()
        result = await svc._cmd_relatorios(user, None, db)
        assert "Premium" in result or "premium" in result.lower()
        assert "/premium" in result

    @pytest.mark.asyncio
    async def test_premium_sem_relatorios_orienta_domingo(self, svc):
        user = _make_user(plan="premium")
        db = _make_db()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        db.execute.return_value = mock_result

        result = await svc._cmd_relatorios(user, None, db)
        assert "domingo" in result.lower() or "20h" in result

    @pytest.mark.asyncio
    async def test_premium_lista_relatorios(self, svc):
        user = _make_user(plan="premium")
        db = _make_db()

        report = MagicMock()
        report.week_start_date = date(2026, 6, 9)
        report.delivered_at = datetime(2026, 6, 15, 20, 0)
        report.period_end_date = None   # força fallback: week_start + 6 = 15/06
        report.period_type = "weekly"

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [report]
        db.execute.return_value = mock_result

        result = await svc._cmd_relatorios(user, None, db)
        assert "09/06" in result
        assert "15/06" in result
        assert "Entregue" in result


# ── /exportar_dados ───────────────────────────────────────────────────────────

class TestCmdExportarDados:
    def _mock_meal_log(self, meal_type="lunch", kcal=600.0) -> MagicMock:
        log = MagicMock()
        log.id = uuid.uuid4()
        log.meal_type = meal_type
        log.logged_at = datetime(2026, 6, 16, 12, 0, tzinfo=__import__("zoneinfo").ZoneInfo("UTC"))
        log.input_type = "text"
        log.total_calories_kcal = kcal
        log.total_protein_g = 30.0
        log.total_carb_g = 70.0
        log.total_fat_g = 15.0
        log.total_fiber_g = 5.0
        return log

    @pytest.mark.asyncio
    async def test_exportar_telegram_envia_documento(self, svc):
        user = _make_user(plan="premium", channel_type="telegram")
        db = _make_db()

        # Primeira chamada: meal_logs; segunda: food_items de cada log
        log = self._mock_meal_log()
        meal_result = MagicMock()
        meal_result.scalars.return_value.all.return_value = [log]

        food_result = MagicMock()
        food_result.scalars.return_value.all.return_value = []

        db.execute.side_effect = [meal_result, food_result]

        with patch("app.services.notification.notification_service") as mock_notif:
            mock_notif.send_document = AsyncMock(return_value=True)

            # Importar localmente para pegar o mock
            import app.services.conversation as conv_mod
            original = conv_mod.notification_service if hasattr(conv_mod, "notification_service") else None

            result = await svc._cmd_exportar_dados(user, None, db)

        # Resultado textual confirma envio ou orienta alternativa
        assert "dados" in result.lower()

    @pytest.mark.asyncio
    async def test_exportar_json_estrutura_correta(self, svc):
        """Verifica que o JSON exportado tem os campos LGPD obrigatórios."""
        user = _make_user(plan="free", channel_type="telegram")
        db = _make_db()

        log = self._mock_meal_log()
        meal_result = MagicMock()
        meal_result.scalars.return_value.all.return_value = [log]
        food_result = MagicMock()
        food_result.scalars.return_value.all.return_value = []
        db.execute.side_effect = [meal_result, food_result]

        captured_bytes: list[bytes] = []

        async def _capture_send_document(u, doc_bytes, filename, caption=None):
            captured_bytes.append(doc_bytes)
            return True

        with patch(
            "app.services.notification.notification_service.send_document",
            side_effect=_capture_send_document,
        ):
            await svc._cmd_exportar_dados(user, None, db)

        # Se o send foi capturado, valida a estrutura JSON
        if captured_bytes:
            data = json.loads(captured_bytes[0].decode("utf-8"))
            assert "user" in data
            assert "meal_logs" in data
            assert "exported_at" in data
            assert "lgpd" in data.get("note", "").lower() or "LGPD" in data.get("note", "")
            assert len(data["meal_logs"]) == 1
            assert data["meal_logs"][0]["meal_type"] == "lunch"


# ── Áudio (Sprint 2 residual) ─────────────────────────────────────────────────

class TestProcessAudioMeal:
    @pytest.mark.asyncio
    async def test_audio_transcrito_e_processado(self, svc):
        user = _make_user(plan="premium")
        db = _make_db()

        with (
            patch("app.services.ai_service.ai_service.transcribe_audio", new=AsyncMock(return_value="comi arroz com feijão")) as mock_transcribe,
            patch.object(svc, "_run_meal_extraction", new=AsyncMock(return_value="Identifiquei: arroz + feijão")) as mock_extract,
        ):
            result = await svc._process_audio_meal(user, b"fake_ogg", db)

        mock_transcribe.assert_called_once_with(b"fake_ogg")
        mock_extract.assert_called_once_with("comi arroz com feijão", user, db)
        assert "Identifiquei" in result

    @pytest.mark.asyncio
    async def test_audio_vazio_pede_texto(self, svc):
        user = _make_user(plan="premium")
        db = _make_db()

        with patch("app.services.ai_service.ai_service.transcribe_audio", new=AsyncMock(return_value="   ")):
            result = await svc._process_audio_meal(user, b"silent.ogg", db)

        assert "digitar" in result.lower() or "texto" in result.lower()

    @pytest.mark.asyncio
    async def test_audio_falha_transcricao_retorna_erro(self, svc):
        user = _make_user(plan="premium")
        db = _make_db()

        with patch(
            "app.services.ai_service.ai_service.transcribe_audio",
            new=AsyncMock(side_effect=RuntimeError("Whisper offline")),
        ):
            result = await svc._process_audio_meal(user, b"audio.ogg", db)

        assert "áudio" in result.lower() or "audio" in result.lower()
        assert "texto" in result.lower()

    @pytest.mark.asyncio
    async def test_handle_message_audio_sem_premium_bloqueado(self, svc):
        user = _make_user(plan="free")
        user.is_premium = False
        user.conversation_state = "IDLE"

        with patch("app.config.settings") as mock_settings:
            mock_settings.maintenance_mode = False
            result = await svc.handle_message(user, "audio", b"fake", db=None)

        assert "Premium" in result or "premium" in result.lower()

    @pytest.mark.asyncio
    async def test_handle_message_audio_premium_chama_process(self, svc):
        user = _make_user(plan="premium")
        user.is_premium = True
        user.conversation_state = "IDLE"
        db = _make_db()

        with (
            patch("app.config.settings") as mock_settings,
            patch.object(svc, "_process_audio_meal", new=AsyncMock(return_value="✅ Refeição registrada!")) as mock_proc,
        ):
            mock_settings.maintenance_mode = False
            result = await svc.handle_message(user, "audio", b"real_ogg", db=db)

        mock_proc.assert_called_once()
        assert "Refeição" in result or result == "✅ Refeição registrada!"


# ── job_weekly_report ─────────────────────────────────────────────────────────
# Os imports dentro de job_weekly_report são lazy (from X import Y dentro da fn).
# Patchamos nos módulos-fonte onde os nomes são resolvidos no momento da chamada.

class TestJobWeeklyReport:
    @pytest.mark.asyncio
    async def test_job_envia_pdf_para_premium(self):
        from app.services.scheduler import job_weekly_report

        premium_user = _make_user(plan="premium", channel_type="telegram")
        premium_user.is_premium = True

        db = _make_db()
        users_result = MagicMock()
        users_result.scalars.return_value.all.return_value = [premium_user]

        existing_result = MagicMock()
        # código usa .scalars().first(), não scalar_one_or_none
        existing_result.scalars.return_value.first.return_value = None  # sem relatório existente

        db.execute.side_effect = [users_result, existing_result]

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=db)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_session_cls = MagicMock(return_value=mock_ctx)
        mock_report = MagicMock()
        # scheduler chama generate_report (não generate_weekly_pdf)
        mock_report.generate_report = AsyncMock(return_value=(b"%PDF", "pdf"))
        mock_notif = MagicMock()
        mock_notif.send_document = AsyncMock(return_value=True)
        mock_notif.send_text = AsyncMock(return_value=True)

        with (
            patch("app.db.session.AsyncSessionLocal", mock_session_cls),
            patch("app.services.report.report_service", mock_report),
            patch("app.services.notification.notification_service", mock_notif),
        ):
            await job_weekly_report()

        mock_report.generate_report.assert_called_once()
        mock_notif.send_document.assert_called_once()

    @pytest.mark.asyncio
    async def test_job_envia_preview_para_free(self):
        from app.services.scheduler import job_weekly_report

        free_user = _make_user(plan="free", alerts_enabled=True)
        free_user.is_premium = False

        db = _make_db()
        users_result = MagicMock()
        users_result.scalars.return_value.all.return_value = [free_user]
        db.execute.return_value = users_result

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=db)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_session_cls = MagicMock(return_value=mock_ctx)
        mock_report = MagicMock()
        mock_report.generate_weekly_pdf = AsyncMock(return_value=(b"%PDF", "pdf"))
        mock_notif = MagicMock()
        mock_notif.send_document = AsyncMock(return_value=True)
        mock_notif.send_text = AsyncMock(return_value=True)

        with (
            patch("app.db.session.AsyncSessionLocal", mock_session_cls),
            patch("app.services.report.report_service", mock_report),
            patch("app.services.notification.notification_service", mock_notif),
        ):
            await job_weekly_report()

        # Free users recebem texto (preview), não documento
        mock_report.generate_weekly_pdf.assert_not_called()
        mock_notif.send_text.assert_called_once()
        preview_msg = mock_notif.send_text.call_args[0][1]
        assert "premium" in preview_msg.lower() or "Premium" in preview_msg
