import base64

from cryptography.fernet import Fernet

from app.config import settings


def _get_fernet() -> Fernet:
    key_bytes = bytes.fromhex(settings.raw_input_encryption_key)
    b64_key = base64.urlsafe_b64encode(key_bytes)
    return Fernet(b64_key)


def encrypt(text: str) -> str:
    """Criptografa texto com AES-256 (Fernet). Retorna string base64."""
    return _get_fernet().encrypt(text.encode()).decode()


def decrypt(token: str) -> str:
    """Descriptografa token Fernet. Retorna texto original."""
    return _get_fernet().decrypt(token.encode()).decode()
