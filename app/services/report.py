"""Geração de relatórios nutricionais em PDF com WeasyPrint (fallback HTML).

Suporta múltiplos períodos: semanal, mensal, trimestral ou intervalo customizado.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.meal_log import MealLog
from app.models.user import User
from app.models.weekly_report import WeeklyReport

logger = logging.getLogger(__name__)

_MEAL_ICONS = {
    "breakfast":       "☀️",
    "morning_snack":   "🍌",
    "lunch":           "🍽️",
    "afternoon_snack": "🍊",
    "dinner":          "🌙",
    "snack":           "🍎",
    "other":           "🍴",
}
_DAY_NAMES_PT = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
_MONTH_NAMES_PT = [
    "", "Jan", "Fev", "Mar", "Abr", "Mai", "Jun",
    "Jul", "Ago", "Set", "Out", "Nov", "Dez",
]
_MONTH_FULL_PT = [
    "", "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
]
_TEMPLATE_DIR = Path(__file__).parent.parent.parent / "data"


def _bar_class(pct: int) -> str:
    if pct == 0:
        return "bar-gray"
    if pct > 110:
        return "bar-orange"
    if pct < 60:
        return "bar-yellow"
    return "bar-green"


def _pct(val: float, goal: float) -> int:
    return min(int(val / goal * 100), 999) if goal else 0


def _bar_color(pct: int) -> str:
    if pct == 0:
        return "#cbd5e1"
    if 80 <= pct <= 115:
        return "#6366F1"  # indigo — igual ao ok-c do painel
    if pct < 80:
        return "#f59e0b"
    return "#ef4444"


def _period_label(start: date, end: date, period_type: str) -> str:
    """Human-readable label for the report period."""
    last = end - timedelta(days=1)
    if period_type == "weekly":
        return f"{start.strftime('%d/%m')} a {last.strftime('%d/%m/%Y')}"
    if period_type == "monthly":
        return f"{_MONTH_FULL_PT[start.month].capitalize()} de {start.year}"
    if period_type == "quarterly":
        start_m = _MONTH_NAMES_PT[start.month]
        end_m = _MONTH_NAMES_PT[last.month]
        return f"{start_m}–{end_m}/{last.year}"
    # custom
    return f"{start.strftime('%d/%m/%Y')} a {last.strftime('%d/%m/%Y')}"


def _build_row(
    label: str, logs: list, goal_kcal: int, tz: ZoneInfo
) -> dict:
    """Build a single row dict for the days table, from a list of MealLog objects."""
    day_kcal = sum(l.total_calories_kcal for l in logs)
    meal_types = {l.meal_type for l in logs}
    pct = int(day_kcal / goal_kcal * 100) if logs and goal_kcal else 0

    if not logs:
        badge_cls, badge_lbl = "badge-miss", "Sem registro"
    elif 80 <= pct <= 115:
        badge_cls, badge_lbl = "badge-ok", "Na meta"
    elif pct < 80:
        badge_cls, badge_lbl = "badge-low", "Abaixo"
    else:
        badge_cls, badge_lbl = "badge-over", "Acima"

    icon_order = ["breakfast", "morning_snack", "lunch", "afternoon_snack", "dinner", "snack", "other"]
    meals_label = " ".join(_MEAL_ICONS[m] for m in icon_order if m in meal_types) or "—"

    return {
        "label": label,
        "kcal": f"{day_kcal:.0f}" if logs else "—",
        "meals_label": meals_label,
        "pct": pct,
        "bar_pct": min(pct, 100),
        "bar_cls": _bar_class(pct),
        "badge_cls": badge_cls,
        "badge_lbl": badge_lbl,
    }


def _group_logs_daily(
    all_logs: list, start: date, end: date, tz: ZoneInfo
) -> list[dict]:
    """One row per calendar day in [start, end)."""
    rows = []
    num_days = (end - start).days
    for i in range(num_days):
        day = start + timedelta(days=i)
        day_logs = [l for l in all_logs if l.logged_at.astimezone(tz).date() == day]
        label = f"{_DAY_NAMES_PT[day.weekday()]} {day.strftime('%d/%m')}"
        rows.append(_build_row(label, day_logs, 0, tz))  # goal_kcal passed at call site
    return rows


def _group_logs_weekly(
    all_logs: list, start: date, end: date, tz: ZoneInfo, goal_kcal: int
) -> list[dict]:
    """One row per 7-day chunk starting from start."""
    rows = []
    cursor = start
    week_num = 1
    while cursor < end:
        chunk_end = min(cursor + timedelta(days=7), end)
        chunk_logs = [
            l for l in all_logs
            if cursor <= l.logged_at.astimezone(tz).date() < chunk_end
        ]
        label = f"Semana {week_num} ({cursor.strftime('%d/%m')}–{(chunk_end - timedelta(days=1)).strftime('%d/%m')})"
        rows.append(_build_row(label, chunk_logs, goal_kcal, tz))
        cursor = chunk_end
        week_num += 1
    return rows


def _group_logs_monthly(
    all_logs: list, start: date, end: date, tz: ZoneInfo, goal_kcal: int
) -> list[dict]:
    """One row per calendar month in [start, end)."""
    import calendar
    rows = []
    year, month = start.year, start.month
    while True:
        month_start = date(year, month, 1)
        last_day = calendar.monthrange(year, month)[1]
        month_end = date(year, month, last_day) + timedelta(days=1)
        actual_end = min(month_end, end)
        if month_start >= end:
            break
        month_logs = [
            l for l in all_logs
            if month_start <= l.logged_at.astimezone(tz).date() < actual_end
        ]
        label = f"{_MONTH_FULL_PT[month].capitalize()} {year}"
        rows.append(_build_row(label, month_logs, goal_kcal, tz))
        month += 1
        if month > 12:
            month = 1
            year += 1
    return rows


class ReportService:

    async def generate_report(
        self,
        user: User,
        start_date: date,
        end_date: date,
        period_type: str,
        db: AsyncSession,
        save: bool = True,
    ) -> tuple[bytes, str]:
        """
        Generate a nutritional report for [start_date, end_date).

        period_type: 'weekly' | 'monthly' | 'quarterly' | 'custom'
        Returns (file_bytes, extension) — 'pdf' or 'html'.
        Saves a WeeklyReport record to DB.
        """
        tz = ZoneInfo(user.timezone or "America/Sao_Paulo")
        start_dt = datetime(start_date.year, start_date.month, start_date.day, 0, 0, tzinfo=tz)
        end_dt = datetime(end_date.year, end_date.month, end_date.day, 0, 0, tzinfo=tz)

        result = await db.execute(
            select(MealLog).where(
                MealLog.user_id == user.id,
                MealLog.logged_at >= start_dt,
                MealLog.logged_at < end_dt,
                MealLog.confirmed.is_(True),
            )
        )
        logs = result.scalars().all()

        goal_kcal = user.daily_calorie_goal or 2000

        # Totals
        total_kcal = total_protein = total_carb = total_fat = 0.0
        days_with_logs: set[date] = set()
        for log in logs:
            d = log.logged_at.astimezone(tz).date()
            days_with_logs.add(d)
            total_kcal += log.total_calories_kcal
            total_protein += log.total_protein_g
            total_carb += log.total_carb_g
            total_fat += log.total_fat_g

        n = max(len(days_with_logs), 1)
        total_days = (end_date - start_date).days
        avg_kcal = int(total_kcal / n)
        avg_protein = int(total_protein / n)
        avg_carb = int(total_carb / n)
        avg_fat = int(total_fat / n)

        # Macro goals (25% prot / 50% carb / 25% fat split)
        goal_protein_g = int(goal_kcal * 0.25 / 4)
        goal_carb_g = int(goal_kcal * 0.50 / 4)
        goal_fat_g = int(goal_kcal * 0.25 / 9)

        pct_kcal = _pct(avg_kcal, goal_kcal)
        pct_protein = _pct(avg_protein, goal_protein_g)
        pct_carb = _pct(avg_carb, goal_carb_g)
        pct_fat = _pct(avg_fat, goal_fat_g)
        pct_days = _pct(len(days_with_logs), total_days)

        # Build table rows based on period granularity
        if period_type == "weekly":
            days_data = _group_logs_daily(list(logs), start_date, end_date, tz)
            # Patch goal_kcal and recompute badge/bar for each row
            for row in days_data:
                day = start_date + timedelta(days=days_data.index(row))
                day_logs = [l for l in logs if l.logged_at.astimezone(tz).date() == day]
                pct_day = int(sum(l.total_calories_kcal for l in day_logs) / goal_kcal * 100) if day_logs and goal_kcal else 0
                row["pct"] = pct_day
                row["bar_pct"] = min(pct_day, 100)
                row["bar_cls"] = _bar_class(pct_day)
                if not day_logs:
                    row["badge_cls"], row["badge_lbl"] = "badge-miss", "Sem registro"
                elif 80 <= pct_day <= 115:
                    row["badge_cls"], row["badge_lbl"] = "badge-ok", "Na meta"
                elif pct_day < 80:
                    row["badge_cls"], row["badge_lbl"] = "badge-low", "Abaixo"
                else:
                    row["badge_cls"], row["badge_lbl"] = "badge-over", "Acima"
        elif period_type in ("monthly", "custom"):
            days_data = _group_logs_weekly(list(logs), start_date, end_date, tz, goal_kcal)
        else:  # quarterly
            days_data = _group_logs_monthly(list(logs), start_date, end_date, tz, goal_kcal)

        week_summary = {
            "avg_kcal": avg_kcal,
            "avg_protein_g": avg_protein,
            "avg_carb_g": avg_carb,
            "avg_fat_g": avg_fat,
            "days_logged": len(days_with_logs),
            "goal_kcal": goal_kcal,
            "total_meals": len(logs),
            "period_type": period_type,
            "total_days": total_days,
        }
        user_context = {
            "name": user.first_name or "Usuário",
            "goal_kcal": goal_kcal,
            "goal_type": user.goal_type or "manutenção",
        }

        from app.services.ai_service import ai_service
        try:
            ai_result = await ai_service.generate_report_suggestions(user_context, week_summary)
            suggestions = [s.model_dump() for s in ai_result.suggestions]
            highlights = ai_result.highlights
            weekly_insight = ai_result.weekly_insight
        except Exception as e:
            logger.warning(f"[REPORT] AI suggestions falhou: {e}")
            suggestions = [{
                "category": "variedade",
                "text": "Continue registrando suas refeições diariamente para receber sugestões personalizadas!",
                "priority": "medium",
            }]
            highlights = []
            weekly_insight = None

        period_label = _period_label(start_date, end_date, period_type)

        env = Environment(loader=FileSystemLoader(str(_TEMPLATE_DIR)), autoescape=True)
        template = env.get_template("report_template.html")
        html = template.render(
            user_name=user.first_name or "Usuário",
            week_label=period_label,
            avg_kcal=avg_kcal,
            avg_protein_g=avg_protein,
            avg_carb_g=avg_carb,
            avg_fat_g=avg_fat,
            goal_kcal=goal_kcal,
            goal_protein_g=goal_protein_g,
            goal_carb_g=goal_carb_g,
            goal_fat_g=goal_fat_g,
            pct_kcal=pct_kcal,
            pct_protein=pct_protein,
            pct_carb=pct_carb,
            pct_fat=pct_fat,
            pct_days=pct_days,
            bar_color_kcal=_bar_color(pct_kcal),
            bar_color_protein=_bar_color(pct_protein),
            bar_color_carb=_bar_color(pct_carb),
            bar_color_fat=_bar_color(pct_fat),
            bar_color_days=_bar_color(pct_days),
            days_logged=len(days_with_logs),
            total_meals=len(logs),
            days=days_data,
            suggestions=suggestions,
            highlights=highlights,
            weekly_insight=weekly_insight,
            generated_at=datetime.now(tz).strftime("%d/%m/%Y às %H:%M"),
        )

        try:
            from weasyprint import HTML as WeasyprintHTML
            file_bytes = WeasyprintHTML(string=html).write_pdf()
            ext = "pdf"
        except Exception as e:
            logger.warning(f"[REPORT] WeasyPrint indisponível ({type(e).__name__}) — retornando HTML")
            file_bytes = html.encode("utf-8")
            ext = "html"

        if save:
            report = WeeklyReport(
                user_id=user.id,
                week_start_date=start_date,
                period_type=period_type,
                period_end_date=end_date - timedelta(days=1),
                summary_json=json.dumps(week_summary, ensure_ascii=False),
                delivered_at=datetime.now(ZoneInfo("UTC")),
            )
            db.add(report)
            await db.commit()

        logger.info(
            f"[REPORT] Gerado para {user.channel_id} — {period_type} {start_date}→{end_date} ({ext})"
        )
        return file_bytes, ext

    async def generate_weekly_pdf(
        self, user: User, week_start: date, db: AsyncSession
    ) -> tuple[bytes, str]:
        """Backward-compatible wrapper — generates a 7-day weekly report."""
        return await self.generate_report(
            user, week_start, week_start + timedelta(days=7), "weekly", db
        )


report_service = ReportService()
