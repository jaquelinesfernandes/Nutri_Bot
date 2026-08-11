# NutriBot — Algoritmo de Lookup de Alimentos (Fuzzy Match)

**Versão:** 1.0 | **Data:** Junho 2026

---

## 1. Problema

O GPT-4o retorna nomes de alimentos em formato semi-padronizado (ex: `"frango grelhado sem pele"`). A base TACO contém entradas como `"Frango, peito, sem pele, grelhado"`. Precisamos fazer o match entre o nome retornado pelo GPT e a entrada correta na TACO/USDA para obter os valores nutricionais precisos.

Desafios:
- Variação de ordem das palavras ("feijão carioca cozido" vs "carioca, feijão, cozido")
- Abreviações e nomes populares ("pão francês" vs "pão de sal")
- Erros de digitação do usuário que chegam transcriados pelo GPT
- Pratos compostos que não têm entrada direta na TACO

---

## 2. Estrutura da Base TACO/USDA (JSON local)

```json
// data/taco.json (exemplo de estrutura)
[
  {
    "code": "001",
    "name": "Arroz, branco, cozido",
    "aliases": ["arroz branco cozido", "arroz cozido", "arroz"],
    "category": "cereais_graos",
    "per_100g": {
      "calories_kcal": 128,
      "protein_g": 2.5,
      "carb_g": 28.1,
      "fat_g": 0.2,
      "fiber_g": 1.6,
      "sodium_mg": 1.0
    },
    "default_portion_g": 180,
    "source": "taco"
  }
]
```

O campo `aliases` é mantido manualmente pela equipe e expandido conforme feedbacks dos usuários. É a primeira linha de lookup (match exato por string normalizada).

---

## 3. Pipeline de Normalização de Texto

Aplicado tanto ao nome retornado pelo GPT quanto às entradas da base antes do match:

```python
import re
import unicodedata

def normalize(text: str) -> str:
    # 1. Lowercase
    text = text.lower()
    # 2. Remove acentos
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    # 3. Remove pontuação e caracteres especiais
    text = re.sub(r"[^\w\s]", " ", text)
    # 4. Colapsa espaços
    text = re.sub(r"\s+", " ", text).strip()
    # 5. Remove stopwords nutricionais irrelevantes
    STOPWORDS = {"cozido", "cozida", "grelhado", "grelhada", "assado",
                 "assada", "sem", "com", "ao", "de", "do", "da", "e"}
    words = [w for w in text.split() if w not in STOPWORDS]
    return " ".join(words)

# Exemplos:
# "Frango, peito, sem pele, grelhado" → "frango peito pele"
# "frango grelhado sem pele"           → "frango pele"
# → score alto entre os dois
```

> **Nota:** Stopwords são removidas apenas para o matching — os valores nutricionais corretos dependem do item completo. Nunca modificar os dados nutricionais da TACO.

---

## 4. Estratégia de Matching em Camadas

```
Nome do GPT: "frango grelhado sem pele"
                        │
                        ▼
            ┌─────────────────────┐
            │  Camada 1: Cache    │
            │  Top 100 alimentos  │
            │  (dict Python)      │
            └────────┬────────────┘
                     │ miss
                     ▼
            ┌─────────────────────┐
            │  Camada 2: Aliases  │
            │  Match exato em     │
            │  campo aliases[]    │
            └────────┬────────────┘
                     │ miss
                     ▼
            ┌─────────────────────┐
            │  Camada 3: RapidFuzz│
            │  token_sort_ratio   │
            │  threshold ≥ 80     │
            └────────┬────────────┘
                     │ miss (< 80)
                     ▼
            ┌─────────────────────┐
            │  Camada 4: USDA     │
            │  Mesmo pipeline     │
            │  (threshold ≥ 75)   │
            └────────┬────────────┘
                     │ miss
                     ▼
            ┌─────────────────────┐
            │  Fallback: GPT est. │
            │  Usa quantidade do  │
            │  GPT + estima macros│
            │  source="gpt_est."  │
            └─────────────────────┘
```

---

## 5. Implementação com RapidFuzz

