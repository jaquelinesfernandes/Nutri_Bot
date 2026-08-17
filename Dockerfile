FROM python:3.13-slim-bookworm

# WeasyPrint requer Pango/Cairo para geração de PDF
# Pinado em bookworm (Debian 12) para evitar quebras de pacote no rolling tags
RUN apt-get update --fix-missing && apt-get install -y --no-install-recommends \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf2.0-0 \
    libcairo2 \
    libcairo-gobject2 \
    libharfbuzz0b \
    libffi-dev \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Usuário não-root para segurança
RUN useradd -m -u 1000 nutribot && chown -R nutribot:nutribot /app
USER nutribot

EXPOSE 8000

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
