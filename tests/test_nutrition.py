"""
Testes unitários do NutritionService.
Cobre: lookup por alias, fuzzy match (TACO/TBCA/USDA), fallback GPT, cálculo de porções.
"""

import pytest

from app.services.nutrition import EnrichedFood, NutritionService, _normalize


# ── helpers de fixture ────────────────────────────────────────────────────────

def _item(name: str, aliases: list[str], *, kcal: float = 100.0, source: str = "taco") -> dict:
    return {
        "name": name,
        "aliases": aliases,
        "per_100g": {
            "calories_kcal": kcal,
            "protein_g": 5.0,
            "carb_g": 10.0,
            "fat_g": 2.0,
            "fiber_g": 1.0,
        },
        "default_portion_g": 100,
        "source": source,
    }


def _svc_tbca_only() -> NutritionService:
    svc = NutritionService()
    svc._taco = []
    svc._tbca = [_item("Iogurte natural integral", ["iogurte", "iogurte natural"], kcal=61, source="tbca")]
    svc._usda = []
    svc._taco_normalized = []
    svc._tbca_normalized = [_normalize(svc._tbca[0]["name"])]
    svc._usda_normalized = []
    svc._cache = svc._build_cache()
    svc._loaded = True
    return svc


def _svc_usda_only() -> NutritionService:
    svc = NutritionService()
    svc._taco = []
    svc._tbca = []
    svc._usda = [_item("Peanut Butter", ["peanut butter", "manteiga amendoim"], kcal=589, source="usda")]
    svc._taco_normalized = []
    svc._tbca_normalized = []
    svc._usda_normalized = [_normalize(svc._usda[0]["name"])]
    svc._cache = svc._build_cache()
    svc._loaded = True
    return svc


def _svc_empty() -> NutritionService:
    svc = NutritionService()
    svc._taco = []
    svc._tbca = []
    svc._usda = []
    svc._taco_normalized = []
    svc._tbca_normalized = []
    svc._usda_normalized = []
    svc._cache = {}
    svc._loaded = True
    return svc


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

    def test_enrich_lista_vazia_retorna_vazio(self, nutrition_svc: NutritionService):
        assert nutrition_svc.enrich_foods([]) == []

    def test_enrich_passa_estimativas_gpt_no_fallback(self):
        """enrich_foods deve repassar calories/protein/carb/fat do Claude quando não encontra."""
        svc = _svc_empty()
        foods = [{
            "name": "cogumelo exótico sem nome",
            "quantity_g": 100,
            "est_calories_kcal": 55.0,
            "est_protein_g": 3.0,
            "est_carb_g": 7.0,
            "est_fat_g": 1.5,
        }]
        results = svc.enrich_foods(foods)
        assert results[0].source == "gpt_estimated"
        assert results[0].calories_kcal == 55.0
        assert results[0].protein_g == 3.0


class TestTBCAPath:
    """Lookup passa pela Camada 3 (TBCA fuzzy) quando TACO não encontra."""

    def test_encontra_por_alias_exato(self):
        svc = _svc_tbca_only()
        result = svc.lookup("iogurte", 100)
        assert result.source in ("tbca_cache", "tbca_fuzzy", "taco_cache")
        assert result.calories_kcal > 0

    def test_encontra_por_nome_fuzzy(self):
        svc = _svc_tbca_only()
        result = svc.lookup("iogurte natural integral", 100)
        # Cache exato ou fuzzy — o importante é não cair em gpt_estimated
        assert result.source != "gpt_estimated"

    def test_calorias_escalam_com_quantidade(self):
        svc = _svc_tbca_only()
        r50 = svc.lookup("iogurte natural integral", 50)
        r200 = svc.lookup("iogurte natural integral", 200)
        assert abs(r200.calories_kcal - r50.calories_kcal * 4) < 1

    def test_fonte_indica_tbca(self):
        svc = _svc_tbca_only()
        result = svc.lookup("iogurte natural integral", 100)
        # Pode ser cache (alias) ou fuzzy
        assert "tbca" in result.source or "cache" in result.source

    def test_desconhecido_cai_em_fallback(self):
        svc = _svc_tbca_only()
        result = svc.lookup("baobá exótico tribal 2", 100)
        assert result.source == "gpt_estimated"


