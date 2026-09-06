"""
Importa a TBCA (Tabela Brasileira de Composição de Alimentos — USP/FoRC)
para o arquivo data/tbca.json, no mesmo schema de data/taco.json.

=== COMO USAR ===

1. Acesse: https://www.tbca.net.br/base-dados/composicao_estatistica.php
2. Clique em "Download" e baixe o Excel da versão mais recente (ex.: tbca_7.2.xlsx).
3. Coloque o arquivo na pasta data/ (ou passe o caminho via argumento).
4. Execute:

   python scripts/import_tbca.py
   # ou
   python scripts/import_tbca.py --input data/tbca_7.2.xlsx --output data/tbca.json

5. Reinicie o servidor para recarregar a base.

=== DEPENDÊNCIAS ===
   pip install pandas openpyxl

=== NOTAS ===
- Alimentos já existentes em data/taco.json NÃO são importados (evita duplicatas).
- Valores "Tr" (traço) e "ND" (não determinado) são convertidos para 0.
- A TACO tem prioridade sobre a TBCA no lookup; a TBCA preenche lacunas.
- O campo "aliases" é gerado automaticamente a partir do nome normalizado.
"""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"

# ─── Mapeamento de grupo TBCA → categoria interna ────────────────────────────
GROUP_MAP: dict[str, str] = {
    "cereais": "cereais_graos",
    "farinhas": "cereais_graos",
    "massas": "cereais_graos",
    "pães": "panificados",
    "paes": "panificados",
    "biscoitos": "panificados",
    "bolos": "panificados",
    "leguminosas": "leguminosas",
    "hortaliças": "hortalicas",
    "hortalicas": "hortalicas",
    "frutas": "frutas",
    "carnes": "carnes_bovinas",
    "bovinos": "carnes_bovinas",
    "suínos": "carnes_suinas",
    "suinos": "carnes_suinas",
    "aves": "carnes_aves",
    "peixes": "peixes",
    "frutos": "frutos_do_mar",
    "leites": "leite_derivados",
    "queijos": "leite_derivados",
    "iogurtes": "leite_derivados",
    "ovos": "ovos",
    "gorduras": "gorduras",
    "óleos": "gorduras",
    "oleos": "gorduras",
    "oleaginosas": "oleaginosas",
    "nozes": "oleaginosas",
    "castanhas": "oleaginosas",
    "bebidas": "bebidas",
    "sucos": "bebidas",
    "açúcares": "doces",
    "acucares": "doces",
    "doces": "doces",
    "sobremesas": "doces",
    "condimentos": "condimentos",
    "temperos": "condimentos",
    "molhos": "condimentos",
    "alimentos prontos": "pratos_tipicos",
    "pratos": "pratos_tipicos",
    "fast food": "industrializados",
    "industrializados": "industrializados",
    "preparações": "pratos_tipicos",
    "preparacoes": "pratos_tipicos",
}

# Tamanho de porção padrão por categoria (g)
DEFAULT_PORTION: dict[str, int] = {
    "cereais_graos": 150,
    "panificados": 50,
    "leguminosas": 140,
    "hortalicas": 80,
    "frutas": 100,
    "carnes_bovinas": 120,
    "carnes_suinas": 120,
    "carnes_aves": 120,
    "peixes": 150,
    "frutos_do_mar": 100,
    "leite_derivados": 200,
    "ovos": 60,
    "gorduras": 10,
    "oleaginosas": 30,
    "bebidas": 200,
    "doces": 50,
    "condimentos": 15,
    "pratos_tipicos": 250,
    "industrializados": 100,
}


def _normalize(text: str) -> str:
    text = text.lower().strip()
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _parse_float(val) -> float:
    """Converte células do Excel: 'Tr' → 0.0, 'ND' → 0.0, '' → 0.0."""
    if val is None:
        return 0.0
    s = str(val).strip().lower()
    if s in ("tr", "nd", "", "-", "nd*", "*"):
        return 0.0
    try:
        return float(s.replace(",", "."))
    except ValueError:
        return 0.0


def _map_group(group_str: str) -> str:
    g = _normalize(group_str)
    for key, cat in GROUP_MAP.items():
        if key in g:
            return cat
    return "outros"


def _make_aliases(name: str) -> list[str]:
    """Gera aliases básicos a partir do nome: nome normalizado + variante sem vírgulas."""
    aliases: list[str] = []
    norm = _normalize(name)
    if norm:
        aliases.append(norm)
    # Versão sem parte após vírgula (ex: "Arroz, branco, cozido" → "arroz")
    parts = [p.strip() for p in name.split(",")]
    if len(parts) > 1:
        short = _normalize(parts[0])
        if short and short not in aliases:
            aliases.append(short)
    return aliases


def _detect_columns(df) -> dict[str, str]:
    """
    Detecta automaticamente os nomes das colunas relevantes,
    que variam entre versões da TBCA.
    """
    cols = {c.strip(): c for c in df.columns}
    mapping: dict[str, str] = {}

    patterns = {
        "code":     [r"c[oó]digo", r"code", r"id"],
        "name":     [r"descri[cç][aã]o", r"nome", r"alimento", r"food"],
        "group":    [r"grupo", r"group", r"categoria"],
        "energy":   [r"energia.*kcal", r"kcal", r"energia"],
        "protein":  [r"prote[ií]na", r"protein"],
        "fat":      [r"lip[ií]d", r"gordura", r"fat"],
        "carb":     [r"carboidrat", r"carb"],
        "fiber":    [r"fibra", r"fiber"],
        "sodium":   [r"s[oó]dio", r"sodium", r"na\b"],
    }

    for field, pats in patterns.items():
        for col_raw, col_real in cols.items():
            col_norm = _normalize(col_raw)
            for pat in pats:
                if re.search(pat, col_norm):
                    mapping[field] = col_real
                    break
            if field in mapping:
                break

    return mapping


