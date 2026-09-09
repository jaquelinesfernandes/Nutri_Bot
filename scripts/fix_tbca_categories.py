"""
Corrige as categorias do data/tbca.json usando os grupos reais da TBCA
(lidos de data/tbca_raw.json, que já foi coletado pelo scraper).

Uso: python scripts/fix_tbca_categories.py
"""
from __future__ import annotations
import json
import re
import unicodedata
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
TBCA_FILE = DATA_DIR / "tbca.json"
RAW_FILE  = DATA_DIR / "tbca_raw.json"


# Mapeamento correto — baseado nos grupos reais encontrados na TBCA
# Chave: fragmento que aparece no grupo normalizado → categoria interna
GROUP_MAP: dict[str, str] = {
    # Grupos reais da TBCA
    "vegetais":               "hortalicas",
    "hortali":                "hortalicas",       # hortaliças
    "cereais":                "cereais_graos",
    "carnes":                 "carnes_bovinas",   # genérico (TBCA não separa bovino/suíno/aves na listagem)
    "aves":                   "carnes_aves",
    "suino":                  "carnes_suinas",
    "frutas":                 "frutas",
    "industrializados":       "industrializados",
    "alimentos industrializ": "industrializados",
    "fins especiais":         "industrializados",  # diet/light
    "pescados":               "peixes",
    "frutos do mar":          "frutos_do_mar",
    "leite":                  "leite_derivados",
    "laticinios":             "leite_derivados",
    "acucares":               "doces",
    "doces":                  "doces",
    "sobremesas":             "doces",
    "leguminosas":            "leguminosas",
    "gorduras":               "gorduras",
    "oleos":                  "gorduras",
    "bebidas":                "bebidas",
    "sucos":                  "bebidas",
    "ovos":                   "ovos",
    "nozes":                  "oleaginosas",
    "sementes":               "oleaginosas",
    "oleaginosas":            "oleaginosas",
    "miscelaneas":            "pratos_tipicos",
    "preparacoes":            "pratos_tipicos",
    "pratos":                 "pratos_tipicos",
    "condimentos":            "condimentos",
    "temperos":               "condimentos",
    "molhos":                 "condimentos",
    "panificados":            "panificados",
    "paes":                   "panificados",
    "biscoitos":              "panificados",
    "massas":                 "cereais_graos",
    "farinhas":               "cereais_graos",
}

DEFAULT_PORTION: dict[str, int] = {
    "cereais_graos": 150, "panificados": 50, "leguminosas": 140,
    "hortalicas": 80,     "frutas": 100,     "carnes_bovinas": 120,
    "carnes_suinas": 120, "carnes_aves": 120,"peixes": 150,
    "frutos_do_mar": 100, "leite_derivados": 200, "ovos": 60,
    "gorduras": 10,       "oleaginosas": 30, "bebidas": 200,
    "doces": 50,          "condimentos": 15, "pratos_tipicos": 250,
    "industrializados": 100,
}


def _normalize(text: str) -> str:
    t = text.lower().strip()
    t = unicodedata.normalize("NFD", t)
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = re.sub(r"[^\w\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _map_group(group_str: str) -> str:
    g = _normalize(group_str)
    for key, cat in GROUP_MAP.items():
        if key in g:
            return cat
    return "outros"


def main() -> None:
    if not RAW_FILE.exists():
        print(f"ERRO: {RAW_FILE} nao encontrado. Execute o scraper primeiro.")
        return
    if not TBCA_FILE.exists():
        print(f"ERRO: {TBCA_FILE} nao encontrado.")
        return

    # Monta índice code→group a partir do raw
    raw_items = json.loads(RAW_FILE.read_text(encoding="utf-8"))
    code_to_group: dict[str, str] = {}
    name_to_group: dict[str, str] = {}
    for item in raw_items:
        code = item.get("code", "").strip()
        name = item.get("name", "").strip()
        group = item.get("group", "").strip()
        if code:
            code_to_group[f"tbca_{code}"] = group
        if name:
            name_to_group[name] = group

    print(f"Raw: {len(raw_items)} itens indexados")

    # Corrige tbca.json
    tbca_items = json.loads(TBCA_FILE.read_text(encoding="utf-8"))
    print(f"TBCA: {len(tbca_items)} itens para corrigir")

    stats: dict[str, int] = {}
    changed = 0

    for item in tbca_items:
        # Descobre o grupo original via code ou name
        group_raw = (
            code_to_group.get(item.get("code", ""))
            or name_to_group.get(item.get("name", ""))
            or ""
        )
        new_cat = _map_group(group_raw)
        old_cat = item.get("category", "outros")

        if new_cat != old_cat:
            changed += 1

        item["category"] = new_cat
        # Atualiza default_portion_g com base na nova categoria
        item["default_portion_g"] = DEFAULT_PORTION.get(new_cat, 100)
        stats[new_cat] = stats.get(new_cat, 0) + 1

    TBCA_FILE.write_text(
        json.dumps(tbca_items, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"\nCategorias corrigidas ({changed} itens alterados):")
    for cat, n in sorted(stats.items(), key=lambda x: -x[1]):
        print(f"  {cat:25s}: {n:4d}")

    outros = stats.get("outros", 0)
    if outros:
        print(f"\nATENCAO: {outros} itens ainda em 'outros' — verificar grupos:")
        uncovered = set()
        for item in tbca_items:
            if item["category"] == "outros":
                group = (
                    code_to_group.get(item.get("code",""))
                    or name_to_group.get(item.get("name",""))
                    or "?"
                )
                uncovered.add(group)
        for g in sorted(uncovered):
            print(f"    '{g}'")
    else:
        print("\nOK: todos os itens categorizados corretamente!")

    print(f"\nArquivo atualizado: {TBCA_FILE}")


if __name__ == "__main__":
    main()
