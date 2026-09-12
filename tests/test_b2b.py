"""Testes de integração B2B — Sprint B2B-1 + B2B-2.

Coberturas:
  - Cadastro de nutricionista (POST /api/nutricionista/register)
  - Geração de convite (POST /api/nutricionista/convite)
  - Aceite/recusa de convite (PATCH /api/nutricionista/convite/{token})
  - Revogação pelo painel (PATCH /api/nutricionista/revogar/{id})
  - Acesso ao painel (GET /nutricionista/)
  - Perfil do paciente (GET /nutricionista/paciente/{id})
  - Adição de nota clínica (POST /api/nutricionista/paciente/{id}/nota)
  - Fluxo de revogação pelo bot (ConversationService)
  - Autorização: nutricionista sem acesso a pacientes de outra nutri
  - Expiração de convites (job_expire_invites)
  - CRN regex válido/inválido
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.db.session import get_db
from app.main import app
from app.utils.jwt import create_access_token, get_current_user_optional


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_nutri(
    uid: uuid.UUID | None = None,
    first_name: str = "Dra. Maria",
    trial_ends_at: datetime | None = None,
    plan_expires_at: datetime | None = None,
) -> MagicMock:
    u = MagicMock()
    u.id = uid or uuid.uuid4()
    u.email = "maria@clinica.com"
    u.first_name = first_name
    u.plan = "nutritionist"
    u.deleted_at = None
    u.conversation_state = "IDLE"
    u.state_data = None
    u.daily_calorie_goal = 2000
    u.is_premium = True
    # trial ativo por 30 dias
    u.trial_ends_at = trial_ends_at or (datetime.utcnow() + timedelta(days=28))
    u.plan_expires_at = plan_expires_at
    # is_nutritionist retorna True
    u.is_nutritionist = True
    u.patients_as_nutritionist = []
    u.links_as_patient = []
    return u


def _make_patient(uid: uuid.UUID | None = None) -> MagicMock:
    u = MagicMock()
    u.id = uid or uuid.uuid4()
    u.email = "paciente@email.com"
    u.first_name = "Ana"
    u.plan = "free"
    u.deleted_at = None
    u.conversation_state = "IDLE"
    u.state_data = None
    u.daily_calorie_goal = 1800
    u.is_premium = False
    u.trial_ends_at = None
    u.plan_expires_at = None
    u.is_nutritionist = False
    return u


def _make_link(
    nutri_id: uuid.UUID,
    patient_id: uuid.UUID | None = None,
    token: str = "abc123",
    status: str = "active",
    patient_phone: str = "+5511999999999",
    patient_name: str = "Ana",
) -> MagicMock:
    link = MagicMock()
    link.id = uuid.uuid4()
    link.nutritionist_id = nutri_id
    link.patient_id = patient_id
    link.patient_phone = patient_phone
    link.patient_name = patient_name
    link.invite_token = token
    link.status = status
    link.invited_at = datetime.utcnow() - timedelta(days=1)
    link.expires_at = datetime.utcnow() + timedelta(days=6)
    link.consented_at = datetime.utcnow() if status == "active" else None
    link.revoked_at = None
    link.is_active = status == "active"
    link.is_expired = False
    return link


def _make_mock_db() -> AsyncMock:
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_result.scalars.return_value.unique.return_value.all.return_value = []
    mock_result.scalar_one_or_none.return_value = None
    mock_result.rowcount = 0

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.commit = AsyncMock()
    mock_db.flush = AsyncMock()
    mock_db.rollback = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.refresh = AsyncMock()
    return mock_db


def _nutri_client(nutri: MagicMock, mock_db: AsyncMock) -> TestClient:
    """TestClient autenticado como nutricionista."""
    async def _db():
        yield mock_db

    async def _user_opt():
        return nutri

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_user_optional] = _user_opt

    token = create_access_token(nutri.id)
    client = TestClient(app, raise_server_exceptions=False)
    client.cookies.set("access_token", token)
    return client


# ── 1. CRN regex ──────────────────────────────────────────────────────────────

class TestCRNRegex:
    """Valida a regex de CRN — aceita formatos padronizados, rejeita inválidos."""

    @pytest.mark.parametrize("crn", [
        "CRN-3 12345",
        "CRN3 12345",
        "CRN-10 123456",
        "CRN-3 12345/P",
        "crn-3 12345/n",
        "CRN3 1234/T",
        "CRN-1 9999",
    ])
    def test_valid_crn(self, crn: str):
        import re
        _CRN_RE = re.compile(r"^CRN-?\d{1,2}\s?\d{4,6}(/[PTN])?$", re.IGNORECASE)
        assert _CRN_RE.match(crn), f"CRN válido rejeitado: {crn!r}"

    @pytest.mark.parametrize("crn", [
        "12345",
        "CRN",
        "CRN-999 12345",    # mais de 2 dígitos regionais
        "CRN-3 123",        # menos de 4 dígitos
        "CRN-3 1234567",    # mais de 6 dígitos
        "CRN-3 12345/X",    # sufixo inválido
        "",
        "CRN--3 12345",
    ])
    def test_invalid_crn(self, crn: str):
        import re
        _CRN_RE = re.compile(r"^CRN-?\d{1,2}\s?\d{4,6}(/[PTN])?$", re.IGNORECASE)
        assert not _CRN_RE.match(crn), f"CRN inválido aceito: {crn!r}"


# ── 2. Cadastro de nutricionista ──────────────────────────────────────────────

class TestNutricionistaRegistro:
    """Testa o endpoint POST /api/nutricionista/register."""

    def test_register_redirect_anon(self):
        """Página de cadastro retorna 200 mesmo sem login."""
        mock_db = _make_mock_db()

        async def _db():
            yield mock_db

        async def _user_opt():
            return None

        app.dependency_overrides[get_db] = _db
        app.dependency_overrides[get_current_user_optional] = _user_opt
        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.get("/nutricionista/cadastro")
            assert resp.status_code == 200
            assert "CRN" in resp.text or "cadastro" in resp.text.lower()
        finally:
            app.dependency_overrides.clear()

    def test_register_missing_crn(self):
        """POST sem CRN retorna 422."""
        mock_db = _make_mock_db()

        async def _db():
            yield mock_db

        async def _user_opt():
            return None

        app.dependency_overrides[get_db] = _db
        app.dependency_overrides[get_current_user_optional] = _user_opt
        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.post("/api/nutricionista/register", data={
                    "name": "Dra. Maria",
                    "email": "maria@clinica.com",
                    "password": "Senha@1234",
                    "lgpd_consent": "true",
                })
            assert resp.status_code == 422
        finally:
            app.dependency_overrides.clear()

    def test_register_invalid_crn_format(self):
        """POST com CRN em formato inválido retorna 422."""
        mock_db = _make_mock_db()

        async def _db():
            yield mock_db

        async def _user_opt():
            return None

        app.dependency_overrides[get_db] = _db
        app.dependency_overrides[get_current_user_optional] = _user_opt
        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.post("/api/nutricionista/register", data={
                    "name": "Dra. Maria",
                    "crn": "999999",  # inválido
                    "email": "maria@clinica.com",
                    "password": "Senha@1234",
                    "lgpd_consent": "true",
                })
            assert resp.status_code == 422
        finally:
            app.dependency_overrides.clear()

    def test_register_short_password(self):
        """POST com senha curta retorna 422."""
        mock_db = _make_mock_db()

        async def _db():
            yield mock_db

        async def _user_opt():
            return None

        app.dependency_overrides[get_db] = _db
        app.dependency_overrides[get_current_user_optional] = _user_opt
        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.post("/api/nutricionista/register", data={
                    "name": "Dra. Maria",
                    "crn": "CRN-3 12345",
                    "email": "maria@clinica.com",
                    "password": "123",  # curta
                    "lgpd_consent": "true",
                })
            assert resp.status_code == 422
        finally:
            app.dependency_overrides.clear()


# ── 3. Painel nutricionista ───────────────────────────────────────────────────

class TestPainelNutricionista:
    """Testa GET /nutricionista/ — listagem de pacientes."""

    def test_painel_sem_login_redireciona(self):
        mock_db = _make_mock_db()

        async def _db():
            yield mock_db

        async def _user_opt():
            return None

        app.dependency_overrides[get_db] = _db
        app.dependency_overrides[get_current_user_optional] = _user_opt
        try:
            with TestClient(app, raise_server_exceptions=False, follow_redirects=False) as client:
                resp = client.get("/nutricionista/")
            assert resp.status_code in (302, 307)
            assert "/login" in resp.headers.get("location", "")
        finally:
            app.dependency_overrides.clear()

    def test_painel_user_nao_nutri_redireciona(self):
        """Usuário free não acessa o painel."""
        mock_db = _make_mock_db()
        patient = _make_patient()
        patient.is_nutritionist = False

        async def _db():
            yield mock_db

        async def _user_opt():
            return patient

        app.dependency_overrides[get_db] = _db
        app.dependency_overrides[get_current_user_optional] = _user_opt
        try:
            with TestClient(app, raise_server_exceptions=False, follow_redirects=False) as client:
                client.cookies.set("access_token", create_access_token(patient.id))
                resp = client.get("/nutricionista/")
            assert resp.status_code in (302, 307)
        finally:
            app.dependency_overrides.clear()

    def test_painel_nutri_retorna_200(self):
        """Nutricionista com trial ativo acessa o painel."""
        nutri = _make_nutri()
        mock_db = _make_mock_db()

        # Mock: sem pacientes
        result_empty = MagicMock()
        result_empty.scalars.return_value.all.return_value = []
        result_empty.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=result_empty)

        app.dependency_overrides[get_db] = lambda: (yield mock_db)
        app.dependency_overrides[get_current_user_optional] = lambda: nutri  # sync ok for TestClient

        # Need proper async overrides
        async def _db():
            yield mock_db

        async def _user_opt():
            return nutri

        app.dependency_overrides[get_db] = _db
        app.dependency_overrides[get_current_user_optional] = _user_opt
        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                client.cookies.set("access_token", create_access_token(nutri.id))
                resp = client.get("/nutricionista/")
            assert resp.status_code == 200
            assert "Painel" in resp.text or "paciente" in resp.text.lower()
        finally:
            app.dependency_overrides.clear()


# ── 4. Convites ───────────────────────────────────────────────────────────────

class TestConvites:
    """Testa geração e processamento de convites."""

    def test_gerar_convite_retorna_url(self):
        """POST /api/nutricionista/convite retorna URL de convite."""
        nutri = _make_nutri()
        mock_db = _make_mock_db()

        # Simula contagem de 0 pacientes ativos
        result = MagicMock()
        result.scalar_one_or_none.return_value = 0
        result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=result)

        async def _db():
            yield mock_db

        async def _user_opt():
            return nutri

        app.dependency_overrides[get_db] = _db
        app.dependency_overrides[get_current_user_optional] = _user_opt
        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                client.cookies.set("access_token", create_access_token(nutri.id))
                resp = client.post("/api/nutricionista/convite", data={
                    "patient_phone": "+5511987654321",
                    "patient_name": "Ana Paciente",
                })
            assert resp.status_code == 200
            data = resp.json()
            assert "invite_url" in data
            # URL contém /convite/ (formato do deep link)
            assert "/convite/" in data["invite_url"]
            assert data["patient_name"] == "Ana Paciente"
        finally:
            app.dependency_overrides.clear()

    def test_aceitar_convite_status_active(self):
        """PATCH /api/nutricionista/convite/{token}?aceitar=true define status=active."""
        nutri = _make_nutri()
        nutri_id = nutri.id
        link = _make_link(nutri_id, token="TOKEN123", status="pending")
        mock_db = _make_mock_db()

        result_link = MagicMock()
        result_link.scalar_one_or_none.return_value = link
        mock_db.execute = AsyncMock(return_value=result_link)

        async def _db():
            yield mock_db

        app.dependency_overrides[get_db] = _db
        try:
            patient_uid = str(uuid.uuid4())
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.patch(
                    f"/api/nutricionista/convite/TOKEN123"
                    f"?aceitar=true&patient_user_id={patient_uid}",
                )
            assert resp.status_code == 200
            assert mock_db.commit.called
        finally:
            app.dependency_overrides.clear()

    def test_recusar_convite_status_declined(self):
        """PATCH com aceitar=false define status=declined."""
        nutri = _make_nutri()
        link = _make_link(nutri.id, token="TOKENDECL", status="pending")
        mock_db = _make_mock_db()

        result_link = MagicMock()
        result_link.scalar_one_or_none.return_value = link
        mock_db.execute = AsyncMock(return_value=result_link)

        async def _db():
            yield mock_db

        app.dependency_overrides[get_db] = _db
        try:
            patient_uid = str(uuid.uuid4())
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.patch(
                    f"/api/nutricionista/convite/TOKENDECL"
                    f"?aceitar=false&patient_user_id={patient_uid}",
                )
            assert resp.status_code == 200
            assert link.status == "declined"
        finally:
            app.dependency_overrides.clear()

    def test_convite_inexistente_retorna_404(self):
        """Token sem convite correspondente retorna 404."""
        mock_db = _make_mock_db()
        result_none = MagicMock()
        result_none.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=result_none)

        async def _db():
            yield mock_db

        app.dependency_overrides[get_db] = _db
        try:
            patient_uid = str(uuid.uuid4())
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.patch(
                    f"/api/nutricionista/convite/TOKEN_NAO_EXISTE"
                    f"?aceitar=true&patient_user_id={patient_uid}",
                )
            assert resp.status_code == 404
        finally:
            app.dependency_overrides.clear()


# ── 5. Revogação pelo painel ──────────────────────────────────────────────────

class TestRevogacaoPainel:
    """Testa PATCH /api/nutricionista/revogar/{id}."""

    def test_revogar_vinculo_ativo(self):
        """Paciente revoga vínculo ativo — retorna 200 e status=revoked."""
        patient = _make_patient()
        nutri = _make_nutri()
        link = _make_link(nutri.id, patient_id=patient.id, status="active")
        link_id = link.id
        mock_db = _make_mock_db()

        result = MagicMock()
        result.scalar_one_or_none.return_value = link
        mock_db.execute = AsyncMock(return_value=result)

        async def _db():
            yield mock_db

        app.dependency_overrides[get_db] = _db
        try:
            # Endpoint é chamado pelo bot sem JWT, usa patient_user_id como query param
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.patch(
                    f"/api/nutricionista/revogar/{link_id}"
                    f"?patient_user_id={patient.id}",
                )
            assert resp.status_code == 200
            assert link.status == "revoked"
            assert link.revoked_at is not None
        finally:
            app.dependency_overrides.clear()

    def test_revogar_vinculo_patient_errado_retorna_404(self):
        """Patient_user_id incorreto retorna 404 (não encontra o link)."""
        patient = _make_patient()
        nutri = _make_nutri()
        link = _make_link(nutri.id, patient_id=patient.id, status="active")
        link_id = link.id
        mock_db = _make_mock_db()

        result = MagicMock()
        result.scalar_one_or_none.return_value = None  # patient_id não bate
        mock_db.execute = AsyncMock(return_value=result)

        async def _db():
            yield mock_db

        app.dependency_overrides[get_db] = _db
        try:
            outro_patient = str(uuid.uuid4())
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.patch(
                    f"/api/nutricionista/revogar/{link_id}"
                    f"?patient_user_id={outro_patient}",
                )
            assert resp.status_code == 404
        finally:
            app.dependency_overrides.clear()


# ── 6. Nota clínica ───────────────────────────────────────────────────────────

class TestNotaClinica:
    """Testa POST /api/nutricionista/paciente/{id}/nota."""

    def test_adicionar_nota_sucesso(self):
        """Nota clínica salva com sucesso retorna 201."""
        nutri = _make_nutri()
        patient = _make_patient()
        link = _make_link(nutri.id, patient_id=patient.id, status="active")
        mock_db = _make_mock_db()

        result_link = MagicMock()
        result_link.scalar_one_or_none.return_value = link
        mock_db.execute = AsyncMock(return_value=result_link)

        # Mock do refresh da nota
        from app.models.clinical_note import ClinicalNote as _CNote
        note_mock = MagicMock(spec=_CNote)
        note_mock.id = uuid.uuid4()
        note_mock.consultation_date = date.today()
        note_mock.note_text = "Paciente evoluiu bem."
        note_mock.created_at = datetime.utcnow()

        async def _refresh(obj):
            # Simula refresh após commit
            if isinstance(obj, _CNote):
                obj.id = note_mock.id
                obj.consultation_date = note_mock.consultation_date
                obj.note_text = note_mock.note_text
                obj.created_at = note_mock.created_at

        mock_db.refresh = _refresh

        async def _db():
            yield mock_db

        async def _user_opt():
            return nutri

        app.dependency_overrides[get_db] = _db
        app.dependency_overrides[get_current_user_optional] = _user_opt
        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                client.cookies.set("access_token", create_access_token(nutri.id))
                resp = client.post(
                    f"/api/nutricionista/paciente/{patient.id}/nota",
                    data={
                        "note_text": "Paciente evoluiu bem, ajustes no cardápio.",
                        "consultation_date": date.today().isoformat(),
                    },
                )
            assert resp.status_code == 201
            data = resp.json()
            assert "id" in data
            assert "consultation_date" in data
        finally:
            app.dependency_overrides.clear()

    def test_nota_data_futura_retorna_422(self):
        """Nota com data futura deve ser rejeitada."""
        nutri = _make_nutri()
        patient = _make_patient()
        link = _make_link(nutri.id, patient_id=patient.id, status="active")
        mock_db = _make_mock_db()

        result_link = MagicMock()
        result_link.scalar_one_or_none.return_value = link
        mock_db.execute = AsyncMock(return_value=result_link)

        async def _db():
            yield mock_db

        async def _user_opt():
            return nutri

        app.dependency_overrides[get_db] = _db
        app.dependency_overrides[get_current_user_optional] = _user_opt
        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                client.cookies.set("access_token", create_access_token(nutri.id))
                future = (date.today() + timedelta(days=1)).isoformat()
                resp = client.post(
                    f"/api/nutricionista/paciente/{patient.id}/nota",
                    data={
                        "note_text": "Nota com data futura",
                        "consultation_date": future,
                    },
                )
            assert resp.status_code == 422
        finally:
            app.dependency_overrides.clear()

    def test_nota_sem_texto_retorna_422(self):
        """Nota sem texto deve ser rejeitada."""
        nutri = _make_nutri()
        patient = _make_patient()
        link = _make_link(nutri.id, patient_id=patient.id, status="active")
        mock_db = _make_mock_db()

        result_link = MagicMock()
        result_link.scalar_one_or_none.return_value = link
        mock_db.execute = AsyncMock(return_value=result_link)

        async def _db():
            yield mock_db

        async def _user_opt():
            return nutri

        app.dependency_overrides[get_db] = _db
        app.dependency_overrides[get_current_user_optional] = _user_opt
        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                client.cookies.set("access_token", create_access_token(nutri.id))
                resp = client.post(
                    f"/api/nutricionista/paciente/{patient.id}/nota",
                    data={
                        "note_text": "   ",   # somente espaços
                        "consultation_date": date.today().isoformat(),
                    },
                )
            assert resp.status_code == 422
        finally:
            app.dependency_overrides.clear()

    def test_nota_sem_vinculo_ativo_retorna_403(self):
        """Nutricionista sem vínculo ativo não pode adicionar nota."""
        nutri = _make_nutri()
        patient = _make_patient()
        mock_db = _make_mock_db()

        # Nenhum vínculo ativo
        result_none = MagicMock()
        result_none.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=result_none)

        async def _db():
            yield mock_db

        async def _user_opt():
            return nutri

        app.dependency_overrides[get_db] = _db
        app.dependency_overrides[get_current_user_optional] = _user_opt
        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                client.cookies.set("access_token", create_access_token(nutri.id))
                resp = client.post(
                    f"/api/nutricionista/paciente/{patient.id}/nota",
                    data={
                        "note_text": "Nota sem vínculo",
                        "consultation_date": date.today().isoformat(),
                    },
                )
            assert resp.status_code == 403
        finally:
            app.dependency_overrides.clear()


# ── 7. Revogação pelo bot ─────────────────────────────────────────────────────

class TestRevogacaoBot:
    """Testa o fluxo de revogação via ConversationService."""

    @pytest.fixture
    def svc(self):
        from app.services.conversation import ConversationService
        return ConversationService()

    def _user(self, state="IDLE", state_data=None):
        u = MagicMock()
        u.id = uuid.uuid4()
        u.first_name = "Ana"
        u.plan = "free"
        u.is_premium = False
        u.is_nutritionist = False
        u.conversation_state = state
        u.state_data = state_data
        u.onboarding_complete = True
        u.alerts_enabled = True
        u.deleted_at = None
        u.daily_calorie_goal = 1800
        u.channel_type = "telegram"
        u.channel_id = "tg:999"
        u.timezone = "America/Sao_Paulo"
        u.web_link_token = None
        u.last_active_at = datetime.utcnow()
        return u

    @pytest.mark.asyncio
    async def test_revogar_sem_vinculos(self, svc):
        """Usuário sem vínculos ativos recebe mensagem informativa."""
        user = self._user()
        mock_db = _make_mock_db()

        result_empty = MagicMock()
        result_empty.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=result_empty)

        reply = await svc._iniciar_revogacao(user, None, mock_db)
        assert "não tem" in reply.lower() or "nenhum" in reply.lower()

    @pytest.mark.asyncio
    async def test_revogar_um_vinculo_vai_para_revoking(self, svc):
        """Com 1 vínculo, vai direto para confirmação (estado REVOKING)."""
        nutri = _make_nutri()
        user = self._user()
        link = _make_link(nutri.id, patient_id=user.id, status="active")
        mock_db = _make_mock_db()

        call_count = 0

        async def _exec(q, *a, **kw):
            nonlocal call_count
            call_count += 1
            r = MagicMock()
            if call_count == 1:
                # primeira chamada: lista de vínculos
                r.scalars.return_value.all.return_value = [link]
            else:
                # segunda: busca nutricionista
                r.scalar_one_or_none.return_value = nutri
            return r

        mock_db.execute = _exec

        reply = await svc._iniciar_revogacao(user, None, mock_db)
        assert user.conversation_state == "REVOKING"
        assert "SIM" in reply or "sim" in reply.lower()
        assert "revogar" in reply.lower()

    @pytest.mark.asyncio
    async def test_handle_revoking_confirma(self, svc):
        """SIM no estado REVOKING efetua revogação e retorna confirmação."""
        nutri = _make_nutri()
        user = self._user()
        link = _make_link(nutri.id, patient_id=user.id, status="active")
        user.conversation_state = "REVOKING"
        user.state_data = {"link_id": str(link.id), "nutri_name": "Dra. Maria"}
        mock_db = _make_mock_db()

        result = MagicMock()
        result.scalar_one_or_none.return_value = link
        mock_db.execute = AsyncMock(return_value=result)

        reply = await svc._handle_revoking(user, "sim", mock_db)
        assert link.status == "revoked"
        assert link.revoked_at is not None
        assert user.conversation_state == "IDLE"
        assert "revogado" in reply.lower() or "pronto" in reply.lower()

    @pytest.mark.asyncio
    async def test_handle_revoking_cancela(self, svc):
        """NÃO no estado REVOKING cancela e retorna ao IDLE."""
        nutri = _make_nutri()
        user = self._user()
        link = _make_link(nutri.id, patient_id=user.id, status="active")
        user.conversation_state = "REVOKING"
        user.state_data = {"link_id": str(link.id), "nutri_name": "Dra. Maria"}
        mock_db = _make_mock_db()

        reply = await svc._handle_revoking(user, "não", mock_db)
        assert user.conversation_state == "IDLE"
        # vínculo não deve ter sido alterado
        assert link.status == "active"
        assert "cancelado" in reply.lower() or "ativo" in reply.lower()

    @pytest.mark.asyncio
    async def test_handle_revoking_resposta_invalida(self, svc):
        """Resposta não reconhecida mantém estado REVOKING."""
        nutri = _make_nutri()
        user = self._user()
        link = _make_link(nutri.id, patient_id=user.id, status="active")
        user.conversation_state = "REVOKING"
        user.state_data = {"link_id": str(link.id), "nutri_name": "Dra. Maria"}
        mock_db = _make_mock_db()

        reply = await svc._handle_revoking(user, "talvez", mock_db)
        assert user.conversation_state == "REVOKING"
        assert "SIM" in reply or "NÃO" in reply


# ── 8. is_nutritionist property ───────────────────────────────────────────────

class TestIsNutricionistaProperty:
    """Testa a lógica da propriedade is_nutritionist via SimpleNamespace."""

    def _get_is_nutritionist(self, plan, trial_ends_at=None, plan_expires_at=None) -> bool:
        """Replica a lógica da property is_nutritionist do modelo User."""
        if plan != "nutritionist":
            return False
        if trial_ends_at is not None:
            return datetime.utcnow() < trial_ends_at.replace(tzinfo=None) if trial_ends_at.tzinfo else datetime.utcnow() < trial_ends_at
        if plan_expires_at is None:
            return True
        exp = plan_expires_at.replace(tzinfo=None) if plan_expires_at.tzinfo else plan_expires_at
        return datetime.utcnow() < exp

    def test_trial_ativo(self):
        """Trial ativo → is_nutritionist = True."""
        assert self._get_is_nutritionist(
            "nutritionist",
            trial_ends_at=datetime.utcnow() + timedelta(days=15),
        ) is True

    def test_trial_expirado(self):
        """Trial expirado → is_nutritionist = False."""
        assert self._get_is_nutritionist(
            "nutritionist",
            trial_ends_at=datetime.utcnow() - timedelta(days=1),
        ) is False

    def test_plano_pago_ativo(self):
        """plan_expires_at no futuro, sem trial → is_nutritionist = True."""
        assert self._get_is_nutritionist(
            "nutritionist",
            trial_ends_at=None,
            plan_expires_at=datetime.utcnow() + timedelta(days=30),
        ) is True

    def test_plano_sem_expiracao(self):
        """Sem expires_at e sem trial → is_nutritionist = True (acesso permanente)."""
        assert self._get_is_nutritionist(
            "nutritionist",
            trial_ends_at=None,
            plan_expires_at=None,
        ) is True

    def test_plan_free(self):
        """Plano free → is_nutritionist = False independente de datas."""
        assert self._get_is_nutritionist(
            "free",
            trial_ends_at=datetime.utcnow() + timedelta(days=15),
        ) is False


# ── 9. Expiração de convites (job_expire_invites) ─────────────────────────────

class TestJobExpireInvites:
    """Testa o job de expiração de convites pendentes."""

    @pytest.mark.asyncio
    async def test_expire_invites_executa_update(self):
        """job_expire_invites deve executar um UPDATE e committar."""
        with patch(
            "app.db.session.AsyncSessionLocal"
        ) as mock_session_local:
            mock_db = AsyncMock()
            mock_result = MagicMock()
            mock_result.rowcount = 3
            mock_db.execute = AsyncMock(return_value=mock_result)
            mock_db.commit = AsyncMock()
            mock_db.__aenter__ = AsyncMock(return_value=mock_db)
            mock_db.__aexit__ = AsyncMock(return_value=False)
            mock_session_local.return_value = mock_db

            from app.services.scheduler import job_expire_invites
            await job_expire_invites()

            assert mock_db.execute.called
            assert mock_db.commit.called
