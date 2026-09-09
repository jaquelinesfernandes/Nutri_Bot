"""
Scraper da TBCA — Tabela Brasileira de Composição de Alimentos (USP/FoRC)
https://www.tbca.net.br/base-dados/composicao_estatistica.php

Percorre as 20 páginas de listagem, coleta os links de detalhe de cada alimento
e extrai os valores nutricionais por 100g de cada item.

Saída: data/tbca.json — mesmo schema de data/taco.json
       data/tbca_raw.json — dados brutos (para debug/inspeção)

Uso:
    python scripts/scrape_tbca.py
    python scripts/scrape_tbca.py --paginas 1-5        # só páginas 1 a 5 (teste)
    python scripts/scrape_tbca.py --delay 1.5          # delay entre requests (padrão: 1.0s)
    python scripts/scrape_tbca.py --retomar            # retoma do ponto onde parou
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import time
import unicodedata
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ─── Configuração ─────────────────────────────────────────────────────────────
BASE_URL  = "https://www.tbca.net.br/base-dados/"
LIST_URL  = BASE_URL + "composicao_estatistica.php"
TOTAL_PAGES = 20
DATA_DIR  = Path(__file__).parent.parent / "data"
RAW_FILE  = DATA_DIR / "tbca_raw.json"
OUT_FILE  = DATA_DIR / "tbca.json"
TACO_FILE = DATA_DIR / "taco.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("scrape_tbca")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9",
}

# ─── Mapeamento grupo TBCA → categoria interna ───────────────────────────────
GROUP_MAP: dict[str, str] = {
    # Grupos reais da TBCA (verificados via scraping):
    # "Vegetais e derivados", "Cereais e derivados", "Carnes e derivados",
    # "Frutas e derivados", "Alimentos industrializados", "Pescados e frutos do mar",
    # "Leite e derivados", "Açúcares e doces", "Alimentos para fins especiais",
    # "Leguminosas e derivados", "Gorduras e óleos", "Bebidas",
    # "Miscelâneas", "Ovos e derivados", "Nozes e sementes"
    "vegetais":               "hortalicas",
    "hortali":                "hortalicas",
    "cereais":                "cereais_graos",
    "massas":                 "cereais_graos",
    "farinhas":               "cereais_graos",
    "paes":                   "panificados",
    "biscoitos":              "panificados",
    "bolos":                  "panificados",
    "panificados":            "panificados",
    "carnes":                 "carnes_bovinas",
    "bovinos":                "carnes_bovinas",
    "suinos":                 "carnes_suinas",
    "aves":                   "carnes_aves",
    "frutas":                 "frutas",
    "alimentos industrializ": "industrializados",
    "fins especiais":         "industrializados",
    "industrializados":       "industrializados",
    "fast food":              "industrializados",
    "pescados":               "peixes",
    "peixes":                 "peixes",
    "frutos do mar":          "frutos_do_mar",
    "frutos":                 "frutos_do_mar",
    "leite":                  "leite_derivados",
    "laticinios":             "leite_derivados",
    "queijos":                "leite_derivados",
    "iogurtes":               "leite_derivados",
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
    "castanhas":              "oleaginosas",
    "miscelaneas":            "pratos_tipicos",
    "preparacoes":            "pratos_tipicos",
    "pratos":                 "pratos_tipicos",
    "alimentos prontos":      "pratos_tipicos",
    "condimentos":            "condimentos",
    "temperos":               "condimentos",
    "molhos":                 "condimentos",
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

# ─── Nutrientes que queremos extrair ─────────────────────────────────────────
# Mapeamento: fragmento de texto na coluna "Componente" → campo interno
NUTRIENT_MAP: dict[str, str] = {
    # Energia — pega somente kcal
    "energia": "_energy_raw",
    # Macros
    "proteína":        "protein_g",
    "proteina":        "protein_g",
    "lipídio":         "fat_g",
    "lipidio":         "fat_g",
    "gordura total":   "fat_g",
    "carboidrato":     "carb_g",
    "fibra":           "fiber_g",
    # Sódio
    "sódio":           "sodium_mg",
    "sodio":           "sodium_mg",
}


# ─── Helpers ──────────────────────────────────────────────────────────────────
def _normalize(text: str) -> str:
    t = text.lower().strip()
    t = unicodedata.normalize("NFD", t)
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = re.sub(r"[^\w\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _parse_float(val: str) -> float:
    """'Tr', 'NA', 'ND', '*', '' → 0.0; '1.234,5' → 1234.5"""
    s = str(val).strip().lower()
    if not s or s in ("tr", "na", "nd", "*", "nd*", "-", "—"):
        return 0.0
    # Remove separador de milhar (ponto) e troca vírgula decimal por ponto
    s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _map_group(group_str: str) -> str:
    g = _normalize(group_str)
    for key, cat in GROUP_MAP.items():
        if key in g:
            return cat
    return "outros"


def _make_aliases(name: str) -> list[str]:
    aliases: list[str] = []
    norm = _normalize(name)
    if norm:
        aliases.append(norm)
    # Versão truncada antes da primeira vírgula
    parts = [p.strip() for p in name.split(",")]
    if len(parts) > 1:
        short = _normalize(parts[0])
        if short and short not in aliases:
            aliases.append(short)
    return aliases


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


# ─── Etapa 1: coletar links de detalhe ───────────────────────────────────────
def collect_detail_links(
    session: requests.Session,
    pages: range,
    delay: float,
) -> list[dict]:
    """Retorna lista de {code, name, group, url} para cada alimento."""
    items: list[dict] = []
    seen_urls: set[str] = set()

    for page in pages:
        url = f"{LIST_URL}?pagina={page}&atuald=2"
        log.info(f"[{page}/{pages[-1]}] Listagem: {url}")

        try:
            resp = session.get(url, timeout=20)
            resp.raise_for_status()
        except Exception as e:
            log.warning(f"  Erro na página {page}: {e} — pulando")
            time.sleep(delay * 2)
            continue

        soup = BeautifulSoup(resp.text, "html.parser")

        # A tabela de alimentos — linhas com link de detalhe
        for a_tag in soup.find_all("a", href=re.compile(r"int_composicao_estatistica")):
            href = a_tag.get("href", "")
            full_url = BASE_URL + href if not href.startswith("http") else href
            if full_url in seen_urls:
                continue
            seen_urls.add(full_url)

            # Pega o tr pai para extrair código, nome, grupo
            tr = a_tag.find_parent("tr")
            if not tr:
                continue
            cells = tr.find_all("td")
            if len(cells) < 2:
                continue

            texts = [c.get_text(strip=True) for c in cells]
            code  = texts[0] if len(texts) > 0 else ""
            name  = texts[1] if len(texts) > 1 else a_tag.get_text(strip=True)
            group = texts[3] if len(texts) > 3 else ""

            items.append({
                "code":  code,
                "name":  name,
                "group": group,
                "url":   full_url,
            })

        log.info(f"  → {len(items)} alimentos coletados até agora")
        time.sleep(delay)

    return items


# ─── Etapa 2: raspar nutrientes da página de detalhe ─────────────────────────
def scrape_nutrients(session: requests.Session, detail_url: str) -> dict | None:
    """
    Retorna dicionário com:
        calories_kcal, protein_g, carb_g, fat_g, fiber_g, sodium_mg
    ou None se falhar.
    """
    try:
        resp = session.get(detail_url, timeout=20)
        resp.raise_for_status()
    except Exception as e:
        log.debug(f"  Erro detail {detail_url}: {e}")
        return None

    soup = BeautifulSoup(resp.text, "html.parser")

    result: dict[str, float] = {
        "calories_kcal": 0.0,
        "protein_g":     0.0,
        "carb_g":        0.0,
        "fat_g":         0.0,
        "fiber_g":       0.0,
        "sodium_mg":     0.0,
    }

    # Percorre todas as linhas de tabela
    for tr in soup.find_all("tr"):
        cells = tr.find_all("td")
        if len(cells) < 4:
            continue

        componente = cells[0].get_text(strip=True).lower()
        unidade    = cells[2].get_text(strip=True).lower() if len(cells) > 2 else ""
        valor_str  = cells[3].get_text(strip=True)          if len(cells) > 3 else "0"

        # Energia — queremos kcal, não kJ
        if "energia" in componente:
            # Se esta linha é kcal ou a unidade contém kcal
            if "kcal" in unidade or "kcal" in componente:
                result["calories_kcal"] = _parse_float(valor_str)
            # Às vezes energia vem em duas sub-linhas (kJ e kcal);
            # a linha com kJ é ignorada quando unidade contém kJ
            continue

        comp_norm = _normalize(componente)
        for key, field in NUTRIENT_MAP.items():
            if field == "_energy_raw":
                continue
            if key in comp_norm:
                # Evita sobrescrever com zero se já temos valor
                val = _parse_float(valor_str)
                if val > 0 or result.get(field, 0) == 0:
                    result[field] = val
                break

    return result


# ─── Etapa 3: montar item final ───────────────────────────────────────────────
def build_item(meta: dict, nutrients: dict) -> dict:
    code     = meta["code"] or f"tbca_{meta['name'][:8]}"
    category = _map_group(meta["group"])
    portion  = DEFAULT_PORTION.get(category, 100)

    return {
        "code":    f"tbca_{code}",
        "name":    meta["name"],
        "aliases": _make_aliases(meta["name"]),
        "category": category,
        "per_100g": {
            "calories_kcal": round(nutrients.get("calories_kcal", 0.0), 1),
            "protein_g":     round(nutrients.get("protein_g",     0.0), 1),
            "carb_g":        round(nutrients.get("carb_g",        0.0), 1),
            "fat_g":         round(nutrients.get("fat_g",         0.0), 1),
            "fiber_g":       round(nutrients.get("fiber_g",       0.0), 1),
            "sodium_mg":     round(nutrients.get("sodium_mg",     0.0), 1),
        },
        "default_portion_g": portion,
        "source": "tbca",
    }


# ─── Main ─────────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(description="Scraper TBCA → data/tbca.json")
    parser.add_argument(
        "--paginas", default=f"1-{TOTAL_PAGES}",
        help=f"Intervalo de páginas (padrão: 1-{TOTAL_PAGES}, ex: 1-5 para teste)",
    )
    parser.add_argument(
        "--delay", type=float, default=1.0,
        help="Delay entre requests em segundos (padrão: 1.0)",
    )
    parser.add_argument(
        "--retomar", action="store_true",
        help="Retoma importação usando tbca_raw.json já existente (pula coleta de links)",
    )
    args = parser.parse_args()

    # Parse do intervalo de páginas
    m = re.match(r"(\d+)-(\d+)", args.paginas)
    if m:
        pages = range(int(m.group(1)), int(m.group(2)) + 1)
    else:
        pages = range(1, TOTAL_PAGES + 1)

    # Carrega nomes existentes no TACO para evitar duplicatas
    existing_names: set[str] = set()
    if TACO_FILE.exists():
        taco_items = json.loads(TACO_FILE.read_text(encoding="utf-8"))
        for item in taco_items:
            existing_names.add(_normalize(item["name"]))
            for alias in item.get("aliases", []):
                existing_names.add(_normalize(alias))
        log.info(f"TACO: {len(taco_items)} itens carregados — serão evitados duplicados")

    session = _session()

    # ── Etapa 1: coletar links ────────────────────────────────────────────────
    if args.retomar and RAW_FILE.exists():
        log.info(f"Retomando: lendo links de {RAW_FILE}")
        all_meta = json.loads(RAW_FILE.read_text(encoding="utf-8"))
        log.info(f"  {len(all_meta)} links carregados do arquivo existente")
    else:
        log.info(f"=== Etapa 1: coletando links (páginas {pages[0]}–{pages[-1]}) ===")
        all_meta = collect_detail_links(session, pages, args.delay)
        RAW_FILE.write_text(
            json.dumps(all_meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        log.info(f"Links salvos em {RAW_FILE} ({len(all_meta)} alimentos)")

    # ── Etapa 2: raspar nutrientes ────────────────────────────────────────────
    log.info(f"=== Etapa 2: extraindo nutrientes de {len(all_meta)} alimentos ===")
    tbca_items: list[dict] = []
    skipped_dup   = 0
    skipped_empty = 0
    errors        = 0

    for i, meta in enumerate(all_meta, 1):
        name = meta.get("name", "")
        if not name:
            skipped_empty += 1
            continue

        # Pula duplicatas com TACO
        if _normalize(name) in existing_names:
            skipped_dup += 1
            log.debug(f"  [{i}/{len(all_meta)}] SKIP dup: {name}")
            continue

        log.info(f"  [{i}/{len(all_meta)}] {name}")
        nutrients = scrape_nutrients(session, meta["url"])

        if nutrients is None:
            errors += 1
            log.warning(f"  Falha ao obter nutrientes: {name}")
            time.sleep(args.delay * 2)
            continue

        # Pula se não tem nenhum dado nutricional
        if all(v == 0.0 for v in nutrients.values()):
            skipped_empty += 1
            log.debug(f"  [{i}] sem dados: {name}")
            continue

        item = build_item(meta, nutrients)
        tbca_items.append(item)

        # Salva progressivamente a cada 50 itens
        if len(tbca_items) % 50 == 0:
            OUT_FILE.write_text(
                json.dumps(tbca_items, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            log.info(f"  [checkpoint] {len(tbca_items)} itens salvos")

        time.sleep(args.delay)

    # ── Salva resultado final ─────────────────────────────────────────────────
    OUT_FILE.write_text(
        json.dumps(tbca_items, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    msg = (
        f"\n{'='*55}\n"
        f"OK TBCA scraping concluido!\n"
        f"   Itens importados   : {len(tbca_items)}\n"
        f"   Pulados (dup TACO) : {skipped_dup}\n"
        f"   Pulados (sem dados): {skipped_empty}\n"
        f"   Erros de rede      : {errors}\n"
        f"   Arquivo gerado     : {OUT_FILE}\n"
        f"   Raw (links)        : {RAW_FILE}\n"
        f"{'='*55}\n"
        f"Proximo passo: reinicie o servidor para recarregar a base."
    )
    # Usa sys.stdout com utf-8 para evitar UnicodeEncodeError no Windows
    import sys
    sys.stdout.buffer.write(msg.encode("utf-8"))
    sys.stdout.buffer.write(b"\n")
    sys.stdout.buffer.flush()


if __name__ == "__main__":
    main()
