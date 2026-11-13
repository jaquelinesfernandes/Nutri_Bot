"""
Testes unitários para utils/* e services/payment.py.

Módulos cobertos:
  - app/utils/crypto.py        (0% → 100%)
  - app/utils/rate_limiter.py  (0% → 100%)
  - app/utils/timezone.py      (0% → 100%)
  - app/services/payment.py    (0% → ~80%)
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest
from cryptography.fernet import InvalidToken


# ─────────────────────────────────────────────────────────────────────────────
# crypto.py
# ─────────────────────────────────────────────────────────────────────────────

class TestCrypto:
    """Testes para encrypt/decrypt com Fernet (AES-256)."""

    def test_round_trip_simples(self):
        from app.utils.crypto import decrypt, encrypt
        original = "olá, mundo!"
        assert decrypt(encrypt(original)) == original

    def test_round_trip_string_vazia(self):
        from app.utils.crypto import decrypt, encrypt
        assert decrypt(encrypt("")) == ""

    def test_round_trip_texto_longo(self):
        from app.utils.crypto import decrypt, encrypt
        texto = "a" * 10_000
        assert decrypt(encrypt(texto)) == texto

    def test_round_trip_caracteres_especiais(self):
        from app.utils.crypto import decrypt, encrypt
        original = "comi arroz, feijão & frango! 🍗 (250g)"
        assert decrypt(encrypt(original)) == original

    def test_ciphertext_diferente_do_original(self):
        from app.utils.crypto import encrypt
        original = "segredo"
        assert encrypt(original) != original

    def test_cada_chamada_gera_token_diferente(self):
        """Fernet usa IV aleatório — dois encrypt do mesmo texto são diferentes."""
        from app.utils.crypto import encrypt
        texto = "mesmo texto"
        assert encrypt(texto) != encrypt(texto)

    def test_decrypt_token_invalido_lanca_excecao(self):
        from app.utils.crypto import decrypt
        with pytest.raises(InvalidToken):
            decrypt("token_invalido_base64")

    def test_decrypt_token_vazio_lanca_excecao(self):
        from app.utils.crypto import decrypt
        with pytest.raises(Exception):
            decrypt("")

    def test_dados_diferentes_geram_ciphertexts_diferentes(self):
        from app.utils.crypto import encrypt
        c1 = encrypt("texto a")
        c2 = encrypt("texto b")
        assert c1 != c2

    def test_decrypt_retorna_string_nao_bytes(self):
        from app.utils.crypto import decrypt, encrypt
        result = decrypt(encrypt("verificar tipo"))
        assert isinstance(result, str)


# ─────────────────────────────────────────────────────────────────────────────
# rate_limiter.py
# ─────────────────────────────────────────────────────────────────────────────

class TestRateLimiter:
    """Testes para RateLimiter — sliding window em memória."""

    @pytest.fixture(autouse=True)
    def fresh_limiter(self):
        """Cria instância nova para cada teste (evita estado compartilhado)."""
        from app.utils.rate_limiter import RateLimiter
        self.limiter = RateLimiter()

    @pytest.mark.asyncio
    async def test_primeira_requisicao_permitida(self):
        assert await self.limiter.is_allowed("user:1", max_requests=3, window_seconds=60) is True

    @pytest.mark.asyncio
    async def test_requisicoes_ate_o_limite_permitidas(self):
        for _ in range(5):
            result = await self.limiter.is_allowed("user:2", max_requests=5, window_seconds=60)
        assert result is True

    @pytest.mark.asyncio
    async def test_acima_do_limite_negado(self):
        key = "user:3"
        for _ in range(3):
            await self.limiter.is_allowed(key, max_requests=3, window_seconds=60)
        result = await self.limiter.is_allowed(key, max_requests=3, window_seconds=60)
        assert result is False

    @pytest.mark.asyncio
    async def test_chaves_diferentes_sao_independentes(self):
        # user:a esgota
        for _ in range(2):
            await self.limiter.is_allowed("user:a", max_requests=2, window_seconds=60)
        negado = await self.limiter.is_allowed("user:a", max_requests=2, window_seconds=60)
        # user:b ainda não foi usado
        permitido = await self.limiter.is_allowed("user:b", max_requests=2, window_seconds=60)
        assert negado is False
        assert permitido is True

    @pytest.mark.asyncio
    async def test_reset_libera_chave(self):
        key = "user:5"
        for _ in range(3):
            await self.limiter.is_allowed(key, max_requests=3, window_seconds=60)
        negado = await self.limiter.is_allowed(key, max_requests=3, window_seconds=60)
        assert negado is False

        await self.limiter.reset(key)
        liberado = await self.limiter.is_allowed(key, max_requests=3, window_seconds=60)
        assert liberado is True

    @pytest.mark.asyncio
    async def test_reset_chave_inexistente_nao_levanta_excecao(self):
        """reset() em chave nunca vista deve ser silencioso."""
        await self.limiter.reset("inexistente")  # não deve levantar

    @pytest.mark.asyncio
    async def test_janela_curta_expira_requisicoes_antigas(self):
        """Entradas fora da janela de 1 segundo devem ser ignoradas."""
        from datetime import datetime, timedelta, timezone
        key = "user:6"
        # Adiciona diretamente uma entrada antiga (há 2 segundos), timezone-aware
        old_time = datetime.now(timezone.utc) - timedelta(seconds=2)
        self.limiter._counts[key] = [old_time]

        # Com janela de 1 segundo, a entrada antiga deve ter expirado
        result = await self.limiter.is_allowed(key, max_requests=1, window_seconds=1)
        assert result is True  # janela expirou, trata como novo

    @pytest.mark.asyncio
    async def test_max_requests_um(self):
        """max_requests=1 permite 1 e bloqueia a segunda."""
        key = "user:7"
        assert await self.limiter.is_allowed(key, max_requests=1, window_seconds=60) is True
        assert await self.limiter.is_allowed(key, max_requests=1, window_seconds=60) is False

    # ── get_wait_seconds ──────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_get_wait_seconds_zero_para_chave_nova(self):
        """Chave sem histórico deve retornar 0."""
        result = await self.limiter.get_wait_seconds("nova_chave", 60)
        assert result == 0

    @pytest.mark.asyncio
    async def test_get_wait_seconds_positivo_com_entradas_na_janela(self):
        """Com requests na janela, retorna o tempo até o mais antigo expirar."""
        key = "wait:1"
        await self.limiter.is_allowed(key, max_requests=5, window_seconds=60)
        result = await self.limiter.get_wait_seconds(key, 60)
        # Deve ser ≈ 60 — o request acabou de entrar na janela de 60s
        assert 55 <= result <= 61

    @pytest.mark.asyncio
    async def test_get_wait_seconds_positivo_apos_bloqueio(self):
        """Depois de atingir o limite, get_wait_seconds deve retornar valor > 0."""
        key = "wait:2"
        for _ in range(3):
            await self.limiter.is_allowed(key, max_requests=3, window_seconds=60)
        # Agora bloqueado — get_wait_seconds deve indicar quanto esperar
        wait = await self.limiter.get_wait_seconds(key, 60)
        assert wait > 0
        assert wait <= 61  # nunca maior que a janela + 1 segundo

    @pytest.mark.asyncio
    async def test_get_wait_seconds_reflete_janela_correta(self):
        """Janela de 10s → tempo de espera nunca excede 11s."""
        key = "wait:3"
        for _ in range(2):
            await self.limiter.is_allowed(key, max_requests=2, window_seconds=10)
        wait = await self.limiter.get_wait_seconds(key, 10)
        assert 0 < wait <= 11

    @pytest.mark.asyncio
    async def test_get_wait_seconds_zero_apos_reset(self):
        """Após reset, chave bloqueada volta a retornar 0."""
        key = "wait:4"
        for _ in range(2):
            await self.limiter.is_allowed(key, max_requests=2, window_seconds=60)
        await self.limiter.reset(key)
        wait = await self.limiter.get_wait_seconds(key, 60)
        assert wait == 0

    @pytest.mark.asyncio
    async def test_requisicoes_concorrentes_nao_excedem_limite(self):
        """Coroutines concorrentes devem respeitar o limite total."""
        key = "user:concurrent"
        results = await asyncio.gather(*[
            self.limiter.is_allowed(key, max_requests=5, window_seconds=60)
            for _ in range(10)
        ])
        permitidas = sum(results)
        assert permitidas == 5


# ─────────────────────────────────────────────────────────────────────────────
# timezone.py
# ─────────────────────────────────────────────────────────────────────────────

class TestTimezone:
    """Testes para helpers de fuso horário e mapeamento de estados BR."""

    # ── get_timezone ──────────────────────────────────────────────────────────

    def test_get_timezone_iana_valido(self):
        from app.utils.timezone import get_timezone
        tz = get_timezone("America/Sao_Paulo")
        assert tz == ZoneInfo("America/Sao_Paulo")

    def test_get_timezone_iana_manaus(self):
        from app.utils.timezone import get_timezone
        tz = get_timezone("America/Manaus")
        assert tz == ZoneInfo("America/Manaus")

    def test_get_timezone_invalido_retorna_sao_paulo(self):
        from app.utils.timezone import get_timezone
        tz = get_timezone("Pais/CidadeInexistente")
        assert tz == ZoneInfo("America/Sao_Paulo")

    def test_get_timezone_string_vazia_retorna_sao_paulo(self):
        from app.utils.timezone import get_timezone
        tz = get_timezone("")
        assert tz == ZoneInfo("America/Sao_Paulo")

    # ── now_in_tz ─────────────────────────────────────────────────────────────

    def test_now_in_tz_retorna_datetime_aware(self):
        from app.utils.timezone import now_in_tz
        dt = now_in_tz("America/Sao_Paulo")
        assert dt.tzinfo is not None

    def test_now_in_tz_fuso_correto(self):
        from app.utils.timezone import now_in_tz
        dt = now_in_tz("America/Manaus")
        assert "Manaus" in str(dt.tzinfo) or dt.tzinfo == ZoneInfo("America/Manaus")

    def test_now_in_tz_invalido_usa_sao_paulo(self):
        from app.utils.timezone import now_in_tz
        dt = now_in_tz("Invalido/TZ")
        assert dt.tzinfo == ZoneInfo("America/Sao_Paulo")

    def test_now_in_tz_data_razoavel(self):
        """Ano retornado deve ser razoável (evita bug de epoch zero)."""
        from app.utils.timezone import now_in_tz
        dt = now_in_tz("America/Sao_Paulo")
        assert dt.year >= 2024

    # ── state_to_tz ───────────────────────────────────────────────────────────

    def test_sp_para_sao_paulo(self):
        from app.utils.timezone import state_to_tz
        assert state_to_tz("SP") == "America/Sao_Paulo"

    def test_rj_para_sao_paulo(self):
        from app.utils.timezone import state_to_tz
        assert state_to_tz("RJ") == "America/Sao_Paulo"

    def test_am_para_manaus(self):
        from app.utils.timezone import state_to_tz
        assert state_to_tz("AM") == "America/Manaus"

    def test_mt_para_manaus(self):
        from app.utils.timezone import state_to_tz
        assert state_to_tz("MT") == "America/Manaus"

    def test_ac_para_rio_branco(self):
        from app.utils.timezone import state_to_tz
        assert state_to_tz("AC") == "America/Rio_Branco"

    def test_fn_para_noronha(self):
        from app.utils.timezone import state_to_tz
        assert state_to_tz("FN") == "America/Noronha"

    def test_sigla_minuscula_funciona(self):
        from app.utils.timezone import state_to_tz
        assert state_to_tz("sp") == "America/Sao_Paulo"
        assert state_to_tz("am") == "America/Manaus"

    def test_sigla_desconhecida_retorna_sao_paulo(self):
        from app.utils.timezone import state_to_tz
        assert state_to_tz("ZZ") == "America/Sao_Paulo"

    def test_state_to_timezone_cobre_todos_estados_uf(self):
        """Todos os 26 estados + DF devem estar mapeados (mais FN = Fernando de Noronha)."""
        from app.utils.timezone import STATE_TO_TIMEZONE
        estados_obrigatorios = {
            "SP", "RJ", "MG", "ES", "PR", "SC", "RS",
            "GO", "DF", "TO", "BA", "SE", "AL", "PE",
            "PB", "RN", "CE", "PI", "MA", "PA", "AP",
            "RR", "AM", "RO", "MT", "MS", "AC", "FN",
        }
        mapeados = set(STATE_TO_TIMEZONE.keys())
        ausentes = estados_obrigatorios - mapeados
        assert not ausentes, f"Estados sem mapeamento: {ausentes}"

    def test_todos_tz_sao_validos(self):
        """Todos os valores do mapa devem ser timezones IANA válidos."""
        from app.utils.timezone import STATE_TO_TIMEZONE
        for estado, tz_str in STATE_TO_TIMEZONE.items():
            try:
                ZoneInfo(tz_str)
            except Exception:
                pytest.fail(f"Estado {estado} tem timezone inválido: {tz_str}")


# ─────────────────────────────────────────────────────────────────────────────
# payment.py
# ─────────────────────────────────────────────────────────────────────────────

class TestPaymentService:
    """Testes para PaymentService (stub — NotImplementedError esperado)."""

    def test_instancia_global_existe(self):
        from app.services.payment import payment_service, PaymentService
        assert isinstance(payment_service, PaymentService)

    def test_generate_checkout_link_nao_implementado(self):
        from app.services.payment import PaymentService
        svc = PaymentService()
        with pytest.raises(NotImplementedError):
            svc.generate_checkout_link("tg:12345", "premium_monthly")

    def test_generate_checkout_link_plano_anual(self):
        from app.services.payment import PaymentService
        svc = PaymentService()
        with pytest.raises(NotImplementedError):
            svc.generate_checkout_link("tg:99999", "premium_annual")

    @pytest.mark.asyncio
    async def test_handle_webhook_nao_implementado(self):
        from app.services.payment import PaymentService
        svc = PaymentService()
        with pytest.raises(NotImplementedError):
            await svc.handle_webhook({"action": "payment", "id": 123})

    @pytest.mark.asyncio
    async def test_handle_webhook_payload_vazio(self):
        from app.services.payment import PaymentService
        svc = PaymentService()
        with pytest.raises(NotImplementedError):
            await svc.handle_webhook({})


# ─────────────────────────────────────────────────────────────────────────────
# jwt.py
# ─────────────────────────────────────────────────────────────────────────────

class TestJWT:
    """Testes para create_access_token, create_magic_token, decode_magic_token, decode_token."""

    def test_create_access_token_retorna_string(self):
        import uuid
        from app.utils.jwt import create_access_token
        token = create_access_token(uuid.uuid4())
        assert isinstance(token, str)
        assert len(token) > 20

    def test_decode_token_roundtrip(self):
        import uuid
        from app.utils.jwt import create_access_token, decode_token
        uid = uuid.uuid4()
        token = create_access_token(uid)
        decoded = decode_token(token)
        assert decoded == uid

    def test_decode_token_invalido_retorna_none(self):
        from app.utils.jwt import decode_token
        assert decode_token("token.invalido.qualquer") is None

    def test_decode_token_vazio_retorna_none(self):
        from app.utils.jwt import decode_token
        assert decode_token("") is None

    def test_decode_token_sem_sub_retorna_none(self):
        """JWT sem campo 'sub' deve retornar None."""
        from jose import jwt as jose_jwt
        from app.config import settings
        from app.utils.jwt import ALGORITHM, decode_token
        from datetime import datetime, timedelta, timezone
        payload = {"exp": datetime.now(timezone.utc) + timedelta(hours=1)}
        token = jose_jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)
        assert decode_token(token) is None

    def test_create_magic_token_retorna_string(self):
        import uuid
        from app.utils.jwt import create_magic_token
        token = create_magic_token(uuid.uuid4(), minutes=10)
        assert isinstance(token, str)
        assert len(token) > 20

    def test_decode_magic_token_roundtrip(self):
        import uuid
        from app.utils.jwt import create_magic_token, decode_magic_token
        uid = uuid.uuid4()
        token = create_magic_token(uid, minutes=10)
        decoded = decode_magic_token(token)
        assert decoded == uid

    def test_decode_magic_token_invalido_retorna_none(self):
        from app.utils.jwt import decode_magic_token
        assert decode_magic_token("lixo.invalido.aqui") is None

    def test_decode_magic_token_rejeita_token_de_sessao(self):
        """Token de sessão normal (sem type='magic') não deve funcionar como magic link."""
        import uuid
        from app.utils.jwt import create_access_token, decode_magic_token
        session_token = create_access_token(uuid.uuid4())
        assert decode_magic_token(session_token) is None

    def test_decode_magic_token_tokens_diferentes(self):
        """Dois magic tokens criados em sequência devem ser diferentes (jti único)."""
        import uuid
        from app.utils.jwt import create_magic_token
        uid = uuid.uuid4()
        t1 = create_magic_token(uid)
        t2 = create_magic_token(uid)
        assert t1 != t2  # jti aleatório garante unicidade

    def test_access_token_e_magic_token_diferentes(self):
        """create_access_token e create_magic_token devem gerar tokens distintos para o mesmo user_id."""
        import uuid
        from app.utils.jwt import create_access_token, create_magic_token
        uid = uuid.uuid4()
        assert create_access_token(uid) != create_magic_token(uid)


# ─────────────────────────────────────────────────────────────────────────────
# models/user.py — propriedades calculadas
# ─────────────────────────────────────────────────────────────────────────────

class TestUserModel:
    """Testa as propriedades @property do modelo User diretamente (sem DB)."""

    # Chama o getter diretamente sobre um namespace simples, evitando SQLAlchemy.
    @staticmethod
    def _prop(prop_name, **attrs):
        from app.models.user import User
        from types import SimpleNamespace
        return getattr(User, prop_name).fget(SimpleNamespace(**attrs))

    # ── is_premium ────────────────────────────────────────────────────────────

    def test_is_premium_false_para_plano_free(self):
        assert self._prop("is_premium", plan="free", plan_expires_at=None) is False

    def test_is_premium_true_sem_data_de_expiracao(self):
        assert self._prop("is_premium", plan="premium", plan_expires_at=None) is True

    def test_is_premium_true_com_expiracao_futura(self):
        from datetime import datetime, timedelta, timezone
        future = datetime.now(timezone.utc) + timedelta(days=30)
        assert self._prop("is_premium", plan="premium", plan_expires_at=future) is True

    def test_is_premium_false_com_expiracao_passada(self):
        from datetime import datetime, timedelta, timezone
        past = datetime.now(timezone.utc) - timedelta(days=1)
        assert self._prop("is_premium", plan="premium", plan_expires_at=past) is False

    # ── is_nutritionist ───────────────────────────────────────────────────────

    def test_is_nutritionist_false_plano_diferente(self):
        assert self._prop(
            "is_nutritionist", plan="premium", trial_ends_at=None, plan_expires_at=None
        ) is False

    def test_is_nutritionist_true_trial_ativo(self):
        from datetime import datetime, timedelta, timezone
        future = datetime.now(timezone.utc) + timedelta(days=5)
        assert self._prop(
            "is_nutritionist", plan="nutritionist", trial_ends_at=future, plan_expires_at=None
        ) is True

    def test_is_nutritionist_false_trial_expirado(self):
        from datetime import datetime, timedelta, timezone
        past = datetime.now(timezone.utc) - timedelta(days=1)
        assert self._prop(
            "is_nutritionist", plan="nutritionist", trial_ends_at=past, plan_expires_at=None
        ) is False

    def test_is_nutritionist_true_sem_expiracao(self):
        assert self._prop(
            "is_nutritionist", plan="nutritionist", trial_ends_at=None, plan_expires_at=None
        ) is True

    def test_is_nutritionist_true_com_plano_ativo(self):
        from datetime import datetime, timedelta, timezone
        future = datetime.now(timezone.utc) + timedelta(days=30)
        assert self._prop(
            "is_nutritionist", plan="nutritionist", trial_ends_at=None, plan_expires_at=future
        ) is True

    def test_is_nutritionist_false_plano_expirado(self):
        from datetime import datetime, timedelta, timezone
        past = datetime.now(timezone.utc) - timedelta(days=1)
        assert self._prop(
            "is_nutritionist", plan="nutritionist", trial_ends_at=None, plan_expires_at=past
        ) is False

    # ── can_access_reports ────────────────────────────────────────────────────

    def test_can_access_reports_true_para_premium(self):
        from datetime import datetime, timezone
        from types import SimpleNamespace
        from app.models.user import User
        # is_premium pré-computado; created_at não é verificado nesse ramo
        u = SimpleNamespace(
            plan="premium", plan_expires_at=None, is_premium=True,
            created_at=datetime.now(timezone.utc)
        )
        assert User.can_access_reports.fget(u) is True

    def test_can_access_reports_true_sete_ou_mais_dias(self):
        from datetime import datetime, timedelta, timezone
        from types import SimpleNamespace
        from app.models.user import User
        u = SimpleNamespace(
            plan="free", plan_expires_at=None, is_premium=False,
            created_at=datetime.now(timezone.utc) - timedelta(days=7)
        )
        assert User.can_access_reports.fget(u) is True

    def test_can_access_reports_false_menos_de_sete_dias(self):
        from datetime import datetime, timedelta, timezone
        from types import SimpleNamespace
        from app.models.user import User
        u = SimpleNamespace(
            plan="free", plan_expires_at=None, is_premium=False,
            created_at=datetime.now(timezone.utc) - timedelta(days=6)
        )
        assert User.can_access_reports.fget(u) is False

    def test_repr_contem_channel_id_e_plan(self):
        from types import SimpleNamespace
        from app.models.user import User
        u = SimpleNamespace(channel_id="tg:12345", plan="premium")
        r = User.__repr__(u)
        assert "tg:12345" in r
        assert "premium" in r
