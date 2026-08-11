from datetime import datetime
from zoneinfo import ZoneInfo

# Mapeamento de sigla de estado para fuso horário IANA
STATE_TO_TIMEZONE: dict[str, str] = {
    # UTC-3 (America/Sao_Paulo)
    "SP": "America/Sao_Paulo", "RJ": "America/Sao_Paulo", "MG": "America/Sao_Paulo",
    "ES": "America/Sao_Paulo", "PR": "America/Sao_Paulo", "SC": "America/Sao_Paulo",
    "RS": "America/Sao_Paulo", "GO": "America/Sao_Paulo", "DF": "America/Sao_Paulo",
    "TO": "America/Sao_Paulo", "BA": "America/Sao_Paulo", "SE": "America/Sao_Paulo",
    "AL": "America/Sao_Paulo", "PE": "America/Sao_Paulo", "PB": "America/Sao_Paulo",
    "RN": "America/Sao_Paulo", "CE": "America/Sao_Paulo", "PI": "America/Sao_Paulo",
    "MA": "America/Sao_Paulo", "PA": "America/Sao_Paulo", "AP": "America/Sao_Paulo",
    "RR": "America/Sao_Paulo",
    # UTC-4 (America/Manaus)
    "AM": "America/Manaus", "RO": "America/Manaus", "MT": "America/Manaus",
    "MS": "America/Manaus",
    # UTC-5 (America/Rio_Branco)
    "AC": "America/Rio_Branco",
    # UTC-2 (America/Noronha)
    "FN": "America/Noronha",
}


def get_timezone(tz_string: str) -> ZoneInfo:
    """Retorna ZoneInfo para string IANA. Fallback para America/Sao_Paulo."""
    try:
        return ZoneInfo(tz_string)
    except Exception:
        return ZoneInfo("America/Sao_Paulo")


def now_in_tz(tz_string: str) -> datetime:
    """Retorna datetime atual no fuso do usuário."""
    return datetime.now(tz=get_timezone(tz_string))


def state_to_tz(state_abbr: str) -> str:
    """Converte sigla de estado BR para string IANA."""
    return STATE_TO_TIMEZONE.get(state_abbr.upper(), "America/Sao_Paulo")
