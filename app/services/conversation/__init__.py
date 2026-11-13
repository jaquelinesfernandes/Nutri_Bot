"""Pacote conversation — re-exporta ConversationService e constantes públicas."""
from ._constants import (
    CONFIRM_WORDS,
    DENY_WORDS,
    MEAL_EMOJI,
    _MEAL_DEFAULT_HOURS,
    _matches_intent,
)
from .service import ConversationService

conversation_service = ConversationService()

__all__ = [
    "ConversationService",
    "conversation_service",
    "CONFIRM_WORDS",
    "DENY_WORDS",
    "MEAL_EMOJI",
    "_MEAL_DEFAULT_HOURS",
    "_matches_intent",
]
