from typing import Literal

from pydantic import BaseModel, Field


class ExtractedFoodItem(BaseModel):
    name: str
    original_term: str = ""
    quantity_g: float = Field(gt=0)
    taco_code: str | None = None
    confidence_score: float = Field(default=0.8, ge=0.0, le=1.0)
    # Estimativas por 100g fornecidas pelo Claude como fallback
    est_calories_kcal: float | None = None
    est_protein_g: float | None = None
    est_carb_g: float | None = None
    est_fat_g: float | None = None


class FoodExtractionResponse(BaseModel):
    foods: list[ExtractedFoodItem]
    meal_type: Literal[
        "breakfast", "morning_snack", "lunch", "afternoon_snack", "dinner", "snack", "other"
    ] = "other"
    meal_time_hint: str | None = None
    unrecognized_terms: list[str] = []
    image_has_food: bool = True
    image_quality: Literal["good", "poor", "unreadable"] = "good"
    overall_confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    # Registro retroativo: detectado a partir do texto do usuário
    date_offset: int = 0        # 0=hoje, -1=ontem, -2=anteontem, etc.
    date_explicit: str | None = None  # "DD/MM" ou "DD/MM/AAAA" quando o usuário cita data explícita


class ReportSuggestion(BaseModel):
    category: Literal["proteina", "carboidrato", "gordura", "hidratacao", "horario", "variedade"]
    text: str
    priority: Literal["high", "medium", "low"] = "medium"


class MenuMeal(BaseModel):
    """Uma refeição dentro do cardápio sugerido pela IA."""
    type: str           # "Café da manhã", "Almoço", "Jantar", etc.
    foods: list[str]    # ["Arroz integral (4 col sopa)", "Feijão (1 concha)"]
    kcal_estimate: int


class MenuSuggestion(BaseModel):
    """Cardápio sugerido para 1 dia, personalizado conforme o objetivo do usuário."""
    title: str
    meals: list[MenuMeal]


class ReportSuggestionsResponse(BaseModel):
    highlights: list[str]
    suggestions: list[ReportSuggestion]
    weekly_insight: str
    menu_suggestion: MenuSuggestion | None = None
