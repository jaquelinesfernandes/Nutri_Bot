"""CommandsMixin — todos os handlers /cmd_* e água."""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.models.meal_log import MealLog
from app.models.user import User
from app.services import analytics

from ._constants import CONFIRM_WORDS, DENY_WORDS, _matches_intent

logger = logging.getLogger(__name__)


class CommandsMixin:

    _MEAL_TYPE_MAP: dict[str, str] = {
        "café": "breakfast", "cafe": "breakfast", "café da manhã": "breakfast",
        "cafe da manha": "breakfast", "pequeno almoço": "breakfast",
        "lanche da manhã": "morning_snack", "lanche da manha": "morning_snack",
        "lanchinho da manhã": "morning_snack", "lanchinho da manha": "morning_snack",
        "almoço": "lunch", "almoco": "lunch",
        "lanche da tarde": "afternoon_snack", "lanchinho da tarde": "afternoon_snack",
        "lanche": "snack", "lanchinho": "snack",
        "jantar": "dinner",
        "ceia": "snack",
    }
    _MEAL_NAME: dict[str, str] = {
        "breakfast":       "Café da manhã",
        "morning_snack":   "Lanche da manhã",
        "lunch":           "Almoço",
        "afternoon_snack": "Lanche da tarde",
        "dinner":          "Jantar",
        "snack":           "Lanche",
        "other":           "Refeição",
    }

    # ── Deleção de refeição ────────────────────────────────────────────────────

    async def _cmd_deletar_refeicao(self, user: User, args: str | None, db: AsyncSession) -> str:
        logs = await self._get_today_logs(user, db)  # type: ignore[attr-defined]

        if not logs:
            return "Nenhuma refeição registrada hoje para deletar. 🍽️"

        if args:
            args_lower = args.strip().lower()
            target_type = next(
                (v for k, v in self._MEAL_TYPE_MAP.items() if k in args_lower), None
            )
            if target_type:
                matched = [l for l in logs if l.meal_type == target_type]
                if matched:
                    return await self._ask_delete_confirm(user, matched[-1], db)
                return (
                    f"Não encontrei {self._MEAL_NAME.get(target_type, args)} "
                    f"registrado hoje.\n\nRefeições de hoje:\n"
                    + self._format_today_logs(logs)  # type: ignore[attr-defined]
                )

        if len(logs) == 1:
            return await self._ask_delete_confirm(user, logs[0], db)

        lines = self._format_today_logs(logs, numbered=True)  # type: ignore[attr-defined]
        self._set_timed_state(user, "CONFIRMING")  # type: ignore[attr-defined]
        user.state_data = {
            "pending_action": "delete_meal_pick",
            "meals": [
                {"id": str(l.id), "meal_type": l.meal_type,
                 "kcal": l.total_calories_kcal, "logged_at": l.logged_at.isoformat()}
                for l in logs
            ],
        }
        flag_modified(user, "state_data")
        await db.commit()
        return (
            f"🗑️ *Qual refeição deseja deletar?*\n\n{lines}\n\n"
            "Responda com o número ou /cancelar para desistir."
        )

    async def _ask_delete_confirm(self, user: User, meal, db: AsyncSession) -> str:
        name = self._MEAL_NAME.get(meal.meal_type, "Refeição")
        tz = ZoneInfo("America/Sao_Paulo")
        hora = meal.logged_at.astimezone(tz).strftime("%H:%M")
        self._set_timed_state(user, "CONFIRMING")  # type: ignore[attr-defined]
        user.state_data = {
            "pending_action": "delete_meal",
            "meal_log_id": str(meal.id),
            "meal_summary": f"{name} ({hora}) — {meal.total_calories_kcal:.0f} kcal",
        }
        flag_modified(user, "state_data")
        await db.commit()
        return (
            f"🗑️ Confirma deletar?\n\n"
            f"*{name}* às {hora} — {meal.total_calories_kcal:.0f} kcal\n\n"
            "Responda *sim* para confirmar ou *não* para cancelar."
        )

    async def _handle_delete_pick(
        self, user: User, text: str, db: AsyncSession, pending: dict
    ) -> str:
        meals = pending.get("meals", [])
        digits = "".join(c for c in text if c.isdigit())
        if digits:
            idx = int(digits) - 1
            if 0 <= idx < len(meals):
                chosen = meals[idx]
                name = self._MEAL_NAME.get(chosen["meal_type"], "Refeição")
                tz = ZoneInfo("America/Sao_Paulo")
                from datetime import datetime as dt
                hora = dt.fromisoformat(chosen["logged_at"]).astimezone(tz).strftime("%H:%M")
                self._set_timed_state(user, "CONFIRMING")  # type: ignore[attr-defined]
                user.state_data = {
                    "pending_action": "delete_meal",
                    "meal_log_id": chosen["id"],
                    "meal_summary": f"{name} ({hora}) — {chosen['kcal']:.0f} kcal",
                }
                flag_modified(user, "state_data")
                await db.commit()
                return (
                    f"🗑️ Confirma deletar?\n\n"
                    f"*{name}* às {hora} — {chosen['kcal']:.0f} kcal\n\n"
                    "Responda *sim* para confirmar ou *não* para cancelar."
                )
        lines = self._format_today_logs_from_state(meals)  # type: ignore[attr-defined]
        return f"Por favor, responda com o número da refeição:\n\n{lines}"

    async def _handle_delete_confirm(
        self, user: User, text: str, db: AsyncSession, pending: dict
    ) -> str:
        import uuid as _uuid
        summary = pending.get("meal_summary", "refeição")

        if _matches_intent(text, CONFIRM_WORDS):
            meal_log_id = pending.get("meal_log_id")
            if meal_log_id:
                result = await db.execute(
                    select(MealLog).where(
                        MealLog.id == _uuid.UUID(meal_log_id),
                        MealLog.user_id == user.id,
                    )
                )
                meal = result.scalar_one_or_none()
                if meal:
                    await db.delete(meal)
            user.conversation_state = "IDLE"
            user.state_data = None
            await db.commit()
            return f"✅ *{summary}* deletado com sucesso!"

        if _matches_intent(text, DENY_WORDS):
            user.conversation_state = "IDLE"
            user.state_data = None
            await db.commit()
            return "Ok, nada foi deletado. 👍"

        return f"Responda *sim* para confirmar a exclusão ou *não* para cancelar.\n_{summary}_"

    # ── Comandos principais ───────────────────────────────────────────────────

    async def _cmd_start(self, user: User, args, db: AsyncSession) -> str:
        if args and str(args).startswith("convite_"):
            token = str(args)[len("convite_"):]
            return await self._iniciar_convite(user, token, db)  # type: ignore[attr-defined]

        if user.conversation_state not in ("IDLE", "ONBOARDING"):
            user.conversation_state = "IDLE"
            user.state_data = None
            user.state_expires_at = None
            await db.commit()

        if user.onboarding_complete:
            name = user.first_name or "você"
            logs = await self._get_today_logs(user, db)  # type: ignore[attr-defined]
            if logs:
                total_kcal = sum(l.total_calories_kcal for l in logs)
                n = len(logs)
                goal_line = ""
                if user.daily_calorie_goal:
                    pct = min(100, int(total_kcal / user.daily_calorie_goal * 100))
                    bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
                    goal_line = f"\n`{bar}` {pct}% da meta ({user.daily_calorie_goal} kcal)"
                return (
                    f"Olá de novo, {name}! 👋\n\n"
                    f"📅 Hoje: {n} refeição{'s' if n > 1 else ''} — {total_kcal:.0f} kcal{goal_line}\n\n"
                    "Me conta o que comeu, ou use /ajuda para ver os comandos."
                )
            return (
                f"Olá de novo, {name}! 👋\n\n"
                "Nenhuma refeição registrada hoje ainda. Me conta o que comeu! 🥗"
            )
        user.conversation_state = "ONBOARDING"
        user.state_data = {"step": 0}
        await db.commit()
        return (
            "👋 Olá! Sou o *NutriBot*, seu assistente de nutrição pessoal! 🥗\n\n"
            "Vou te ajudar a:\n"
            "• Registrar refeições em linguagem natural\n"
            "• Acompanhar calorias e macros\n"
            "• Receber relatórios semanais com insights\n\n"
            "Para começar, qual é o seu *nome*?"
        )

    async def _cmd_ajuda(self, user: User, args, db) -> str:
        if user.is_premium:
            return (
                "📋 *NutriBot Premium — Comandos:*\n\n"
                "🍽️ *Refeições*\n"
                "• /hoje — resumo do dia\n"
                "• /historico — histórico de refeições\n"
                "• /registrar [data] — adicionar refeição de dia passado\n"
                "• /deletar [refeição] — apagar refeição de hoje\n"
                "• /desfazer — desfazer última refeição\n\n"
                "💧 *Hidratação*\n"
                "• /agua [ml] — registrar água (padrão 250ml)\n\n"
                "📊 *Relatórios Premium*\n"
                "• /relatorio semana — gerar agora\n"
                "• /relatorios — ver histórico\n"
                "• /frequencia — configurar envio automático\n\n"
                "⚙️ *Configurações*\n"
                "• /meta [kcal] — meta calórica diária\n"
                "• /alertas on|off — lembretes de refeição\n"
                "• /silenciar [horas] — pausar alertas\n"
                "• /painel — abrir painel web\n"
                "• /plano — seu plano atual\n\n"
                "🔒 *Privacidade & Conta*\n"
                "• /privacidade — política LGPD\n"
                "• /exportar\\_dados — exportar dados\n"
                "• /deletar\\_dados — apagar tudo (72h)\n"
                "• /feedback [texto] — enviar feedback\n"
                "• /cancelar — cancelar ação em curso"
            )
        return (
            "📋 *NutriBot — Comandos:*\n\n"
            "🍽️ *Refeições*\n"
            "• /hoje — resumo do dia\n"
            "• /historico — histórico de refeições\n"
            "• /registrar [data] — adicionar refeição de dia passado\n"
            "• /deletar [refeição] — apagar refeição de hoje\n"
            "• /desfazer — desfazer última refeição\n\n"
            "💧 *Hidratação*\n"
            "• /agua [ml] — registrar água (padrão 250ml)\n\n"
            "⚙️ *Configurações*\n"
            "• /meta [kcal] — meta calórica diária\n"
            "• /alertas on|off — lembretes de refeição\n"
            "• /silenciar [horas] — pausar alertas temporariamente\n"
            "• /painel — abrir painel web\n\n"
            "🔒 *Privacidade & Conta*\n"
            "• /privacidade — política LGPD\n"
            "• /exportar\\_dados — exportar dados\n"
            "• /deletar\\_dados — apagar tudo (72h)\n"
            "• /feedback [texto] — enviar feedback\n"
            "• /cancelar — cancelar ação em curso"
        )

    async def _cmd_hoje(self, user: User, args, db: AsyncSession) -> str:
        from app.models.water_log import WaterLog
        from sqlalchemy import func as _f

        logs = await self._get_today_logs(user, db)  # type: ignore[attr-defined]

        tz = ZoneInfo(user.timezone or "America/Sao_Paulo")
        now = datetime.now(tz)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end   = day_start + timedelta(days=1)

        w_res = await db.execute(
            select(_f.coalesce(_f.sum(WaterLog.volume_ml), 0.0)).where(
                WaterLog.user_id == user.id,
                WaterLog.logged_at >= day_start,
                WaterLog.logged_at < day_end,
            )
        )
        water_ml  = int(w_res.scalar_one() or 0)
        goal_water = user.daily_water_goal_ml or 2000
        pct_water  = min(100, round(water_ml / goal_water * 100))
        w_filled   = pct_water // 20
        water_bar  = "💧" * w_filled + "○" * (5 - w_filled)

        if not logs:
            water_line = (
                f"\n\n💧 *Hidratação:* {water_ml}ml / {goal_water}ml\n"
                f"{water_bar} {pct_water}%\n"
                "_Use /agua para registrar_"
            ) if water_ml > 0 else (
                "\n\n💧 *Hidratação:* nenhum registro hoje\n"
                "_Use /agua 250 ou 'bebi um copo de água'_"
            )
            return (
                "Nenhuma refeição registrada hoje ainda! 🍽️\n"
                "Me conta o que você comeu."
                + water_line
            )

        total_kcal    = sum(l.total_calories_kcal for l in logs)
        total_protein = sum(l.total_protein_g for l in logs)
        total_carb    = sum(l.total_carb_g for l in logs)
        total_fat     = sum(l.total_fat_g for l in logs)

        meal_names = {
            "breakfast": "Café", "morning_snack": "Lanche manhã",
            "lunch": "Almoço", "afternoon_snack": "Lanche tarde",
            "dinner": "Jantar", "snack": "Lanche", "other": "Refeição",
        }
        lines = "\n".join(
            f"• {meal_names.get(l.meal_type, 'Refeição')}: {l.total_calories_kcal:.0f} kcal"
            for l in logs
        )

        msg = (
            f"📅 *Hoje ({len(logs)} refeição{'s' if len(logs) > 1 else ''}):*\n\n"
            f"{lines}\n\n"
            f"📊 *Total:* {total_kcal:.0f} kcal | "
            f"P: {total_protein:.0f}g | C: {total_carb:.0f}g | G: {total_fat:.0f}g"
        )

        pct_goal = 0
        if user.daily_calorie_goal:
            remaining = user.daily_calorie_goal - total_kcal
            pct_goal  = min(100, int(total_kcal / user.daily_calorie_goal * 100))
            bar = "█" * (pct_goal // 10) + "░" * (10 - pct_goal // 10)
            msg += (
                f"\n\n🎯 *Meta calórica:* {user.daily_calorie_goal} kcal\n"
                f"`{bar}` {pct_goal}%\n"
                f"{'⚠️ Meta atingida!' if remaining <= 0 else f'Faltam {remaining:.0f} kcal'}"
            )

        water_status = "🎉 Meta atingida!" if pct_water >= 100 else f"Faltam {goal_water - water_ml}ml"
        msg += (
            f"\n\n💧 *Hidratação:* {water_ml}ml / {goal_water}ml\n"
            f"{water_bar} {pct_water}%  {water_status}"
        )
        if water_ml == 0:
            msg += "\n_Use /agua ou diga 'bebi 1 copo de água'_"

        analytics.daily_summary_viewed(user.channel_id, total_kcal, pct_goal)
        return msg

    async def _cmd_historico(self, user: User, args, db: AsyncSession) -> str:
        from app.config import settings
        from collections import defaultdict

        max_days = 30 if user.is_premium else settings.free_tier_history_days
        days = max_days
        if args:
            digits = "".join(c for c in str(args) if c.isdigit())
            if digits:
                days = min(int(digits), max_days)

        tz = ZoneInfo(user.timezone or "America/Sao_Paulo")
        now = datetime.now(tz)
        since = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days - 1)

        stmt = (
            select(MealLog)
            .where(
                MealLog.user_id == user.id,
                MealLog.logged_at >= since,
                MealLog.confirmed.is_(True),
            )
            .order_by(MealLog.logged_at)
        )
        result = await db.execute(stmt)
        logs = list(result.scalars().all())

        if not logs:
            period = "hoje" if days == 1 else f"nos últimos {days} dias"
            return (
                f"Nenhuma refeição registrada {period} ainda! 🍽️\n"
                "Me conta o que você comeu."
            )

        days_map = defaultdict(list)
        for log in logs:
            local_date = log.logged_at.astimezone(tz).date()
            days_map[local_date].append(log)

        MEAL_NAMES = {
            "breakfast": "Café", "morning_snack": "Lanche manhã",
            "lunch": "Almoço", "afternoon_snack": "Lanche tarde",
            "dinner": "Jantar", "snack": "Lanche", "other": "Refeição",
        }
        WEEKDAYS = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]

        sections = []
        all_day_totals = []

        for date_key in sorted(days_map.keys(), reverse=True):
            day_logs = sorted(days_map[date_key], key=lambda l: l.logged_at)
            day_kcal = sum(l.total_calories_kcal for l in day_logs)
            day_protein = sum(l.total_protein_g for l in day_logs)
            day_carb = sum(l.total_carb_g for l in day_logs)
            day_fat = sum(l.total_fat_g for l in day_logs)
            all_day_totals.append(day_kcal)

            weekday = WEEKDAYS[date_key.weekday()]
            date_str = date_key.strftime("%d/%m")
            meal_lines = "\n".join(
                f"  • {MEAL_NAMES.get(l.meal_type, 'Refeição')}: {l.total_calories_kcal:.0f} kcal"
                for l in day_logs
            )
            day_text = (
                f"📆 *{weekday}, {date_str}*\n"
                f"{meal_lines}\n"
                f"  *Total: {day_kcal:.0f} kcal* | P:{day_protein:.0f}g C:{day_carb:.0f}g G:{day_fat:.0f}g"
            )

            if user.daily_calorie_goal:
                pct = min(100, int(day_kcal / user.daily_calorie_goal * 100))
                bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
                day_text += f"\n  `{bar}` {pct}% da meta"

            sections.append(day_text)

        avg = sum(all_day_totals) / len(all_day_totals)
        n_days = len(days_map)
        header = f"📅 *Histórico — {n_days} dia{'s' if n_days != 1 else ''} com registro*\n"
        footer = f"\n📊 *Média diária:* {avg:.0f} kcal"
        if not user.is_premium:
            footer += f"\n\n🔓 Plano Premium mostra até 30 dias · /premium"

        return header + "\n" + "\n\n".join(sections) + footer

    async def _cmd_meta(self, user: User, args, db: AsyncSession) -> str:
        if args:
            stripped = args.strip().lower()

            if stripped.startswith("agua"):
                rest = stripped[4:].strip()
                if not rest:
                    cur = user.daily_water_goal_ml or 2000
                    return (
                        f"💧 Meta de água atual: *{cur}ml/dia*.\n"
                        "Para alterar: /meta agua 2500"
                    )
                digits = "".join(c for c in rest if c.isdigit())
                if not digits:
                    return "Por favor, informe um valor em ml. Ex: /meta agua 2500"
                ml = int(digits)
                if ml < 1000 or ml > 5000:
                    return "❌ A meta de água deve estar entre 1.000 e 5.000 ml."
                user.daily_water_goal_ml = ml
                await db.commit()
                return f"✅ Meta de água atualizada para *{ml}ml/dia*! 💧"

            digits = "".join(c for c in args if c.isdigit())
            if not digits:
                return "Por favor, informe um valor em kcal. Ex: /meta 1800\nPara água: /meta agua 2500"
            kcal = int(digits)
            if kcal < 500 or kcal > 10000:
                return "Meta deve estar entre 500 e 10.000 kcal."
            user.daily_calorie_goal = kcal
            await db.commit()
            analytics.goal_set(user.channel_id, kcal, user.goal_type or "manter")
            return f"✅ Meta atualizada para *{kcal} kcal/dia*!"

        lines = []
        if user.daily_calorie_goal:
            lines.append(f"🔥 Meta calórica: *{user.daily_calorie_goal} kcal/dia*")
        else:
            lines.append("🔥 Meta calórica: não definida")
        water = user.daily_water_goal_ml or 2000
        lines.append(f"💧 Meta de água: *{water}ml/dia*")
        lines.append("\nPara alterar: /meta 1800 ou /meta agua 2500")
        return "\n".join(lines)

    async def _cmd_alertas(self, user: User, args: str | None, db: AsyncSession) -> str:
        arg = (args or "").strip().lower()

        if arg in ("off", "desativar", "pausar", "0", "nao", "não"):
            user.alerts_enabled = False
            await db.commit()
            return (
                "🔕 Alertas desativados.\n"
                "Você não receberá mais lembretes de refeição.\n"
                "Para reativar: /alertas on"
            )

        if arg in ("on", "ativar", "ligar", "1", "sim"):
            user.alerts_enabled = True
            user.alerts_paused_until = None
            await db.commit()
            return (
                "🔔 Alertas ativados!\n"
                "Você vai receber lembretes:\n"
                "• ☀️ 09:30 — Café da manhã\n"
                "• 🍽️ 12:30 — Almoço\n"
                "• 🌙 19:30 — Jantar\n\n"
                "O lembrete só é enviado se você ainda não registrou a refeição."
            )

        status = "🔔 Ativados" if user.alerts_enabled else "🔕 Desativados"
        return (
            f"*Alertas de refeição:* {status}\n\n"
            "Horários:\n"
            "• ☀️ 09:30 — Café da manhã\n"
            "• 🍽️ 12:30 — Almoço\n"
            "• 🌙 19:30 — Jantar\n\n"
            "Comandos:\n"
            "• /alertas on — ativar\n"
            "• /alertas off — desativar"
        )

    async def _cmd_premium(self, user: User, args, db) -> str:
        if not user.is_premium:
            analytics.premium_cta_shown(user.channel_id, "cmd_premium")
        return (
            "🌟 *NutriBot Premium*\n\n"
            "✅ Alertas de refeição personalizados\n"
            "✅ Relatório semanal completo com insights de IA\n"
            "✅ Histórico ilimitado\n\n"
            "💳 R$ 19,90/mês ou R$ 149,90/ano\n\n"
            "👉 [Assinar agora](https://nutri.bot/premium)"
        )

    async def _cmd_plano(self, user: User, args, db) -> str:
        plano = "Premium ✨" if user.is_premium else "Gratuito"
        validade = ""
        if user.plan_expires_at:
            validade = f"\nVálido até: {user.plan_expires_at.strftime('%d/%m/%Y')}"
        return f"Seu plano atual: *{plano}*{validade}"

    async def _cmd_cancelar(self, user: User, args, db: AsyncSession) -> str:
        prev_state = user.conversation_state
        user.conversation_state = "IDLE"
        user.state_data = None
        await db.commit()
        if prev_state == "IDLE":
            return "Não há nenhuma ação em andamento."
        return "✅ Ação cancelada. Me conta o que você comeu quando quiser!"

    async def _cmd_deletar_dados(self, user: User, args, db: AsyncSession) -> str:
        analytics.deletion_requested(user.channel_id)
        self._set_timed_state(user, "DELETING")  # type: ignore[attr-defined]
        user.state_data = {}
        await db.commit()
        return (
            "⚠️ *Atenção: exclusão irreversível*\n\n"
            "Todos os seus dados (refeições, histórico, configurações) serão removidos "
            "permanentemente em até 72 horas, conforme a LGPD.\n\n"
            "Para confirmar, escreva exatamente:\n`DELETAR`\n\n"
            "Ou /cancelar para desistir."
        )

    async def _cmd_exportar_dados(self, user: User, args, db: AsyncSession) -> str:
        import json as _json

        from app.models.food_item import FoodItem
        from app.services.notification import notification_service

        result = await db.execute(
            select(MealLog)
            .where(MealLog.user_id == user.id, MealLog.confirmed.is_(True))
            .order_by(MealLog.logged_at)
        )
        logs = result.scalars().all()

        meal_data = []
        for log in logs:
            from app.models.food_item import FoodItem as _FI
            fi_result = await db.execute(
                select(_FI).where(_FI.meal_log_id == log.id)
            )
            food_items = fi_result.scalars().all()
            meal_data.append({
                "id": str(log.id),
                "meal_type": log.meal_type,
                "logged_at": log.logged_at.isoformat(),
                "input_type": log.input_type,
                "total_calories_kcal": log.total_calories_kcal,
                "total_protein_g": log.total_protein_g,
                "total_carb_g": log.total_carb_g,
                "total_fat_g": log.total_fat_g,
                "total_fiber_g": log.total_fiber_g,
                "food_items": [
                    {
                        "name": fi.name,
                        "original_term": fi.original_term,
                        "quantity_g": fi.quantity_g,
                        "calories_kcal": fi.calories_kcal,
                        "protein_g": fi.protein_g,
                        "carb_g": fi.carb_g,
                        "fat_g": fi.fat_g,
                        "fiber_g": fi.fiber_g,
                        "source": fi.source,
                    }
                    for fi in food_items
                ],
            })

        export = {
            "user": {
                "channel_type": user.channel_type,
                "timezone": user.timezone,
                "daily_calorie_goal": user.daily_calorie_goal,
                "goal_type": user.goal_type,
                "plan": user.plan,
                "first_name": user.first_name,
                "created_at": user.created_at.isoformat() if user.created_at else None,
                "lgpd_consent_at": user.lgpd_consent_at.isoformat() if user.lgpd_consent_at else None,
            },
            "meal_logs": meal_data,
            "exported_at": datetime.now(ZoneInfo("UTC")).isoformat(),
            "note": "NutriBot — exportação conforme LGPD Art. 18 (portabilidade de dados)",
        }

        export_bytes = _json.dumps(export, ensure_ascii=False, indent=2).encode("utf-8")
        safe_id = user.channel_id.replace(":", "_")
        filename = f"nutribot_dados_{safe_id}.json"

        sent = await notification_service.send_document(
            user,
            export_bytes,
            filename,
            caption="📦 *Seus dados NutriBot* — LGPD Art. 18\n_Arquivo JSON com todas as suas refeições._",
        )

        analytics.data_exported(user.channel_id, len(logs))
        if sent:
            return "✅ Seus dados foram enviados como arquivo JSON!"
        return (
            "📦 Seus dados foram preparados!\n"
            "Para receber o arquivo via Telegram, use o bot pelo Telegram.\n"
            "WhatsApp ainda não suporta envio de arquivos JSON."
        )

    async def _cmd_privacidade(self, user: User, args, db: AsyncSession) -> str:
        from app.models.nutritionist_patient import NutritionistPatient
        from sqlalchemy import select as sa_select

        nutri_links: list[str] = []
        if db and user.id:
            result = await db.execute(
                sa_select(NutritionistPatient).where(
                    NutritionistPatient.patient_id == user.id,
                    NutritionistPatient.status == "active",
                ).order_by(NutritionistPatient.consented_at)
            )
            links = result.scalars().all()
            for lk in links:
                nutri_result = await db.execute(
                    sa_select(User).where(User.id == lk.nutritionist_id)
                )
                nutri = nutri_result.scalar_one_or_none()
                if nutri:
                    crn = (nutri.state_data or {}).get("crn", "CRN não informado")
                    consented = lk.consented_at.strftime("%d/%m/%Y") if lk.consented_at else "?"
                    nutri_links.append(
                        f"• {nutri.first_name or 'Nutricionista'} ({crn}) — desde {consented}"
                    )

        base_text = (
            "🔒 *Privacidade e LGPD*\n\n"
            "Seus dados de saúde são protegidos conforme a LGPD (Lei 13.709/2018) "
            "como *dados sensíveis* (Art. 11).\n\n"
        )

        if nutri_links:
            base_text += (
                "👩‍⚕️ *Nutricionistas com acesso ativo:*\n"
                + "\n".join(nutri_links)
                + "\n\nPara revogar o acesso, responda com: *revogar [nome da nutricionista]*\n\n"
            )
        else:
            base_text += "👩‍⚕️ Nenhuma nutricionista tem acesso aos seus dados no momento.\n\n"

        base_text += (
            "• /exportar\\_dados — baixar seus dados\n"
            "• /deletar\\_dados — apagar tudo em até 72h\n\n"
            "📄 [Política de Privacidade completa](https://nutri.bot/privacidade)"
        )
        return base_text

    async def _cmd_vincular(self, user: User, args, db: AsyncSession) -> str:
        import secrets

        if user.channel_type != "telegram":
            return "Este comando só funciona no Telegram. 😊"

        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        code = "".join(secrets.choice(alphabet) for _ in range(6))

        user.web_link_token = code
        user.web_link_token_expires_at = datetime.now(ZoneInfo("UTC")) + timedelta(minutes=10)
        if db:
            await db.commit()

        return (
            "🔗 *Vincular conta Telegram ao painel web*\n\n"
            f"Seu código de vinculação:\n\n"
            f"```\n{code}\n```\n\n"
            "📋 *Como usar:*\n"
            "1. Acesse o painel web e faça login\n"
            "2. Vá em *Configurações* → seção *Vincular Telegram*\n"
            "3. Digite o código acima e clique em *Vincular*\n\n"
            "⏱️ Válido por *10 minutos*.\n"
            "Após a vinculação, seu histórico do Telegram ficará visível no painel!"
        )

    async def _cmd_painel(self, user: User, args, db: AsyncSession) -> str:
        from app.config import settings
        from app.utils.jwt import create_magic_token

        token = create_magic_token(user.id, minutes=10)
        base = (settings.app_url or "https://nutri-bot-ot0p.onrender.com").rstrip("/")
        link = f"{base}/auth/magic?t={token}"

        name = user.first_name or "você"
        return (
            f"🌐 *Painel do NutriBot*\n\n"
            f"Olá, {name}! Seu painel está pronto:\n\n"
            f"👉 [Abrir agora]({link})\n\n"
            "⏱️ Link válido por *10 minutos*.\n"
            "📲 No celular, toque em *'Adicionar à tela inicial'* para instalar como app!"
        )

    async def _cmd_registrar(self, user: User, args: str | None, db: AsyncSession) -> str:
        tz = ZoneInfo(user.timezone or "America/Sao_Paulo")
        today = datetime.now(tz).date()

        if not args or not args.strip():
            return (
                "📅 *Registro retroativo*\n\n"
                "Me diz a data da refeição que quer adicionar:\n"
                "• /registrar ontem\n"
                "• /registrar anteontem\n"
                "• /registrar 20/08\n\n"
                "Ou simplesmente me conta diretamente:\n"
                "_'Ontem de manhã comi pão com ovo'_"
            )

        target = self._parse_date_from_args(args, user)  # type: ignore[attr-defined]
        if target is None:
            return (
                "Não entendi a data 🤔\n\n"
                "Exemplos:\n"
                "• /registrar ontem\n"
                "• /registrar anteontem\n"
                "• /registrar 20/08\n"
                "• /registrar dia 15"
            )

        err = self._check_backdate_limit(target, user)  # type: ignore[attr-defined]
        if err:
            return err

        lbl = self._date_label(target, tz)  # type: ignore[attr-defined]
        self._set_timed_state(user, "BACKDATING")  # type: ignore[attr-defined]
        user.state_data = {"target_date": target.isoformat()}
        flag_modified(user, "state_data")
        await db.commit()

        return (
            f"📅 Ok! Vou registrar para *{lbl}*.\n\n"
            "Me conta o que você comeu nesse dia.\n"
            "Pode mandar por tipo de refeição:\n"
            "_'Café da manhã: pão com ovo e café'_\n"
            "_'Almoço: arroz, feijão e frango'_\n\n"
            "• /cancelar — desistir"
        )

    async def _cmd_relatorios(self, user: User, args, db: AsyncSession) -> str:
        from app.config import settings
        from app.models.weekly_report import WeeklyReport

        if not user.can_access_reports and not settings.reports_open_beta:
            from datetime import datetime as _dt
            delta = (_dt.utcnow() - user.created_at.replace(tzinfo=None)).days
            faltam = 7 - delta
            return (
                "📊 *Relatórios*\n\n"
                f"Seus relatórios serão liberados em {faltam} dia(s)! "
                "Após 7 dias de cadastro você terá acesso completo. 🎉\n\n"
                "Enquanto isso, continue registrando suas refeições para ter um relatório rico.\n\n"
                "👉 Quer acesso imediato? /premium"
            )

        result = await db.execute(
            select(WeeklyReport)
            .where(WeeklyReport.user_id == user.id)
            .order_by(WeeklyReport.week_start_date.desc())
            .limit(10)
        )
        reports = result.scalars().all()

        _freq_labels = {
            "weekly": "Semanal (todo domingo)",
            "monthly": "Mensal (1º de cada mês)",
            "quarterly": "Trimestral (1º de jan/abr/jul/out)",
            "none": "Desativado",
        }
        freq = _freq_labels.get(user.report_frequency or "weekly", user.report_frequency)

        if not reports:
            return (
                f"📊 Nenhum relatório gerado ainda.\n"
                f"Frequência atual: *{freq}*\n\n"
                "Solicite um agora:\n"
                "• /relatorio semana\n"
                "• /relatorio mes\n"
                "• /relatorio 3meses\n"
                "• /relatorio total"
            )

        lines = []
        _period_icons = {"weekly": "📅", "monthly": "🗓️", "quarterly": "📆", "custom": "🔍"}
        for r in reports:
            icon = _period_icons.get(r.period_type or "weekly", "📊")
            end_d = r.period_end_date or (r.week_start_date + timedelta(days=6))
            status = "✅ Entregue" if r.delivered_at else "⏳ Pendente"
            lines.append(
                f"{icon} {r.week_start_date.strftime('%d/%m')} a "
                f"{end_d.strftime('%d/%m/%Y')} — {status}"
            )

        return (
            f"📊 *Seus relatórios:*\n\n"
            + "\n".join(lines)
            + f"\n\n_Frequência automática: {freq}_\n"
            "Use /frequencia para alterar."
        )

    async def _cmd_relatorio_ondemand(self, user: User, args: str | None, db: AsyncSession) -> str:
        from datetime import date as _date
        import calendar

        from app.config import settings
        from app.services.notification import notification_service
        from app.services.report import report_service

        if not user.can_access_reports and not settings.reports_open_beta:
            from datetime import datetime as _dt
            delta = (_dt.utcnow() - user.created_at.replace(tzinfo=None)).days
            faltam = 7 - delta
            return (
                "📊 *Relatórios*\n\n"
                f"Faltam {faltam} dia(s) para liberar seus relatórios! "
                "Após 7 dias de cadastro você pode solicitar a qualquer momento. 🎉\n\n"
                "👉 Quer acesso imediato? /premium"
            )

        arg = (args or "semana").strip().lower()
        today = _date.today()

        if arg in ("semana", "week", "7", "7dias"):
            period_type = "weekly"
            end_date = today + timedelta(days=1)
            start_date = today - timedelta(days=6)
            label = "última semana"
        elif arg in ("mes", "mês", "month", "30", "30dias"):
            period_type = "monthly"
            first_of_month = today.replace(day=1)
            end_date = first_of_month
            start_date = (first_of_month - timedelta(days=1)).replace(day=1)
            label = "último mês"
        elif arg in ("3meses", "trimestre", "90", "90dias", "quarter"):
            period_type = "quarterly"
            month = today.month
            q_starts = [1, 4, 7, 10]
            current_q_start = max(m for m in q_starts if m <= month)
            if current_q_start == 1:
                start_date = _date(today.year - 1, 10, 1)
            else:
                start_date = _date(today.year, current_q_start - 3, 1)
            end_date = _date(today.year, current_q_start, 1)
            label = "últimos 3 meses"
        elif arg in ("total", "tudo", "historico", "histórico", "all"):
            period_type = "custom"
            from sqlalchemy import func
            from app.models.meal_log import MealLog as _ML
            res = await db.execute(
                select(func.min(_ML.logged_at)).where(
                    _ML.user_id == user.id,
                    _ML.confirmed.is_(True),
                )
            )
            first_log_at = res.scalar_one_or_none()
            if not first_log_at:
                return "Nenhuma refeição registrada ainda para gerar relatório! 🍽️"
            tz = ZoneInfo(user.timezone or "America/Sao_Paulo")
            start_date = first_log_at.astimezone(tz).date()
            end_date = today + timedelta(days=1)
            label = "histórico completo"
        else:
            return (
                "Período não reconhecido. Use:\n"
                "• /relatorio semana\n"
                "• /relatorio mes\n"
                "• /relatorio 3meses\n"
                "• /relatorio total"
            )

        await notification_service.send_text(
            user, f"📊 Gerando relatório do {label}… aguarde alguns segundos! ⏳"
        )

        try:
            file_bytes, ext = await report_service.generate_report(
                user, start_date, end_date, period_type, db
            )
            name = user.first_name or "você"
            filename = f"nutribot_{period_type}_{start_date.strftime('%Y-%m-%d')}.{ext}"
            caption = (
                f"📊 *Relatório do {label}, {name}!*\n"
                "Confira seu progresso 👆"
            )
            await notification_service.send_document(user, file_bytes, filename, caption)
            return ""
        except Exception as e:
            logger.error(f"[REPORT-ONDEMAND] Falha para {user.channel_id}: {e}")
            return "Ocorreu um erro ao gerar o relatório 😔 Tente novamente em instantes."

    async def _cmd_frequencia(self, user: User, args: str | None, db: AsyncSession) -> str:
        _map = {
            "semanal": "weekly", "semana": "weekly", "weekly": "weekly",
            "mensal": "monthly", "mes": "monthly", "mês": "monthly", "monthly": "monthly",
            "trimestral": "quarterly", "trimestre": "quarterly",
            "3meses": "quarterly", "quarterly": "quarterly",
            "nunca": "none", "desativar": "none", "none": "none", "off": "none",
        }
        _labels = {
            "weekly":    "Semanal — todo domingo às 20h 📅",
            "monthly":   "Mensal — 1º dia de cada mês às 20h 🗓️",
            "quarterly": "Trimestral — 1º de jan/abr/jul/out às 20h 📆",
            "none":      "Desativado — sem envio automático 🔕",
        }

        arg = (args or "").strip().lower()
        freq = _map.get(arg)

        if not freq:
            current = _labels.get(user.report_frequency or "weekly", user.report_frequency)
            return (
                f"📅 *Frequência de relatórios automáticos*\n\n"
                f"Atual: *{current}*\n\n"
                "Para alterar:\n"
                "• /frequencia semanal\n"
                "• /frequencia mensal\n"
                "• /frequencia trimestral\n"
                "• /frequencia nunca\n\n"
                "_Você pode pedir um relatório a qualquer hora com /relatorio_"
            )

        if not user.is_premium and freq != "none":
            return (
                "🔒 Relatórios automáticos são exclusivos do plano Premium.\n"
                "👉 /premium para assinar\n\n"
                "_Você ainda pode usar /relatorio para solicitar relatórios avulsos._"
            )

        user.report_frequency = freq
        await db.commit()
        return f"✅ Frequência atualizada!\n\n*{_labels[freq]}*"

    async def _cmd_feedback(self, user: User, args, db) -> str:
        if not args:
            return (
                "Por favor, escreva seu feedback após o comando.\n"
                "Ex: /feedback O bot não reconheceu minha comida"
            )
        logger.info(f"Feedback de {user.channel_id}: {args[:200]}")
        return "Obrigado pelo feedback! 💚 Isso nos ajuda a melhorar."

    async def _cmd_desfazer(self, user: User, args: str | None, db: AsyncSession) -> str:
        logs = await self._get_today_logs(user, db)  # type: ignore[attr-defined]
        if not logs:
            return "Não há refeições registradas hoje para desfazer. 🍽️"

        last = logs[-1]
        name = self._MEAL_NAME.get(last.meal_type, "Refeição")
        tz = ZoneInfo(user.timezone or "America/Sao_Paulo")
        hora = last.logged_at.astimezone(tz).strftime("%H:%M")
        kcal = last.total_calories_kcal

        await db.delete(last)
        await db.commit()

        analytics.meal_deleted(user.channel_id)
        return (
            f"↩️ *{name}* ({hora} — {kcal:.0f} kcal) desfeito!\n"
            "Use /hoje para ver o resumo atualizado."
        )

    # ── Água ──────────────────────────────────────────────────────────────────

    _WATER_ALIASES: dict[str, float] = {
        "litro": 1000, "litros": 1000, "l": 1000,
        "meio litro": 500, "meia garrafa": 500,
        "garrafa": 500, "garrafas": 500,
        "copo": 250, "copos": 250,
        "copão": 400, "copões": 400,
        "xicara": 240, "xícara": 240, "xicaras": 240, "xícaras": 240,
        "copo americano": 200,
    }

    _WATER_KEYWORDS = (
        "água", "agua", "hidrat", "beber", "bebi", "tomar", "tomei",
        "ingestão", "ingestao", "litro", "litros", "copo", "copos",
        "garraf", "xicara", "xícara", "copão",
    )

    @classmethod
    def _parse_water_ml(cls, text: str) -> int | None:
        import re
        t = text.strip().lower()

        m = re.search(r"(\d+[\.,]?\d*)\s*ml\b", t)
        if m:
            return min(int(float(m.group(1).replace(",", "."))), 5000)

        for alias, vol in sorted(cls._WATER_ALIASES.items(), key=lambda x: -len(x[0])):
            esc = re.escape(alias)
            pattern = rf"(\d+[\.,]?\d*)\s*{esc}(?!\w)|(?<!\w){esc}(?!\w)"
            m = re.search(pattern, t)
            if m:
                qty_str = m.group(1) if m.lastindex and m.group(1) else "1"
                qty = float(qty_str.replace(",", "."))
                return min(int(qty * vol), 5000)

        m = re.search(r"\b(\d{2,4})\b", t)
        if m:
            return min(int(m.group(1)), 5000)

        return None

    @classmethod
    def _is_water_message(cls, text_lower: str) -> bool:
        import re
        has_kw = any(kw in text_lower for kw in cls._WATER_KEYWORDS)
        if not has_kw:
            return False
        food_words = ("comi", "almocei", "jantei", "ceia", "café", "lanche",
                      "refeição", "prato", "arroz", "feijão", "carne", "fruta",
                      "vitamina", "suco", "shake", "iogurte", "leite", "sopa")
        if any(fw in text_lower for fw in food_words):
            return bool(re.search(r"\b(agua|água|hidrat|litro|copo|ml)\b", text_lower))
        return True

    async def _log_water_and_reply(self, user: User, ml: int, db: AsyncSession) -> str:
        from app.models.water_log import WaterLog
        from sqlalchemy import func

        db.add(WaterLog(user_id=user.id, volume_ml=float(ml)))
        await db.flush()

        tz = ZoneInfo(user.timezone or "America/Sao_Paulo")
        now = datetime.now(tz)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        result = await db.execute(
            select(func.sum(WaterLog.volume_ml)).where(
                WaterLog.user_id == user.id,
                WaterLog.logged_at >= day_start,
            )
        )
        today_total = float(result.scalar_one_or_none() or ml)
        await db.commit()

        goal_ml = user.daily_water_goal_ml or 2000
        pct    = min(100, int(today_total / goal_ml * 100))
        filled = pct // 20
        bar    = "💧" * filled + "○" * (5 - filled)
        suffix = " 🎉 Meta atingida!" if pct >= 100 else ""
        return (
            f"💧 *{ml}ml registrado!*\n\n"
            f"Hoje: {today_total:.0f}ml / {goal_ml}ml\n"
            f"{bar} {pct}%{suffix}\n\n"
            "_Use /agua 250 ou 'bebi 1 copo' a qualquer hora_"
        )

    async def _cmd_agua(self, user: User, args: str | None, db: AsyncSession) -> str:
        if not args:
            return await self._log_water_and_reply(user, 250, db)
        ml = self._parse_water_ml(args)
        if ml is None or ml < 50:
            return (
                "Não entendi a quantidade. Exemplos:\n"
                "• /agua 250\n"
                "• /agua 500ml\n"
                "• /agua 1 litro\n"
                "• /agua 2 copos\n\n"
                "_Sem argumento registra 1 copo (250ml)_"
            )
        return await self._log_water_and_reply(user, ml, db)

    async def _cmd_silenciar(self, user: User, args: str | None, db: AsyncSession) -> str:
        hours = 8
        if args:
            digits = "".join(c for c in args if c.isdigit())
            if digits:
                hours = min(int(digits), 72)

        user.alerts_paused_until = datetime.now(ZoneInfo("UTC")) + timedelta(hours=hours)
        await db.commit()

        tz = ZoneInfo(user.timezone or "America/Sao_Paulo")
        resume_time = (datetime.now(tz) + timedelta(hours=hours)).strftime("%H:%M")
        duration = f"{hours}h" if hours < 24 else f"{hours // 24}d"
        return (
            f"🔕 Alertas pausados por *{duration}*.\n"
            f"Volto a avisar a partir das {resume_time}.\n"
            "Use /alertas on para reativar antes."
        )
