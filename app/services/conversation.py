"""
ConversationService — máquina de estados da conversa.
Estados: IDLE | ONBOARDING | CONFIRMING | CORRECTING | DELETING | BACKDATING
Ver docs/NutriBot_PRD_v2.1.md seção 7 para diagrama completo.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.models.food_item import FoodItem
from app.models.meal_log import MealLog
from app.models.meal_window import MealWindow
from app.models.user import User
from app.services import analytics

logger = logging.getLogger(__name__)

ConversationState = Literal[
    "IDLE", "ONBOARDING", "CONFIRMING", "CORRECTING", "DELETING"
]

CONFIRM_WORDS = {"sim", "s", "yes", "y", "ok", "confirmar", "confirma", "certo", "isso", "exato", "correto"}
DENY_WORDS = {"não", "nao", "n", "no", "errado", "corrigir", "incorreto", "errada"}

MEAL_EMOJI = {
    "breakfast":      "🌅",
    "morning_snack":  "🍌",
    "lunch":          "☀️",
    "afternoon_snack":"🍊",
    "dinner":         "🌙",
    "snack":          "🍎",
    "other":          "🍽️",
}

GOAL_SUGGESTIONS = {
    "perder": 1500,
    "emagrecer": 1500,
    "manter": 2000,
    "ganhar": 2500,
    "massa": 2500,
    "hipertrofia": 2500,
}

_STATE_TIMEOUTS = {
    "CONFIRMING": timedelta(minutes=10),
    "CORRECTING": timedelta(minutes=5),
    "DELETING":   timedelta(minutes=5),
    "BACKDATING": timedelta(minutes=10),
}

# Hora padrão (local) usada ao salvar um registro retroativo por tipo de refeição
_MEAL_DEFAULT_HOURS: dict[str, int] = {
    "breakfast":      8,
    "morning_snack":  10,
    "lunch":          12,
    "afternoon_snack": 15,
    "dinner":         19,
    "snack":          12,
    "other":          12,
}

# Limite de dias para registro retroativo (free / premium)
_BACKDATE_LIMIT_FREE    = 7
_BACKDATE_LIMIT_PREMIUM = 30

MAINTENANCE_RESPONSE = (
    "Estou em manutenção no momento 🔧\n"
    "Volto em breve! Seus dados estão seguros."
)

UNRECOGNIZED_RESPONSE = (
    "Oi! 😊 Pode me contar o que comeu "
    "(ex: 'almocei arroz e frango') ou usar /ajuda para ver os comandos disponíveis."
)


class ConversationService:

    # ── "Ver painel" footer ────────────────────────────────────────────────────

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
            return reply + self._panel_link(user)
        return reply

    # ── Handlers públicos ──────────────────────────────────────────────────────

    async def handle_message(
        self,
        user: User,
        message_type: Literal["text", "photo", "audio"],
        content: str | bytes,
        caption: str | None = None,
        db: AsyncSession | None = None,
    ) -> str:
        reply = await self._dispatch_message(user, message_type, content, caption, db)
        return self._append_panel_link(reply, user)

    async def _dispatch_message(
        self,
        user: User,
        message_type: Literal["text", "photo", "audio"],
        content: str | bytes,
        caption: str | None = None,
        db: AsyncSession | None = None,
    ) -> str:
        from app.config import settings

        if settings.maintenance_mode:
            return MAINTENANCE_RESPONSE

        state = user.conversation_state

        if state not in ("IDLE", "ONBOARDING"):
            now_utc = datetime.now(ZoneInfo("UTC"))
            expires = user.state_expires_at

            # expires=None significa "sem prazo definido" — estado válido indefinidamente.
            # Só expira quando um datetime explícito no passado for atribuído.
            if expires is None:
                expired = False
            else:
                if expires.tzinfo is None:
                    expires = expires.replace(tzinfo=ZoneInfo("UTC"))
                expired = now_utc > expires

            if expired:
                user.conversation_state = "IDLE"
                user.state_data = None
                user.state_expires_at = None
                if db:
                    await db.commit()
                return (
                    "⏱️ Sua ação anterior expirou por inatividade.\n"
                    "Me conta o que você comeu, ou use /ajuda para ver os comandos."
                )
            state = user.conversation_state

        if state == "ONBOARDING":
            return await self._handle_onboarding(user, str(content), db)

        if state == "CONFIRMING":
            return await self._handle_confirming(user, str(content), db)

        if state == "CORRECTING":
            return await self._handle_correcting(user, str(content), db)

        if state == "DELETING":
            return await self._handle_deleting(user, str(content), db)

        if state == "BACKDATING":
            return await self._handle_backdating(user, str(content), db)

        # IDLE
        if message_type == "text":
            return await self._process_text_meal(user, str(content), db)
        if message_type == "photo":
            return await self._process_photo_meal(user, bytes(content), caption, db)
        if message_type == "audio":
            if not user.is_premium:
                return "🎤 Registro por áudio é exclusivo do plano Premium!\nUse /premium para saber mais."
            return await self._process_audio_meal(user, bytes(content), db)

        return UNRECOGNIZED_RESPONSE

    async def handle_command(
        self,
        user: User,
        command: str,
        args: str | None = None,
        db: AsyncSession | None = None,
    ) -> str:
        cmd = command.lower().strip("/")

        handlers = {
            "start":          self._cmd_start,
            "ajuda":          self._cmd_ajuda,
            "hoje":           self._cmd_hoje,
            "historico":      self._cmd_historico,
            "relatorios":     self._cmd_relatorios,
            "relatorio":      self._cmd_relatorio_ondemand,
            "frequencia":     self._cmd_frequencia,
            "deletar":        self._cmd_deletar_refeicao,
            "desfazer":       self._cmd_desfazer,
            "meta":           self._cmd_meta,
            "agua":           self._cmd_agua,
            "silenciar":      self._cmd_silenciar,
            "premium":        self._cmd_premium,
            "plano":          self._cmd_plano,
            "alertas":        self._cmd_alertas,
            "cancelar":       self._cmd_cancelar,
            "deletar_dados":  self._cmd_deletar_dados,
            "exportar_dados": self._cmd_exportar_dados,
            "privacidade":    self._cmd_privacidade,
            "feedback":       self._cmd_feedback,
            "vincular":       self._cmd_vincular,
            "painel":         self._cmd_painel,
            "dashboard":      self._cmd_painel,  # alias
            "registrar":      self._cmd_registrar,
        }

        handler = handlers.get(cmd)
        reply = (
            await handler(user, args, db)
            if handler
            else f"Comando /{cmd} não reconhecido. Use /ajuda para ver os disponíveis."
        )
        return self._append_panel_link(reply, user)

    # ── Helpers de estado ──────────────────────────────────────────────────────

    def _set_timed_state(self, user: User, state: str) -> None:
        user.conversation_state = state
        timeout = _STATE_TIMEOUTS.get(state)
        user.state_expires_at = (
            datetime.now(ZoneInfo("UTC")) + timeout if timeout else None
        )

    # ── Handlers de estado ─────────────────────────────────────────────────────

    async def _handle_onboarding(self, user: User, text: str, db: AsyncSession) -> str:
        # Copia defensiva para garantir que SQLAlchemy detecte a mudança no JSONB
        data = {**(user.state_data or {})}
        step = data.get("step", 0)

        if step == 0:
            name = text.strip().split()[0].capitalize() if text.strip() else "usuário"
            data["name"] = name
            data["step"] = 1
            user.state_data = data
            flag_modified(user, "state_data")
            user.first_name = name
            await db.commit()
            return (
                f"Prazer, {name}! 🎉\n\n"
                "Qual é o seu principal objetivo?\n\n"
                "1️⃣ Perder peso\n"
                "2️⃣ Manter o peso\n"
                "3️⃣ Ganhar massa muscular\n\n"
                "Responda com o número ou descreva seu objetivo."
            )

        if step == 1:
            raw = text.strip().lower()
            if "1" in raw or "perder" in raw or "emagrecer" in raw:
                goal_type = "perder_peso"
                goal_label = "perder peso"
                suggested_kcal = 1500
            elif "3" in raw or "ganhar" in raw or "massa" in raw or "hipertrofia" in raw:
                goal_type = "ganhar_massa"
                goal_label = "ganhar massa muscular"
                suggested_kcal = 2500
            else:
                goal_type = "manter"
                goal_label = "manter o peso"
                suggested_kcal = 2000

            data["goal_type"] = goal_type
            data["goal_label"] = goal_label
            data["suggested_kcal"] = suggested_kcal
            data["step"] = 2
            user.state_data = data
            flag_modified(user, "state_data")
            await db.commit()

            name = data.get("name", "")
            return (
                f"Ótimo, {name}! Registrei: *{goal_label}* 💪\n\n"
                f"Qual é a sua meta diária de calorias?\n"
                f"Sugestão para seu objetivo: *{suggested_kcal} kcal*\n\n"
                "Digite o número ou responda *ok* para usar a sugestão.\n\n"
                "📋 Ao continuar, você concorda com nossa "
                "[Política de Privacidade](https://nutri.bot/privacidade) "
                "e autoriza o processamento dos seus dados de saúde conforme a LGPD (Art. 11)."
            )

        if step == 2:
            raw = text.strip().lower()
            suggested = data.get("suggested_kcal", 2000)
            if raw in ("ok", "s", "sim", "yes"):
                kcal_goal = suggested
            else:
                digits = "".join(c for c in raw if c.isdigit())
                kcal_goal = int(digits) if digits else suggested

            user.daily_calorie_goal = kcal_goal
            user.goal_type = data.get("goal_type", "manter")
            user.onboarding_complete = True
            user.lgpd_consent_at = datetime.now(ZoneInfo("UTC"))
            user.conversation_state = "IDLE"
            user.state_data = None

            # Cria janelas de refeição padrão
            for name_w, start, end in [
                ("Café da manhã", "07:00", "10:00"),
                ("Almoço",        "11:30", "14:00"),
                ("Jantar",        "18:00", "21:00"),
            ]:
                db.add(MealWindow(user_id=user.id, name=name_w, start_time=start, end_time=end))

            await db.commit()
            analytics.onboarding_completed(user.channel_id, user.channel_type, kcal_goal)

            # Gera magic link para acesso imediato ao dashboard (sem vincular)
            from app.config import settings as _cfg
            from app.utils.jwt import create_magic_token
            _magic = create_magic_token(user.id, minutes=1440)  # 24h no onboarding
            _base = (_cfg.app_url or "https://nutri-bot-ot0p.onrender.com").rstrip("/")
            _link = f"{_base}/auth/magic?t={_magic}"

            name = data.get("name", "")
            return (
                f"🎊 *Tudo certo, {name}! Bem-vindo(a) ao NutriBot!*\n\n"
                f"✅ Meta diária: *{kcal_goal} kcal*\n"
                f"✅ Objetivo: *{data.get('goal_label', '')}*\n"
                f"✅ Lembretes: ☀️ 09:30 · 🍽️ 12:30 · 🌙 19:30\n\n"
                "Agora é simples — *me conte o que comeu!*\n\n"
                "💬 Texto: _'almocei arroz com feijão e frango grelhado'_\n"
                "📸 Foto do prato (Premium)\n"
                "🎤 Áudio descrevendo a refeição (Premium)\n\n"
                f"📊 *Seu painel web:* [Abrir agora]({_link})\n"
                "_Toque em 'Adicionar à tela inicial' para instalar como app!_ 📲\n\n"
                "Use /ajuda para ver todos os comandos. 🥗"
            )

        # Estado inconsistente — resetar
        user.conversation_state = "IDLE"
        user.state_data = None
        await db.commit()
        return UNRECOGNIZED_RESPONSE

    async def _handle_confirming(self, user: User, text: str, db: AsyncSession) -> str:
        normalized = text.strip().lower()
        pending = user.state_data or {}

        if not pending:
            user.conversation_state = "IDLE"
            await db.commit()
            return "Não há registro pendente. Me conte o que você comeu!"

        action = pending.get("pending_action", "confirm_meal")

        if action == "delete_meal_pick":
            return await self._handle_delete_pick(user, normalized, db, pending)

        if action == "delete_meal":
            return await self._handle_delete_confirm(user, normalized, db, pending)

        # Fluxo padrão: confirmação de refeição registrada
        if any(w in normalized for w in CONFIRM_WORDS):
            return await self._save_confirmed_meal(user, db)

        if any(w in normalized for w in DENY_WORDS):
            self._set_timed_state(user, "CORRECTING")
            await db.commit()
            return (
                "Tudo bem! ✏️ Me diga a correção.\n"
                "Ex: 'era arroz integral, não branco' ou 'a porção era menor, uns 100g'"
            )

        return (
            "Não entendi. 😊 Responda:\n"
            "• *sim* — confirmar a refeição\n"
            "• *não* — corrigir a identificação\n"
            "• /cancelar — descartar"
        )

    async def _handle_correcting(self, user: User, text: str, db: AsyncSession) -> str:
        return await self._run_meal_extraction(text, user, db, is_correction=True)

    async def _handle_deleting(self, user: User, text: str, db: AsyncSession) -> str:
        if text.strip() == "DELETAR":
            user.deleted_at = datetime.now(ZoneInfo("UTC"))
            user.conversation_state = "IDLE"
            user.state_data = None
            await db.commit()
            return (
                "✅ Seus dados foram marcados para exclusão.\n"
                "O processo será concluído em até 72 horas, conforme a LGPD."
            )
        user.conversation_state = "IDLE"
        user.state_data = None
        await db.commit()
        return "Exclusão cancelada. Seus dados permanecem salvos."

    # ── Deleção de refeição ────────────────────────────────────────────────────

    # Mapeamento de palavras em PT-BR para meal_type do banco
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
        "breakfast":      "Café da manhã",
        "morning_snack":  "Lanche da manhã",
        "lunch":          "Almoço",
        "afternoon_snack":"Lanche da tarde",
        "dinner":         "Jantar",
        "snack":          "Lanche",
        "other":          "Refeição",
    }

    async def _cmd_deletar_refeicao(self, user: User, args: str | None, db: AsyncSession) -> str:
        logs = await self._get_today_logs(user, db)

        if not logs:
            return "Nenhuma refeição registrada hoje para deletar. 🍽️"

        # Se args informado, tenta achar o meal_type direto
        if args:
            args_lower = args.strip().lower()
            target_type = next(
                (v for k, v in self._MEAL_TYPE_MAP.items() if k in args_lower), None
            )
            if target_type:
                matched = [l for l in logs if l.meal_type == target_type]
                if matched:
                    meal = matched[-1]  # mais recente do tipo
                    return await self._ask_delete_confirm(user, meal, db)
                return (
                    f"Não encontrei {self._MEAL_NAME.get(target_type, args)} "
                    f"registrado hoje.\n\nRefeições de hoje:\n"
                    + self._format_today_logs(logs)
                )

        # Sem args ou tipo não reconhecido: lista todas para o usuário escolher
        if len(logs) == 1:
            return await self._ask_delete_confirm(user, logs[0], db)

        lines = self._format_today_logs(logs, numbered=True)
        self._set_timed_state(user, "CONFIRMING")
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

    def _format_today_logs(self, logs: list, numbered: bool = False) -> str:
        lines = []
        for i, l in enumerate(logs, 1):
            name = self._MEAL_NAME.get(l.meal_type, "Refeição")
            tz = ZoneInfo("America/Sao_Paulo")
            hora = l.logged_at.astimezone(tz).strftime("%H:%M")
            prefix = f"{i}. " if numbered else "• "
            lines.append(f"{prefix}{name} ({hora}) — {l.total_calories_kcal:.0f} kcal")
        return "\n".join(lines)

    async def _ask_delete_confirm(self, user: User, meal, db: AsyncSession) -> str:
        name = self._MEAL_NAME.get(meal.meal_type, "Refeição")
        tz = ZoneInfo("America/Sao_Paulo")
        hora = meal.logged_at.astimezone(tz).strftime("%H:%M")
        self._set_timed_state(user, "CONFIRMING")
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
        # Tenta extrair número da resposta
        digits = "".join(c for c in text if c.isdigit())
        if digits:
            idx = int(digits) - 1
            if 0 <= idx < len(meals):
                chosen = meals[idx]
                name = self._MEAL_NAME.get(chosen["meal_type"], "Refeição")
                tz = ZoneInfo("America/Sao_Paulo")
                from datetime import datetime as dt
                hora = dt.fromisoformat(chosen["logged_at"]).astimezone(tz).strftime("%H:%M")
                self._set_timed_state(user, "CONFIRMING")
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
        lines = self._format_today_logs_from_state(meals)
        return f"Por favor, responda com o número da refeição:\n\n{lines}"

    def _format_today_logs_from_state(self, meals: list[dict]) -> str:
        lines = []
        tz = ZoneInfo("America/Sao_Paulo")
        from datetime import datetime as dt
        for i, m in enumerate(meals, 1):
            name = self._MEAL_NAME.get(m["meal_type"], "Refeição")
            hora = dt.fromisoformat(m["logged_at"]).astimezone(tz).strftime("%H:%M")
            lines.append(f"{i}. {name} ({hora}) — {m['kcal']:.0f} kcal")
        return "\n".join(lines)

    async def _handle_delete_confirm(
        self, user: User, text: str, db: AsyncSession, pending: dict
    ) -> str:
        import uuid as _uuid
        summary = pending.get("meal_summary", "refeição")

        if any(w in text for w in CONFIRM_WORDS):
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

        if any(w in text for w in DENY_WORDS):
            user.conversation_state = "IDLE"
            user.state_data = None
            await db.commit()
            return "Ok, nada foi deletado. 👍"

        return f"Responda *sim* para confirmar a exclusão ou *não* para cancelar.\n_{summary}_"

    # ── Registro retroativo: helpers de data ──────────────────────────────────

    def _date_label(self, target: date, tz: ZoneInfo) -> str:
        """'21/08 (ontem)', '19/08 (anteontem)', '17/08 (sábado)', etc."""
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
        """Converte texto livre ('ontem', '20/08', 'dia 15') em um objeto date."""
        tz = ZoneInfo(user.timezone or "America/Sao_Paulo")
        today = datetime.now(tz).date()

        if not args:
            return None
        text = args.strip().lower()

        if "anteontem" in text or "antes de ontem" in text:
            return today - timedelta(days=2)
        if "ontem" in text:
            return today - timedelta(days=1)

        # "20/08", "20-08", "20/08/2026"
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

        # "dia 20" ou apenas "20"
        m = re.search(r'(?:dia\s+)?(\d{1,2})$', text)
        if m:
            day = int(m.group(1))
            if 1 <= day <= 31:
                try:
                    target = date(today.year, today.month, day)
                    if target > today:
                        # Mês anterior
                        first = today.replace(day=1)
                        prev_month_last = first - timedelta(days=1)
                        target = date(prev_month_last.year, prev_month_last.month, day)
                    return target
                except ValueError:
                    return None
        return None

    def _check_backdate_limit(self, target: date, user: User) -> str | None:
        """Retorna mensagem de erro se a data estiver fora do limite, ou None se ok."""
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
        """Total de kcal confirmadas do usuário em uma data específica (no fuso dele)."""
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

    # ── Processadores de mídia ─────────────────────────────────────────────────

    # ── Handler do estado BACKDATING ──────────────────────────────────────────

    async def _handle_backdating(self, user: User, text: str, db: AsyncSession) -> str:
        """Estado onde o usuário está descrevendo refeições de um dia passado específico."""
        pending = user.state_data or {}
        target_date_str = pending.get("target_date")
        if not target_date_str:
            user.conversation_state = "IDLE"
            user.state_data = None
            await db.commit()
            return "Algo deu errado. Me conta o que comeu!"
        target = date.fromisoformat(target_date_str)
        return await self._run_meal_extraction(text, user, db, target_date=target)

    # ── Processadores de mídia ─────────────────────────────────────────────────

    async def _process_text_meal(self, user: User, text: str, db: AsyncSession) -> str:
        return await self._run_meal_extraction(text, user, db)

    async def _process_photo_meal(
        self, user: User, image: bytes, caption: str | None, db: AsyncSession
    ) -> str:
        from app.services.ai_service import ai_service
        from app.services.nutrition import nutrition_service
        from app.utils.crypto import encrypt

        try:
            extraction = await ai_service.extract_foods_from_image(image, caption)
        except Exception as e:
            logger.error(f"Extração de foto falhou: {e}")
            return (
                "Não consegui analisar a foto agora 😔\n"
                "Tente novamente ou descreva a refeição em texto."
            )

        if not extraction.image_has_food or not extraction.foods:
            return (
                "Não identifiquei alimentos nessa foto 📸\n"
                "Tente uma foto mais clara e de frente para o prato.\n"
                "Ou me descreva o que você comeu em texto!"
            )

        foods_raw = [
            {
                "name": f.name,
                "quantity_g": f.quantity_g,
                "est_calories_kcal": f.est_calories_kcal,
                "est_protein_g": f.est_protein_g,
                "est_carb_g": f.est_carb_g,
                "est_fat_g": f.est_fat_g,
            }
            for f in extraction.foods
        ]
        enriched = nutrition_service.enrich_foods(foods_raw)

        total_kcal = round(sum(e.calories_kcal for e in enriched), 1)
        total_protein = round(sum(e.protein_g for e in enriched), 1)
        total_carb = round(sum(e.carb_g for e in enriched), 1)
        total_fat = round(sum(e.fat_g for e in enriched), 1)
        total_fiber = round(sum(e.fiber_g for e in enriched), 1)

        foods_lines = "\n".join(
            f"• {e.name} ({e.quantity_g:.0f}g) — {e.calories_kcal:.0f} kcal"
            for e in enriched
        )

        self._set_timed_state(user, "CONFIRMING")
        user.state_data = {
            "raw_input_encrypted": encrypt(caption or "foto"),
            "meal_type": extraction.meal_type,
            "input_type": "photo",
            "total_calories_kcal": total_kcal,
            "total_protein_g": total_protein,
            "total_carb_g": total_carb,
            "total_fat_g": total_fat,
            "total_fiber_g": total_fiber,
            "food_items": [
                {
                    "name": e.name,
                    "original_term": e.original_term,
                    "quantity_g": e.quantity_g,
                    "calories_kcal": e.calories_kcal,
                    "protein_g": e.protein_g,
                    "carb_g": e.carb_g,
                    "fat_g": e.fat_g,
                    "fiber_g": e.fiber_g,
                    "source": e.source,
                    "confidence_score": e.confidence_score,
                    "taco_code": e.taco_code,
                }
                for e in enriched
            ],
        }
        flag_modified(user, "state_data")
        await db.commit()

        quality_note = ""
        if extraction.image_quality == "poor":
            quality_note = "\n\n⚠️ _Foto com baixa qualidade — valores são aproximados._"

        emoji = MEAL_EMOJI.get(extraction.meal_type, "🍽️")
        return (
            f"📸 {emoji} *Identifiquei na foto:*\n\n"
            f"{foods_lines}\n\n"
            f"📊 *Total:* {total_kcal:.0f} kcal | "
            f"P: {total_protein:.0f}g | C: {total_carb:.0f}g | G: {total_fat:.0f}g"
            f"{quality_note}\n\n"
            "✅ Está correto? Responda *sim* para confirmar ou *não* para corrigir."
        )

    async def _process_audio_meal(self, user: User, audio: bytes, db) -> str:
        from app.services.ai_service import ai_service

        try:
            transcript = await ai_service.transcribe_audio(audio)
        except Exception as e:
            logger.error(f"Transcrição de áudio falhou: {e}")
            return (
                "Não consegui transcrever o áudio agora 😔\n"
                "Tente novamente ou descreva a refeição em texto."
            )

        if not transcript or not transcript.strip():
            return (
                "Não entendi o áudio 😕\n"
                "Pode digitar o que comeu?"
            )

        return await self._run_meal_extraction(transcript.strip(), user, db)

    # ── Lógica de extração compartilhada ─────────────────────────────────────

    async def _run_meal_extraction(
        self,
        text: str,
        user: User,
        db: AsyncSession,
        is_correction: bool = False,
        target_date: date | None = None,
    ) -> str:
        from app.services.ai_service import ai_service
        from app.services.nutrition import nutrition_service
        from app.utils.crypto import encrypt

        # Em modo correção, preserva o target_date já definido no state_data anterior
        if is_correction and target_date is None:
            existing = user.state_data or {}
            td_str = existing.get("target_date")
            if td_str:
                target_date = date.fromisoformat(td_str)

        try:
            extraction = await ai_service.extract_foods_from_text(text)
        except Exception as e:
            logger.error(f"Extração AI falhou: {e}")
            return (
                "Não consegui processar sua mensagem agora 😔\n"
                "Tente novamente em instantes ou descreva de forma diferente."
            )

        if not extraction.foods:
            if is_correction:
                user.conversation_state = "IDLE"
                user.state_data = None
                await db.commit()
                return "Não identifiquei alimentos na correção. Registro cancelado — me conte novamente quando quiser!"
            return (
                "Não consegui identificar alimentos na sua mensagem 🤔\n"
                "Tente ser mais específico.\n"
                "Ex: 'almocei arroz com feijão e frango grelhado'"
            )

        # ── Detecção de data retroativa via NLP (Opção B) ─────────────────────
        # Só aplicada quando o chamador não especificou target_date (fluxo IDLE normal).
        if target_date is None and (extraction.date_offset != 0 or extraction.date_explicit):
            tz = ZoneInfo(user.timezone or "America/Sao_Paulo")
            today = datetime.now(tz).date()

            if extraction.date_offset != 0:
                candidate = today + timedelta(days=extraction.date_offset)
            else:
                # Parseia "DD/MM" retornado pelo Claude
                m = re.match(r'(\d{1,2})[/\-](\d{1,2})(?:[/\-](\d{2,4}))?',
                              extraction.date_explicit or "")
                candidate = None
                if m:
                    try:
                        day, month = int(m.group(1)), int(m.group(2))
                        yr_raw = m.group(3)
                        yr = int(yr_raw) if yr_raw else today.year
                        if yr < 100:
                            yr += 2000
                        candidate = date(yr, month, day)
                        if candidate > today:
                            candidate = date(yr - 1, month, day)
                    except ValueError:
                        candidate = None

            if candidate and candidate < today:
                err = self._check_backdate_limit(candidate, user)
                if err:
                    return err
                target_date = candidate
        # ──────────────────────────────────────────────────────────────────────

        foods_raw = [
            {
                "name": f.name,
                "quantity_g": f.quantity_g,
                "est_calories_kcal": f.est_calories_kcal,
                "est_protein_g": f.est_protein_g,
                "est_carb_g": f.est_carb_g,
                "est_fat_g": f.est_fat_g,
            }
            for f in extraction.foods
        ]
        enriched = nutrition_service.enrich_foods(foods_raw)

        total_kcal = round(sum(e.calories_kcal for e in enriched), 1)
        total_protein = round(sum(e.protein_g for e in enriched), 1)
        total_carb = round(sum(e.carb_g for e in enriched), 1)
        total_fat = round(sum(e.fat_g for e in enriched), 1)
        total_fiber = round(sum(e.fiber_g for e in enriched), 1)

        foods_lines = "\n".join(
            f"• {e.name} ({e.quantity_g:.0f}g) — {e.calories_kcal:.0f} kcal"
            for e in enriched
        )

        state_data: dict = {
            "raw_input_encrypted": encrypt(text),
            "meal_type": extraction.meal_type,
            "input_type": "text",
            "total_calories_kcal": total_kcal,
            "total_protein_g": total_protein,
            "total_carb_g": total_carb,
            "total_fat_g": total_fat,
            "total_fiber_g": total_fiber,
            "food_items": [
                {
                    "name": e.name,
                    "original_term": e.original_term,
                    "quantity_g": e.quantity_g,
                    "calories_kcal": e.calories_kcal,
                    "protein_g": e.protein_g,
                    "carb_g": e.carb_g,
                    "fat_g": e.fat_g,
                    "fiber_g": e.fiber_g,
                    "source": e.source,
                    "confidence_score": e.confidence_score,
                    "taco_code": e.taco_code,
                }
                for e in enriched
            ],
        }
        if target_date is not None:
            state_data["target_date"] = target_date.isoformat()

        self._set_timed_state(user, "CONFIRMING")
        user.state_data = state_data
        flag_modified(user, "state_data")
        await db.commit()

        emoji = MEAL_EMOJI.get(extraction.meal_type, "🍽️")

        if is_correction:
            prefix = "🔄 *Corrigi para:*\n\n"
        elif target_date is not None:
            tz = ZoneInfo(user.timezone or "America/Sao_Paulo")
            lbl = self._date_label(target_date, tz)
            prefix = f"📅 *{lbl.capitalize()}* — {emoji} *Identifiquei:*\n\n"
        else:
            prefix = f"{emoji} *Identifiquei sua refeição:*\n\n"

        return (
            f"{prefix}{foods_lines}\n\n"
            f"📊 *Total:* {total_kcal:.0f} kcal | "
            f"P: {total_protein:.0f}g | C: {total_carb:.0f}g | G: {total_fat:.0f}g\n\n"
            "✅ Está correto? Responda *sim* para confirmar ou *não* para corrigir."
        )

    async def _save_confirmed_meal(self, user: User, db: AsyncSession) -> str:
        pending = user.state_data or {}
        # Captura atributos necessários ANTES do commit (evita lazy-load expirado)
        user_goal = user.daily_calorie_goal

        # ── Registro retroativo: monta logged_at no fuso do usuário ───────────
        target_date_str = pending.get("target_date")
        logged_at_override: datetime | None = None
        target_date_obj: date | None = None
        if target_date_str:
            target_date_obj = date.fromisoformat(target_date_str)
            tz = ZoneInfo(user.timezone or "America/Sao_Paulo")
            default_hour = _MEAL_DEFAULT_HOURS.get(pending.get("meal_type", "other"), 12)
            logged_at_override = datetime(
                target_date_obj.year, target_date_obj.month, target_date_obj.day,
                default_hour, 0, 0, tzinfo=tz,
            )
        # ──────────────────────────────────────────────────────────────────────

        meal_log = MealLog(
            user_id=user.id,
            meal_type=pending.get("meal_type", "other"),
            raw_input_encrypted=pending.get("raw_input_encrypted"),
            input_type=pending.get("input_type", "text"),
            total_calories_kcal=pending.get("total_calories_kcal", 0.0),
            total_protein_g=pending.get("total_protein_g", 0.0),
            total_carb_g=pending.get("total_carb_g", 0.0),
            total_fat_g=pending.get("total_fat_g", 0.0),
            total_fiber_g=pending.get("total_fiber_g", 0.0),
            confirmed=True,
        )
        if logged_at_override is not None:
            meal_log.logged_at = logged_at_override
        db.add(meal_log)
        await db.flush()

        for fi in pending.get("food_items", []):
            try:
                db.add(FoodItem(
                    meal_log_id=meal_log.id,
                    name=fi.get("name", "Alimento"),
                    original_term=fi.get("original_term"),
                    quantity_g=float(fi.get("quantity_g") or 0),
                    calories_kcal=float(fi.get("calories_kcal") or 0),
                    protein_g=float(fi.get("protein_g") or 0),
                    carb_g=float(fi.get("carb_g") or 0),
                    fat_g=float(fi.get("fat_g") or 0),
                    fiber_g=float(fi.get("fiber_g") or 0),
                    source=fi.get("source", "taco"),
                    confidence_score=float(fi.get("confidence_score") or 1.0),
                    taco_code=fi.get("taco_code"),
                ))
            except Exception as e:
                logger.warning(f"[MEAL] FoodItem ignorado por dado inválido: {e} — {fi}")

        # Reseta estado ANTES do commit: garante que qualquer falha no flush
        # não deixe o usuário preso em CONFIRMING
        user.conversation_state = "IDLE"
        user.state_data = None
        user.state_expires_at = None
        await db.commit()

        kcal = pending.get("total_calories_kcal", 0)
        analytics.meal_confirmed(
            user.channel_id, pending.get("meal_type", "other"), float(kcal)
        )

        # ── Mensagem de confirmação ────────────────────────────────────────────
        if target_date_obj is not None:
            tz = ZoneInfo(user.timezone or "America/Sao_Paulo")
            lbl = self._date_label(target_date_obj, tz)
            msg = f"✅ *Registrado para {lbl}!* {kcal:.0f} kcal\n"
            if user_goal:
                day_total = await self._get_date_total_kcal(user, db, target_date_obj)
                remaining = user_goal - day_total
                pct = min(100, int(day_total / user_goal * 100))
                bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
                msg += (
                    f"\n📊 {lbl.capitalize()}: {day_total:.0f} / {user_goal} kcal\n"
                    f"`{bar}` {pct}%\n"
                    f"{'⚠️ Meta atingida nesse dia!' if remaining <= 0 else f'Faltam {remaining:.0f} kcal'}"
                )
        else:
            msg = f"✅ *Refeição registrada!* {kcal:.0f} kcal\n"
            if user_goal:
                today_total = await self._get_today_total_kcal(user, db)
                remaining = user_goal - today_total
                pct = min(100, int(today_total / user_goal * 100))
                bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
                msg += (
                    f"\n📊 Hoje: {today_total:.0f} / {user_goal} kcal\n"
                    f"`{bar}` {pct}%\n"
                    f"{'⚠️ Meta atingida!' if remaining <= 0 else f'Faltam {remaining:.0f} kcal'}"
                )

        return msg

    # ── Helper: CTA de acesso ao dashboard ────────────────────────────────────

    # URL canônica do painel web — usada nos CTAs do bot
    _APP_URL = "https://nutri-bot-ot0p.onrender.com"

    def _get_base_url(self) -> str:
        from app.config import settings
        return (settings.app_url or settings.webhook_base_url or self._APP_URL).rstrip("/")

    def _dashboard_cta_from(self, email: str | None) -> str:
        """Retorna rodapé com link do dashboard — recebe email pré-carregado (safe pós-commit)."""
        base = self._get_base_url()
        if email:
            return f"\n\n🌐 [Ver no dashboard]({base}/dashboard)"
        else:
            return (
                f"\n\n📊 *Acesse pelo painel web:*\n"
                f"[Criar conta]({base}/cadastro) e envie /vincular para conectar 🔗"
            )

    def _dashboard_cta(self, user: User) -> str:
        """Retorna rodapé com link do dashboard — usa atributos do user diretamente."""
        return self._dashboard_cta_from(user.email)

    # ── Helpers de banco de dados ──────────────────────────────────────────────

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
        logs = result.scalars().all()
        return sum(log.total_calories_kcal for log in logs)

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

    # ── Comandos ──────────────────────────────────────────────────────────────

    async def _cmd_start(self, user: User, args, db: AsyncSession) -> str:
        # Sempre libera estado preso — /start funciona como escape de emergência
        if user.conversation_state not in ("IDLE", "ONBOARDING"):
            user.conversation_state = "IDLE"
            user.state_data = None
            user.state_expires_at = None
            await db.commit()

        if user.onboarding_complete:
            name = user.first_name or "você"
            logs = await self._get_today_logs(user, db)
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
                "• /historico — histórico (até 30 dias)\n"
                "• /registrar [data] — adicionar refeição de dia passado\n"
                "• /deletar [refeição] — apagar refeição de hoje\n"
                "• /desfazer — desfazer última refeição\n\n"
                "💧 *Hidratação*\n"
                "• /agua [ml] — registrar água (padrão 250ml)\n\n"
                "📊 *Relatórios*\n"
                "• /relatorios — histórico de relatórios\n"
                "• /relatorio [semana|mes|3meses|total]\n"
                "• /frequencia [semanal|mensal|trimestral|nunca]\n\n"
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
            "• /historico — últimos 7 dias\n"
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
            "• /cancelar — cancelar ação em curso\n\n"
            "🔓 */premium* — desbloquear foto, áudio e relatórios completos"
        )

    async def _cmd_hoje(self, user: User, args, db: AsyncSession) -> str:
        logs = await self._get_today_logs(user, db)

        if not logs:
            return (
                "Nenhuma refeição registrada hoje ainda! 🍽️\n"
                "Me conta o que você comeu."
            )

        total_kcal = sum(l.total_calories_kcal for l in logs)
        total_protein = sum(l.total_protein_g for l in logs)
        total_carb = sum(l.total_carb_g for l in logs)
        total_fat = sum(l.total_fat_g for l in logs)

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
            pct_goal = min(100, int(total_kcal / user.daily_calorie_goal * 100))
            bar = "█" * (pct_goal // 10) + "░" * (10 - pct_goal // 10)
            msg += (
                f"\n\n🎯 Meta: {user.daily_calorie_goal} kcal\n"
                f"`{bar}` {pct_goal}%\n"
                f"{'⚠️ Meta atingida!' if remaining <= 0 else f'Faltam {remaining:.0f} kcal'}"
            )

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

        # Agrupar por data local
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
        header = (
            f"📅 *Histórico — {n_days} dia{'s' if n_days != 1 else ''} com registro*\n"
        )
        footer = f"\n📊 *Média diária:* {avg:.0f} kcal"
        if not user.is_premium:
            footer += f"\n\n🔓 Plano Premium mostra até 30 dias · /premium"

        return header + "\n" + "\n\n".join(sections) + footer

    async def _cmd_meta(self, user: User, args, db: AsyncSession) -> str:
        if args:
            digits = "".join(c for c in args if c.isdigit())
            if not digits:
                return "Por favor, informe um valor em kcal. Ex: /meta 1800"
            kcal = int(digits)
            if kcal < 500 or kcal > 10000:
                return "Meta deve estar entre 500 e 10.000 kcal."
            user.daily_calorie_goal = kcal
            await db.commit()
            analytics.goal_set(user.channel_id, kcal, user.goal_type or "manter")
            return f"✅ Meta atualizada para *{kcal} kcal/dia*!"
        if user.daily_calorie_goal:
            return f"Sua meta atual é *{user.daily_calorie_goal} kcal/dia*.\nPara alterar: /meta 1800"
        return "Você não tem meta definida.\nPara definir: /meta 1800"

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

        # Sem args: mostra status atual
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
            "✅ Registro por foto e áudio\n"
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
        self._set_timed_state(user, "DELETING")
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

        # Carregar food_items de cada log
        meal_data = []
        for log in logs:
            fi_result = await db.execute(
                select(FoodItem).where(FoodItem.meal_log_id == log.id)
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

    async def _cmd_privacidade(self, user: User, args, db) -> str:
        return (
            "🔒 *Privacidade e LGPD*\n\n"
            "Seus dados de saúde são protegidos conforme a LGPD (Lei 13.709/2018) "
            "como *dados sensíveis* (Art. 11).\n\n"
            "• /exportar\\_dados — baixar seus dados\n"
            "• /deletar\\_dados — apagar tudo em até 72h\n\n"
            "📄 [Política de Privacidade completa](https://nutri.bot/privacidade)"
        )

    async def _cmd_vincular(self, user: User, args, db: AsyncSession) -> str:
        """Gera um código temporário para vincular a conta Telegram ao painel web."""
        import secrets

        if user.channel_type != "telegram":
            return "Este comando só funciona no Telegram. 😊"

        # Código de 6 caracteres alfanumérico maiúsculo, sem ambíguos (0/O, I/1)
        # secrets.choice é criptograficamente seguro (ao contrário de random.choices)
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
        """Gera um magic link de acesso direto ao dashboard web (válido 10 min)."""
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
        """Abre o fluxo de registro retroativo para um dia passado específico."""
        tz = ZoneInfo(user.timezone or "America/Sao_Paulo")
        today = datetime.now(tz).date()

        if not args or not args.strip():
            limit = _BACKDATE_LIMIT_PREMIUM if user.is_premium else _BACKDATE_LIMIT_FREE
            return (
                "📅 *Registro retroativo*\n\n"
                "Me diz a data da refeição que quer adicionar:\n"
                "• /registrar ontem\n"
                "• /registrar anteontem\n"
                "• /registrar 20/08\n\n"
                f"Ou simplesmente me conta diretamente:\n"
                "_'Ontem de manhã comi pão com ovo'_\n\n"
                f"ℹ️ Limite: {limit} dias para o plano {'Premium' if user.is_premium else 'gratuito'}"
            )

        target = self._parse_date_from_args(args, user)
        if target is None:
            return (
                "Não entendi a data 🤔\n\n"
                "Exemplos:\n"
                "• /registrar ontem\n"
                "• /registrar anteontem\n"
                "• /registrar 20/08\n"
                "• /registrar dia 15"
            )

        err = self._check_backdate_limit(target, user)
        if err:
            return err

        lbl = self._date_label(target, tz)
        self._set_timed_state(user, "BACKDATING")
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

        if not user.is_premium and not settings.reports_open_beta:
            return (
                "📊 *Relatórios — Premium*\n\n"
                "Você recebe relatórios automáticos conforme a periodicidade configurada.\n"
                "Ou solicite um agora:\n"
                "• /relatorio semana — últimos 7 dias\n"
                "• /relatorio mes — último mês\n"
                "• /relatorio 3meses — últimos 3 meses\n"
                "• /relatorio total — todo o histórico\n\n"
                "👉 /premium para assinar"
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
        """Gera e envia um relatório sob demanda para o período solicitado."""
        from datetime import date as _date
        import calendar

        from app.config import settings
        from app.services.notification import notification_service
        from app.services.report import report_service

        if not user.is_premium and not settings.reports_open_beta:
            return (
                "📊 *Relatórios sob demanda — Premium*\n\n"
                "Assine o Premium para solicitar relatórios a qualquer momento:\n"
                "• /relatorio semana\n"
                "• /relatorio mes\n"
                "• /relatorio 3meses\n"
                "• /relatorio total\n\n"
                "👉 /premium"
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
            # Busca data do primeiro log do usuário
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
            return ""  # caption already sent via send_document
        except Exception as e:
            logger.error(f"[REPORT-ONDEMAND] Falha para {user.channel_id}: {e}")
            return "Ocorreu um erro ao gerar o relatório 😔 Tente novamente em instantes."

    async def _cmd_frequencia(self, user: User, args: str | None, db: AsyncSession) -> str:
        """Configura a frequência de envio automático dos relatórios."""
        _map = {
            "semanal": "weekly",
            "semana": "weekly",
            "weekly": "weekly",
            "mensal": "monthly",
            "mes": "monthly",
            "mês": "monthly",
            "monthly": "monthly",
            "trimestral": "quarterly",
            "trimestre": "quarterly",
            "3meses": "quarterly",
            "quarterly": "quarterly",
            "nunca": "none",
            "desativar": "none",
            "none": "none",
            "off": "none",
        }
        _labels = {
            "weekly": "Semanal — todo domingo às 20h 📅",
            "monthly": "Mensal — 1º dia de cada mês às 20h 🗓️",
            "quarterly": "Trimestral — 1º de jan/abr/jul/out às 20h 📆",
            "none": "Desativado — sem envio automático 🔕",
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
        label = _labels[freq]
        return f"✅ Frequência atualizada!\n\n*{label}*"

    async def _cmd_feedback(self, user: User, args, db) -> str:
        if not args:
            return (
                "Por favor, escreva seu feedback após o comando.\n"
                "Ex: /feedback O bot não reconheceu minha comida"
            )
        logger.info(f"Feedback de {user.channel_id}: {args[:200]}")
        return "Obrigado pelo feedback! 💚 Isso nos ajuda a melhorar."

    async def _cmd_agua(self, user: User, args: str | None, db: AsyncSession) -> str:
        from app.models.water_log import WaterLog
        from sqlalchemy import func

        ml = 250
        if args:
            digits = "".join(c for c in args if c.isdigit())
            if digits:
                ml = min(int(digits), 5000)

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
        today_total = result.scalar_one_or_none() or float(ml)
        await db.commit()

        goal_ml = 2000
        pct = min(100, int(today_total / goal_ml * 100))
        filled = pct // 20
        bar = "💧" * filled + "○" * (5 - filled)
        return (
            f"💧 *{ml:.0f}ml registrado!*\n\n"
            f"Hoje: {today_total:.0f}ml / {goal_ml}ml\n"
            f"{bar} {pct}%"
        )

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

    async def _cmd_desfazer(self, user: User, args: str | None, db: AsyncSession) -> str:
        logs = await self._get_today_logs(user, db)
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


conversation_service = ConversationService()
