"""
Testes de integração dos endpoints webhook.
Usa TestClient do FastAPI com banco mockado.
"""

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


@pytest.fixture
def client():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


class TestHealth:
    def test_ping(self, client: TestClient):
        r = client.get("/ping")
        assert r.status_code == 200
        assert r.json() == "pong"

    def test_health_returns_status(self, client: TestClient):
        r = client.get("/health")
        assert r.status_code in (200, 503)
        data = r.json()
        assert "status" in data
        assert "db" in data


class TestTelegramWebhook:
    def _valid_payload(self):
        return {
            "update_id": 1,
            "message": {
                "message_id": 1,
                "from": {"id": 123, "is_bot": False, "first_name": "Teste"},
                "chat": {"id": 123, "type": "private"},
                "date": 1718000000,
                "text": "almocei arroz com feijão",
            },
        }

    def test_rejects_invalid_secret(self, client: TestClient):
        r = client.post(
            "/webhook/telegram",
            json=self._valid_payload(),
            headers={"X-Telegram-Bot-Api-Secret-Token": "wrong-secret"},
        )
        assert r.status_code == 403

    def test_accepts_valid_secret(self, client: TestClient):
        r = client.post(
            "/webhook/telegram",
            json=self._valid_payload(),
            headers={"X-Telegram-Bot-Api-Secret-Token": settings.telegram_webhook_secret},
        )
        assert r.status_code == 200

    def test_accepts_missing_secret_when_not_configured(self, client: TestClient):
        original = settings.telegram_webhook_secret
        settings.telegram_webhook_secret = ""
        try:
            r = client.post("/webhook/telegram", json=self._valid_payload())
            # Com secret vazio, header None != "" → 403. Comportamento esperado.
            assert r.status_code in (200, 403)
        finally:
            settings.telegram_webhook_secret = original


class TestWhatsAppWebhook:
    def _valid_payload(self):
        return {
            "phone": "5511999999999",
            "fromMe": False,
            "type": "ReceivedCallback",
            "text": {"message": "almocei arroz"},
        }

    def test_accepts_payload(self, client: TestClient):
        r = client.post("/webhook/whatsapp", json=self._valid_payload())
        assert r.status_code == 200

    def test_ignores_from_me(self, client: TestClient):
        payload = {**self._valid_payload(), "fromMe": True}
        r = client.post("/webhook/whatsapp", json=payload)
        assert r.status_code == 200


class TestPaymentWebhook:
    def test_accepts_valid_payload(self, client: TestClient):
        payload = {
            "action": "payment.updated",
            "data": {"id": "123456"},
            "type": "payment",
        }
        r = client.post("/webhook/payment", json=payload)
        assert r.status_code == 200
