from cryptography.fernet import Fernet

from config import SESSION_ENCRYPTION_KEY

_fernet = Fernet(SESSION_ENCRYPTION_KEY.encode())


def encrypt_session(plain: str) -> str:
    return _fernet.encrypt(plain.encode()).decode()


def decrypt_session(token: str) -> str:
    return _fernet.decrypt(token.encode()).decode()
