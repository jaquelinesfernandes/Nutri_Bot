import json
from pathlib import Path

import pytest

from app.services.nutrition import NutritionService, _normalize

FIXTURES_DIR = Path(__file__).parent / "fixtures"


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
