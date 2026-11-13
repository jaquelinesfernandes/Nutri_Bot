import asyncio
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import settings
from app.db.base import Base
import app.models  # noqa: F401 — registra todos os models no metadata

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _sync_url(url: str) -> str:
    """Converte a URL asyncpg para psycopg2 (usado em migrações no Windows)."""
    from urllib.parse import urlparse, urlencode, urlunparse, parse_qsl
    parsed = urlparse(url)
    scheme = "postgresql+psycopg2"
    params = dict(parse_qsl(parsed.query))
    params.pop("ssl", None)
    new_query = urlencode(params)
    return urlunparse(parsed._replace(scheme=scheme, query=new_query))


def run_migrations_offline() -> None:
    url = settings.database_url
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_sync() -> None:
    """Usado no Windows onde asyncpg tem problemas de socket com Docker."""
    import os
    from urllib.parse import urlparse
    import sqlalchemy

    # libpq no Windows usa a code page do sistema (CP1252 em PT-BR).
    # Forçamos UTF-8 para psycopg2 conseguir decodificar as mensagens de erro.
    os.environ.setdefault("PGCLIENTENCODING", "utf8")
    os.environ.setdefault("PYTHONUTF8", "1")

    parsed = urlparse(settings.database_url)
    connect_args = {
        "host": parsed.hostname,
        "port": parsed.port or 5432,
        "dbname": parsed.path.lstrip("/"),
        "user": parsed.username,
        "password": parsed.password,
    }

    def _connect():
        import psycopg2
        conn = psycopg2.connect(**connect_args)
        conn.set_client_encoding("UTF8")
        return conn

    engine = sqlalchemy.create_engine(
        "postgresql+psycopg2://",
        creator=_connect,
        poolclass=pool.NullPool,
    )
    with engine.connect() as connection:
        do_run_migrations(connection)
    engine.dispose()


async def run_migrations_online() -> None:
    engine = create_async_engine(settings.database_url)
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
elif sys.platform == "win32":
    run_migrations_sync()
else:
    asyncio.run(run_migrations_online())
