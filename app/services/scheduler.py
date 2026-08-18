"""APScheduler jobs: alertas de refeição, relatório semanal, re-engajamento."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

logger = logging.getLogger(__name__)

# Configuração dos alertas: (meal_type, hora, minuto, mensagem)
_ALERT_JOBS = [
    (
        "breakfast", 9, 30,
        "Bom dia, {name}! ☀️ Você já tomou café da manhã?\n"
        "Me conta o que comeu para eu registrar suas calorias! 🥣",
    ),
    (
        "lunch", 12, 30,
        "Ei, {name}! 🍽️ Já passaram das 12h — você já almoçou?\n"
        "Me conta o que comeu! 🥗",
    ),
    (
        "dinner", 19, 30,
        "Boa noite, {name}! 🌙 Hora de registrar o jantar.\n"
        "O que você comeu esta noite? 🍲",
    ),
]


async def _send_meal_alert(meal_type: str, message_template: str) -> None:
    """Envia alerta para todos os usuários que não registraram a refeição ainda."""
    from app.db.session import AsyncSessionLocal
    from app.models.meal_log import MealLog
    from app.models.user import User
    from app.services.notification import notification_service

    tz = ZoneInfo("America/Sao_Paulo")
    now = datetime.now(tz)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)

    async with AsyncSessionLocal() as db:
        # Busca usuários elegíveis: onboarding completo, alertas ativos, não deletados
        result = await db.execute(
            select(User).where(
                User.onboarding_complete.is_(True),
                User.alerts_enabled.is_(True),
                User.deleted_at.is_(None),
            )
        )
        users = result.scalars().all()

        alerted = 0
        for user in users:
            # Respeita pausa de alertas
            if user.alerts_paused_until:
                paused_until = user.alerts_paused_until
                if paused_until.tzinfo is None:
                    paused_until = paused_until.replace(tzinfo=ZoneInfo("UTC"))
                if now.astimezone(ZoneInfo("UTC")) < paused_until:
                    continue

            # Verifica se já registrou essa refeição hoje
            log_result = await db.execute(
                select(MealLog).where(
                    MealLog.user_id == user.id,
                    MealLog.meal_type == meal_type,
                    MealLog.logged_at >= day_start,
                    MealLog.logged_at < day_end,
                    MealLog.confirmed.is_(True),
                )
            )
            if log_result.scalar_one_or_none():
                continue  # já registrou, não precisa de lembrete

            name = user.first_name or "você"
            message = message_template.format(name=name)
            sent = await notification_service.send_text(user, message)
            if sent:
                alerted += 1

        logger.info(f"[ALERT] {meal_type}: {alerted}/{len(users)} alertas enviados")


async def job_alert_breakfast() -> None:
    await _send_meal_alert("breakfast", _ALERT_JOBS[0][3])


async def job_alert_lunch() -> None:
    await _send_meal_alert("lunch", _ALERT_JOBS[1][3])


async def job_alert_dinner() -> None:
    await _send_meal_alert("dinner", _ALERT_JOBS[2][3])


async def _send_periodic_report(period_type: str) -> None:
    """Gera e envia relatório para todos os usuários premium com a frequência configurada.

    period_type: 'weekly' | 'monthly' | 'quarterly'
    """
    import asyncio
    from datetime import date, timedelta
    import calendar

    from sqlalchemy import select

    from app.db.session import AsyncSessionLocal
    from app.models.user import User
    from app.models.weekly_report import WeeklyReport
    from app.services.notification import notification_service
    from app.services.report import report_service

    today = date.today()

    if period_type == "weekly":
        # Segunda-feira da semana que terminou ontem (domingo=hoje)
        end_date = today + timedelta(days=1)  # exclusive
        start_date = today - timedelta(days=6)
        period_label_short = "semanal"
    elif period_type == "monthly":
        # Mês anterior completo
        first_of_month = today.replace(day=1)
        last_month_end = first_of_month
        last_month_start = (first_of_month - timedelta(days=1)).replace(day=1)
        start_date, end_date = last_month_start, last_month_end
        period_label_short = "mensal"
    else:  # quarterly
        # Trimestre anterior
        month = today.month
        quarter_start_months = [1, 4, 7, 10]
        current_q_start = max(m for m in quarter_start_months if m <= month)
        if current_q_start == 1:
            prev_q_start = date(today.year - 1, 10, 1)
        else:
            prev_q_start = date(today.year, current_q_start - 3, 1)
        end_date = date(today.year, current_q_start, 1)
        start_date = prev_q_start
        period_label_short = "trimestral"

    logger.info(f"job_report_{period_type} iniciado: {start_date} → {end_date}")

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(User).where(
                User.onboarding_complete.is_(True),
                User.deleted_at.is_(None),
            )
        )
        users = result.scalars().all()

        # Premium com a frequência configurada (ou 'none' = nunca)
        premium_users = [
            u for u in users
            if u.is_premium and u.report_frequency == period_type
        ]
        free_users = [u for u in users if not u.is_premium and u.alerts_enabled]

        # ── Premium: PDF/HTML completo ────────────────────────────────────────
        sent = skipped = errors = 0
        for i, user in enumerate(premium_users):
            existing = await db.execute(
                select(WeeklyReport).where(
                    WeeklyReport.user_id == user.id,
                    WeeklyReport.week_start_date == start_date,
                    WeeklyReport.period_type == period_type,
                ).limit(1)
            )
            if existing.scalars().first():
                skipped += 1
                continue

            try:
                file_bytes, ext = await report_service.generate_report(
                    user, start_date, end_date, period_type, db
                )
                name = user.first_name or "você"
                filename = f"nutribot_relatorio_{period_type}_{start_date.strftime('%Y-%m-%d')}.{ext}"
                caption = (
                    f"📊 *Seu relatório {period_label_short} chegou, {name}!*\n"
                    "Confira seu progresso 👆"
                )
                await notification_service.send_document(user, file_bytes, filename, caption)
                sent += 1
            except Exception as e:
                logger.error(f"[REPORT] Falha para {user.channel_id}: {e}")
                errors += 1

            if (i + 1) % 25 == 0:
                await asyncio.sleep(1.0)
            else:
                await asyncio.sleep(0.04)

        logger.info(
            f"[REPORT] {period_type} Premium: {sent} enviados, {skipped} já tinham, {errors} erros"
        )

        # ── Free: preview com CTA de upgrade (apenas no semanal) ─────────────
        if period_type == "weekly":
            preview_sent = 0
            for i, user in enumerate(free_users):
                name = user.first_name or "você"
                ok = await notification_service.send_text(
                    user,
                    f"📊 *{name}, seu resumo semanal está pronto!*\n\n"
                    "Você usou o NutriBot esta semana 🎉\n\n"
                    "🔒 *Desbloqueie o relatório completo com Premium:*\n"
                    "• Gráfico diário de calorias\n"
                    "• Análise de macros da semana\n"
                    "• Sugestões personalizadas de IA\n"
                    "• PDF para compartilhar\n\n"
                    "👉 /premium — R$ 19,90/mês",
                )
                if ok:
                    preview_sent += 1
                if (i + 1) % 25 == 0:
                    await asyncio.sleep(1.0)
                else:
                    await asyncio.sleep(0.04)
            logger.info(f"[REPORT] Free preview: {preview_sent}/{len(free_users)} enviados")


async def job_weekly_report() -> None:
    """Domingo 20h: relatório semanal para usuários com frequência 'weekly'."""
    await _send_periodic_report("weekly")


async def job_monthly_report() -> None:
    """1º dia do mês 20h: relatório mensal para usuários com frequência 'monthly'."""
    await _send_periodic_report("monthly")


async def job_quarterly_report() -> None:
    """1º dia do trimestre 20h: relatório trimestral para usuários com frequência 'quarterly'."""
    await _send_periodic_report("quarterly")


async def job_reengagement() -> None:
    """Segunda 10h: re-engaja usuários que não acessam há 3+ dias."""
    from app.db.session import AsyncSessionLocal
    from app.models.user import User
    from app.services.notification import notification_service
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("America/Sao_Paulo")
    cutoff = datetime.now(tz) - timedelta(days=3)

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(User).where(
                User.onboarding_complete.is_(True),
                User.alerts_enabled.is_(True),
                User.deleted_at.is_(None),
                User.last_active_at < cutoff,
            )
        )
        users = result.scalars().all()
        for user in users:
            name = user.first_name or "você"
            await notification_service.send_text(
                user,
                f"Oi, {name}! 👋 Faz alguns dias que não nos falamos.\n"
                "Que tal registrar o que você comeu hoje? Estou aqui para ajudar! 🥗"
            )
        logger.info(f"[REENGAGEMENT] {len(users)} mensagens enviadas")


async def start_scheduler() -> AsyncIOScheduler:
    # Timezone explícito em todos os CronTriggers: o Render roda em UTC e o
    # CronTrigger sem timezone usa o fuso do sistema (UTC), ignorando o timezone
    # do scheduler. Passamos "America/Sao_Paulo" explicitamente em cada trigger
    # para garantir que os horários sejam interpretados no fuso correto.
    SP_TZ = "America/Sao_Paulo"
    scheduler = AsyncIOScheduler(timezone=SP_TZ)

    # Alertas de refeição — hora fixa por refeição (horário de Brasília)
    scheduler.add_job(job_alert_breakfast, CronTrigger(hour=9,  minute=30, timezone=SP_TZ))
    scheduler.add_job(job_alert_lunch,     CronTrigger(hour=12, minute=30, timezone=SP_TZ))
    scheduler.add_job(job_alert_dinner,    CronTrigger(hour=19, minute=30, timezone=SP_TZ))

    # Relatórios automáticos por frequência (horário de Brasília)
    scheduler.add_job(job_weekly_report,    CronTrigger(day_of_week="sun", hour=20, minute=0, timezone=SP_TZ))
    scheduler.add_job(job_monthly_report,   CronTrigger(day=1, hour=20, minute=0, timezone=SP_TZ))
    # Trimestral: 1º de jan, abr, jul, out
    scheduler.add_job(job_quarterly_report, CronTrigger(month="1,4,7,10", day=1, hour=20, minute=0, timezone=SP_TZ))

    # Re-engajamento (horário de Brasília)
    scheduler.add_job(job_reengagement, CronTrigger(day_of_week="mon", hour=10, minute=0, timezone=SP_TZ))

    scheduler.start()
    logger.info(
        "Scheduler iniciado (America/Sao_Paulo): alertas 09:30/12:30/19:30 | "
        "relatório dom 20h (semanal) | 1º/mês 20h (mensal) | 1º trimestre 20h (trimestral)"
    )
    return scheduler
