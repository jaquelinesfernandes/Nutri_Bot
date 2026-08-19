from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Anthropic (Claude) — NLP + Vision
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-haiku-4-5-20251001"
    anthropic_vision_model: str = "claude-sonnet-4-6"

    # OpenAI — apenas Whisper (áudio, Sprint 2)
    openai_api_key: str = ""
    openai_whisper_model: str = "whisper-1"

    # Banco de dados
    database_url: str = "postgresql+asyncpg://user:pass@localhost/nutribot"

    @field_validator("database_url")
    @classmethod
    def coerce_async_db_url(cls, v: str) -> str:
        """Normaliza a DATABASE_URL para ser compatível com asyncpg.

        Converte automaticamente URLs coladas do Neon ou Railway sem edição manual:
        - postgresql://  →  postgresql+asyncpg://
        - sslmode=require  →  ssl=require  (asyncpg não aceita parâmetro libpq)
        - remove channel_binding=require  (parâmetro libpq não suportado por asyncpg)
        """
        from urllib.parse import urlparse, urlencode, urlunparse, parse_qsl

        # 1. Driver prefix
        if v.startswith("postgresql://"):
            v = "postgresql+asyncpg://" + v[len("postgresql://"):]

        # 2. Normalizar query string — remover/converter parâmetros incompatíveis
        parsed = urlparse(v)
        params = dict(parse_qsl(parsed.query))

        # sslmode (libpq) → ssl (asyncpg)
        if "sslmode" in params:
            sslmode = params.pop("sslmode")
            if sslmode in ("require", "verify-full", "verify-ca"):
                params.setdefault("ssl", "require")
            elif sslmode == "prefer":
                params.setdefault("ssl", "prefer")
            # sslmode=disable → não adiciona ssl

        # channel_binding é parâmetro libpq — asyncpg não reconhece
        params.pop("channel_binding", None)

        new_query = urlencode(params)
        return urlunparse(parsed._replace(query=new_query))

    # Telegram
    telegram_bot_token: str = ""
    telegram_webhook_secret: str = ""

    # WhatsApp (Evolution API)
    evolution_api_url: str = ""        # ex: https://evolution-api.onrender.com
    evolution_api_instance: str = ""   # nome da instância criada no Evolution
    evolution_api_key: str = ""        # API key global configurada no Evolution
    evolution_webhook_secret: str = "" # secret para validar webhooks recebidos

    # Mercado Pago
    mercadopago_access_token: str = ""
    mercadopago_webhook_secret: str = ""
    mercadopago_monthly_plan_id: str = ""
    mercadopago_annual_plan_id: str = ""

    # JWT / autenticação web
    jwt_secret: str = "change-me-in-production-use-32-chars-min"
    jwt_expire_days: int = 7

    # Segurança
    raw_input_encryption_key: str = "0" * 64  # placeholder — substituir em produção

    # Analytics
    posthog_api_key: str = ""
    posthog_host: str = "https://app.posthog.com"

    # Monitoramento
    sentry_dsn: str = ""

    # Aplicação
    app_env: str = "development"
    app_url: str = "https://nutri-bot-ot0p.onrender.com"  # URL pública — sobrescreva com APP_URL no Render
    webhook_base_url: str = ""        # fallback legado (WEBHOOK_BASE_URL)
    log_level: str = "INFO"
    maintenance_mode: bool = False
    default_timezone: str = "America/Sao_Paulo"

    # Rate limiting
    rate_limit_messages_per_minute: int = 10
    rate_limit_photos_per_hour: int = 10
    free_tier_max_logs_per_day: int = 3
    free_tier_history_days: int = 3


settings = Settings()
