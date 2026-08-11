"""Mercado Pago Subscriptions integration."""

from __future__ import annotations

import logging

from app.config import settings

logger = logging.getLogger(__name__)


class PaymentService:
    def generate_checkout_link(self, user_channel_id: str, plan: str) -> str:
        """
        Cria preferência no Mercado Pago e retorna link de checkout.
        plan: 'premium_monthly' | 'premium_annual'
        TODO Sprint 2: implementar via mercadopago SDK
        """
        raise NotImplementedError

    async def handle_webhook(self, payload: dict) -> None:
        """
        Processa webhook do Mercado Pago.
        Atualiza plano do usuário no DB conforme status do pagamento.
        TODO Sprint 2
        """
        raise NotImplementedError


payment_service = PaymentService()
