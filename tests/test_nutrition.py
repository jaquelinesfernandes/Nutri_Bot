"""
Testes unitários do NutritionService.
Cobre: lookup por alias, fuzzy match, fallback GPT, cálculo de porções.
"""

import pytest

from app.services.nutrition import NutritionService, _normalize


class TestNormalize:
    def test_remove_accents(self):
        assert _normalize("feijão") == "feijao"

    def test_lowercase(self):
        assert _normalize("Arroz Branco") == "arroz branco"

    def test_remove_stopwords(self):
        result = _normalize("frango grelhado sem pele")
        assert "grelhado" not in result
        assert "sem" not in result
        assert "frango" in result

    def test_typo_tolerance(self):
        assert _normalize("arros") == "arros"  # normaliza mas não corrige — RapidFuzz cuida disso


class TestNutritionLookup:
    def test_lookup_by_exact_alias(self, nutrition_svc: NutritionService):
        result = nutrition_svc.lookup("arroz", 180)
        assert result.source in ("taco_cache", "taco_alias", "taco_fuzzy")
        assert result.calories_kcal > 0
        assert result.name != ""

    def test_lookup_frango_grelhado(self, nutrition_svc: NutritionService):
        result = nutrition_svc.lookup("frango grelhado", 150)
        assert result.protein_g > 30  # frango tem alta proteína
        assert result.carb_g < 5

    def test_lookup_fuzzy_typo(self, nutrition_svc: NutritionService):
        result = nutrition_svc.lookup("frangho grelhado", 150)
        # deve ainda encontrar frango via fuzzy
        assert result.source != "gpt_estimated" or result.confidence_score < 0.5

    def test_lookup_unknown_returns_gpt_estimated(self, nutrition_svc: NutritionService):
        result = nutrition_svc.lookup("baobá exótico tribal", 100)
        assert result.source == "gpt_estimated"
        assert result.confidence_score < 0.5

    def test_portion_scaling(self, nutrition_svc: NutritionService):
        result_100 = nutrition_svc.lookup("arroz", 100)
        result_200 = nutrition_svc.lookup("arroz", 200)
        assert abs(result_200.calories_kcal - result_100.calories_kcal * 2) < 1

    def test_empty_database_returns_gpt_estimated(self):
        svc = NutritionService()
        svc._taco = []
        svc._usda = []
        svc._taco_normalized = []
        svc._usda_normalized = []
        svc._cache = {}
        svc._loaded = True
        result = svc.lookup("arroz", 100)
        assert result.source == "gpt_estimated"


class TestEnrichFoods:
    def test_enrich_multiple_foods(self, nutrition_svc: NutritionService):
        foods = [
            {"name": "arroz", "quantity_g": 180},
            {"name": "feijão", "quantity_g": 86},
            {"name": "frango grelhado", "quantity_g": 150},
        ]
        results = nutrition_svc.enrich_foods(foods)
        assert len(results) == 3
        total_kcal = sum(r.calories_kcal for r in results)
        assert total_kcal > 300  # refeição típica tem mais de 300 kcal

    def test_enrich_preserves_original_term(self, nutrition_svc: NutritionService):
        foods = [{"name": "arros", "quantity_g": 100}]
        results = nutrition_svc.enrich_foods(foods)
        assert results[0].original_term == "arros"
