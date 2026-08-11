"""
Coverage-focused tests for report, notification, ai_service, and scheduler services.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest


# ─── Helpers compartilhados ───────────────────────────────────────────────────

def _svc_user(
    plan: str = "premium",
    channel_type: str = "telegram",
    channel_id: str = "tg:12345",
    report_frequency: str = "weekly",
    daily_calorie_goal: int = 2000,
    first_name: str = "Ana",
    goal_type: str = "manter",
    timezone: str = "America/Sao_Paulo",
) -> MagicMock:
    u = MagicMock()
    u.id = uuid.uuid4()
    u.channel_type = channel_type
    u.channel_id = channel_id
    u.timezone = timezone
    u.plan = plan
    u.is_premium = plan != "free"
    u.daily_calorie_goal = daily_calorie_goal
    u.goal_type = goal_type
    u.first_name = first_name
    u.report_frequency = report_frequency
    u.onboarding_complete = True
    u.alerts_enabled = True
    u.deleted_at = None
    u.alerts_paused_until = None
    u.last_active_at = datetime(2026, 6, 20, tzinfo=ZoneInfo("UTC"))
    return u


class _FakeLog:
    """Objeto similar a MealLog com datetimes reais para funções de agrupamento."""

    def __init__(
        self,
        kcal: float = 600.0,
        meal_type: str = "lunch",
        logged_at: datetime | None = None,
    ) -> None:
        self.total_calories_kcal = kcal
        self.total_protein_g = 30.0
        self.total_carb_g = 70.0
        self.total_fat_g = 15.0
        self.meal_type = meal_type
        self.confirmed = True
        self.logged_at = logged_at or datetime(
            2026, 6, 16, 12, 0, tzinfo=ZoneInfo("America/Sao_Paulo")
        )


def _mock_db() -> AsyncMock:
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=result)
    db.add = MagicMock()
    db.commit = AsyncMock()
    return db


def _mock_ai_suggestions() -> MagicMock:
    s = MagicMock()
    s.suggestions = []
    s.highlights = ["Boa semana!"]
    s.weekly_insight = "Continue assim."
    return s


# ═════════════════════════════════════════════════════════════════════════════
# report.py — funções puras (sem mock)
# ═════════════════════════════════════════════════════════════════════════════

class TestReportHelpers:

    # ── _bar_class ────────────────────────────────────────────────────────────

    def test_bar_class_zero(self):
        from app.services.report import _bar_class
        assert _bar_class(0) == "bar-gray"

    def test_bar_class_over_110(self):
        from app.services.report import _bar_class
        assert _bar_class(111) == "bar-orange"

    def test_bar_class_exactly_110(self):
        from app.services.report import _bar_class
        assert _bar_class(110) == "bar-green"

    def test_bar_class_below_60(self):
        from app.services.report import _bar_class
        assert _bar_class(55) == "bar-yellow"

    def test_bar_class_exactly_60(self):
        from app.services.report import _bar_class
        assert _bar_class(60) == "bar-green"

    def test_bar_class_ok_range(self):
        from app.services.report import _bar_class
        assert _bar_class(90) == "bar-green"

    # ── _pct ─────────────────────────────────────────────────────────────────

    def test_pct_normal(self):
        from app.services.report import _pct
        assert _pct(1500, 2000) == 75

    def test_pct_over_100(self):
        from app.services.report import _pct
        assert _pct(2200, 2000) == 110

    def test_pct_zero_goal(self):
        from app.services.report import _pct
        assert _pct(500, 0) == 0

    def test_pct_caps_at_999(self):
        from app.services.report import _pct
        # min(int(20000/2000*100), 999) = min(1000, 999) = 999
        assert _pct(20000, 2000) == 999

    # ── _bar_color ────────────────────────────────────────────────────────────

    def test_bar_color_zero(self):
        from app.services.report import _bar_color
        assert _bar_color(0) == "#cbd5e1"

    def test_bar_color_green_80(self):
        from app.services.report import _bar_color
        assert _bar_color(80) == "#16a34a"

    def test_bar_color_green_115(self):
        from app.services.report import _bar_color
        assert _bar_color(115) == "#16a34a"

    def test_bar_color_yellow_below_80(self):
        from app.services.report import _bar_color
        assert _bar_color(70) == "#f59e0b"

    def test_bar_color_red_above_115(self):
        from app.services.report import _bar_color
        assert _bar_color(120) == "#ef4444"

    # ── _period_label ─────────────────────────────────────────────────────────

    def test_period_label_weekly(self):
        from app.services.report import _period_label
        label = _period_label(date(2026, 6, 9), date(2026, 6, 16), "weekly")
        assert "09/06" in label
        assert "15/06" in label

    def test_period_label_monthly(self):
        from app.services.report import _period_label
        label = _period_label(date(2026, 6, 1), date(2026, 7, 1), "monthly")
        assert "junho" in label.lower()
        assert "2026" in label

    def test_period_label_quarterly(self):
        from app.services.report import _period_label
        label = _period_label(date(2026, 4, 1), date(2026, 7, 1), "quarterly")
        assert "2026" in label
        # Deve mencionar meses de início e fim do trimestre
        assert "Abr" in label or "Jun" in label

    def test_period_label_custom(self):
        from app.services.report import _period_label
        label = _period_label(date(2026, 6, 1), date(2026, 6, 15), "custom")
        assert "01/06/2026" in label
        assert "14/06/2026" in label

    # ── _build_row ────────────────────────────────────────────────────────────

    def test_build_row_no_logs(self):
        from app.services.report import _build_row
        tz = ZoneInfo("America/Sao_Paulo")
        row = _build_row("Seg 09/06", [], 2000, tz)
        assert row["kcal"] == "—"
        assert row["badge_cls"] == "badge-miss"
        assert row["pct"] == 0
        assert row["bar_pct"] == 0

    def test_build_row_ok_range(self):
        from app.services.report import _build_row
        tz = ZoneInfo("America/Sao_Paulo")
        row = _build_row("Seg 09/06", [_FakeLog(kcal=1800.0)], 2000, tz)
        assert row["badge_cls"] == "badge-ok"
        assert "1800" in row["kcal"]
        assert "lunch" in row["meals_label"] or "🍽️" in row["meals_label"]

    def test_build_row_over_goal(self):
        from app.services.report import _build_row
        tz = ZoneInfo("America/Sao_Paulo")
        row = _build_row("Ter 10/06", [_FakeLog(kcal=2500.0)], 2000, tz)
        assert row["badge_cls"] == "badge-over"

    def test_build_row_below_goal(self):
        from app.services.report import _build_row
        tz = ZoneInfo("America/Sao_Paulo")
        row = _build_row("Qua 11/06", [_FakeLog(kcal=800.0)], 2000, tz)
        assert row["badge_cls"] == "badge-low"

    def test_build_row_zero_goal(self):
        from app.services.report import _build_row
        tz = ZoneInfo("America/Sao_Paulo")
        row = _build_row("Qui 12/06", [_FakeLog(kcal=1500.0)], 0, tz)
        assert row["pct"] == 0  # goal=0 → sem percentual

    # ── _group_logs_daily ─────────────────────────────────────────────────────

    def test_group_logs_daily_with_log(self):
        from app.services.report import _group_logs_daily
        tz = ZoneInfo("America/Sao_Paulo")
        log = _FakeLog(kcal=1800.0, logged_at=datetime(2026, 6, 9, 12, 0, tzinfo=tz))
        rows = _group_logs_daily([log], date(2026, 6, 9), date(2026, 6, 12), tz)
        assert len(rows) == 3
        assert "09/06" in rows[0]["label"]

    def test_group_logs_daily_empty(self):
        from app.services.report import _group_logs_daily
        tz = ZoneInfo("America/Sao_Paulo")
        rows = _group_logs_daily([], date(2026, 6, 9), date(2026, 6, 16), tz)
        assert len(rows) == 7
        assert all(r["kcal"] == "—" for r in rows)

    # ── _group_logs_weekly ────────────────────────────────────────────────────

    def test_group_logs_weekly_counts_chunks(self):
        from app.services.report import _group_logs_weekly
        tz = ZoneInfo("America/Sao_Paulo")
        log = _FakeLog(kcal=1800.0, logged_at=datetime(2026, 6, 9, 12, 0, tzinfo=tz))
        rows = _group_logs_weekly([log], date(2026, 6, 1), date(2026, 6, 29), tz, 2000)
        assert len(rows) == 4

    # ── _group_logs_monthly ───────────────────────────────────────────────────

    def test_group_logs_monthly_three_months(self):
        from app.services.report import _group_logs_monthly
        tz = ZoneInfo("America/Sao_Paulo")
        log = _FakeLog(kcal=1800.0, logged_at=datetime(2026, 5, 15, 12, 0, tzinfo=tz))
        rows = _group_logs_monthly([log], date(2026, 4, 1), date(2026, 7, 1), tz, 2000)
        assert len(rows) == 3
        labels = [r["label"] for r in rows]
        assert any("abril" in l.lower() for l in labels)
        assert any("maio" in l.lower() for l in labels)
        assert any("junho" in l.lower() for l in labels)


# ═════════════════════════════════════════════════════════════════════════════
# report.py — ReportService (integração com mock DB)
# ═════════════════════════════════════════════════════════════════════════════

class TestReportService:

    @pytest.mark.asyncio
    async def test_generate_weekly_pdf_wrapper(self):
        """generate_weekly_pdf delega para generate_report com período de 7 dias."""
        from app.services.report import ReportService
        svc = ReportService()
        user = _svc_user()
        db = _mock_db()

        with patch(
            "app.services.ai_service.ai_service.generate_report_suggestions",
            AsyncMock(return_value=_mock_ai_suggestions()),
        ):
            file_bytes, ext = await svc.generate_weekly_pdf(user, date(2026, 6, 9), db)

        assert isinstance(file_bytes, bytes)
        assert len(file_bytes) > 0
        assert ext in ("pdf", "html")

    @pytest.mark.asyncio
    async def test_generate_report_weekly_no_logs(self):
        """Relatório semanal sem refeições: retorna HTML com zeros."""
        from app.services.report import ReportService
        svc = ReportService()
        user = _svc_user()
        db = _mock_db()

        with patch(
            "app.services.ai_service.ai_service.generate_report_suggestions",
            AsyncMock(return_value=_mock_ai_suggestions()),
        ):
            file_bytes, ext = await svc.generate_report(
                user, date(2026, 6, 9), date(2026, 6, 16), "weekly", db
            )

        assert isinstance(file_bytes, bytes)
        assert ext in ("pdf", "html")
        db.add.assert_called_once()
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_generate_report_monthly(self):
        """Relatório mensal usa agrupamento semanal."""
        from app.services.report import ReportService
        svc = ReportService()
        user = _svc_user()
        db = _mock_db()

        with patch(
            "app.services.ai_service.ai_service.generate_report_suggestions",
            AsyncMock(return_value=_mock_ai_suggestions()),
        ):
            file_bytes, ext = await svc.generate_report(
                user, date(2026, 5, 1), date(2026, 6, 1), "monthly", db
            )

        assert isinstance(file_bytes, bytes)
        assert ext in ("pdf", "html")

    @pytest.mark.asyncio
    async def test_generate_report_quarterly(self):
        """Relatório trimestral usa agrupamento mensal."""
        from app.services.report import ReportService
        svc = ReportService()
        user = _svc_user()
        db = _mock_db()

        with patch(
            "app.services.ai_service.ai_service.generate_report_suggestions",
            AsyncMock(return_value=_mock_ai_suggestions()),
        ):
            file_bytes, ext = await svc.generate_report(
                user, date(2026, 1, 1), date(2026, 4, 1), "quarterly", db
            )

        assert isinstance(file_bytes, bytes)
        assert ext in ("pdf", "html")

    @pytest.mark.asyncio
    async def test_generate_report_ai_fallback_on_error(self):
        """Se a IA falhar, retorna sugestão padrão sem levantar exceção."""
        from app.services.report import ReportService
        svc = ReportService()
        user = _svc_user()
        db = _mock_db()

        with patch(
            "app.services.ai_service.ai_service.generate_report_suggestions",
            AsyncMock(side_effect=RuntimeError("AI offline")),
        ):
            file_bytes, ext = await svc.generate_report(
                user, date(2026, 6, 9), date(2026, 6, 16), "weekly", db
            )

        assert isinstance(file_bytes, bytes)
        assert ext in ("pdf", "html")

    @pytest.mark.asyncio
    async def test_generate_report_with_logs(self):
        """Relatório com refeições reais calcula médias corretamente."""
        from app.services.report import ReportService
        svc = ReportService()
        user = _svc_user(daily_calorie_goal=2000)

        tz = ZoneInfo("America/Sao_Paulo")
        fake_log = _FakeLog(kcal=1800.0, logged_at=datetime(2026, 6, 10, 12, 0, tzinfo=tz))

        db = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = [fake_log]
        db.execute = AsyncMock(return_value=result)
        db.add = MagicMock()
        db.commit = AsyncMock()

        with patch(
            "app.services.ai_service.ai_service.generate_report_suggestions",
            AsyncMock(return_value=_mock_ai_suggestions()),
        ):
            file_bytes, ext = await svc.generate_report(
                user, date(2026, 6, 9), date(2026, 6, 16), "weekly", db
            )

        assert isinstance(file_bytes, bytes)
        assert ext in ("pdf", "html")


# ═════════════════════════════════════════════════════════════════════════════
# notification.py
# ═════════════════════════════════════════════════════════════════════════════

class TestNotificationService:

    def _httpx_mock(self, status_code: int = 200) -> tuple[MagicMock, MagicMock]:
        """Retorna (mock_client_cls, mock_client_instance) com context manager correto."""
        mock_response = MagicMock()
        mock_response.status_code = status_code
        mock_response.text = "ok" if status_code == 200 else "error"

        mock_instance = MagicMock()
        mock_instance.post = AsyncMock(return_value=mock_response)
        mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_instance.__aexit__ = AsyncMock(return_value=None)

        mock_cls = MagicMock(return_value=mock_instance)
        return mock_cls, mock_instance

    @pytest.mark.asyncio
    async def test_send_text_telegram_success(self):
        from app.services.notification import NotificationService
        svc = NotificationService()
        user = _svc_user(channel_type="telegram", channel_id="tg:12345")

        mock_cls, _ = self._httpx_mock(200)
        with (
            patch("app.config.settings") as mock_settings,
            patch("httpx.AsyncClient", mock_cls),
        ):
            mock_settings.telegram_bot_token = "fake_token_123"
            result = await svc.send_text(user, "Olá!")

        assert result is True

    @pytest.mark.asyncio
    async def test_send_text_telegram_no_token_returns_false(self):
        from app.services.notification import NotificationService
        svc = NotificationService()
        user = _svc_user(channel_type="telegram", channel_id="tg:12345")

        with patch("app.config.settings") as mock_settings:
            mock_settings.telegram_bot_token = None
            result = await svc.send_text(user, "Olá!")

        assert result is False

    @pytest.mark.asyncio
    async def test_send_text_telegram_http_error_returns_false(self):
        from app.services.notification import NotificationService
        svc = NotificationService()
        user = _svc_user(channel_type="telegram", channel_id="tg:12345")

        mock_cls, _ = self._httpx_mock(400)
        with (
            patch("app.config.settings") as mock_settings,
            patch("httpx.AsyncClient", mock_cls),
        ):
            mock_settings.telegram_bot_token = "fake_token"
            result = await svc.send_text(user, "Olá!")

        assert result is False

    @pytest.mark.asyncio
    async def test_send_text_whatsapp_success(self):
        from app.services.notification import NotificationService
        svc = NotificationService()
        user = _svc_user(channel_type="whatsapp", channel_id="wa:5511999999999")

        mock_cls, _ = self._httpx_mock(200)
        with (
            patch("app.config.settings") as mock_settings,
            patch("httpx.AsyncClient", mock_cls),
        ):
            mock_settings.zapi_instance_id = "inst123"
            mock_settings.zapi_token = "tok456"
            result = await svc.send_text(user, "Olá pelo WhatsApp!")

        assert result is True

    @pytest.mark.asyncio
    async def test_send_text_whatsapp_no_credentials_returns_false(self):
        from app.services.notification import NotificationService
        svc = NotificationService()
        user = _svc_user(channel_type="whatsapp", channel_id="wa:5511999999999")

        with patch("app.config.settings") as mock_settings:
            mock_settings.zapi_instance_id = None
            mock_settings.zapi_token = None
            result = await svc.send_text(user, "Olá!")

        assert result is False

    @pytest.mark.asyncio
    async def test_send_document_telegram_success(self):
        from app.services.notification import NotificationService
        svc = NotificationService()
        user = _svc_user(channel_type="telegram", channel_id="tg:12345")

        mock_cls, _ = self._httpx_mock(200)
        with (
            patch("app.config.settings") as mock_settings,
            patch("httpx.AsyncClient", mock_cls),
        ):
            mock_settings.telegram_bot_token = "fake_token"
            result = await svc.send_document(
                user, b"%PDF-dummy", "relatorio.pdf", caption="Seu relatório!"
            )

        assert result is True

    @pytest.mark.asyncio
    async def test_send_document_telegram_no_token_returns_false(self):
        from app.services.notification import NotificationService
        svc = NotificationService()
        user = _svc_user(channel_type="telegram", channel_id="tg:12345")

        with patch("app.config.settings") as mock_settings:
            mock_settings.telegram_bot_token = None
            result = await svc.send_document(user, b"bytes", "file.pdf")

        assert result is False

    @pytest.mark.asyncio
    async def test_send_text_exception_returns_false(self):
        """Exceção interna retorna False sem propagar."""
        from app.services.notification import NotificationService
        svc = NotificationService()
        user = _svc_user(channel_type="telegram", channel_id="tg:12345")

        with (
            patch("app.config.settings") as mock_settings,
            patch("httpx.AsyncClient", side_effect=RuntimeError("network error")),
        ):
            mock_settings.telegram_bot_token = "tok"
            result = await svc.send_text(user, "Olá!")

        assert result is False


# ═════════════════════════════════════════════════════════════════════════════
# ai_service.py
# ═════════════════════════════════════════════════════════════════════════════

class TestAIService:

    def _make_svc(self) -> object:
        """Cria AIService com cliente Anthropic mockado."""
        with patch("anthropic.AsyncAnthropic", MagicMock()):
            from app.services.ai_service import AIService
            svc = AIService()
        svc._client = AsyncMock()
        return svc

    def _make_anthropic_response(self, json_text: str) -> MagicMock:
        resp = MagicMock()
        resp.content = [MagicMock(text=json_text)]
        return resp

    @pytest.mark.asyncio
    async def test_extract_foods_from_text(self):
        svc = self._make_svc()
        json_text = (
            '{"foods":[{"name":"arroz","original_term":"arroz","quantity_g":80.0,'
            '"taco_code":null,"confidence_score":0.9,"est_calories_kcal":130.0,'
            '"est_protein_g":2.5,"est_carb_g":28.0,"est_fat_g":0.2}],'
            '"meal_type":"lunch","meal_time_hint":null,"unrecognized_terms":[]}'
        )
        svc._client.messages.create = AsyncMock(
            return_value=self._make_anthropic_response(json_text)
        )

        result = await svc.extract_foods_from_text("comi arroz")

        assert len(result.foods) == 1
        assert result.foods[0].name == "arroz"
        assert result.meal_type == "lunch"

    @pytest.mark.asyncio
    async def test_extract_foods_strips_markdown_fence(self):
        """Remove bloco ```json ... ``` antes de parsear."""
        svc = self._make_svc()
        inner = (
            '{"foods":[],"meal_type":"other","meal_time_hint":null,'
            '"unrecognized_terms":["xyz"]}'
        )
        raw = f"```json\n{inner}\n```"
        svc._client.messages.create = AsyncMock(
            return_value=self._make_anthropic_response(raw)
        )

        result = await svc.extract_foods_from_text("xyz")
        assert result.foods == []
        assert "xyz" in result.unrecognized_terms

    @pytest.mark.asyncio
    async def test_extract_foods_from_image(self):
        svc = self._make_svc()
        json_text = (
            '{"image_has_food":true,"image_quality":"good","foods":[{"name":"frango",'
            '"quantity_g":100.0,"taco_code":null,"confidence_score":0.85,'
            '"est_calories_kcal":165.0,"est_protein_g":31.0,"est_carb_g":0.0,'
            '"est_fat_g":3.6}],"meal_type":"lunch","overall_confidence":0.85}'
        )
        svc._client.messages.create = AsyncMock(
            return_value=self._make_anthropic_response(json_text)
        )

        result = await svc.extract_foods_from_image(b"fake_image_bytes", caption="almoço")

        assert result.image_has_food is True
        assert result.foods[0].name == "frango"
        assert result.image_quality == "good"

    @pytest.mark.asyncio
    async def test_generate_report_suggestions(self):
        svc = self._make_svc()
        json_text = (
            '{"highlights":["Boa semana!"],'
            '"suggestions":[{"category":"proteina","text":"Aumente proteína.","priority":"high"}],'
            '"weekly_insight":"Você fez bem."}'
        )
        svc._client.messages.create = AsyncMock(
            return_value=self._make_anthropic_response(json_text)
        )

        result = await svc.generate_report_suggestions(
            {"name": "Ana", "goal_kcal": 2000, "goal_type": "manter"},
            {"avg_kcal": 1800, "days_logged": 5},
        )

        assert result.weekly_insight == "Você fez bem."
        assert len(result.suggestions) == 1
        assert result.suggestions[0].category == "proteina"

    @pytest.mark.asyncio
    async def test_transcribe_audio(self):
        svc = self._make_svc()

        with patch("openai.AsyncOpenAI") as mock_openai_cls:
            mock_openai_client = MagicMock()
            mock_openai_cls.return_value = mock_openai_client
            mock_openai_client.audio.transcriptions.create = AsyncMock(
                return_value="arroz com feijão"
            )
            with patch("app.config.settings") as mock_settings:
                mock_settings.openai_api_key = "fake_key"
                mock_settings.openai_whisper_model = "whisper-1"
                result = await svc.transcribe_audio(b"fake_audio_bytes")

        assert result == "arroz com feijão"

    @pytest.mark.asyncio
    async def test_api_status_error_500_retries(self):
        """Erro 5xx do Anthropic deve retentar antes de levantar exceção."""
        import anthropic as anthropic_lib

        svc = self._make_svc()

        class FakeStatus500(anthropic_lib.APIStatusError):
            def __init__(self):
                self.status_code = 500
                self.message = "internal error"
                self.body = {}
                self.response = MagicMock()

        # Falha 3 vezes → levanta RuntimeError
        svc._client.messages.create = AsyncMock(side_effect=FakeStatus500())

        with patch("asyncio.sleep", AsyncMock()):
            with pytest.raises(RuntimeError, match="500"):
                await svc.extract_foods_from_text("teste")


# ═════════════════════════════════════════════════════════════════════════════
# scheduler.py
# ═════════════════════════════════════════════════════════════════════════════

class TestSchedulerJobs:

    def _mock_session(self, db: AsyncMock) -> tuple[MagicMock, MagicMock]:
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=db)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_session_cls = MagicMock(return_value=mock_ctx)
        return mock_session_cls, mock_ctx

    @pytest.mark.asyncio
    async def test_send_meal_alert_notifies_eligible_user(self):
        from app.services.scheduler import _send_meal_alert

        user = _svc_user()

        db = AsyncMock()
        users_result = MagicMock()
        users_result.scalars.return_value.all.return_value = [user]

        no_meal_result = MagicMock()
        no_meal_result.scalar_one_or_none.return_value = None  # não registrou

        db.execute.side_effect = [users_result, no_meal_result]

        mock_session_cls, _ = self._mock_session(db)
        mock_notif = MagicMock()
        mock_notif.send_text = AsyncMock(return_value=True)

        with (
            patch("app.db.session.AsyncSessionLocal", mock_session_cls),
            patch("app.services.notification.notification_service", mock_notif),
        ):
            await _send_meal_alert("lunch", "Ei, {name}! Já almoçou?")

        mock_notif.send_text.assert_called_once()
        call_args = mock_notif.send_text.call_args[0]
        assert "Ana" in call_args[1]

    @pytest.mark.asyncio
    async def test_send_meal_alert_skips_user_who_already_logged(self):
        from app.services.scheduler import _send_meal_alert

        user = _svc_user()

        db = AsyncMock()
        users_result = MagicMock()
        users_result.scalars.return_value.all.return_value = [user]

        already_logged = MagicMock()  # truthy → já registrou
        already_logged.scalar_one_or_none.return_value = already_logged

        db.execute.side_effect = [users_result, already_logged]

        mock_session_cls, _ = self._mock_session(db)
        mock_notif = MagicMock()
        mock_notif.send_text = AsyncMock(return_value=True)

        with (
            patch("app.db.session.AsyncSessionLocal", mock_session_cls),
            patch("app.services.notification.notification_service", mock_notif),
        ):
            await _send_meal_alert("lunch", "Ei, {name}!")

        mock_notif.send_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_meal_alert_respects_paused_alerts(self):
        from app.services.scheduler import _send_meal_alert
        from datetime import timezone

        user = _svc_user()
        # pausa até amanhã
        user.alerts_paused_until = datetime.now(timezone.utc) + timedelta(hours=24)

        db = AsyncMock()
        users_result = MagicMock()
        users_result.scalars.return_value.all.return_value = [user]
        db.execute.return_value = users_result

        mock_session_cls, _ = self._mock_session(db)
        mock_notif = MagicMock()
        mock_notif.send_text = AsyncMock(return_value=True)

        with (
            patch("app.db.session.AsyncSessionLocal", mock_session_cls),
            patch("app.services.notification.notification_service", mock_notif),
        ):
            await _send_meal_alert("lunch", "Ei, {name}!")

        mock_notif.send_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_job_reengagement_sends_to_inactive_users(self):
        from app.services.scheduler import job_reengagement

        user = _svc_user()

        db = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = [user]
        db.execute = AsyncMock(return_value=result)

        mock_session_cls, _ = self._mock_session(db)
        mock_notif = MagicMock()
        mock_notif.send_text = AsyncMock(return_value=True)

        with (
            patch("app.db.session.AsyncSessionLocal", mock_session_cls),
            patch("app.services.notification.notification_service", mock_notif),
        ):
            await job_reengagement()

        mock_notif.send_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_periodic_report_monthly(self):
        """job_monthly_report gera relatório para usuários com frequência 'monthly'."""
        from app.services.scheduler import job_monthly_report

        user = _svc_user(report_frequency="monthly")

        db = AsyncMock()
        users_result = MagicMock()
        users_result.scalars.return_value.all.return_value = [user]

        existing_result = MagicMock()
        existing_result.scalars.return_value.first.return_value = None

        db.execute.side_effect = [users_result, existing_result]

        mock_session_cls, _ = self._mock_session(db)
        mock_report = MagicMock()
        mock_report.generate_report = AsyncMock(return_value=(b"%PDF", "pdf"))
        mock_notif = MagicMock()
        mock_notif.send_document = AsyncMock(return_value=True)
        mock_notif.send_text = AsyncMock(return_value=True)

        with (
            patch("app.db.session.AsyncSessionLocal", mock_session_cls),
            patch("app.services.report.report_service", mock_report),
            patch("app.services.notification.notification_service", mock_notif),
        ):
            await job_monthly_report()

        mock_report.generate_report.assert_called_once()
        mock_notif.send_document.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_periodic_report_free_preview_only_on_weekly(self):
        """Usuários free só recebem preview no ciclo semanal, não no mensal."""
        from app.services.scheduler import job_monthly_report

        free_user = _svc_user(plan="free")
        free_user.is_premium = False

        db = AsyncMock()
        users_result = MagicMock()
        users_result.scalars.return_value.all.return_value = [free_user]
        db.execute = AsyncMock(return_value=users_result)

        mock_session_cls, _ = self._mock_session(db)
        mock_report = MagicMock()
        mock_notif = MagicMock()
        mock_notif.send_text = AsyncMock(return_value=True)

        with (
            patch("app.db.session.AsyncSessionLocal", mock_session_cls),
            patch("app.services.report.report_service", mock_report),
            patch("app.services.notification.notification_service", mock_notif),
        ):
            await job_monthly_report()

        # Mensal não envia preview para free
        mock_notif.send_text.assert_not_called()
        mock_report.generate_report.assert_not_called()

    @pytest.mark.asyncio
    async def test_start_scheduler_registers_all_jobs(self):
        from app.services.scheduler import start_scheduler

        with patch("app.services.scheduler.AsyncIOScheduler") as mock_sched_cls:
            mock_sched = MagicMock()
            mock_sched_cls.return_value = mock_sched
            mock_sched.add_job = MagicMock()
            mock_sched.start = MagicMock()

            result = await start_scheduler()

        assert result is mock_sched
        mock_sched.start.assert_called_once()
        # 3 alertas + 3 relatórios (weekly/monthly/quarterly) + 1 re-engajamento = 7
        assert mock_sched.add_job.call_count == 7


# ═════════════════════════════════════════════════════════════════════════════
# analytics.py
# ═════════════════════════════════════════════════════════════════════════════

class TestAnalytics:

    def _mock_posthog(self):
        """Retorna mock_posthog e configura settings com API key."""
        mock_ph = MagicMock()
        return mock_ph

    def test_track_skips_when_no_api_key(self):
        """Sem PostHog configurado, track não levanta exceção."""
        import app.services.analytics as analytics_mod
        old_client = analytics_mod._posthog

        with patch("app.config.settings") as mock_settings:
            mock_settings.posthog_api_key = ""
            analytics_mod._posthog = None
            analytics_mod.track("tg:123", "test_event")

        analytics_mod._posthog = old_client  # restaura estado

    def test_track_sends_event_when_configured(self):
        """Com PostHog configurado, track chama capture."""
        import app.services.analytics as analytics_mod

        mock_ph = MagicMock()
        old_client = analytics_mod._posthog
        analytics_mod._posthog = mock_ph

        analytics_mod.track("tg:123", "test_event", {"key": "val"})

        mock_ph.capture.assert_called_once_with(
            distinct_id="tg:123", event="test_event", properties={"key": "val"}
        )
        analytics_mod._posthog = old_client

    def test_track_swallows_posthog_exception(self):
        """Exceção do PostHog não propaga — analytics é fire-and-forget."""
        import app.services.analytics as analytics_mod

        mock_ph = MagicMock()
        mock_ph.capture.side_effect = RuntimeError("PostHog down")
        old_client = analytics_mod._posthog
        analytics_mod._posthog = mock_ph

        analytics_mod.track("tg:123", "test_event")  # não deve levantar

        analytics_mod._posthog = old_client

    def test_track_empty_properties_defaults_to_dict(self):
        """Propriedades None são substituídas por {} internamente."""
        import app.services.analytics as analytics_mod

        mock_ph = MagicMock()
        old_client = analytics_mod._posthog
        analytics_mod._posthog = mock_ph

        analytics_mod.track("tg:123", "event_sem_props")

        mock_ph.capture.assert_called_once_with(
            distinct_id="tg:123", event="event_sem_props", properties={}
        )
        analytics_mod._posthog = old_client

    def _with_client(self, fn):
        """Executa fn com _posthog mockado, restaura depois."""
        import app.services.analytics as analytics_mod
        mock_ph = MagicMock()
        old = analytics_mod._posthog
        analytics_mod._posthog = mock_ph
        try:
            fn(analytics_mod, mock_ph)
        finally:
            analytics_mod._posthog = old

    def test_meal_logged(self):
        def run(mod, ph):
            mod.meal_logged("tg:1", "text", "lunch", 3, 620.5)
            props = ph.capture.call_args[1]["properties"]
            assert props["input_type"] == "text"
            assert props["meal_type"] == "lunch"
            assert props["items_count"] == 3
            assert props["total_kcal"] == 620.5
        self._with_client(run)

    def test_meal_confirmed(self):
        def run(mod, ph):
            mod.meal_confirmed("tg:1", "dinner", 750.333)
            props = ph.capture.call_args[1]["properties"]
            assert props["meal_type"] == "dinner"
            assert props["total_kcal"] == 750.3
        self._with_client(run)

    def test_meal_deleted(self):
        def run(mod, ph):
            mod.meal_deleted("tg:1")
            ph.capture.assert_called_once()
            assert ph.capture.call_args[1]["event"] == mod.MEAL_DELETED
        self._with_client(run)

    def test_onboarding_completed(self):
        def run(mod, ph):
            mod.onboarding_completed("tg:1", "telegram", 2000)
            props = ph.capture.call_args[1]["properties"]
            assert props["channel_type"] == "telegram"
            assert props["goal_kcal"] == 2000
        self._with_client(run)

    def test_goal_set(self):
        def run(mod, ph):
            mod.goal_set("tg:1", 1800, "perder")
            props = ph.capture.call_args[1]["properties"]
            assert props["goal_kcal"] == 1800
            assert props["goal_type"] == "perder"
        self._with_client(run)

    def test_goal_set_none_type_defaults_to_manter(self):
        def run(mod, ph):
            mod.goal_set("tg:1", 2000, None)
            props = ph.capture.call_args[1]["properties"]
            assert props["goal_type"] == "manter"
        self._with_client(run)

    def test_alert_sent(self):
        def run(mod, ph):
            mod.alert_sent("tg:1", "breakfast")
            props = ph.capture.call_args[1]["properties"]
            assert props["meal_type"] == "breakfast"
        self._with_client(run)

    def test_alert_paused(self):
        def run(mod, ph):
            mod.alert_paused("tg:1", 24)
            props = ph.capture.call_args[1]["properties"]
            assert props["hours"] == 24
        self._with_client(run)

    def test_report_requested_default_trigger(self):
        def run(mod, ph):
            mod.report_requested("tg:1", "weekly")
            props = ph.capture.call_args[1]["properties"]
            assert props["period_type"] == "weekly"
            assert props["trigger"] == "command"
        self._with_client(run)

    def test_report_requested_scheduler_trigger(self):
        def run(mod, ph):
            mod.report_requested("tg:1", "monthly", trigger="scheduler")
            props = ph.capture.call_args[1]["properties"]
            assert props["trigger"] == "scheduler"
        self._with_client(run)

    def test_report_generated(self):
        def run(mod, ph):
            mod.report_generated("tg:1", "weekly", "pdf")
            props = ph.capture.call_args[1]["properties"]
            assert props["file_format"] == "pdf"
        self._with_client(run)

    def test_premium_cta_shown(self):
        def run(mod, ph):
            mod.premium_cta_shown("tg:1", "cmd_premium")
            props = ph.capture.call_args[1]["properties"]
            assert props["context"] == "cmd_premium"
        self._with_client(run)

    def test_data_exported(self):
        def run(mod, ph):
            mod.data_exported("tg:1", 42)
            props = ph.capture.call_args[1]["properties"]
            assert props["logs_count"] == 42
        self._with_client(run)

    def test_deletion_requested(self):
        def run(mod, ph):
            mod.deletion_requested("tg:1")
            ph.capture.assert_called_once()
            assert ph.capture.call_args[1]["event"] == mod.DELETION_REQUESTED
        self._with_client(run)

    def test_daily_summary_viewed(self):
        def run(mod, ph):
            mod.daily_summary_viewed("tg:1", 1523.789, 76)
            props = ph.capture.call_args[1]["properties"]
            assert props["total_kcal"] == 1523.8
            assert props["pct_goal"] == 76
        self._with_client(run)

    def test_get_client_lazy_init(self):
        """_get_client inicializa PostHog na primeira chamada com API key."""
        import app.services.analytics as analytics_mod

        old_client = analytics_mod._posthog
        analytics_mod._posthog = None

        mock_ph_module = MagicMock()
        mock_ph_module.api_key = None
        mock_ph_module.host = None

        with (
            patch("app.config.settings") as mock_settings,
            patch.dict("sys.modules", {"posthog": mock_ph_module}),
        ):
            mock_settings.posthog_api_key = "ph_test_key"
            mock_settings.posthog_host = "https://app.posthog.com"
            analytics_mod._posthog = None  # força reinit
            client = analytics_mod._get_client()

        assert client is not None
        analytics_mod._posthog = old_client  # restaura
