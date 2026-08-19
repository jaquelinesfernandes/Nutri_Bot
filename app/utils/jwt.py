"""Utilitários JWT para autenticação web do NutriBot."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import Cookie, Depends, HTTPException, status
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.session import get_db

ALGORITHM = "HS256"


def create_access_token(user_id: uuid.UUID) -> str:
    """Cria JWT com expiração configurada em jwt_expire_days."""
    expire = datetime.now(timezone.utc) + timedelta(days=settings.jwt_expire_days)
    payload = {"sub": str(user_id), "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def decode_token(token: str) -> uuid.UUID | None:
    """Decodifica o JWT e retorna o user_id, ou None se inválido/expirado."""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
        sub = payload.get("sub")
        if sub is None:
            return None
        return uuid.UUID(sub)
    except (JWTError, ValueError):
        return None


async def get_current_user(
    access_token: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Dependência FastAPI — exige usuário autenticado (lê cookie httpOnly)."""
    from app.models.user import User

    if not access_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Não autenticado",
        )
    user_id = decode_token(access_token)
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido ou expirado",
        )
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or user.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuário não encontrado",
        )
    return user


async def get_current_user_optional(
    access_token: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Dependência FastAPI — retorna usuário ou None (para páginas com redirect)."""
    if not access_token:
        return None
    user_id = decode_token(access_token)
    if user_id is None:
        return None
    from app.models.user import User
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    return user if (user and user.deleted_at is None) else None
