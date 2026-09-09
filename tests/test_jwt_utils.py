"""
Testes das funções utilitárias JWT — paths de sucesso e erro.

Cobre app/utils/jwt.py linhas não cobertas:
  - decode_magic_token: token inválido, tipo errado, sub ausente
  - decode_token: token inválido, sub ausente
  - create_magic_token: resultado decodificável com type='magic'
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from jose import jwt

from app.config import settings
from app.utils.jwt import (
    ALGORITHM,
    create_access_token,
    create_magic_token,
    decode_magic_token,
    decode_token,
)


class TestCreateAccessToken:
    def test_retorna_string(self):
        token = create_access_token(uuid.uuid4())
        assert isinstance(token, str) and len(token) > 10

    def test_payload_contem_sub(self):
        uid = uuid.uuid4()
        token = create_access_token(uid)
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
        assert payload["sub"] == str(uid)

    def test_nao_tem_campo_type(self):
        token = create_access_token(uuid.uuid4())
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
        assert "type" not in payload


class TestCreateMagicToken:
    def test_retorna_string(self):
        token = create_magic_token(uuid.uuid4())
        assert isinstance(token, str) and len(token) > 10

    def test_tipo_magic(self):
        uid = uuid.uuid4()
        token = create_magic_token(uid)
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
        assert payload["type"] == "magic"
        assert payload["sub"] == str(uid)
        assert "jti" in payload

    def test_expiracao_customizavel(self):
        token = create_magic_token(uuid.uuid4(), minutes=1)
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
        exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        now = datetime.now(timezone.utc)
        assert timedelta(seconds=50) < (exp - now) < timedelta(minutes=2)


class TestDecodeMagicToken:
    def test_sucesso(self):
        uid = uuid.uuid4()
        token = create_magic_token(uid)
        result = decode_magic_token(token)
        assert result == uid

    def test_token_invalido_retorna_none(self):
        assert decode_magic_token("token.invalido.aqui") is None

    def test_token_de_sessao_retorna_none(self):
        """Token de sessão (sem type='magic') deve ser rejeitado."""
        token = create_access_token(uuid.uuid4())
        assert decode_magic_token(token) is None

    def test_token_expirado_retorna_none(self):
        uid = uuid.uuid4()
        payload = {
            "sub": str(uid),
            "type": "magic",
            "exp": datetime.now(timezone.utc) - timedelta(seconds=1),
            "jti": str(uuid.uuid4()),
        }
        token = jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)
        assert decode_magic_token(token) is None

    def test_token_sem_sub_retorna_none(self):
        payload = {
            "type": "magic",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        }
        token = jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)
        assert decode_magic_token(token) is None

    def test_assinatura_errada_retorna_none(self):
        uid = uuid.uuid4()
        token = create_magic_token(uid)
        # Corrompe a assinatura trocando o secret
        partes = token.split(".")
        outro = jwt.encode({"sub": str(uid), "type": "magic"}, "outro-secret", algorithm=ALGORITHM)
        token_corrompido = ".".join(partes[:2]) + "." + outro.split(".")[2]
        assert decode_magic_token(token_corrompido) is None


class TestDecodeToken:
    def test_sucesso(self):
        uid = uuid.uuid4()
        token = create_access_token(uid)
        assert decode_token(token) == uid

    def test_token_invalido_retorna_none(self):
        assert decode_token("lixo") is None

    def test_token_expirado_retorna_none(self):
        uid = uuid.uuid4()
        payload = {
            "sub": str(uid),
            "exp": datetime.now(timezone.utc) - timedelta(seconds=1),
        }
        token = jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)
        assert decode_token(token) is None

    def test_token_sem_sub_retorna_none(self):
        payload = {"exp": datetime.now(timezone.utc) + timedelta(hours=1)}
        token = jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)
        assert decode_token(token) is None

    def test_token_com_sub_invalido_retorna_none(self):
        """UUID inválido no campo sub levanta ValueError → retorna None."""
        payload = {
            "sub": "nao-e-uuid",
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        }
        token = jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)
        assert decode_token(token) is None
