from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

engine = create_async_engine(
    settings.database_url,
    pool_size=3,       # Neon free tier: limite de 10 conexões simultâneas
    max_overflow=5,    # máximo total: 8 — margem segura abaixo do limite
    pool_timeout=30,
    pool_recycle=1800, # reconectar após 30 min (evita conexões zumbis)
    echo=settings.app_env == "development",
)

AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
