"""
Testes para app/routers/admin.py — login, dashboard, usuários e LGPD.
Usa TestClient síncrono (o mesmo padrão do projeto) com DB e dependências mockadas.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from jose import jwt

from app.config import settings
from app.db.session import get_db
from app.main import app

_ALGORITHM = "HS256"
_ADMIN_COOKIE = "admin_session"


# ── Helpers ──────────────────────────────────────────────────────────────────

def _issue_admin_token(*, expired: bool = False) -> str:
    delta = timedelta(hours=-1) if expired else timedelta(hours=2)
    payload = {
        "sub": "admin",
        "type": "admin",
        "exp": datetime.now(timezone.utc) + delta,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=_ALGORITHM)


def _make_mock_db() -> AsyncMock:
    result = MagicMock()
    result.scalar.return_value = 0
    result.scalar_one_or_none.return_value = None
    result.scalars.return_value.all.return_value = []
    result.all.return_value = []
    result.rowcount = 0

    db = AsyncMock()
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.add = MagicMock()
    db.refresh = AsyncMock()
    return db


def _make_mock_user(uid: uuid.UUID | None = None) -> MagicMock:
    u = MagicMock()
    u.id = uid or uuid.uuid4()
    u.email = "paciente@test.com"
    u.first_name = "Paciente Teste"
    u.channel_id = "tg:99999"
    u.channel_type = "telegram"
    u.plan = "free"
    u.deleted_at = None
    u.daily_calorie_goal = 2000
    u.is_premium = False
    u.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    u.state_data = None
    u.lgpd_consent_at = None
    u.password_hash = None
    return u


@pytest.fixture
def client_with_db():
    """TestClient com DB mockado, sem autenticação admin."""
    mock_db = _make_mock_db()

    async def _override_db():
        yield mock_db

    app.dependency_overrides[get_db] = _override_db
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c, mock_db
    app.dependency_overrides.clear()


@pytest.fixture
def authed_client():
    """TestClient com cookie admin_session válido."""
    mock_db = _make_mock_db()

    async def _override_db():
        yield mock_db

    app.dependency_overrides[get_db] = _override_db
    token = _issue_admin_token()
    with TestClient(app, raise_server_exceptions=False) as c:
        c.cookies.set(_ADMIN_COOKIE, token)
        yield c, mock_db
    app.dependency_overrides.clear()


# ── GET /admin/login ──────────────────────────────────────────────────────────

class TestAdminLoginPage:
    def test_shows_login_form_unauthenticated(self, client_with_db):
        client, _ = client_with_db
        r = client.get("/admin/login")
        assert r.status_code == 200
        assert "admin" in r.text.lower() or "senha" in r.text.lower() or "login" in r.text.lower()

    def test_redirects_to_dashboard_when_already_authed(self, authed_client):
        client, _ = authed_client
        r = client.get("/admin/login", follow_redirects=False)
        assert r.status_code == 302
        assert r.headers["location"].endswith("/admin")

    def test_shows_expired_message_with_bad_cookie(self, client_with_db):
        client, _ = client_with_db
        client.cookies.set(_ADMIN_COOKIE, "invalid.token.here")
        r = client.get("/admin/login")
        assert r.status_code == 200
        assert "expirou" in r.text.lower() or "login" in r.text.lower()


# ── POST /admin/login ─────────────────────────────────────────────────────────

class TestAdminLoginPost:
    def test_correct_password_redirects_to_admin(self, client_with_db):
        client, _ = client_with_db
        with patch.object(settings, "admin_password", "supersecret"):
            r = client.post("/admin/login", data={"password": "supersecret"},
                            follow_redirects=False)
        assert r.status_code == 302
        assert r.headers["location"].endswith("/admin")
        assert _ADMIN_COOKIE in r.cookies

    def test_wrong_password_returns_401(self, client_with_db):
        client, _ = client_with_db
        with patch.object(settings, "admin_password", "supersecret"):
            r = client.post("/admin/login", data={"password": "wrong"},
                            follow_redirects=False)
        assert r.status_code == 401
        assert "incorreta" in r.text.lower()

    def test_missing_admin_password_env_returns_500(self, client_with_db):
        client, _ = client_with_db
        with patch.object(settings, "admin_password", None):
            r = client.post("/admin/login", data={"password": "anything"})
        assert r.status_code == 500

    def test_unauthenticated_dashboard_redirects(self, client_with_db):
        client, _ = client_with_db
        r = client.get("/admin/", follow_redirects=False)
        assert r.status_code == 302
        assert "/admin/login" in r.headers["location"]


# ── POST /admin/logout ────────────────────────────────────────────────────────

class TestAdminLogout:
    def test_logout_clears_cookie_and_redirects(self, authed_client):
        client, _ = authed_client
        r = client.post("/admin/logout", follow_redirects=False)
        assert r.status_code == 302
        assert "/admin/login" in r.headers["location"]


# ── GET /admin/ (dashboard) ───────────────────────────────────────────────────

class TestAdminDashboard:
    def test_authenticated_renders_dashboard(self, authed_client):
        client, _ = authed_client
        r = client.get("/admin/")
        assert r.status_code == 200

    def test_unauthenticated_redirects(self, client_with_db):
        client, _ = client_with_db
        r = client.get("/admin/", follow_redirects=False)
        assert r.status_code == 302


# ── GET /admin/usuarios ───────────────────────────────────────────────────────

class TestAdminUsuarios:
    def test_renders_for_authenticated(self, authed_client):
        client, _ = authed_client
        r = client.get("/admin/usuarios")
        assert r.status_code == 200

    def test_redirects_for_unauthenticated(self, client_with_db):
        client, _ = client_with_db
        r = client.get("/admin/usuarios", follow_redirects=False)
        assert r.status_code == 302


# ── POST /admin/api/usuarios/{id}/deletar (LGPD) ─────────────────────────────

class TestAdminLGPDDelete:
    def test_requires_auth(self, client_with_db):
        client, _ = client_with_db
        uid = str(uuid.uuid4())
        r = client.post(f"/admin/api/usuarios/{uid}/deletar",
                        data={"confirm": "CONFIRMAR"})
        assert r.status_code == 403

    def test_requires_confirm_field(self, authed_client):
        client, _ = authed_client
        uid = str(uuid.uuid4())
        r = client.post(f"/admin/api/usuarios/{uid}/deletar",
                        data={"confirm": "errado"})
        assert r.status_code == 422

    def test_returns_404_for_unknown_user(self, authed_client):
        client, _ = authed_client
        uid = str(uuid.uuid4())
        r = client.post(f"/admin/api/usuarios/{uid}/deletar",
                        data={"confirm": "CONFIRMAR"})
        assert r.status_code == 404

    def test_anonymizes_existing_user(self, authed_client):
        client, mock_db = authed_client
        uid = uuid.uuid4()
        mock_user = _make_mock_user(uid=uid)

        result_with_user = MagicMock()
        result_with_user.scalar_one_or_none.return_value = mock_user
        result_empty = MagicMock()
        result_empty.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(side_effect=[result_with_user, result_empty, result_empty])

        r = client.post(f"/admin/api/usuarios/{uid}/deletar",
                        data={"confirm": "CONFIRMAR"})
        assert r.status_code == 200
        data = r.json()
        assert data.get("ok") is True
        assert mock_user.deleted_at is not None
        assert mock_user.email is None
        assert mock_user.first_name is None