```python
from rapidfuzz import process, fuzz
from functools import lru_cache

class NutritionService:
    def __init__(self):
        self._taco = self._load_and_index("data/taco.json")
        self._usda = self._load_and_index("data/usda.json")
        self._cache = self._build_cache()

    def _build_cache(self) -> dict[str, dict]:
        """Top 100 alimentos mais comuns — lookup O(1)."""
        TOP_100 = [
            "arroz branco cozido", "feijao carioca cozido", "frango peito",
            "carne bovina", "ovo cozido", "pao frances", "leite integral",
            # ... lista completa em data/food_cache.json
        ]
        return {normalize(name): self._lookup_taco(name) for name in TOP_100}

    def lookup(self, gpt_name: str, quantity_g: float) -> EnrichedFood:
        normalized = normalize(gpt_name)

        # Camada 1: cache de top 100
        if normalized in self._cache:
            return self._build_result(self._cache[normalized], quantity_g, "taco_cache")

        # Camada 2: match exato em aliases
        for item in self._taco:
            for alias in item.get("aliases", []):
                if normalize(alias) == normalized:
                    return self._build_result(item, quantity_g, "taco_alias")

        # Camada 3: RapidFuzz na TACO
        taco_names = [normalize(item["name"]) for item in self._taco]
        result = process.extractOne(
            normalized,
            taco_names,
            scorer=fuzz.token_sort_ratio,
            score_cutoff=80
        )
        if result:
            matched_item = self._taco[result[2]]
            return self._build_result(matched_item, quantity_g, "taco_fuzzy")

        # Camada 4: RapidFuzz na USDA (threshold menor)
        usda_names = [normalize(item["name"]) for item in self._usda]
        result = process.extractOne(
            normalized,
            usda_names,
            scorer=fuzz.token_sort_ratio,
            score_cutoff=75
        )
        if result:
            matched_item = self._usda[result[2]]
            return self._build_result(matched_item, quantity_g, "usda_fuzzy")

        # Fallback: GPT estimou macros — usar como está
        return EnrichedFood(
            name=gpt_name,
            quantity_g=quantity_g,
            source="gpt_estimated",
            confidence_score=0.4,
            # macros virão do campo de estimativa do GPT
        )

    def _build_result(self, item: dict, quantity_g: float, source: str) -> EnrichedFood:
        ratio = quantity_g / 100.0
        per_100g = item["per_100g"]
        return EnrichedFood(
            name=item["name"],
            quantity_g=quantity_g,
            calories_kcal=round(per_100g["calories_kcal"] * ratio, 1),
            protein_g=round(per_100g["protein_g"] * ratio, 1),
            carb_g=round(per_100g["carb_g"] * ratio, 1),
            fat_g=round(per_100g["fat_g"] * ratio, 1),
            source=source,
            confidence_score=0.95 if "cache" in source or "alias" in source else 0.80
        )
```

---

## 6. Expansão do Alias por Feedback de Usuário

Quando um usuário corrige um alimento que o sistema errou, o evento `meal_corrected` é registrado no PostHog. O processo de manutenção semanal:

1. Exportar `meal_corrected` events da semana
2. Identificar os 10 itens mais corrigidos
3. Para cada um: verificar se o alias correto já existe em `taco.json`
4. Se não: adicionar ao campo `aliases[]` do item correto
5. PR de atualização dos dados nutricionais — revisado pelo PM
6. Após merge, o NutritionService recarrega a base em memória no próximo deploy

---

## 7. Benchmarks de Performance

Medidos em Python 3.13, base TACO completa (~6.000 itens):

| Camada | Tempo médio por lookup |
|--------|----------------------|
| Cache top 100 | < 0.01ms |
| Alias match | ~0.5ms |
| RapidFuzz TACO | ~8ms |
| RapidFuzz USDA | ~15ms (adicional) |
| **Total (caso ruim: até USDA)** | **~25ms** |

Aceitável considerando que o gargalo real é a chamada à OpenAI API (~1–3s). O lookup nutricional representa < 1% do tempo total de resposta.

---

## 8. Casos Especiais

| Caso | Estratégia |
|------|-----------|
| Pratos compostos sem entrada TACO ("feijoada") | GPT lista os componentes individualmente; cada um é lookupado separadamente |
| Alimentos industrializados com marca ("Activia") | Lookup falha → GPT estimado; usuário pode corrigir; candidato para adição ao USDA local |
| Sucos e bebidas | Base TACO tem "suco de laranja natural", "refrigerante cola" etc. — cobertos |
| Quantidades em unidades não-métricas | GPT converte para gramas como parte do prompt (1 concha = 86g de feijão) |
| Alimento mencionado sem quantidade | GPT usa porção padrão TACO (campo `default_portion_g`); exibido ao usuário para confirmação |
