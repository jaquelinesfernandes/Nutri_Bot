"""
Testes dos endpoints REST /api/meals.

Cobre:
  - GET  /api/meals/today        — retorna balanço do dia
  - GET  /api/meals?date=...     — por data, com fallback em data inválida
  - GET  /api/meals/week         — 7 dias
  - POST /api/meals              — criação manual (IA + nutrição mockados)
  - POST /api/meals (validações) — data futura, data inválida, IA indisponível, sem alimentos
  - DELETE /api/meals/{id}       — 404 quando não encontrado
  - Sem autenticação             — 401 / redirect
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.db.session import get_db
from app.main import app
from app.utils.jwt import create_access_token, get_current_user, get_current_user_optional


# ── fixtures ──────────────────────────────────────────────────────────────────

def _mock_user(plan: str = "free") -> MagicMock:
    u = MagicMock()
    u.id = uuid.uuid4()
    u.plan = plan
    u.is_premium = plan != "free"
    u.deleted_at = None
    u.daily_calorie_goal = 2000
    u.timezone = "America/Sao_Paulo"
    u.channel_type = "telegram"
    u.channel_id = "tg:999"
    u.first_name = "Teste"
    return u


def _mock_db() -> AsyncMock:
    r = MagicMock()
    r.scalars.return_value.all.return_value = []
    r.scalar_one_or_none.return_value = None
    r.scalar_one.return_value = 0
    r.scalars.return_value.unique.return_value.all.return_value = []
    db = AsyncMock()
    db.execute = AsyncMock(return_value=r)
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()
    db.delete = AsyncMock()
    return db


@pytest.fixture
def auth_client():
    mock_db = _mock_db()
    mock_user = _mock_user()

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
def anon_client():
    mock_db = _mock_db()

    async def _override_db():
        yield mock_db

    app.dependency_overrides[get_db] = _override_db

    with TestClient(app, raise_server_exceptions=False) as client:
        yield client

    app.dependency_overrides.clear()


# ── GET /api/meals/today ───────────────────────────────────────────────────────

class TestGetToday:

    def test_retorna_200_com_autenticacao(self, auth_client):
        r = auth_client.get("/api/meals/today")
        assert r.status_code == 200

    def test_estrutura_de_resposta(self, auth_client):
        r = auth_client.get("/api/meals/today")
        data = r.json()
        assert "date" in data
        assert "total_calories_kcal" in data
        assert "meals" in data
        assert isinstance(data["meals"], list)

    def test_meals_vazio_sem_registros(self, auth_client):
        r = auth_client.get("/api/meals/today")
        assert r.json()["meals"] == []

    def test_sem_autenticacao_retorna_401(self, anon_client):
        r = anon_client.get("/api/meals/today")
        assert r.status_code in (401, 403)


# ── GET /api/meals?date=... ────────────────────────────────────────────────────

class TestGetByDate:

    def test_data_valida_retorna_200(self, auth_client):
        r = auth_client.get("/api/meals?date=2026-01-15")
        assert r.status_code == 200

    def test_data_no_body_retorna_200(self, auth_client):
        r = auth_client.get("/api/meals")
        assert r.status_code == 200

    def test_data_invalida_usa_hoje(self, auth_client):
        """Data inválida não deve retornar 422 — o endpoint usa hoje como fallback."""
        r = auth_client.get("/api/meals?date=nao-e-uma-data")
        assert r.status_code == 200

    def test_data_no_passado_retorna_200(self, auth_client):
        r = auth_client.get("/api/meals?date=2020-06-01")
        assert r.status_code == 200

    def test_sem_autenticacao_retorna_401(self, anon_client):
        r = anon_client.get("/api/meals?date=2026-01-15")
        assert r.status_code in (401, 403)


# ── GET /api/meals/week ────────────────────────────────────────────────────────

class TestGetWeek:

    def test_retorna_200(self, auth_client):
        r = auth_client.get("/api/meals/week")
        assert r.status_code == 200

    def test_retorna_lista_de_7_itens(self, auth_client):
        r = auth_client.get("/api/meals/week")
        data = r.json()
        assert isinstance(data, list)
        assert len(data) == 7

    def test_cada_item_tem_estrutura_correta(self, auth_client):
        r = auth_client.get("/api/meals/week")
        for item in r.json():
            assert "date" in item
            assert "total_calories_kcal" in item
            assert "meals" in item

    def test_datas_em_ordem_crescente(self, auth_client):
        r = auth_client.get("/api/meals/week")
        dates = [item["date"] for item in r.json()]
        assert dates == sorted(dates)

    def test_sem_autenticacao_retorna_401(self, anon_client):
        r = anon_client.get("/api/meals/week")
        assert r.status_code in (401, 403)


# ── POST /api/meals — validações ──────────────────────────────────────────────

class TestCreateMealValidation:

    def test_data_futura_retorna_422(self, auth_client):
        tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")
        r = auth_client.post("/api/meals", json={
            "meal_type": "lunch",
            "logged_date": tomorrow,
            "description": "arroz e feijão",
        })
        assert r.status_code == 422

    def test_data_invalida_retorna_422(self, auth_client):
        r = auth_client.post("/api/meals", json={
            "meal_type": "lunch",
            "logged_date": "not-a-date",
            "description": "arroz",
        })
        assert r.status_code == 422

    def test_descricao_muito_curta_retorna_422(self, auth_client):
        r = auth_client.post("/api/meals", json={
            "meal_type": "lunch",
            "logged_date": "2026-01-15",
            "description": "ab",
        })
        assert r.status_code == 422

    def test_ia_indisponivel_retorna_503(self, auth_client):
        with patch("app.services.ai_service.ai_service") as mock_ai:
            mock_ai.extract_foods_from_text = AsyncMock(side_effect=Exception("AI down"))
            r = auth_client.post("/api/meals", json={
                "meal_type": "lunch",
                "logged_date": "2026-01-15",
                "description": "arroz com frango",
            })
        assert r.status_code == 503

    def test_sem_alimentos_identificados_retorna_422(self, auth_client):
        from app.schemas.ai_response import FoodExtractionResponse
        empty_extraction = FoodExtractionResponse(foods=[], meal_type="other")
        with patch("app.services.ai_service.ai_service") as mock_ai:
            mock_ai.extract_foods_from_text = AsyncMock(return_value=empty_extraction)
            r = auth_client.post("/api/meals", json={
                "meal_type": "lunch",
                "logged_date": "2026-01-15",
                "description": "xyzxyz totalmente desconhecido",
            })
        assert r.status_code == 422

    def test_sem_autenticacao_retorna_401(self, anon_client):
        r = anon_client.post("/api/meals", json={
            "meal_type": "lunch",
            "logged_date": "2026-01-15",
            "description": "arroz",
        })
        assert r.status_code in (401, 403)


# ── POST /api/meals — sucesso 201 ─────────────────────────────────────────────

class TestCreateMealSuccess:

    @pytest.fixture
    def client_with_post_mocks(self):
        """auth_client com mock da IA + nutrição + DB configurado para retornar o MealLog criado."""
        from app.schemas.ai_response import ExtractedFoodItem, FoodExtractionResponse
        from app.services.nutrition import EnrichedFood

        fake_food = ExtractedFoodItem(name="arroz", quantity_g=180)
        fake_extraction = FoodExtractionResponse(foods=[fake_food], meal_type="lunch")
        fake_enriched = [EnrichedFood(
            name="Arroz, branco, cozido",
            original_term="arroz",
            quantity_g=180,
            calories_kcal=230.4,
            protein_g=4.5,
            carb_g=50.6,
            fat_g=0.4,
            fiber_g=2.9,
            source="taco_cache",
            confidence_score=0.95,
            taco_code="001",
        )]

        # MealLog mock com food_items
        mock_food_item = MagicMock()
        mock_food_item.name = "Arroz, branco, cozido"
        mock_food_item.quantity_g = 180.0
        mock_food_item.calories_kcal = 230.4
        mock_food_item.protein_g = 4.5
        mock_food_item.carb_g = 50.6
        mock_food_item.fat_g = 0.4
        mock_food_item.fiber_g = 2.9
        mock_food_item.source = "taco_cache"
        mock_food_item.confidence_score = 0.95

        mock_meal = MagicMock()
        mock_meal.id = uuid.uuid4()
        mock_meal.meal_type = "lunch"
        mock_meal.logged_at = datetime.now(timezone.utc)
        mock_meal.total_calories_kcal = 230.4
        mock_meal.total_protein_g = 4.5
        mock_meal.total_carb_g = 50.6
        mock_meal.total_fat_g = 0.4
        mock_meal.total_fiber_g = 2.9
        mock_meal.food_items = [mock_food_item]

        result_with_meal = MagicMock()
        result_with_meal.scalar_one.return_value = mock_meal

        result_empty = MagicMock()
        result_empty.scalars.return_value.all.return_value = []

        db = AsyncMock()
        db.execute = AsyncMock(return_value=result_with_meal)
        db.commit = AsyncMock()
        db.flush = AsyncMock()
        db.add = MagicMock()

        mock_user = _mock_user()

        async def _override_db():
            yield db

        async def _override_user():
            return mock_user

        async def _override_user_optional():
            return mock_user

        app.dependency_overrides[get_db] = _override_db
        app.dependency_overrides[get_current_user] = _override_user
        app.dependency_overrides[get_current_user_optional] = _override_user_optional

        with patch("app.services.ai_service.ai_service") as mock_ai, \
             patch("app.services.nutrition.nutrition_service") as mock_nutrition:
            mock_ai.extract_foods_from_text = AsyncMock(return_value=fake_extraction)
            mock_nutrition.enrich_foods.return_value = fake_enriched

            token = create_access_token(mock_user.id)
            with TestClient(app, raise_server_exceptions=False) as client:
                client.cookies.set("access_token", token)
                yield client

        app.dependency_overrides.clear()

    def test_retorna_201(self, client_with_post_mocks):
        r = client_with_post_mocks.post("/api/meals", json={
            "meal_type": "lunch",
            "logged_date": "2026-01-15",
            "description": "arroz branco cozido",
        })
        assert r.status_code == 201

    def test_resposta_tem_id_e_meal_type(self, client_with_post_mocks):
        r = client_with_post_mocks.post("/api/meals", json={
            "meal_type": "lunch",
            "logged_date": "2026-01-15",
            "description": "arroz branco cozido",
        })
        data = r.json()
        assert "id" in data
        assert data["meal_type"] == "lunch"

    def test_resposta_tem_calorias(self, client_with_post_mocks):
        r = client_with_post_mocks.post("/api/meals", json={
            "meal_type": "lunch",
            "logged_date": "2026-01-15",
            "description": "arroz branco cozido",
        })
        data = r.json()
        assert data["total_calories_kcal"] > 0


# ── DELETE /api/meals/{id} ─────────────────────────────────────────────────────

class TestDeleteMeal:

    def test_id_inexistente_retorna_404(self, auth_client):
        r = auth_client.delete(f"/api/meals/{uuid.uuid4()}")
        assert r.status_code == 404

    def test_sem_autenticacao_retorna_401(self, anon_client):
        r = anon_client.delete(f"/api/meals/{uuid.uuid4()}")
        assert r.status_code in (401, 403)

    def test_uuid_invalido_retorna_422(self, auth_client):
        r = auth_client.delete("/api/meals/nao-e-um-uuid")
        assert r.status_code == 422

    def test_delete_sucesso_retorna_204(self):
        """DELETE encontra a refeição no DB e a apaga — deve retornar 204."""
        mock_meal = MagicMock()
        mock_meal.id = uuid.uuid4()

        result_with_meal = MagicMock()
        result_with_meal.scalar_one_or_none.return_value = mock_meal

        db = AsyncMock()
        db.execute = AsyncMock(return_value=result_with_meal)
        db.commit = AsyncMock()
        db.delete = AsyncMock()

        mock_user = _mock_user()

        async def _override_db():
            yield db

        async def _override_user():
            return mock_user

        async def _override_user_optional():
            return mock_user

        app.dependency_overrides[get_db] = _override_db
        app.dependency_overrides[get_current_user] = _override_user
        app.dependency_overrides[get_current_user_optional] = _override_user_optional

        try:
            token = create_access_token(mock_user.id)
            with TestClient(app, raise_server_exceptions=False) as client:
                client.cookies.set("access_token", token)
                r = client.delete(f"/api/meals/{mock_meal.id}")
            assert r.status_code == 204
            db.delete.assert_called_once_with(mock_meal)
            db.commit.assert_called_once()
        finally:
            app.dependency_overrides.clear()
