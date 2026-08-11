"""PostHog event tracking — eventos do domínio NutriBot."""

from __future__ import annotations

import logging

from app.config import settings

logger = logging.getLogger(__name__)

_posthog = None

# ── Nomes de eventos ──────────────────────────────────────────────────────────

MEAL_LOGGED          = "meal_logged"
MEAL_CONFIRMED       = "meal_confirmed"
MEAL_DELETED         = "meal_deleted"
ONBOARDING_COMPLETE  = "onboarding_completed"
GOAL_SET             = "goal_set"
ALERT_SENT           = "alert_sent"
ALERT_PAUSED         = "alert_paused"
REPORT_REQUESTED     = "report_requested"
REPORT_GENERATED     = "report_generated"
PREMIUM_CTA_SHOWN    = "premium_cta_shown"
DATA_EXPORTED        = "data_exported"
DELETION_REQUESTED   = "account_deletion_requested"
DAILY_SUMMARY_VIEWED = "daily_summary_viewed"


def _get_client():
    global _posthog
    if _posthog is None and settings.posthog_api_key:
        import posthog
        posthog.api_key = settings.posthog_api_key
        posthog.host = settings.posthog_host
        _posthog = posthog
    return _posthog


def track(channel_id: str, event: str, properties: dict | None = None) -> None:
    """Envia evento ao PostHog (fire-and-forget, nunca levanta exceção)."""
    client = _get_client()
    if client is None:
        logger.debug(f"[ANALYTICS skip] {event} — PostHog não configurado")
        return
    try:
        client.capture(distinct_id=channel_id, event=event, properties=properties or {})
    except Exception as e:
        logger.warning(f"[ANALYTICS] PostHog error: {e}")


# ── Helpers de domínio ────────────────────────────────────────────────────────

def meal_logged(
    channel_id: str,
    input_type: str,
    meal_type: str,
    items: int,
    total_kcal: float,
) -> None:
    """Refeição processada pela IA (antes da confirmação do usuário)."""
    track(channel_id, MEAL_LOGGED, {
        "input_type": input_type,   # "text" | "image" | "audio"
        "meal_type": meal_type,
        "items_count": items,
        "total_kcal": round(total_kcal, 1),
    })


def meal_confirmed(channel_id: str, meal_type: str, total_kcal: float) -> None:
    """Usuário confirmou uma refeição identificada pela IA."""
    track(channel_id, MEAL_CONFIRMED, {
        "meal_type": meal_type,
        "total_kcal": round(total_kcal, 1),
    })


def meal_deleted(channel_id: str) -> None:
    """Usuário excluiu um registro de refeição."""
    track(channel_id, MEAL_DELETED)


def onboarding_completed(
    channel_id: str, channel_type: str, goal_kcal: int
) -> None:
    """Usuário concluiu o fluxo de cadastro."""
    track(channel_id, ONBOARDING_COMPLETE, {
        "channel_type": channel_type,   # "telegram" | "whatsapp"
        "goal_kcal": goal_kcal,
    })


def goal_set(channel_id: str, goal_kcal: int, goal_type: str) -> None:
    """Usuário configurou ou alterou a meta calórica diária."""
    track(channel_id, GOAL_SET, {
        "goal_kcal": goal_kcal,
        "goal_type": goal_type or "manter",
    })


def alert_sent(channel_id: str, meal_type: str) -> None:
    """Lembrete de refeição enviado com sucesso."""
    track(channel_id, ALERT_SENT, {"meal_type": meal_type})


def alert_paused(channel_id: str, hours: int) -> None:
    """Usuário pausou os alertas por N horas."""
    track(channel_id, ALERT_PAUSED, {"hours": hours})


def report_requested(
    channel_id: str,
    period_type: str,
    trigger: str = "command",
) -> None:
    """Usuário solicitou relatório sob demanda ou recebeu via scheduler."""
    track(channel_id, REPORT_REQUESTED, {
        "period_type": period_type,   # "weekly" | "monthly" | "quarterly" | "custom"
        "trigger": trigger,           # "command" | "scheduler"
    })


def report_generated(
    channel_id: str, period_type: str, file_format: str
) -> None:
    """Relatório gerado e enviado com sucesso."""
    track(channel_id, REPORT_GENERATED, {
        "period_type": period_type,
        "file_format": file_format,   # "pdf" | "html"
    })


def premium_cta_shown(channel_id: str, context: str) -> None:
    """CTA de upgrade exibido a usuário free."""
    track(channel_id, PREMIUM_CTA_SHOWN, {"context": context})


def data_exported(channel_id: str, logs_count: int) -> None:
    """Usuário solicitou exportação de dados (LGPD Art. 18 — portabilidade)."""
    track(channel_id, DATA_EXPORTED, {"logs_count": logs_count})


def deletion_requested(channel_id: str) -> None:
    """Usuário iniciou fluxo de exclusão de conta."""
    track(channel_id, DELETION_REQUESTED)


def daily_summary_viewed(
    channel_id: str, total_kcal: float, pct_goal: int
) -> None:
    """Usuário consultou o resumo diário via /hoje."""
    track(channel_id, DAILY_SUMMARY_VIEWED, {
        "total_kcal": round(total_kcal, 1),
        "pct_goal": pct_goal,
    })
