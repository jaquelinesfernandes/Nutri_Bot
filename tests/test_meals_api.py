"""
Testes de integração para os endpoints REST de refeições:
  POST /api/meals  — criação manual via painel web
  DELETE /api/meals/{id} — remoção de refeição

Usa FastAPI TestClient com dependências mockadas:
  - get_current_user   → usuário fake sem banco
  - get_db             → AsyncMock (sem DB real)
  - ai_service         → mock do Claude
  - nutrition_service  → mock de enriquecimento TACO/USDA
  - encrypt            → mock da criptografia Fernet
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.utils.jwt import get_current_user
from app.db.session import get_db


# ── Helpers ───────────────────────────────────────────────────────────────────

BRT = ZoneInfo("America/Sao_Paulo")
TODAY = date(2026, 8, 22)  # data fixa para testes determinísticos


def _make_user(plan: str = "free") -> MagicMock:
    u = MagicMock()
    u.id = uuid.uuid4()
    u.plan = plan
    u.is_premium = plan != "free"
    u.timezone = "America/Sao_Paulo"
    u.daily_calorie_goal = 2000
    return u


def _make_db() -> AsyncMock:
    db = AsyncMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.add = MagicMock()
    db.delete = AsyncMock()
    return db


def _make_extraction(
    foods: list[dict] | None = None,
    meal_type: str = "lunch",
) -> MagicMock:
    ext = MagicMock()
    ext.meal_type = meal_type
    ext.foods = []
    if foods:
        for f in foods:
            food = MagicMock()
            food.name = f.get("name", "Arroz")
            food.quantity_g = f.get("quantity_g", 100.0)
            food.est_calories_kcal = f.get("kcal", 130.0)
            food.est_protein_g = f.get("prot", 2.5)
            food.est_carb_g = f.get("carb", 28.0)
            food.est_fat_g = f.get("fat", 0.3)
            ext.foods.append(food)
    return ext


def _make_enriched(name: str = "Arroz branco cozido") -> MagicMock:
    e = MagicMock()
    e.name = name
    e.original_term = name
    e.quantity_g = 100.0
    e.calories_kcal = 128.0
    e.protein_g = 2.5
    e.carb_g = 28.1
    e.fat_g = 0.2
    e.fiber_g = 0.8
    e.source = "taco"
    e.confidence_score = 0.95
    e.taco_code = "1"
    return e


def _make_meal_log_db(meal_id: uuid.UUID, user_id: uuid.UUID) -> MagicMock:
    """Simula um MealLog retornado pelo SELECT após criação."""
    log = MagicMock()
    log.id = meal_id
    log.user_id = user_id
    log.meal_type = "lunch"
    log.logged_at = datetime(2026, 8, 22, 12, 0, tzinfo=BRT)
    log.total_calories_kcal = 128.0
    log.total_protein_g = 2.5
    log.total_carb_g = 28.1
    log.total_fat_g = 0.2
    food = MagicMock()
    food.name = "Arroz branco cozido"
    food.quantity_g = 100.0
    food.calories_kcal = 128.0
    food.protein_g = 2.5
    food.carb_g = 28.1
    food.fat_g = 0.2
    food.source = "taco"
    food.confidence_score = 0.95
    log.food_items = [food]
    return log


# ── Fixture: client com overrides ─────────────────────────────────────────────

@pytest.fixture
def free_user() -> MagicMock:
    return _make_user(plan="free")


@pytest.fixture
def premium_user() -> MagicMock:
    return _make_user(plan="premium")


@pytest.fixture
def db_mock() -> AsyncMock:
    return _make_db()


def _client_for(user: MagicMock, db: AsyncMock) -> TestClient:
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app, raise_server_exceptions=False)


# ── POST /api/meals ───────────────────────────────────────────────────────────

class TestCreateMeal:
    """POST /api/meals — criação manual de refeição."""

    def _post(self, client, payload):
        return client.post("/api/meals", json=payload)

    @patch("app.routers.meals.datetime")
    @patch("app.utils.crypto.encrypt", return_value=b"encrypted")
    @patch("app.services.nutrition.nutrition_service")
    @patch("app.services.ai_service.ai_service")
    def test_cria_refeicao_hoje_usuario_free(
        self, mock_ai, mock_nutrition, mock_encrypt, mock_dt,
        free_user, db_mock
    ):
        """Criação para data de hoje funciona para usuário free."""
        meal_id = uuid.uuid4()

        # Fixa "hoje" para o router
        mock_dt.now.return_value = datetime(2026, 8, 22, 10, 0, tzinfo=BRT)
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

        mock_ai.extract_foods_from_text = AsyncMock(
            return_value=_make_extraction(
                foods=[{"name": "Arroz", "quantity_g": 100, "kcal": 130}]
            )
        )
        mock_nutrition.enrich_foods.return_value = [_make_enriched()]

        # SELECT após flush retorna o meal_log criado
        result_mock = MagicMock()
        result_mock.scalar_one.return_value = _make_meal_log_db(meal_id, free_user.id)
        db_mock.execute = AsyncMock(return_value=result_mock)

        with _client_for(free_user, db_mock) as client:
            r = self._post(client, {
                "logged_date": "2026-08-22",
                "meal_type": "lunch",
                "description": "arroz branco 100g",
            })

        assert r.status_code == 201
        data = r.json()
        assert data["meal_type"] == "lunch"
        assert data["total_calories_kcal"] == pytest.approx(128.0, abs=1)

    @patch("app.routers.meals.datetime")
    @patch("app.utils.crypto.encrypt", return_value=b"encrypted")
    @patch("app.services.nutrition.nutrition_service")
    @patch("app.services.ai_service.ai_service")
    def test_cria_refeicao_retroativa_dentro_limite_free(
        self, mock_ai, mock_nutrition, mock_encrypt, mock_dt,
        free_user, db_mock
    ):
        """Retroativo 5 dias atrás aceito para free (limite 7)."""
        meal_id = uuid.uuid4()
        mock_dt.now.return_value = datetime(2026, 8, 22, 10, 0, tzinfo=BRT)
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

        mock_ai.extract_foods_from_text = AsyncMock(
            return_value=_make_extraction(
                foods=[{"name": "Feijão", "quantity_g": 80, "kcal": 86}]
            )
        )
        mock_nutrition.enrich_foods.return_value = [_make_enriched("Feijão carioca cozido")]

        result_mock = MagicMock()
        result_mock.scalar_one.return_value = _make_meal_log_db(meal_id, free_user.id)
        db_mock.execute = AsyncMock(return_value=result_mock)

        with _client_for(free_user, db_mock) as client:
            r = self._post(client, {
                "logged_date": "2026-08-17",  # 5 dias atrás
                "meal_type": "lunch",
                "description": "feijão 80g",
            })

        assert r.status_code == 201

    @patch("app.routers.meals.datetime")
    def test_rejeita_retroativo_alem_limite_free(self, mock_dt, free_user, db_mock):
        """Free user não pode registrar >7 dias atrás."""
        mock_dt.now.return_value = datetime(2026, 8, 22, 10, 0, tzinfo=BRT)
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

        with _client_for(free_user, db_mock) as client:
            r = self._post(client, {
                "logged_date": "2026-08-10",  # 12 dias atrás
                "meal_type": "lunch",
                "description": "arroz e feijão",
            })

        assert r.status_code == 422
        assert "gratuito" in r.json()["detail"].lower()

    @patch("app.routers.meals.datetime")
    @patch("app.utils.crypto.encrypt", return_value=b"encrypted")
    @patch("app.services.nutrition.nutrition_service")
    @patch("app.services.ai_service.ai_service")
    def test_premium_aceita_retroativo_25_dias(
        self, mock_ai, mock_nutrition, mock_encrypt, mock_dt,
        premium_user, db_mock
    ):
        """Premium pode registrar até 30 dias atrás."""
        meal_id = uuid.uuid4()
        mock_dt.now.return_value = datetime(2026, 8, 22, 10, 0, tzinfo=BRT)
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

        mock_ai.extract_foods_from_text = AsyncMock(
            return_value=_make_extraction(
                foods=[{"name": "Frango", "quantity_g": 150, "kcal": 220}]
            )
        )
        mock_nutrition.enrich_foods.return_value = [_make_enriched("Frango grelhado")]

        result_mock = MagicMock()
        result_mock.scalar_one.return_value = _make_meal_log_db(meal_id, premium_user.id)
        db_mock.execute = AsyncMock(return_value=result_mock)

        with _client_for(premium_user, db_mock) as client:
            r = self._post(client, {
                "logged_date": "2026-07-28",  # 25 dias atrás
                "meal_type": "dinner",
                "description": "frango grelhado 150g",
            })

        assert r.status_code == 201

    @patch("app.routers.meals.datetime")
    def test_rejeita_data_futura(self, mock_dt, free_user, db_mock):
        """Não permite registrar refeição para data futura."""
        mock_dt.now.return_value = datetime(2026, 8, 22, 10, 0, tzinfo=BRT)
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

        with _client_for(free_user, db_mock) as client:
            r = self._post(client, {
                "logged_date": "2026-08-25",
                "meal_type": "lunch",
                "description": "almoço de amanhã",
            })

        assert r.status_code == 422
        assert "futura" in r.json()["detail"].lower()

    @patch("app.routers.meals.datetime")
    def test_rejeita_data_invalida(self, mock_dt, free_user, db_mock):
        """Data malformada retorna 422."""
        mock_dt.now.return_value = datetime(2026, 8, 22, 10, 0, tzinfo=BRT)
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

        with _client_for(free_user, db_mock) as client:
            r = self._post(client, {
                "logged_date": "22/08/2026",   # formato errado
                "meal_type": "lunch",
                "description": "arroz e feijão",
            })

        assert r.status_code == 422

    @patch("app.routers.meals.datetime")
    @patch("app.services.ai_service.ai_service")
    def test_ia_nao_identifica_alimento(self, mock_ai, mock_dt, free_user, db_mock):
        """Se IA não extrair nenhum alimento, retorna 422 com mensagem clara."""
        mock_dt.now.return_value = datetime(2026, 8, 22, 10, 0, tzinfo=BRT)
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

        mock_ai.extract_foods_from_text = AsyncMock(
            return_value=_make_extraction(foods=[])  # nenhum alimento
        )

        with _client_for(free_user, db_mock) as client:
            r = self._post(client, {
                "logged_date": "2026-08-22",
                "meal_type": "lunch",
                "description": "xyz abc",
            })

        assert r.status_code == 422
        assert "alimento" in r.json()["detail"].lower()

    @patch("app.routers.meals.datetime")
    @patch("app.services.ai_service.ai_service")
    def test_ia_indisponivel_retorna_503(self, mock_ai, mock_dt, free_user, db_mock):
        """Se a IA lançar exceção, retorna 503."""
        mock_dt.now.return_value = datetime(2026, 8, 22, 10, 0, tzinfo=BRT)
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

        mock_ai.extract_foods_from_text = AsyncMock(
            side_effect=RuntimeError("API timeout")
        )

        with _client_for(free_user, db_mock) as client:
            r = self._post(client, {
                "logged_date": "2026-08-22",
                "meal_type": "lunch",
                "description": "arroz e feijão",
            })

        assert r.status_code == 503

    @patch("app.routers.meals.datetime")
    @patch("app.utils.crypto.encrypt", return_value=b"encrypted")
    @patch("app.services.nutrition.nutrition_service")
    @patch("app.services.ai_service.ai_service")
    def test_meal_type_explicito_prevalece_sobre_ia(
        self, mock_ai, mock_nutrition, mock_encrypt, mock_dt,
        free_user, db_mock
    ):
        """O meal_type explícito do usuário prevalece sobre o sugerido pela IA."""
        meal_id = uuid.uuid4()
        mock_dt.now.return_value = datetime(2026, 8, 22, 10, 0, tzinfo=BRT)
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

        # IA sugere "lunch", mas usuário enviou "breakfast"
        mock_ai.extract_foods_from_text = AsyncMock(
            return_value=_make_extraction(
                foods=[{"name": "Pão", "quantity_g": 50, "kcal": 130}],
                meal_type="lunch",
            )
        )
        mock_nutrition.enrich_foods.return_value = [_make_enriched("Pão francês")]

        # Retorna log com meal_type breakfast
        log = _make_meal_log_db(meal_id, free_user.id)
        log.meal_type = "breakfast"
        result_mock = MagicMock()
        result_mock.scalar_one.return_value = log
        db_mock.execute = AsyncMock(return_value=result_mock)

        with _client_for(free_user, db_mock) as client:
            r = self._post(client, {
                "logged_date": "2026-08-22",
                "meal_type": "breakfast",   # explícito
                "description": "pão 50g",
            })

        assert r.status_code == 201
        assert r.json()["meal_type"] == "breakfast"

    @patch("app.routers.meals.datetime")
    def test_rejeita_descricao_muito_curta(self, mock_dt, free_user, db_mock):
        """Descrição < 3 caracteres falha validação Pydantic (422)."""
        mock_dt.now.return_value = datetime(2026, 8, 22, 10, 0, tzinfo=BRT)
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

        with _client_for(free_user, db_mock) as client:
            r = self._post(client, {
                "logged_date": "2026-08-22",
                "meal_type": "lunch",
                "description": "ok",   # apenas 2 chars
            })

        assert r.status_code == 422

    def test_requer_autenticacao(self):
        """Sem cookie JWT → 401 ou 403 (dependência get_current_user não sobreposta)."""
        app.dependency_overrides.clear()
        with TestClient(app, raise_server_exceptions=False) as client:
            r = client.post("/api/meals", json={
                "logged_date": "2026-08-22",
                "meal_type": "lunch",
                "description": "arroz e feijão",
            })
        assert r.status_code in (401, 403)


# ── DELETE /api/meals/{id} ────────────────────────────────────────────────────

class TestDeleteMeal:
    """DELETE /api/meals/{id} — remoção de refeição."""

    def _delete(self, client, meal_id):
        return client.delete(f"/api/meals/{meal_id}")

    def test_deleta_refeicao_propria(self, free_user, db_mock):
        """Owner consegue deletar sua refeição — retorna 204."""
        meal_id = uuid.uuid4()
        meal = MagicMock()
        meal.id = meal_id
        meal.user_id = free_user.id

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = meal
        db_mock.execute = AsyncMock(return_value=result_mock)

        with _client_for(free_user, db_mock) as client:
            r = self._delete(client, meal_id)

        assert r.status_code == 204
        db_mock.delete.assert_called_once_with(meal)
        db_mock.commit.assert_called_once()

    def test_retorna_404_refeicao_nao_encontrada(self, free_user, db_mock):
        """ID inexistente ou de outro usuário → 404."""
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        db_mock.execute = AsyncMock(return_value=result_mock)

        with _client_for(free_user, db_mock) as client:
            r = self._delete(client, uuid.uuid4())

        assert r.status_code == 404
        assert "não encontrada" in r.json()["detail"].lower()

    def test_retorna_422_id_invalido(self, free_user, db_mock):
        """ID não-UUID retorna 422 (validação FastAPI)."""
        with _client_for(free_user, db_mock) as client:
            r = self._delete(client, "nao-e-uuid")

        assert r.status_code == 422

    def test_requer_autenticacao(self):
        """Sem JWT → 401/403."""
        app.dependency_overrides.clear()
        with TestClient(app, raise_server_exceptions=False) as client:
            r = client.delete(f"/api/meals/{uuid.uuid4()}")
        assert r.status_code in (401, 403)

    def test_nao_deleta_refeicao_de_outro_usuario(self, free_user, db_mock):
        """SELECT filtra por user_id: outro user_id → retorna None → 404."""
        # O SELECT inclui MealLog.user_id == current_user.id,
        # então se a refeição for de outro usuário, scalar_one_or_none() = None
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        db_mock.execute = AsyncMock(return_value=result_mock)

        with _client_for(free_user, db_mock) as client:
            r = self._delete(client, uuid.uuid4())

        assert r.status_code == 404
        db_mock.delete.assert_not_called()


# ── Schema validation (MealLogCreate) ────────────────────────────────────────

class TestMealLogCreateSchema:
    """Validação de schema diretamente, sem HTTP."""

    def test_schema_valido(self):
        from app.schemas.meal import MealLogCreate
        m = MealLogCreate(logged_date="2026-08-22", description="arroz e feijão")
        assert m.meal_type == "other"
        assert m.logged_date == "2026-08-22"

    def test_descricao_minima_3_chars(self):
        from app.schemas.meal import MealLogCreate
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            MealLogCreate(logged_date="2026-08-22", description="ab")

    def test_descricao_maxima_500_chars(self):
        from app.schemas.meal import MealLogCreate
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            MealLogCreate(logged_date="2026-08-22", description="x" * 501)

    def test_meal_type_default_other(self):
        from app.schemas.meal import MealLogCreate
        m = MealLogCreate(logged_date="2026-08-22", description="maçã")
        assert m.meal_type == "other"
