"""
Testes dos endpoints REST de autenticação JSON:
  POST /api/auth/register
  POST /api/auth/login
  POST /api/auth/logout

Cobre app/routers/auth.py linhas: 25, 44-72, 83-105.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.db.session import get_db
from app.main import app


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_db(user=None) -> AsyncMock:
    """DB mock que retorna 'user' para scalar_one_or_none."""
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = user
    mock_result.rowcount = 0

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.commit = AsyncMock()
    mock_db.flush = AsyncMock()
    mock_db.rollback = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.refresh = AsyncMock()
    return mock_db


def _anon(mock_db: AsyncMock) -> TestClient:
    """TestClient sem autenticação com DB mockado."""
    async def _override():
        yield mock_db
    app.dependency_overrides[get_db] = _override
    return TestClient(app, raise_server_exceptions=False)


# ── POST /api/auth/register ───────────────────────────────────────────────────

class TestRegister:
    def test_registro_sucesso_retorna_201(self):
        """Novo usuário com dados válidos → 201 + user_name no body."""
        mock_db = _make_db(None)  # sem usuário existente
        with _anon(mock_db) as client:
            with patch("app.routers.auth.pwd_context") as mock_pwd:
                mock_pwd.hash.return_value = "$2b$12$fakehash_gerado"
                r = client.post(
                    "/api/auth/register",
                    json={"name": "Ana Teste", "email": "ana@register.com", "password": "senha123"},
                )
        app.dependency_overrides.clear()
        assert r.status_code == 201
        body = r.json()
        assert body["user_name"] == "Ana Teste"
        assert body["ok"] is True

    def test_registro_define_cookie_httponly(self):
        """Cookie access_token deve ser definido na resposta."""
        mock_db = _make_db(None)
        with _anon(mock_db) as client:
            with patch("app.routers.auth.pwd_context") as mock_pwd:
                mock_pwd.hash.return_value = "$2b$12$fakehash"
                r = client.post(
                    "/api/auth/register",
                    json={"name": "Cookie Test", "email": "cookie@test.com", "password": "senha123"},
                )
        app.dependency_overrides.clear()
        assert r.status_code == 201
        assert "access_token" in r.cookies

    def test_email_duplicado_retorna_400(self):
        """E-mail já existente no DB → 400."""
        existing_user = MagicMock(id=uuid.uuid4(), email="dup@test.com")
        mock_db = _make_db(existing_user)
        with _anon(mock_db) as client:
            r = client.post(
                "/api/auth/register",
                json={"name": "Dup", "email": "dup@test.com", "password": "senha123"},
            )
        app.dependency_overrides.clear()
        assert r.status_code == 400
        assert "cadastrado" in r.json()["detail"].lower()

    def test_senha_curta_retorna_422(self):
        """Senha < 6 chars é rejeitada pelo Pydantic validator → 422."""
        mock_db = _make_db(None)
        with _anon(mock_db) as client:
            r = client.post(
                "/api/auth/register",
                json={"name": "X", "email": "x@x.com", "password": "123"},
            )
        app.dependency_overrides.clear()
        assert r.status_code == 422

    def test_nome_vazio_retorna_422(self):
        """Nome vazio é rejeitado pelo Pydantic → 422."""
        mock_db = _make_db(None)
        with _anon(mock_db) as client:
            r = client.post(
                "/api/auth/register",
                json={"name": "   ", "email": "vazio@x.com", "password": "senha123"},
            )
        app.dependency_overrides.clear()
        assert r.status_code == 422


# ── POST /api/auth/login ──────────────────────────────────────────────────────

class TestLogin:
    def test_usuario_inexistente_retorna_401(self):
        """E-mail não encontrado no DB → dummy_verify + 401."""
        mock_db = _make_db(None)
        with _anon(mock_db) as client:
            with patch("app.routers.auth.pwd_context") as mock_pwd:
                mock_pwd.dummy_verify = MagicMock()
                r = client.post(
                    "/api/auth/login",
                    json={"email": "naoexiste@test.com", "password": "qualquer"},
                )
        app.dependency_overrides.clear()
        assert r.status_code == 401
        assert "incorretos" in r.json()["detail"]

    def test_usuario_sem_senha_retorna_401(self):
        """Usuário de bot (sem password_hash) → dummy_verify + 401."""
        user_sem_hash = MagicMock()
        user_sem_hash.password_hash = None  # usuário Telegram sem senha web
        mock_db = _make_db(user_sem_hash)
        with _anon(mock_db) as client:
            with patch("app.routers.auth.pwd_context") as mock_pwd:
                mock_pwd.dummy_verify = MagicMock()
                r = client.post(
                    "/api/auth/login",
                    json={"email": "bot@test.com", "password": "qualquer"},
                )
        app.dependency_overrides.clear()
        assert r.status_code == 401

    def test_senha_incorreta_retorna_401(self):
        """pwd_context.verify retorna False → 401."""
        user = MagicMock()
        user.password_hash = "$2b$12$fakehash"
        user.deleted_at = None
        mock_db = _make_db(user)
        with _anon(mock_db) as client:
            with patch("app.routers.auth.pwd_context") as mock_pwd:
                mock_pwd.verify.return_value = False
                r = client.post(
                    "/api/auth/login",
                    json={"email": "ana@test.com", "password": "errada"},
                )
        app.dependency_overrides.clear()
        assert r.status_code == 401

    def test_conta_deletada_retorna_403(self):
        """Usuário com deleted_at preenchido → 403."""
        user = MagicMock()
        user.password_hash = "$2b$12$fakehash"
        user.deleted_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        mock_db = _make_db(user)
        with _anon(mock_db) as client:
            with patch("app.routers.auth.pwd_context") as mock_pwd:
                mock_pwd.verify.return_value = True
                r = client.post(
                    "/api/auth/login",
                    json={"email": "deletada@test.com", "password": "senha123"},
                )
        app.dependency_overrides.clear()
        assert r.status_code == 403
        assert "desativada" in r.json()["detail"].lower()

    def test_login_sucesso_retorna_200_e_cookie(self):
        """Credenciais corretas → 200, user_name no body, cookie access_token setado."""
        user = MagicMock()
        user.id = uuid.uuid4()
        user.password_hash = "$2b$12$fakehash"
        user.deleted_at = None
        user.first_name = "Ana"
        mock_db = _make_db(user)
        with _anon(mock_db) as client:
            with patch("app.routers.auth.rate_limiter") as mock_rl, \
                 patch("app.routers.auth.pwd_context") as mock_pwd:
                mock_rl.is_allowed = AsyncMock(return_value=True)
                mock_pwd.verify.return_value = True
                r = client.post(
                    "/api/auth/login",
                    json={"email": "ana@test.com", "password": "certa"},
                )
        app.dependency_overrides.clear()
        assert r.status_code == 200
        assert r.json()["user_name"] == "Ana"
        assert "access_token" in r.cookies

    def test_login_sucesso_sem_first_name_usa_email(self):
        """Quando first_name é vazio/None, user_name cai para o email."""
        user = MagicMock()
        user.id = uuid.uuid4()
        user.password_hash = "$2b$12$fakehash"
        user.deleted_at = None
        user.first_name = None  # sem nome → usa body.email
        mock_db = _make_db(user)
        with _anon(mock_db) as client:
            with patch("app.routers.auth.rate_limiter") as mock_rl, \
                 patch("app.routers.auth.pwd_context") as mock_pwd:
                mock_rl.is_allowed = AsyncMock(return_value=True)
                mock_pwd.verify.return_value = True
                r = client.post(
                    "/api/auth/login",
                    json={"email": "anon@test.com", "password": "certa"},
                )
        app.dependency_overrides.clear()
        assert r.status_code == 200
        assert r.json()["user_name"] == "anon@test.com"


# ── POST /api/auth/logout ─────────────────────────────────────────────────────

class TestLogout:
    def test_logout_retorna_200_e_mensagem(self):
        """Logout limpa cookie e retorna mensagem de confirmação."""
        mock_db = _make_db(None)
        with _anon(mock_db) as client:
            r = client.post("/api/auth/logout")
        app.dependency_overrides.clear()
        assert r.status_code == 200
        assert "Logout" in r.json()["message"]

    def test_logout_remove_cookie(self):
        """Cookie access_token é deletado (Set-Cookie com max-age=0 ou expires passado)."""
        mock_db = _make_db(None)
        with _anon(mock_db) as client:
            r = client.post("/api/auth/logout")
        app.dependency_overrides.clear()
        assert r.status_code == 200
        # TestClient reflete o cookie deletado como ausente do jar
        assert "access_token" not in r.cookies
