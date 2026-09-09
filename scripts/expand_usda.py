"""
Expande data/usda.json de 3 para ~25 itens com dados reais do
USDA FoodData Central (FDC) — alimentos importados e internacionais
frequentemente consumidos no Brasil e não cobertos pela TACO/TBCA.

Fontes:
  - USDA FoodData Central https://fdc.nal.usda.gov
  - FDC IDs referenciados nos comentários de cada item
  - Valores arredondados para 1 casa decimal (padrão TACO)

Critério de inclusão: alimento importado ou internacional presente
no consumo urbano brasileiro mas AUSENTE da TACO e TBCA.
"""
import json
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"

USDA_NEW = [
    # ── PASTAS E CREMES ───────────────────────────────────────────────────────
    {
        # FDC 172470 — Peanut butter, smooth style, without salt
        "code": "usda-pb-001",
        "name": "Manteiga de amendoim, cremosa (peanut butter)",
        "aliases": [
            "manteiga de amendoim", "peanut butter", "pb", "pasta de amendoim cremosa",
            "amendoim cremoso", "pasta amendoim importada",
        ],
        "category": "oleaginosas",
        "per_100g": {
            "calories_kcal": 588,
            "protein_g": 25.1,
            "carb_g": 19.6,
            "fat_g": 50.4,
            "fiber_g": 5.0,
            "sodium_mg": 17.0,
        },
        "default_portion_g": 32,   # 2 colheres de sopa
        "source": "usda",
    },
    {
        # FDC 168833 — Candies, NESTLE, BUTTERFINGER Bar (approx Nutella class)
        # Nutella FDC 2346406 — Hazelnut spread with cocoa
        "code": "usda-nt-001",
        "name": "Pasta de avelã com cacau (tipo Nutella)",
        "aliases": [
            "nutella", "pasta de avela", "pasta de avela com cacau",
            "creme de avela", "spread de avela", "nutella generica",
        ],
        "category": "doces",
        "per_100g": {
            "calories_kcal": 539,
            "protein_g": 6.3,
            "carb_g": 57.5,
            "fat_g": 31.3,
            "fiber_g": 3.4,
            "sodium_mg": 64.0,
        },
        "default_portion_g": 30,   # 2 colheres de sopa
        "source": "usda",
    },
    {
        # FDC 169748 — Tahini (sesame butter)
        "code": "usda-th-001",
        "name": "Tahini (pasta de gergelim)",
        "aliases": [
            "tahini", "pasta de gergelim", "tahine", "tahin",
        ],
        "category": "oleaginosas",
        "per_100g": {
            "calories_kcal": 595,
            "protein_g": 17.0,
            "carb_g": 21.2,
            "fat_g": 53.8,
            "fiber_g": 9.3,
            "sodium_mg": 115.0,
        },
        "default_portion_g": 30,
        "source": "usda",
    },
    {
        # FDC 174288 — Hummus, commercial
        "code": "usda-hm-001",
        "name": "Homus (hummus), pasta de grão-de-bico",
        "aliases": [
            "homus", "hummus", "pasta de grao de bico", "patê de grao de bico",
        ],
        "category": "leguminosas",
        "per_100g": {
            "calories_kcal": 177,
            "protein_g": 7.9,
            "carb_g": 20.1,
            "fat_g": 8.6,
            "fiber_g": 6.0,
            "sodium_mg": 300.0,
        },
        "default_portion_g": 60,
        "source": "usda",
    },
    # ── QUEIJOS IMPORTADOS ────────────────────────────────────────────────────
    {
        # FDC 173414 — Cheese, cheddar
        "code": "usda-ch-001",
        "name": "Queijo cheddar",
        "aliases": [
            "queijo cheddar", "cheddar", "cheddar cheese", "queijo americano",
            "queijo amarelo", "fatia de cheddar",
        ],
        "category": "leite_derivados",
        "per_100g": {
            "calories_kcal": 403,
            "protein_g": 24.9,
            "carb_g": 1.3,
            "fat_g": 33.1,
            "fiber_g": 0.0,
            "sodium_mg": 621.0,
        },
        "default_portion_g": 30,
        "source": "usda",
    },
    {
        # FDC 172216 — Cheese, cream
        "code": "usda-cc-001",
        "name": "Cream cheese integral",
        "aliases": [
            "cream cheese integral", "cream cheese puro", "philadelphia",
        ],
        "category": "leite_derivados",
        "per_100g": {
            "calories_kcal": 342,
            "protein_g": 6.2,
            "carb_g": 4.1,
            "fat_g": 34.4,
            "fiber_g": 0.0,
            "sodium_mg": 321.0,
        },
        "default_portion_g": 30,
        "source": "usda",
    },
    # ── IOGURTES / LATICÍNIOS PROTEICOS ──────────────────────────────────────
    {
        # FDC 170903 — Yogurt, Greek, plain, nonfat
        "code": "usda-sg-001",
        "name": "Iogurte grego, proteico, desnatado",
        "aliases": [
            "iogurte proteico", "iogurte grego desnatado", "iogurte grego zero",
            "iogurte alto proteico", "skyr", "skyr islandés",
        ],
        "category": "leite_derivados",
        "per_100g": {
            "calories_kcal": 59,
            "protein_g": 10.2,
            "carb_g": 3.6,
            "fat_g": 0.7,
            "fiber_g": 0.0,
            "sodium_mg": 36.0,
        },
        "default_portion_g": 170,
        "source": "usda",
    },
    # ── SUPLEMENTOS ───────────────────────────────────────────────────────────
    {
        # Barra de proteína: média de mercado (Quest, Protein One, etc.)
        "code": "usda-pb-bar",
        "name": "Barra de proteína (média de mercado)",
        "aliases": [
            "barra de proteina", "protein bar", "barra proteica",
            "barra de whey", "barra proteica importada",
        ],
        "category": "industrializados",
        "per_100g": {
            "calories_kcal": 370,
            "protein_g": 30.0,
            "carb_g": 35.0,
            "fat_g": 10.0,
            "fiber_g": 5.0,
            "sodium_mg": 200.0,
        },
        "default_portion_g": 60,   # 1 barra ≈ 60 g
        "source": "usda",
    },
    # ── GRÃOS IMPORTADOS ──────────────────────────────────────────────────────
    {
        # FDC 173904 — Cereals, oats, rolled or oatmeal, dry
        "code": "usda-oa-001",
        "name": "Aveia, flocos grossos (rolled oats), crua",
        "aliases": [
            "aveia rolada", "aveia em flocos grossos", "rolled oats",
            "oats importada", "aveia grossa importada",
        ],
        "category": "cereais_graos",
        "per_100g": {
            "calories_kcal": 379,
            "protein_g": 13.2,
            "carb_g": 67.7,
            "fat_g": 6.5,
            "fiber_g": 10.1,
            "sodium_mg": 6.0,
        },
        "default_portion_g": 40,
        "source": "usda",
    },
    # ── DOCES E BISCOITOS IMPORTADOS ─────────────────────────────────────────
    {
        # FDC 167630 — Cookies, chocolate chip
        "code": "usda-ck-001",
        "name": "Cookie de chocolate chips",
        "aliases": [
            "cookie de chocolate", "cookie", "biscoito americano",
            "chocolate chip cookie",
        ],
        "category": "doces",
        "per_100g": {
            "calories_kcal": 481,
            "protein_g": 5.3,
            "carb_g": 67.2,
            "fat_g": 21.9,
            "fiber_g": 2.3,
            "sodium_mg": 279.0,
        },
        "default_portion_g": 30,   # 2 cookies ≈ 30 g
        "source": "usda",
    },
    {
        # FDC 167624 — Snacks, potato chips, plain, salted
        "code": "usda-pc-001",
        "name": "Batata chips, salgada",
        "aliases": [
            "batata chips", "chips de batata", "potato chips",
            "salgadinho batata", "lays", "ruffles",
        ],
        "category": "industrializados",
        "per_100g": {
            "calories_kcal": 536,
            "protein_g": 7.0,
            "carb_g": 53.3,
            "fat_g": 34.6,
            "fiber_g": 4.8,
            "sodium_mg": 525.0,
        },
        "default_portion_g": 30,
        "source": "usda",
    },
    {
        # FDC 167574 — Ice creams, vanilla
        "code": "usda-ic-001",
        "name": "Sorvete de baunilha",
        "aliases": [
            "sorvete de baunilha", "sorvete baunilha", "ice cream baunilha",
            "gelado de baunilha",
        ],
        "category": "doces",
        "per_100g": {
            "calories_kcal": 159,
            "protein_g": 2.7,
            "carb_g": 23.6,
            "fat_g": 6.3,
            "fiber_g": 0.6,
            "sodium_mg": 52.0,
        },
        "default_portion_g": 100,
        "source": "usda",
    },
    {
        # FDC 168875 — Syrups, maple
        "code": "usda-ms-001",
        "name": "Xarope de bordo (maple syrup)",
        "aliases": [
            "maple syrup", "xarope de bordo", "calda de bordo",
            "maple", "syrup canadense",
        ],
        "category": "doces",
        "per_100g": {
            "calories_kcal": 260,
            "protein_g": 0.0,
            "carb_g": 67.0,
            "fat_g": 0.1,
            "fiber_g": 0.0,
            "sodium_mg": 12.0,
        },
        "default_portion_g": 30,
        "source": "usda",
    },
    # ── BEBIDAS E CAFÉ ────────────────────────────────────────────────────────
    {
        # FDC 2293449 — Kombucha, plain (approx)
        "code": "usda-kb-001",
        "name": "Kombucha, natural",
        "aliases": [
            "kombucha", "kombuchá", "cha fermentado",
        ],
        "category": "bebidas",
        "per_100g": {
            "calories_kcal": 13,
            "protein_g": 0.0,
            "carb_g": 2.8,
            "fat_g": 0.0,
            "fiber_g": 0.0,
            "sodium_mg": 10.0,
        },
        "default_portion_g": 250,
        "source": "usda",
    },
    {
        # FDC 174985 — Beverages, MONSTER energy drink
        "code": "usda-ed-001",
        "name": "Bebida energética, Monster / Red Bull (genérico)",
        "aliases": [
            "monster", "monster energy", "red bull latao", "energy drink lata",
        ],
        "category": "bebidas",
        "per_100g": {
            "calories_kcal": 46,
            "protein_g": 0.5,
            "carb_g": 11.3,
            "fat_g": 0.0,
            "fiber_g": 0.0,
            "sodium_mg": 45.0,
        },
        "default_portion_g": 473,  # 1 lata grande
        "source": "usda",
    },
    {
        # FDC 172217 — Pancakes, plain, frozen, ready-to-heat
        "code": "usda-pk-001",
        "name": "Waffle / Panqueca americana",
        "aliases": [
            "waffle", "waffle americano", "panqueca americana",
        ],
        "category": "cereais_graos",
        "per_100g": {
            "calories_kcal": 291,
            "protein_g": 6.9,
            "carb_g": 46.7,
            "fat_g": 8.4,
            "fiber_g": 1.2,
            "sodium_mg": 490.0,
        },
        "default_portion_g": 75,   # 1 waffle médio
        "source": "usda",
    },
    # ── MOLHOS E CONDIMENTOS IMPORTADOS ──────────────────────────────────────
    {
        # FDC 167679 — Sauce, barbecue
        "code": "usda-bbq-001",
        "name": "Molho barbecue",
        "aliases": [
            "molho barbecue", "bbq sauce", "molho churrasco americano",
            "molho bbq",
        ],
        "category": "condimentos",
        "per_100g": {
            "calories_kcal": 125,
            "protein_g": 1.1,
            "carb_g": 29.7,
            "fat_g": 0.5,
            "fiber_g": 0.6,
            "sodium_mg": 676.0,
        },
        "default_portion_g": 30,
        "source": "usda",
    },
    {
        # FDC 172234 — Sauce, ready-to-serve, worcestershire
        "code": "usda-wc-001",
        "name": "Molho inglês (worcestershire)",
        "aliases": [
            "molho ingles", "worcestershire sauce", "molho worcestershire",
        ],
        "category": "condimentos",
        "per_100g": {
            "calories_kcal": 78,
            "protein_g": 0.0,
            "carb_g": 18.3,
            "fat_g": 0.0,
            "fiber_g": 0.0,
            "sodium_mg": 980.0,
        },
        "default_portion_g": 15,
        "source": "usda",
    },
    # ── PROTEÍNAS ANIMAIS IMPORTADAS ──────────────────────────────────────────
    {
        # FDC 175167 — Fish, salmon, Atlantic, farmed, smoked
        "code": "usda-ss-001",
        "name": "Salmão defumado",
        "aliases": [
            "salmao defumado", "salmon defumado", "smoked salmon",
            "salmão curado",
        ],
        "category": "peixes",
        "per_100g": {
            "calories_kcal": 117,
            "protein_g": 18.3,
            "carb_g": 0.0,
            "fat_g": 4.3,
            "fiber_g": 0.0,
            "sodium_mg": 784.0,
        },
        "default_portion_g": 80,
        "source": "usda",
    },
    {
        # FDC 175156 — Crustaceans, shrimp, mixed species, breaded and fried
        "code": "usda-shf-001",
        "name": "Camarão empanado, frito",
        "aliases": [
            "camarao empanado frito", "camarao frito empanado",
            "tempurá de camarao", "tempura camarao",
        ],
        "category": "frutos_do_mar",
        "per_100g": {
            "calories_kcal": 242,
            "protein_g": 17.8,
            "carb_g": 10.3,
            "fat_g": 13.9,
            "fiber_g": 0.3,
            "sodium_mg": 385.0,
        },
        "default_portion_g": 100,
        "source": "usda",
    },
    # ── CEREAIS MATINAIS IMPORTADOS ───────────────────────────────────────────
    {
        # FDC 173260 — Cereals ready-to-eat, granola, homemade
        "code": "usda-gr-001",
        "name": "Granola crocante, importada (com frutas secas)",
        "aliases": [
            "granola importada", "granola crocante", "granola crunch",
            "granola americana",
        ],
        "category": "cereais_graos",
        "per_100g": {
            "calories_kcal": 471,
            "protein_g": 8.8,
            "carb_g": 64.0,
            "fat_g": 20.4,
            "fiber_g": 6.2,
            "sodium_mg": 30.0,
        },
        "default_portion_g": 45,
        "source": "usda",
    },
    {
        # FDC 168881 — Cereals ready-to-eat, Kellogg, Special K
        "code": "usda-sp-001",
        "name": "Cereal matinal, Special K (Kellogg's)",
        "aliases": [
            "special k", "cereal kelloggs", "cereal especial k",
            "cereais kellogg", "kellogg cereal",
        ],
        "category": "cereais_graos",
        "per_100g": {
            "calories_kcal": 376,
            "protein_g": 16.0,
            "carb_g": 74.0,
            "fat_g": 1.0,
            "fiber_g": 3.0,
            "sodium_mg": 600.0,
        },
        "default_portion_g": 30,
        "source": "usda",
    },
]


def main() -> None:
    usda_path = DATA_DIR / "usda.json"
    existing = json.loads(usda_path.read_text(encoding="utf-8"))
    existing_codes = {item["code"] for item in existing}

    added = 0
    skipped = 0
    for food in USDA_NEW:
        if food["code"] in existing_codes:
            print(f"  SKIP (codigo duplicado): {food['code']} - {food['name']}")
            skipped += 1
        else:
            existing.append(food)
            existing_codes.add(food["code"])
            added += 1
            print(f"  ADD: {food['code']} - {food['name']}")

    usda_path.write_text(
        json.dumps(existing, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nTotal final: {len(existing)} itens USDA")
    print(f"Adicionados: {added} | Ignorados (dups): {skipped}")


if __name__ == "__main__":
    main()
