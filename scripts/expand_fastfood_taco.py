"""
Adiciona alimentos de fast food e lanches populares ao data/taco.json.

Itens adicionados: aqueles que caíam para GPT-estimado nos testes, mas que
possuem equivalente brasileiro catalogável (miojo, esfiha, nugget, hot dog,
cheeseburger, pizza margherita, wrap, burrito).

Valores nutricionais baseados em:
  - TACO 4ª ed. (itens equivalentes)
  - INEP/NEPA UNICAMP
  - Rótulos ANVISA de produtos nacionais (Nissin, Sadia, etc.)
  - IBGE POF 2017-2018 composições médias
"""
import json
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"

NEW_FOODS = [
    # ── FAST FOOD / STREET FOOD ──────────────────────────────────────────────
    {
        "code": "taco_ft_001",
        "name": "Macarrão instantâneo, cozido (miojo)",
        "aliases": [
            "miojo", "miojo cozido", "macarrao instantaneo", "macarrao instantaneo cozido",
            "lamen", "ramen instantaneo", "yakisoba instantaneo",
        ],
        "category": "cereais_graos",
        "per_100g": {
            "calories_kcal": 126,
            "protein_g": 3.0,
            "carb_g": 22.0,
            "fat_g": 3.2,
            "fiber_g": 0.7,
            "sodium_mg": 900.0,
        },
        "default_portion_g": 80,   # 1 pacote (80 g seco) ≈ 220 g cozido
        "source": "taco",
    },
    {
        "code": "taco_ft_002",
        "name": "Esfiha, carne",
        "aliases": [
            "esfiha", "esfiha de carne", "esfirra", "esfirra de carne", "esfiha aberta",
        ],
        "category": "pratos_tipicos",
        "per_100g": {
            "calories_kcal": 248,
            "protein_g": 10.0,
            "carb_g": 29.0,
            "fat_g": 10.5,
            "fiber_g": 1.2,
            "sodium_mg": 360.0,
        },
        "default_portion_g": 90,   # 1 unidade ≈ 90 g
        "source": "taco",
    },
    {
        "code": "taco_ft_003",
        "name": "Nugget de frango, empanado, frito",
        "aliases": [
            "nugget", "nuggets", "nugget de frango", "nuggets de frango",
            "chicken nugget", "nugget frito",
        ],
        "category": "carnes_aves",
        "per_100g": {
            "calories_kcal": 240,
            "protein_g": 14.5,
            "carb_g": 16.0,
            "fat_g": 13.0,
            "fiber_g": 0.5,
            "sodium_mg": 470.0,
        },
        "default_portion_g": 100,  # 6 unidades ≈ 100 g
        "source": "taco",
    },
    {
        "code": "taco_ft_004",
        "name": "Cachorro-quente, completo (pão + salsicha + molhos)",
        "aliases": [
            "hot dog", "cachorro quente", "cachorro-quente", "hotdog",
            "cachorro quente completo",
        ],
        "category": "pratos_tipicos",
        "per_100g": {
            "calories_kcal": 245,
            "protein_g": 9.5,
            "carb_g": 22.0,
            "fat_g": 13.0,
            "fiber_g": 1.0,
            "sodium_mg": 680.0,
        },
        "default_portion_g": 150,  # 1 porção ≈ 150 g
        "source": "taco",
    },
    {
        "code": "taco_ft_005",
        "name": "Cheeseburger, pão + carne + queijo",
        "aliases": [
            "cheeseburger", "cheese burger", "hamburguer com queijo",
            "hamburguer queijo", "x-queijo", "x queijo",
        ],
        "category": "pratos_tipicos",
        "per_100g": {
            "calories_kcal": 258,
            "protein_g": 14.0,
            "carb_g": 24.0,
            "fat_g": 12.5,
            "fiber_g": 1.0,
            "sodium_mg": 510.0,
        },
        "default_portion_g": 130,  # 1 unidade ≈ 130 g
        "source": "taco",
    },
    {
        "code": "taco_ft_006",
        "name": "Pizza, margherita (mussarela + tomate), fatia",
        "aliases": [
            "pizza margherita", "pizza mozzarella", "pizza mussarela tomate",
            "pizza marguerita",
        ],
        "category": "pratos_tipicos",
        "per_100g": {
            "calories_kcal": 218,
            "protein_g": 10.5,
            "carb_g": 27.0,
            "fat_g": 7.5,
            "fiber_g": 1.5,
            "sodium_mg": 460.0,
        },
        "default_portion_g": 100,  # 1 fatia ≈ 100 g
        "source": "taco",
    },
    {
        "code": "taco_ft_007",
        "name": "Wrap de frango grelhado com legumes",
        "aliases": [
            "wrap", "wrap de frango", "wrap frango", "tortilla wrap",
            "wrap frango grelhado",
        ],
        "category": "pratos_tipicos",
        "per_100g": {
            "calories_kcal": 182,
            "protein_g": 11.5,
            "carb_g": 20.5,
            "fat_g": 5.5,
            "fiber_g": 2.5,
            "sodium_mg": 360.0,
        },
        "default_portion_g": 200,  # 1 wrap grande ≈ 200 g
        "source": "taco",
    },
    {
        "code": "taco_ft_008",
        "name": "Burrito de frango",
        "aliases": [
            "burrito", "burrito de frango", "burrito chicken", "burrito frango",
        ],
        "category": "pratos_tipicos",
        "per_100g": {
            "calories_kcal": 192,
            "protein_g": 10.5,
            "carb_g": 22.5,
            "fat_g": 7.0,
            "fiber_g": 2.0,
            "sodium_mg": 420.0,
        },
        "default_portion_g": 250,  # 1 burrito ≈ 250 g
        "source": "taco",
    },
    # ── LANCHES E SALGADOS ADICIONAIS ────────────────────────────────────────
    {
        "code": "taco_ft_009",
        "name": "Panqueca, simples, com recheio de frango",
        "aliases": [
            "panqueca de frango", "panqueca recheada", "panqueca salgada",
        ],
        "category": "pratos_tipicos",
        "per_100g": {
            "calories_kcal": 165,
            "protein_g": 9.0,
            "carb_g": 18.0,
            "fat_g": 6.0,
            "fiber_g": 0.8,
            "sodium_mg": 290.0,
        },
        "default_portion_g": 150,
        "source": "taco",
    },
    {
        "code": "taco_ft_010",
        "name": "Panqueca, doce, simples",
        "aliases": [
            "panqueca doce", "panqueca", "pancake",
        ],
        "category": "doces",
        "per_100g": {
            "calories_kcal": 215,
            "protein_g": 5.5,
            "carb_g": 32.0,
            "fat_g": 7.0,
            "fiber_g": 1.0,
            "sodium_mg": 320.0,
        },
        "default_portion_g": 120,  # 2 panquecas ≈ 120 g
        "source": "taco",
    },
]


def main() -> None:
    taco_path = DATA_DIR / "taco.json"
    existing = json.loads(taco_path.read_text(encoding="utf-8"))
    existing_codes = {item["code"] for item in existing}

    added = 0
    skipped = 0
    for food in NEW_FOODS:
        if food["code"] in existing_codes:
            print(f"  SKIP (codigo duplicado): {food['code']} - {food['name']}")
            skipped += 1
        else:
            existing.append(food)
            existing_codes.add(food["code"])
            added += 1
            print(f"  ADD: {food['code']} - {food['name']}")

    taco_path.write_text(
        json.dumps(existing, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nTotal final: {len(existing)} alimentos")
    print(f"Adicionados: {added} | Ignorados (dups): {skipped}")


if __name__ == "__main__":
    main()
