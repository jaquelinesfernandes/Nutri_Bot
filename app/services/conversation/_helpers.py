"""HelpersMixin — helpers de estado, URL, banco e datas."""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.meal_log import MealLog
from app.models.user import User

from ._constants import _BACKDATE_LIMIT_FREE, _BACKDATE_LIMIT_PREMIUM, _STATE_TIMEOUTS

logger = logging.getLogger(__name__)


class HelpersMixin:

    _APP_URL = "http://localhost:8000"

    # ── Estado com timeout ─────────────────────────────────────────────────────

    def _set_timed_state(self, user: User, state: str) -> None:
        user.conversation_state = state
        timeout = _STATE_TIMEOUTS.get(state)
        user.state_expires_at = (
            datetime.now(ZoneInfo("UTC")) + timeout if timeout else None
        )

    # ── Links do painel web ────────────────────────────────────────────────────

    def _panel_link(self, user: User) -> str:
        """Rodapé com magic link de 30 min para o painel web."""
        from app.config import settings
        from app.utils.jwt import create_magic_token

        token = create_magic_token(user.id, minutes=30)
        base = (settings.app_url or self._APP_URL).rstrip("/")
        return f"\n\n🌐 [Ver painel]({base}/auth/magic?t={token})"

    def _append_panel_link(self, reply: str, user: User) -> str:
        """Adiciona o link do painel no final, evitando duplicação."""
        if reply and "auth/magic" not in reply:
            try:
                return reply + self._panel_link(user)
            except Exception as e:
                logger.warning(f"[CONV] _panel_link falhou (user={user.channel_id}): {e}")
        return reply

    def _get_base_url(self) -> str:
        from app.config import settings
        return (settings.app_url or self._APP_URL).rstrip("/")

    def _dashboard_cta_from(self, email: str | None) -> str:
        base = self._get_base_url()
        if email:
            return f"\n\n🌐 [Ver no dashboard]({base}/dashboard)"
        else:
            return (
                f"\n\n📊 *Acesse pelo painel web:*\n"
                f"[Criar conta]({base}/cadastro) e envie /vincular para conectar 🔗"
            )

    def _dashboard_cta(self, user: User) -> str:
        return self._dashboard_cta_from(user.email)

    # ── Banco de dados ─────────────────────────────────────────────────────────

    async def _get_today_total_kcal(self, user: User, db: AsyncSession) -> float:
        tz = ZoneInfo(user.timezone or "America/Sao_Paulo")
        now = datetime.now(tz)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)

        stmt = select(MealLog).where(
            MealLog.user_id == user.id,
            MealLog.logged_at >= day_start,
            MealLog.logged_at < day_end,
            MealLog.confirmed.is_(True),
        )
        result = await db.execute(stmt)
        return sum(log.total_calories_kcal for log in result.scalars().all())

    async def _get_today_logs(self, user: User, db: AsyncSession) -> list[MealLog]:
        tz = ZoneInfo(user.timezone or "America/Sao_Paulo")
        now = datetime.now(tz)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)

        stmt = (
            select(MealLog)
            .where(
                MealLog.user_id == user.id,
                MealLog.logged_at >= day_start,
                MealLog.logged_at < day_end,
                MealLog.confirmed.is_(True),
            )
            .order_by(MealLog.logged_at)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    # ── Helpers de data / registro retroativo ─────────────────────────────────

    def _date_label(self, target: date, tz: ZoneInfo) -> str:
        today = datetime.now(tz).date()
        delta = (today - target).days
        date_str = target.strftime("%d/%m")
        if delta == 0:
            return f"{date_str} (hoje)"
        if delta == 1:
            return f"{date_str} (ontem)"
        if delta == 2:
            return f"{date_str} (anteontem)"
        weekdays = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
        return f"{date_str} ({weekdays[target.weekday()]})"

    def _parse_date_from_args(self, args: str | None, user: User) -> date | None:
        tz = ZoneInfo(user.timezone or "America/Sao_Paulo")
        today = datetime.now(tz).date()

        if not args:
            return None
        text = args.strip().lower()

        if "anteontem" in text or "antes de ontem" in text:
            return today - timedelta(days=2)
        if "ontem" in text:
            return today - timedelta(days=1)

        m = re.search(r'(\d{1,2})[/\-](\d{1,2})(?:[/\-](\d{2,4}))?', text)
        if m:
            day, month = int(m.group(1)), int(m.group(2))
            year_raw = m.group(3)
            year = int(year_raw) if year_raw else today.year
            if year < 100:
                year += 2000
            try:
                target = date(year, month, day)
                if target > today:
                    target = date(year - 1, month, day)
                return target
            except ValueError:
                return None

        m = re.search(r'(?:dia\s+)?(\d{1,2})$', text)
        if m:
            day = int(m.group(1))
            if 1 <= day <= 31:
                try:
                    target = date(today.year, today.month, day)
                    if target > today:
                        first = today.replace(day=1)
                        prev_month_last = first - timedelta(days=1)
                        target = date(prev_month_last.year, prev_month_last.month, day)
                    return target
                except ValueError:
                    return None
        return None

    def _check_backdate_limit(self, target: date, user: User) -> str | None:
        tz = ZoneInfo(user.timezone or "America/Sao_Paulo")
        today = datetime.now(tz).date()
        if target >= today:
            return "Só posso registrar refeições de dias passados. Para hoje, é só me contar o que comeu! 😊"
        limit = _BACKDATE_LIMIT_PREMIUM if user.is_premium else _BACKDATE_LIMIT_FREE
        delta = (today - target).days
        if delta > limit:
            if not user.is_premium:
                return (
                    f"No plano gratuito, o registro retroativo é limitado a {_BACKDATE_LIMIT_FREE} dias. "
                    f"A data {target.strftime('%d/%m')} está fora desse limite. 📅\n\n"
                    f"Com o Premium o limite sobe para {_BACKDATE_LIMIT_PREMIUM} dias! /premium"
                )
            return (
                f"Só consigo registrar até {_BACKDATE_LIMIT_PREMIUM} dias atrás. "
                f"A data {target.strftime('%d/%m')} está fora desse limite. 📅"
            )
        return None

    async def _get_date_total_kcal(self, user: User, db: AsyncSession, target: date) -> float:
        tz = ZoneInfo(user.timezone or "America/Sao_Paulo")
        day_start = datetime(target.year, target.month, target.day, 0, 0, 0, tzinfo=tz)
        day_end = day_start + timedelta(days=1)
        stmt = select(MealLog).where(
            MealLog.user_id == user.id,
            MealLog.logged_at >= day_start,
            MealLog.logged_at < day_end,
            MealLog.confirmed.is_(True),
        )
        result = await db.execute(stmt)
        return sum(log.total_calories_kcal for log in result.scalars().all())

    # ── Formatadores de log (usados em delete e hoje) ─────────────────────────

    def _format_today_logs(self, logs: list, numbered: bool = False) -> str:
        lines = []
        for i, l in enumerate(logs, 1):
            name = self._MEAL_NAME.get(l.meal_type, "Refeição")  # type: ignore[attr-defined]
            tz = ZoneInfo("America/Sao_Paulo")
            hora = l.logged_at.astimezone(tz).strftime("%H:%M")
            prefix = f"{i}. " if numbered else "• "
            lines.append(f"{prefix}{name} ({hora}) — {l.total_calories_kcal:.0f} kcal")
        return "\n".join(lines)

    def _format_today_logs_from_state(self, meals: list[dict]) -> str:
        lines = []
        tz = ZoneInfo("America/Sao_Paulo")
        from datetime import datetime as dt
        for i, m in enumerate(meals, 1):
            name = self._MEAL_NAME.get(m["meal_type"], "Refeição")  # type: ignore[attr-defined]
            hora = dt.fromisoformat(m["logged_at"]).astimezone(tz).strftime("%H:%M")
            lines.append(f"{i}. {name} ({hora}) — {m['kcal']:.0f} kcal")
        return "\n".join(lines)
