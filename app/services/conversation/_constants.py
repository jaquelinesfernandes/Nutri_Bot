"""Constantes e helpers puros do módulo de conversa."""
from __future__ import annotations

from datetime import timedelta
from typing import Literal

ConversationState = Literal[
    "IDLE", "ONBOARDING", "CONFIRMING", "CORRECTING", "DELETING", "INVITE_PENDING", "REVOKING"
]

CONFIRM_WORDS = {"sim", "s", "yes", "y", "ok", "confirmar", "confirma", "certo", "isso", "exato", "correto"}
DENY_WORDS = {"não", "nao", "n", "no", "errado", "corrigir", "incorreto", "errada"}


def _matches_intent(normalized: str, words: set[str]) -> bool:
    """Verifica se o texto normalizado corresponde a uma palavra de intenção (palavras inteiras)."""
    if normalized in words:
        return True
    parts = normalized.split()
    if len(parts) <= 4:
        return any(p in words for p in parts)
    return False


MEAL_EMOJI = {
    "breakfast":       "🌅",
    "morning_snack":   "🍌",
    "lunch":           "☀️",
    "afternoon_snack": "🍊",
    "dinner":          "🌙",
    "snack":           "🍎",
    "other":           "🍽️",
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
    "CONFIRMING":     timedelta(minutes=10),
    "CORRECTING":     timedelta(minutes=5),
    "DELETING":       timedelta(minutes=5),
    "BACKDATING":     timedelta(minutes=10),
    "INVITE_PENDING": timedelta(minutes=30),
    "REVOKING":       timedelta(minutes=10),
}

_MEAL_DEFAULT_HOURS: dict[str, int] = {
    "breakfast":       8,
    "morning_snack":   10,
    "lunch":           12,
    "afternoon_snack": 15,
    "dinner":          19,
    "snack":           12,
    "other":           12,
}

# Temporariamente sem restrição — ambos os planos aceitam qualquer data passada
_BACKDATE_LIMIT_FREE    = 3650
_BACKDATE_LIMIT_PREMIUM = 3650

MAINTENANCE_RESPONSE = (
    "Estou em manutenção no momento 🔧\n"
    "Volto em breve! Seus dados estão seguros."
)

UNRECOGNIZED_RESPONSE = (
    "Oi! 😊 Pode me contar o que comeu "
    "(ex: 'almocei arroz e frango') ou usar /ajuda para ver os comandos disponíveis."
)
