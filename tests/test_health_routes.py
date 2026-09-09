"""
Testes das rotas de saúde e administração:
  GET  /health
  GET  /ping
  GET  /scheduler/status
  POST /scheduler/trigger/{job_id}

Cobre app/routers/health.py linhas: 15-16, 26-28, 57-80, 101-115.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


# ── /health ───────────────────────────────────────────────────────────────────

class TestHealth:
    def test_health_db_conectado(self, anon_client: TestClient):
        """DB responde → status='ok', db='connected'."""
        mock_session = AsyncMock()
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("app.routers.health.AsyncSessionLocal", return_value=mock_ctx):
            r = anon_client.get("/health")

        assert r.status_code == 200
        data = r.json()
        assert data["db"] == "connected"
        assert data["status"] == "ok"

    def test_health_db_desconectado(self, anon_client: TestClient):
        """DB falha → status='degraded', db='disconnected'."""
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(side_effect=Exception("connection refused"))
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("app.routers.health.AsyncSessionLocal", return_value=mock_ctx):
            r = anon_client.get("/health")

        assert r.status_code == 200
        data = r.json()
        assert data["db"] == "disconnected"
        assert data["status"] == "degraded"

    def test_ping(self, anon_client: TestClient):
        r = anon_client.get("/ping")
        assert r.status_code == 200
        assert r.json() == "pong"


# ── _require_admin ────────────────────────────────────────────────────────────

class TestRequireAdmin:
    def test_chave_incorreta_retorna_403(self, anon_client: TestClient):
        """Com ADMIN_API_KEY configurada e chave errada → 403."""
        with patch.object(settings, "admin_api_key", "chave-secreta"):
            r = anon_client.get(
                "/scheduler/status",
                headers={"X-Admin-Key": "chave-errada"},
            )
        assert r.status_code == 403

    def test_sem_admin_key_configurada_passa(self, anon_client: TestClient):
        """Sem ADMIN_API_KEY, qualquer chave (ou nenhuma) passa."""
        with patch.object(settings, "admin_api_key", ""):
            r = anon_client.get("/scheduler/status")
        # Sem scheduler → 200 com running=False
        assert r.status_code == 200


# ── /scheduler/status ─────────────────────────────────────────────────────────

class TestSchedulerStatus:
    def test_sem_scheduler_retorna_running_false(self, anon_client: TestClient):
        """Sem scheduler no app.state, retorna running=False e jobs=[]."""
        if hasattr(app.state, "scheduler"):
            del app.state.scheduler

        with patch.object(settings, "admin_api_key", ""):
            r = anon_client.get("/scheduler/status")

        assert r.status_code == 200
        data = r.json()
        assert data["running"] is False
        assert data["jobs"] == []

    def test_scheduler_parado_retorna_running_false(self, anon_client: TestClient):
        """Scheduler configurado mas não rodando (running=False) → running=False."""
        mock_scheduler = MagicMock()
        mock_scheduler.running = False

        app.state.scheduler = mock_scheduler
        try:
            with patch.object(settings, "admin_api_key", ""):
                r = anon_client.get("/scheduler/status")
            assert r.status_code == 200
            assert r.json()["running"] is False
        finally:
            del app.state.scheduler

    def test_scheduler_rodando_retorna_jobs(self, anon_client: TestClient):
        """Scheduler rodando com jobs → retorna running=True e lista de jobs."""
        job_com_next = MagicMock()
        job_com_next.id = "alert_breakfast"
        job_com_next.name = "Alerta Café da Manhã"
        job_com_next.next_run_time = datetime(2026, 9, 10, 8, 0, tzinfo=timezone.utc)

        job_sem_next = MagicMock()
        job_sem_next.id = "report_weekly"
        job_sem_next.name = "Relatório Semanal"
        job_sem_next.next_run_time = None

        mock_scheduler = MagicMock()
        mock_scheduler.running = True
        mock_scheduler.get_jobs.return_value = [job_com_next, job_sem_next]

        app.state.scheduler = mock_scheduler
        try:
            with patch.object(settings, "admin_api_key", ""):
                r = anon_client.get("/scheduler/status")
            assert r.status_code == 200
            data = r.json()
            assert data["running"] is True
            assert len(data["jobs"]) == 2
            # Job com next_run_time deve ter campo in_minutes
            job_info = next(j for j in data["jobs"] if j["id"] == "alert_breakfast")
            assert "next_run_brt" in job_info
            # Job sem next_run deve ter next_run_brt=None
            job_none = next(j for j in data["jobs"] if j["id"] == "report_weekly")
            assert job_none["next_run_brt"] is None
        finally:
            del app.state.scheduler


# ── /scheduler/trigger/{job_id} ───────────────────────────────────────────────

class TestSchedulerTrigger:
    def test_sem_scheduler_retorna_503(self, anon_client: TestClient):
        """Sem scheduler rodando → 503."""
        if hasattr(app.state, "scheduler"):
            del app.state.scheduler

        with patch.object(settings, "admin_api_key", ""):
            r = anon_client.post("/scheduler/trigger/alert_breakfast")
        assert r.status_code == 503

    def test_scheduler_parado_retorna_503(self, anon_client: TestClient):
        """Scheduler configurado mas parado → 503."""
        mock_scheduler = MagicMock()
        mock_scheduler.running = False

        app.state.scheduler = mock_scheduler
        try:
            with patch.object(settings, "admin_api_key", ""):
                r = anon_client.post("/scheduler/trigger/alert_breakfast")
            assert r.status_code == 503
        finally:
            del app.state.scheduler

    def test_job_nao_encontrado_retorna_404(self, anon_client: TestClient):
        """Job ID inválido → 404 com lista de IDs válidos."""
        mock_scheduler = MagicMock()
        mock_scheduler.running = True
        mock_scheduler.get_job.return_value = None
        mock_scheduler.get_jobs.return_value = []

        app.state.scheduler = mock_scheduler
        try:
            with patch.object(settings, "admin_api_key", ""):
                r = anon_client.post("/scheduler/trigger/job_inexistente")
            assert r.status_code == 404
            assert "não encontrado" in r.json()["detail"].lower()
        finally:
            del app.state.scheduler

    def test_trigger_job_valido_retorna_200(self, anon_client: TestClient):
        """Job ID válido → 200 com triggered e status='queued'."""
        mock_job = MagicMock()
        mock_job.id = "alert_breakfast"
        mock_job.modify = MagicMock()

        mock_scheduler = MagicMock()
        mock_scheduler.running = True
        mock_scheduler.get_job.return_value = mock_job

        app.state.scheduler = mock_scheduler
        try:
            with patch.object(settings, "admin_api_key", ""):
                r = anon_client.post("/scheduler/trigger/alert_breakfast")
            assert r.status_code == 200
            data = r.json()
            assert data["triggered"] == "alert_breakfast"
            assert data["status"] == "queued"
            mock_job.modify.assert_called_once()
        finally:
            del app.state.scheduler
