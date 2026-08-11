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
        """Garante que a URL use o driver asyncpg (não psycopg2)."""
        if v.startswith("postgresql://"):
            v = "postgresql+asyncpg://" + v[len("postgresql://"):]
        return v

    # Telegram
    telegram_bot_token: str = ""
    telegram_webhook_secret: str = ""

    # WhatsApp (Z-API)
    zapi_instance_id: str = ""
    zapi_token: str = ""
    zapi_webhook_secret: str = ""

    # Mercado Pago
    mercadopago_access_token: str = ""
    mercadopago_webhook_secret: str = ""
    mercadopago_monthly_plan_id: str = ""
    mercadopago_annual_plan_id: str = ""

    # Segurança
    raw_input_encryption_key: str = "0" * 64  # placeholder — substituir em produção

    # Analytics
    posthog_api_key: str = ""
    posthog_host: str = "https://app.posthog.com"

    # Monitoramento
    sentry_dsn: str = ""

    # Aplicação
    app_env: str = "development"
    log_level: str = "INFO"
    maintenance_mode: bool = False
    default_timezone: str = "America/Sao_Paulo"

    # Rate limiting
    rate_limit_messages_per_minute: int = 10
    rate_limit_photos_per_hour: int = 10
    free_tier_max_logs_per_day: int = 3
    free_tier_history_days: int = 3


settings = Settings()
