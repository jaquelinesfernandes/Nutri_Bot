"""Endpoints de autenticação web — registro, login, logout."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.session import get_db
from app.models.user import User
from app.schemas.auth import AuthResponse, LoginRequest, RegisterRequest
from app.utils.jwt import create_access_token
from app.utils.rate_limiter import rate_limiter

router = APIRouter(prefix="/api/auth", tags=["auth"])
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

_COOKIE_MAX_AGE = settings.jwt_expire_days * 86_400  # segundos


def _set_auth_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        secure=settings.app_env == "production",
        samesite="lax",
        max_age=_COOKIE_MAX_AGE,
        path="/",
    )


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def register(
    body: RegisterRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> AuthResponse:
    # Rate limit: 5 registros por IP por hora (evita criação em massa)
    client_ip = request.client.host if request.client else "unknown"
    if not await rate_limiter.is_allowed(f"register:{client_ip}", max_requests=5, window_seconds=3600):
        raise HTTPException(status_code=429, detail="Muitas tentativas. Tente em 1 hora.")

    # Verifica e-mail duplicado
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="E-mail já cadastrado")

    user = User(
        channel_id=f"web:{body.email}",
        channel_type="web",
        email=body.email,
        password_hash=pwd_context.hash(body.password),
        first_name=body.name,
        daily_calorie_goal=body.daily_calorie_goal,
        onboarding_complete=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    token = create_access_token(user.id)
    _set_auth_cookie(response, token)
    # Token NÃO é retornado no body — apenas no cookie httpOnly (evita leitura por JS)
    return AuthResponse(user_name=user.first_name or body.name)


@router.post("/login", response_model=AuthResponse)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> AuthResponse:
    # Rate limit: 5 tentativas por IP por 5 minutos (anti-brute-force)
    client_ip = request.client.host if request.client else "unknown"
    if not await rate_limiter.is_allowed(f"login:{client_ip}", max_requests=5, window_seconds=300):
        raise HTTPException(status_code=429, detail="Muitas tentativas. Tente em 5 minutos.")

    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    # Anti-timing-attack: faz dummy_verify mesmo quando o usuário não existe,
    # para que o tempo de resposta seja igual quer o e-mail exista ou não.
    if not user or not user.password_hash:
        pwd_context.dummy_verify()
        raise HTTPException(status_code=401, detail="E-mail ou senha incorretos")
    if not pwd_context.verify(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="E-mail ou senha incorretos")
    if user.deleted_at is not None:
        raise HTTPException(status_code=403, detail="Conta desativada")

    token = create_access_token(user.id)
    _set_auth_cookie(response, token)
    return AuthResponse(user_name=user.first_name or body.email)


@router.post("/logout")
async def logout(response: Response) -> dict:
    response.delete_cookie("access_token", path="/")
    return {"message": "Logout realizado"}
