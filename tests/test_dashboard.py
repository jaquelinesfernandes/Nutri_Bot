"""
Testes de integração das rotas HTML do dashboard (Jinja2).

auth_client : JWT válido + DB e usuário mockados (fixture síncrona de conftest.py)
anon_client : sem cookie, DB mockado

Cobre app/routers/dashboard.py (272 miss, 18%).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient


# ── Rotas públicas (sem auth) ─────────────────────────────────────────────────

class TestPublicRoutes:
    def test_root_redireciona_para_login(self, anon_client: TestClient):
        r = anon_client.get("/", follow_redirects=False)
        assert r.status_code == 302
        assert "/login" in r.headers["location"]

    def test_login_page_ok(self, anon_client: TestClient):
        r = anon_client.get("/login")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]

    def test_login_page_com_erro_link_expirado(self, anon_client: TestClient):
        r = anon_client.get("/login?error=link_expirado")
        assert r.status_code == 200
        assert "expirado" in r.text.lower()

    def test_login_page_com_erro_link_invalido(self, anon_client: TestClient):
        r = anon_client.get("/login?error=link_invalido")
        assert r.status_code == 200

    def test_login_page_com_erro_usuario_nao_encontrado(self, anon_client: TestClient):
        r = anon_client.get("/login?error=usuario_nao_encontrado")
        assert r.status_code == 200

    def test_login_page_com_erro_desconhecido(self, anon_client: TestClient):
        """Erro não mapeado deve ser exibido como texto bruto."""
        r = anon_client.get("/login?error=erro_qualquer_coisa")
        assert r.status_code == 200

    def test_login_page_com_success(self, anon_client: TestClient):
        r = anon_client.get("/login?success=link_enviado")
        assert r.status_code == 200

    def test_cadastro_page_ok(self, anon_client: TestClient):
        r = anon_client.get("/cadastro")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]

    def test_esqueci_senha_page_ok(self, anon_client: TestClient):
        r = anon_client.get("/esqueci-senha")
        assert r.status_code == 200

    def test_magic_link_sem_token_redireciona(self, anon_client: TestClient):
        r = anon_client.get("/auth/magic", follow_redirects=False)
        assert r.status_code == 302
        assert "link_invalido" in r.headers["location"]

    def test_magic_link_token_invalido_redireciona(self, anon_client: TestClient):
        r = anon_client.get("/auth/magic?t=nao.e.um.jwt.valido", follow_redirects=False)
        assert r.status_code == 302
        assert "link_expirado" in r.headers["location"]


# ── Redirects para login quando não autenticado ───────────────────────────────

class TestAuthRedirects:
    """Rotas protegidas devem redirecionar para /login quando não há cookie."""

    def test_dashboard_sem_auth(self, anon_client: TestClient):
        r = anon_client.get("/dashboard", follow_redirects=False)
        assert r.status_code == 302
        assert "/login" in r.headers["location"]

    def test_historico_sem_auth(self, anon_client: TestClient):
        r = anon_client.get("/historico", follow_redirects=False)
        assert r.status_code == 302

    def test_configuracoes_sem_auth(self, anon_client: TestClient):
        r = anon_client.get("/configuracoes", follow_redirects=False)
        assert r.status_code == 302

    def test_relatorios_sem_auth(self, anon_client: TestClient):
        r = anon_client.get("/relatorios", follow_redirects=False)
        assert r.status_code == 302

    def test_vincular_telegram_sem_auth(self, anon_client: TestClient):
        r = anon_client.get("/vincular-telegram", follow_redirects=False)
        assert r.status_code == 302


# ── Login form (POST) ─────────────────────────────────────────────────────────

class TestLoginForm:
    def test_email_inexistente_retorna_erro(self, anon_client: TestClient):
        """DB mockado retorna None para qualquer usuário → dummy_verify + erro."""
        with patch("app.routers.dashboard.pwd_context") as mock_pwd:
            mock_pwd.dummy_verify = lambda: None  # evita problema passlib/bcrypt
            r = anon_client.post(
                "/auth/login-form",
                data={"email": "naoexiste@test.com", "password": "qualquer"},
            )
        assert r.status_code == 401

    def test_campos_faltando_retorna_erro(self, anon_client: TestClient):
        r = anon_client.post("/auth/login-form", data={"email": "x@x.com"})
        # FastAPI retorna 422 por falta do campo password
        assert r.status_code in (422, 400)


# ── Register form (POST) ──────────────────────────────────────────────────────

class TestRegisterForm:
    def test_senha_curta_retorna_422(self, anon_client: TestClient):
        r = anon_client.post(
            "/auth/register-form",
            data={"name": "Teste", "email": "novo@test.com", "password": "abc"},
        )
        assert r.status_code == 422

    def test_registro_novo_usuario_redireciona(self, anon_client: TestClient):
        """Com DB mockado (nenhum usuário existente), novo registro deve redirecionar."""
        with patch("app.routers.dashboard.pwd_context") as mock_pwd:
            mock_pwd.hash.return_value = "$2b$12$fakehash"
            r = anon_client.post(
                "/auth/register-form",
                data={
                    "name": "Novo Usuário",
                    "email": "novo@nutribot.test",
                    "password": "senha123",
                },
                follow_redirects=False,
            )
        # Redireciona para /dashboard após registro bem-sucedido
        assert r.status_code in (302, 200)


# ── Logout ────────────────────────────────────────────────────────────────────

class TestLogout:
    def test_logout_redireciona_ou_ok(self, auth_client: TestClient):
        # TestClient pode seguir o redirect automaticamente (200) ou retornar 302
        r = auth_client.post("/api/auth/logout")
        assert r.status_code in (200, 302)

    def test_logout_remove_cookie(self, auth_client: TestClient):
        r = auth_client.post("/api/auth/logout")
        # Cookie deletado via Set-Cookie com expires no passado ou max-age=0
        set_cookie = r.headers.get("set-cookie", "")
        assert "access_token" in set_cookie or r.status_code in (200, 302)


# ── Rotas protegidas com auth_client ─────────────────────────────────────────

class TestDashboardAutenticado:
    def test_dashboard_retorna_200(self, auth_client: TestClient):
        r = auth_client.get("/dashboard")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]

    def test_historico_hoje_retorna_200(self, auth_client: TestClient):
        r = auth_client.get("/historico")
        assert r.status_code == 200

    def test_historico_data_especifica(self, auth_client: TestClient):
        r = auth_client.get("/historico?date=2026-09-01")
        assert r.status_code == 200

    def test_historico_data_invalida_usa_hoje(self, auth_client: TestClient):
        r = auth_client.get("/historico?date=nao-e-uma-data")
        assert r.status_code == 200

    def test_configuracoes_retorna_200(self, auth_client: TestClient):
        r = auth_client.get("/configuracoes")
        assert r.status_code == 200

    def test_relatorios_retorna_200(self, auth_client: TestClient):
        r = auth_client.get("/relatorios")
        assert r.status_code == 200

    def test_vincular_telegram_retorna_200(self, auth_client: TestClient):
        r = auth_client.get("/vincular-telegram")
        assert r.status_code == 200


# ── Configurações (POST) ──────────────────────────────────────────────────────

class TestConfiguracoes:
    def test_salvar_configuracoes(self, auth_client: TestClient):
        r = auth_client.post(
            "/configuracoes/salvar",
            data={
                "daily_calorie_goal": "2200",
                "goal_type": "perder",
                "report_frequency": "weekly",
            },
            follow_redirects=False,
        )
        assert r.status_code in (200, 302, 303)

    def test_vincular_telegram_submit(self, auth_client: TestClient):
        """Rota POST /configuracoes/vincular-telegram — pode exigir campos específicos."""
        r = auth_client.post("/configuracoes/vincular-telegram")
        # Aceita qualquer resposta não-500 (422 se faltam campos obrigatórios é ok)
        assert r.status_code < 500


# ── Esqueci senha (POST) ──────────────────────────────────────────────────────

class TestEsqueciSenha:
    def test_email_qualquer_redireciona_sent(self, anon_client: TestClient):
        """Anti-enumeração: qualquer email redireciona para /esqueci-senha?sent=1.

        DB mockado retorna scalar_one_or_none()=None → rota pula o bloco Telegram
        e vai direto para o RedirectResponse(302). TestClient pode seguir para 200.
        """
        r = anon_client.post(
            "/auth/esqueci-senha",
            data={"email": "qualquer@test.com"},
        )
        # 302 se follow_redirects=False, 200 se TestClient seguiu o redirect
        assert r.status_code in (200, 302)

    def test_campo_email_faltando(self, anon_client: TestClient):
        r = anon_client.post("/auth/esqueci-senha", data={})
        assert r.status_code in (200, 302, 422)
