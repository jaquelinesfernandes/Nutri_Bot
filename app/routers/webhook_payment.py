import hashlib
import hmac
import logging
import time

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request

from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter(tags=["payment"])


def _validate_mp_signature(body: bytes, x_signature: str, x_request_id: str) -> bool:
    """Valida assinatura HMAC do Mercado Pago."""
    if not settings.mercadopago_webhook_secret:
        return True  # Não validar em dev se secret não configurado

    try:
        parts = dict(p.split("=", 1) for p in x_signature.split(","))
        ts = parts.get("ts", "")
        v1 = parts.get("v1", "")
        manifest = f"id:{x_request_id};request-id:{x_request_id};ts:{ts};"
        expected = hmac.new(
            settings.mercadopago_webhook_secret.encode(),
            manifest.encode(),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, v1)
    except Exception:
        return False


async def _process_payment(payload: dict) -> None:
    try:
        logger.info(f"[PAYMENT] action={payload.get('action')} id={payload.get('data', {}).get('id')}")
        # TODO Sprint 2: chamar payment_service.handle_webhook(payload)
    except Exception:
        logger.exception("Erro ao processar webhook de pagamento")


@router.post("/webhook/payment")
async def webhook_payment(
    request: Request,
    background_tasks: BackgroundTasks,
    x_signature: str | None = Header(default=None),
    x_request_id: str | None = Header(default=None),
):
    body = await request.body()

    if settings.app_env == "production":
        # Em produção, assinatura é OBRIGATÓRIA — impede criação de premium falso
        if not x_signature:
            logger.warning("[PAYMENT] Webhook sem assinatura rejeitado em produção")
            raise HTTPException(status_code=403, detail="Signature required")
        if not _validate_mp_signature(body, x_signature, x_request_id or ""):
            logger.warning("[PAYMENT] Assinatura inválida no webhook")
            raise HTTPException(status_code=403, detail="Invalid signature")
    elif x_signature and not _validate_mp_signature(body, x_signature, x_request_id or ""):
        # Em dev/staging, valida se vier mas não exige
        raise HTTPException(status_code=403, detail="Invalid signature")

    import json
    payload = json.loads(body)
    background_tasks.add_task(_process_payment, payload)
    return {}
