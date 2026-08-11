"""
NutritionService — lookup de alimentos na base TACO/USDA.
Algoritmo em 4 camadas: cache → alias → RapidFuzz TACO → RapidFuzz USDA → GPT estimado.
Ver docs/fuzzy-match.md para detalhes.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from rapidfuzz import fuzz, process

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent.parent / "data"

STOPWORDS = {
    # artigos / preposições
    "de", "do", "da", "dos", "das", "com", "sem", "ao", "na", "no", "em", "e", "a", "o",
    # métodos de preparo — não mudam a identidade nutricional
    "cozido", "cozida", "cozidos", "cozidas",
    "grelhado", "grelhada", "grelhados", "grelhadas",
    "assado", "assada", "assados", "assadas",
    "frito", "frita", "fritos", "fritas",
    "refogado", "refogada", "refogados", "refogadas",
    "mexido", "mexida", "mexidos", "mexidas",
    "estrelado", "estrelada",
    "temperado", "temperada",
    "caramelizado", "caramelizada",  # cebola caramelizada → cebola
    "dourado", "dourada",            # cebola dourada → cebola
    "picado", "picada",              # salsa picada → salsa
    "ralado", "ralada",              # cenoura ralada → cenoura
    "inteiro", "inteira",
    "caseiro", "caseira", "artesanal",
    "em", "conserva", "lata", "frasco",  # palmito em conserva → palmito
    # adjetivos genéricos
    "natural", "fresco", "fresca", "frescos", "frescas",
    "simples", "puro", "pura", "tradicional", "original",
    "cru", "crua",
}


@dataclass
class EnrichedFood:
    name: str
    original_term: str
    quantity_g: float
    calories_kcal: float
    protein_g: float
    carb_g: float
    fat_g: float
    fiber_g: float
    source: str  # taco_cache | taco_alias | taco_fuzzy | usda_fuzzy | gpt_estimated
    confidence_score: float
    taco_code: str | None = None


def _normalize(text: str) -> str:
    text = text.lower()
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    words = [w for w in text.split() if w not in STOPWORDS]
    return " ".join(words)


class NutritionService:
    def __init__(self) -> None:
        self._taco: list[dict] = []
        self._usda: list[dict] = []
        self._cache: dict[str, dict] = {}
        self._taco_normalized: list[str] = []
        self._usda_normalized: list[str] = []
        self._loaded = False

    def load_data(self) -> None:
        taco_path = DATA_DIR / "taco.json"
        usda_path = DATA_DIR / "usda.json"

        if taco_path.exists():
            self._taco = json.loads(taco_path.read_text(encoding="utf-8"))
        else:
            logger.warning("data/taco.json não encontrado")

        if usda_path.exists():
            self._usda = json.loads(usda_path.read_text(encoding="utf-8"))
        else:
            logger.warning("data/usda.json não encontrado")

        self._taco_normalized = [_normalize(item["name"]) for item in self._taco]
        self._usda_normalized = [_normalize(item["name"]) for item in self._usda]
        self._cache = self._build_cache()
        self._loaded = True
        logger.info(f"Base nutricional carregada: {len(self._taco)} TACO + {len(self._usda)} USDA")

    def _build_cache(self) -> dict[str, dict]:
        """Pré-calcula lookup para os alimentos (TACO tem prioridade sobre USDA)."""
        cache: dict[str, dict] = {}
        # USDA primeiro (menor prioridade), depois TACO sobrescreve
        for item in self._usda + self._taco:
            for alias in item.get("aliases", []):
                cache[_normalize(alias)] = item
            cache[_normalize(item["name"])] = item
        return cache

    def lookup(
        self,
        gpt_name: str,
        quantity_g: float,
        gpt_calories: float | None = None,
        gpt_protein: float | None = None,
        gpt_carb: float | None = None,
        gpt_fat: float | None = None,
    ) -> EnrichedFood:
        normalized = _normalize(gpt_name)

        # Camada 1: cache (alias exato normalizado)
        if normalized in self._cache:
            return self._build_result(self._cache[normalized], gpt_name, quantity_g, "taco_cache")

        # Camada 2: fuzzy match na TACO (threshold 80)
        if self._taco_normalized:
            result = process.extractOne(
                normalized,
                self._taco_normalized,
                scorer=fuzz.token_sort_ratio,
                score_cutoff=80,
            )
            if result:
                return self._build_result(
                    self._taco[result[2]], gpt_name, quantity_g, "taco_fuzzy"
                )

        # Camada 3: fuzzy match na USDA (threshold 75)
        if self._usda_normalized:
            result = process.extractOne(
                normalized,
                self._usda_normalized,
                scorer=fuzz.token_sort_ratio,
                score_cutoff=75,
            )
            if result:
                return self._build_result(
                    self._usda[result[2]], gpt_name, quantity_g, "usda_fuzzy"
                )

        # Fallback: usa estimativa do GPT
        ratio = quantity_g / 100.0
        return EnrichedFood(
            name=gpt_name,
            original_term=gpt_name,
            quantity_g=quantity_g,
            calories_kcal=round((gpt_calories or 0) * ratio, 1),
            protein_g=round((gpt_protein or 0) * ratio, 1),
            carb_g=round((gpt_carb or 0) * ratio, 1),
            fat_g=round((gpt_fat or 0) * ratio, 1),
            fiber_g=0.0,
            source="gpt_estimated",
            confidence_score=0.4,
        )

    def _build_result(
        self, item: dict, original_term: str, quantity_g: float, source: str
    ) -> EnrichedFood:
        ratio = quantity_g / 100.0
        p = item["per_100g"]
        confidence = 0.95 if source == "taco_cache" else 0.80
        return EnrichedFood(
            name=item["name"],
            original_term=original_term,
            quantity_g=quantity_g,
            calories_kcal=round(p.get("calories_kcal", 0) * ratio, 1),
            protein_g=round(p.get("protein_g", 0) * ratio, 1),
            carb_g=round(p.get("carb_g", 0) * ratio, 1),
            fat_g=round(p.get("fat_g", 0) * ratio, 1),
            fiber_g=round(p.get("fiber_g", 0) * ratio, 1),
            source=source,
            confidence_score=confidence,
            taco_code=item.get("code"),
        )

    def enrich_foods(self, foods: list[dict]) -> list[EnrichedFood]:
        """Enriquece lista de alimentos extraídos pelo Claude com dados nutricionais."""
        return [
            self.lookup(
                gpt_name=f["name"],
                quantity_g=f.get("quantity_g", 100),
                gpt_calories=f.get("est_calories_kcal"),
                gpt_protein=f.get("est_protein_g"),
                gpt_carb=f.get("est_carb_g"),
                gpt_fat=f.get("est_fat_g"),
            )
            for f in foods
        ]


nutrition_service = NutritionService()
