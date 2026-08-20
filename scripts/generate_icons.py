#!/usr/bin/env python
"""
Gera os ícones PNG do NutriBot para PWA.

Uso:
    python scripts/generate_icons.py

Saída: app/static/icon-192.png e app/static/icon-512.png
"""
from pathlib import Path
from PIL import Image, ImageDraw

OUT = Path(__file__).parent.parent / "app" / "static"
OUT.mkdir(parents=True, exist_ok=True)

for size in (192, 512):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Fundo com gradiente simulado: círculo cheio com cor primária
    margin = size // 10
    d.ellipse([margin, margin, size - margin, size - margin], fill="#6366F1")

    # "N" central em branco
    font_size = int(size * 0.48)
    try:
        from PIL import ImageFont
        # Tenta fonte do sistema; fallback para default
        font = ImageFont.truetype("arial.ttf", font_size)
    except Exception:
        font = ImageFont.load_default()

    text = "N"
    # Calcula posição central
    bbox = d.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    tx = (size - tw) // 2 - bbox[0]
    ty = (size - th) // 2 - bbox[1]
    d.text((tx, ty), text, fill="white", font=font)

    path = OUT / f"icon-{size}.png"
    img.save(path, "PNG")
    print(f"✅ {path}")

print("Ícones gerados com sucesso!")
