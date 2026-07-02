import os
import re
from cryptography.fernet import Fernet
from src.logger import get_logger

logger = get_logger("crypto")

KEY_ENV_VAR = 'CRED_KEY'
_OLD_KEY_ENV_VAR = 'COROS_CRED_KEY'
_fernet_cache = None


# Путь к .env файлу (Path to .env file)
def _get_env_path():
    return os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), '.env')


# Прочитать ключ из .env файла (Read key from .env file)
def _read_key_from_env_file():
    env_path = _get_env_path()
    if not os.path.exists(env_path):
        return None
    key = None
    with open(env_path) as f:
        for line in f:
            m = re.match(r'^' + KEY_ENV_VAR + r'=(.+)$', line.strip())
            if m:
                key = m.group(1)
    return key


# Получить Fernet-экземпляр (кэшируется после первого вызова) (Get Fernet instance, cached after first call)
def _get_fernet():
    global _fernet_cache
    if _fernet_cache is not None:
        return _fernet_cache
    key = os.environ.get(KEY_ENV_VAR)
    if not key:
        key = os.environ.get(_OLD_KEY_ENV_VAR)
        if key:
            logger.warning("COROS_CRED_KEY is deprecated, rename to CRED_KEY in .env")
    if not key:
        key = _read_key_from_env_file()
    if not key:
        raise RuntimeError(
            f"{KEY_ENV_VAR} не задан. Укажите CRED_KEY (или COROS_CRED_KEY) в .env "
            f"или переменной окружения. Сгенерировать: "
            f"python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    _fernet_cache = Fernet(key.encode())
    return _fernet_cache


# Зашифровать строку (Encrypt a string)
def encrypt(plaintext: str) -> str:
    if not plaintext:
        return ''
    return _get_fernet().encrypt(plaintext.encode()).decode()


# Расшифровать строку (Decrypt a string)
def decrypt(ciphertext: str) -> str:
    if not ciphertext:
        return ''
    return _get_fernet().decrypt(ciphertext.encode()).decode()
