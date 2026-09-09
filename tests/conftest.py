import json
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.db.session import get_db
from app.main import app
from app.services.nutrition import NutritionService, _normalize
from app.utils.jwt import (
    create_access_token,
    get_current_user,
    get_current_user_optional,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"

# ── Nutrition fixtures (existentes) ───────────────────────────────────────────

@pytest.fixture(scope="session")
def nutrition_svc() -> NutritionService:
    """NutritionService carregado com dados de fixture (taco_sample.json)."""
    svc = NutritionService()
    taco = json.loads((FIXTURES_DIR / "taco_sample.json").read_text(encoding="utf-8"))
    svc._taco = taco
    svc._usda = []
    svc._taco_normalized = [_normalize(item["name"]) for item in taco]
    svc._usda_normalized = []
    svc._cache = svc._build_cache()
    svc._loaded = True
    return svc


@pytest.fixture
def golden_meals() -> list[dict]:
    return json.loads((FIXTURES_DIR / "golden_meals.json").read_text(encoding="utf-8"))


# ── Helpers para mocks ────────────────────────────────────────────────────────

def _make_mock_db() -> AsyncMock:
    """AsyncMock de AsyncSession — retorna listas vazias para qualquer query."""
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_result.scalars.return_value.unique.return_value.all.return_value = []
    mock_result.scalar_one_or_none.return_value = None
    mock_result.rowcount = 0

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.commit = AsyncMock()
    mock_db.flush = AsyncMock()
    mock_db.rollback = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.refresh = AsyncMock()
    return mock_db


def _make_mock_user(email: str = "ana@nutribot.test", plan: str = "free") -> MagicMock:
    """Usuário mock com campos suficientes para renderizar todos os templates."""
    u = MagicMock()
    u.id = uuid.uuid4()
    u.email = email
    u.first_name = "Ana Teste"
    u.channel_type = "web"
    u.channel_id = f"web:{email}"
    u.is_premium = plan != "free"
    u.plan = plan
    u.deleted_at = None
    u.daily_calorie_goal = 2000
    u.timezone = "America/Sao_Paulo"
    u.onboarding_complete = True
    u.premium_until = None
    u.report_frequency = "weekly"
    u.goal_type = "manter"
    u.conversation_state = "IDLE"
    u.web_link_token = None
    u.alerts_enabled = True
    u.channel_id = "web:ana@nutribot.test"
    return u


# ── TestClients ────────────────────────────────────────────────────────────────

@pytest.fixture
def auth_client() -> TestClient:
    """TestClient com JWT válido no cookie + DB e usuário mockados (fixture síncrona).

    Cobre rotas protegidas: /dashboard, /historico, /relatorios, /configuracoes, etc.
    """
    mock_db = _make_mock_db()
    mock_user = _make_mock_user()

    async def _override_db():
        yield mock_db

    async def _override_user():
        return mock_user

    async def _override_user_optional():
        return mock_user

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = _override_user
    app.dependency_overrides[get_current_user_optional] = _override_user_optional

    token = create_access_token(mock_user.id)
    with TestClient(app, raise_server_exceptions=False) as client:
        client.cookies.set("access_token", token)
        yield client

    app.dependency_overrides.clear()


@pytest.fixture
def anon_client() -> TestClient:
    """TestClient sem autenticação + DB mockado — para rotas públicas e redirects."""
    mock_db = _make_mock_db()

    async def _override_db():
        yield mock_db

    app.dependency_overrides[get_db] = _override_db

    with TestClient(app, raise_server_exceptions=False) as client:
        yield client

    app.dependency_overrides.clear()
