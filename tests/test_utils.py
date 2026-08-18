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
        key = "user:6"
        # Adiciona diretamente uma entrada antiga (há 2 segundos)
        import datetime as dt
        from unittest.mock import patch

        old_time = dt.datetime.utcnow() - dt.timedelta(seconds=2)
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
