from pydantic import BaseModel, EmailStr, field_validator


class RegisterRequest(BaseModel):
    name: str
    email: EmailStr
    password: str
    daily_calorie_goal: int | None = None

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 6:
            raise ValueError("Senha deve ter ao menos 6 caracteres")
        return v

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Nome não pode ser vazio")
        return v.strip()


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class AuthResponse(BaseModel):
    """Resposta de login/registro — o JWT é enviado APENAS via cookie httpOnly.
    Não incluímos o token no corpo da resposta para evitar que JS o leia e
    armazene em localStorage (vetor de ataque XSS)."""

    user_name: str
    ok: bool = True


# Alias retrocompatível — remover após atualizar todos os callers
TokenResponse = AuthResponse