def import_tbca(input_path: Path, output_path: Path) -> None:
    try:
        import pandas as pd
    except ImportError:
        raise SystemExit("Instale pandas: pip install pandas openpyxl")

    print(f"Lendo {input_path} …")
    # Tenta todas as abas; a principal costuma ser a primeira com dados
    xls = pd.ExcelFile(input_path)
    df = None
    for sheet in xls.sheet_names:
        candidate = xls.parse(sheet, header=None)
        # Detecta a linha de cabeçalho: procura linha que contenha "Código" ou "Energia"
        for i, row in candidate.iterrows():
            row_str = " ".join(str(v).lower() for v in row.values if pd.notna(v))
            if any(kw in row_str for kw in ("código", "energia", "kcal", "proteína", "descri")):
                df = candidate.iloc[i + 1:].copy()
                df.columns = candidate.iloc[i].values
                df = df.reset_index(drop=True)
                print(f"  Aba '{sheet}', cabeçalho na linha {i}")
                break
        if df is not None:
            break

    if df is None:
        raise SystemExit(
            "Não foi possível detectar a tabela no Excel. "
            "Tente abrir o arquivo e identificar a aba correta, "
            "depois ajuste este script."
        )

    col = _detect_columns(df)
    print(f"  Colunas detectadas: {col}")

    required = ["name", "energy"]
    missing = [f for f in required if f not in col]
    if missing:
        raise SystemExit(
            f"Colunas obrigatórias não encontradas: {missing}\n"
            f"Colunas disponíveis: {list(df.columns)}"
        )

    # Carrega nomes já existentes no taco.json para evitar duplicatas semânticas
    taco_path = DATA_DIR / "taco.json"
    existing_names: set[str] = set()
    if taco_path.exists():
        taco_items = json.loads(taco_path.read_text(encoding="utf-8"))
        for item in taco_items:
            existing_names.add(_normalize(item["name"]))
            for alias in item.get("aliases", []):
                existing_names.add(_normalize(alias))
        print(f"  {len(taco_items)} alimentos TACO carregados (serão evitados duplicados)")

    tbca_items: list[dict] = []
    skipped_dup = 0
    skipped_empty = 0

    for _, row in df.iterrows():
        name_raw = str(row.get(col.get("name", ""), "")).strip()
        if not name_raw or name_raw.lower() in ("nan", "none", ""):
            skipped_empty += 1
            continue

        # Verifica duplicata com TACO
        if _normalize(name_raw) in existing_names:
            skipped_dup += 1
            continue

        code_raw = str(row.get(col.get("code", ""), "")).strip()
        code = f"tbca_{code_raw}" if code_raw and code_raw.lower() != "nan" else f"tbca_{len(tbca_items) + 1}"

        group_raw = str(row.get(col.get("group", ""), "")).strip()
        category = _map_group(group_raw) if group_raw and group_raw.lower() != "nan" else "outros"

        energy  = _parse_float(row.get(col.get("energy", ""), 0))
        protein = _parse_float(row.get(col.get("protein", ""), 0))
        fat     = _parse_float(row.get(col.get("fat", ""), 0))
        carb    = _parse_float(row.get(col.get("carb", ""), 0))
        fiber   = _parse_float(row.get(col.get("fiber", ""), 0))
        sodium  = _parse_float(row.get(col.get("sodium", ""), 0))

        # Ignora alimentos sem dados energéticos
        if energy == 0 and protein == 0 and carb == 0:
            skipped_empty += 1
            continue

        aliases = _make_aliases(name_raw)
        portion = DEFAULT_PORTION.get(category, 100)

        tbca_items.append({
            "code": code,
            "name": name_raw,
            "aliases": aliases,
            "category": category,
            "per_100g": {
                "calories_kcal": round(energy, 1),
                "protein_g":     round(protein, 1),
                "carb_g":        round(carb, 1),
                "fat_g":         round(fat, 1),
                "fiber_g":       round(fiber, 1),
                "sodium_mg":     round(sodium, 1),
            },
            "default_portion_g": portion,
            "source": "tbca",
        })

    output_path.write_text(
        json.dumps(tbca_items, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        f"\n✅ TBCA importada com sucesso!\n"
        f"   Itens importados : {len(tbca_items)}\n"
        f"   Pulados (dup TACO): {skipped_dup}\n"
        f"   Pulados (sem dados): {skipped_empty}\n"
        f"   Arquivo gerado   : {output_path}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Importa TBCA (USP) para data/tbca.json")
    parser.add_argument(
        "--input", "-i",
        default=str(DATA_DIR / "tbca.xlsx"),
        help="Caminho do Excel TBCA (padrão: data/tbca.xlsx)",
    )
    parser.add_argument(
        "--output", "-o",
        default=str(DATA_DIR / "tbca.json"),
        help="Arquivo de saída (padrão: data/tbca.json)",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        raise SystemExit(
            f"Arquivo não encontrado: {input_path}\n\n"
            "Baixe a TBCA em:\n"
            "  https://www.tbca.net.br/base-dados/composicao_estatistica.php\n"
            "e salve como data/tbca.xlsx (ou passe --input <caminho>)."
        )

    import_tbca(input_path, Path(args.output))


if __name__ == "__main__":
    main()