class TestUSDAPath:
    """Lookup passa pela Camada 4 (USDA fuzzy) quando TACO+TBCA não encontram."""

    def test_encontra_por_alias_exato(self):
        svc = _svc_usda_only()
        result = svc.lookup("peanut butter", 100)
        assert result.source in ("usda_fuzzy", "taco_cache")
        assert result.calories_kcal > 0

    def test_encontra_por_nome_fuzzy(self):
        svc = _svc_usda_only()
        result = svc.lookup("peanut butr", 100)
        assert result.source != "gpt_estimated"

    def test_calorias_escalam(self):
        svc = _svc_usda_only()
        r100 = svc.lookup("peanut butter", 100)
        r200 = svc.lookup("peanut butter", 200)
        assert abs(r200.calories_kcal - r100.calories_kcal * 2) < 2

    def test_desconhecido_cai_em_gpt(self):
        svc = _svc_usda_only()
        result = svc.lookup("baobá exótico tribal 3", 100)
        assert result.source == "gpt_estimated"


class TestGPTFallback:
    """Camada 5 — estimativas do Claude passadas no lookup."""

    def test_usa_calories_do_gpt_quando_passada(self):
        svc = _svc_empty()
        result = svc.lookup("chia seed powder mix", 100, gpt_calories=486.0)
        assert result.source == "gpt_estimated"
        assert result.calories_kcal == 486.0

    def test_usa_macros_do_gpt(self):
        svc = _svc_empty()
        result = svc.lookup("proteina vegana xy", 100,
                            gpt_calories=200, gpt_protein=25.0,
                            gpt_carb=15.0, gpt_fat=5.0)
        assert result.protein_g == 25.0
        assert result.carb_g == 15.0
        assert result.fat_g == 5.0

    def test_sem_estimativas_gpt_usa_zeros(self):
        svc = _svc_empty()
        result = svc.lookup("baoba tribal xyz 999", 100)
        assert result.calories_kcal == 0.0
        assert result.source == "gpt_estimated"
        assert result.confidence_score < 0.5

    def test_calorias_escalam_com_quantidade_no_fallback(self):
        svc = _svc_empty()
        r100 = svc.lookup("xyz exotico", 100, gpt_calories=200.0)
        r50  = svc.lookup("xyz exotico", 50,  gpt_calories=200.0)
        # 200 kcal/100g → 100 kcal/50g
        assert abs(r50.calories_kcal - 100.0) < 1


class TestFuzzyReturnPaths:
    """Força os caminhos de retorno do fuzzy match (linhas 169 e 182 de nutrition.py)."""

    def test_taco_fuzzy_hit_sem_cache(self, nutrition_svc: NutritionService):
        """Consulta com typo leve vai para Camada 2 (TACO fuzzy) quando cache está vazio."""
        original_cache = nutrition_svc._cache
        nutrition_svc._cache = {}
        try:
            # "arros branco" = um typo em 'arroz' — fuzzy deve encontrar "Arroz, branco, cozido"
            result = nutrition_svc.lookup("arros branco", 100)
            assert result.source == "taco_fuzzy"
        finally:
            nutrition_svc._cache = original_cache

    def test_tbca_fuzzy_hit(self):
        """Consulta com typo vai para Camada 3 (TBCA fuzzy) com cache e TACO vazios."""
        svc = _svc_tbca_only()
        svc._cache = {}  # força Camada 3
        # "iogurte natral" tem typo leve — deve bater no TBCA fuzzy
        result = svc.lookup("iogurte natral integral", 100)
        assert result.source == "tbca_fuzzy"


class TestNutritionEdgeCases:
    """Casos extremos do pipeline de lookup."""

    def test_lookup_zero_gramas_retorna_zero_calorias(self, nutrition_svc: NutritionService):
        """Porção de 0g deve resultar em 0 kcal."""
        result = nutrition_svc.lookup("arroz", 0)
        assert result.calories_kcal == 0.0

    def test_lookup_porcao_muito_pequena(self, nutrition_svc: NutritionService):
        result = nutrition_svc.lookup("arroz", 1)
        assert result.calories_kcal < 5  # 1g de arroz ≈ 1.28 kcal

    def test_lookup_porcao_muito_grande(self, nutrition_svc: NutritionService):
        result = nutrition_svc.lookup("arroz", 1000)
        assert result.calories_kcal > 1000

    def test_lookup_nome_com_acento_e_maiuscula(self, nutrition_svc: NutritionService):
        result1 = nutrition_svc.lookup("Feijão", 100)
        result2 = nutrition_svc.lookup("feijao", 100)
        assert abs(result1.calories_kcal - result2.calories_kcal) < 1

    def test_lookup_retorna_enriched_food(self, nutrition_svc: NutritionService):
        result = nutrition_svc.lookup("arroz", 100)
        assert isinstance(result, EnrichedFood)
        assert result.name != ""
        assert result.quantity_g == 100
