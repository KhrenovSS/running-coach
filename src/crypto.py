import os
import re
from cryptography.fernet import Fernet
from src.logger import get_logger

logger = get_logger("crypto")

KEY_ENV_VAR = 'COROS_CRED_KEY'
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
        key = _read_key_from_env_file()
    if not key:
        logger.warning(
            "%s не задан — генерирую временный ключ. "
            "В Docker/production задайте COROS_CRED_KEY в .env, "
            "иначе зашифрованные данные будут потеряны при рестарте. "
            "Сгенерировать: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"",
            KEY_ENV_VAR,
        )
        key = Fernet.generate_key().decode()
        env_path = _get_env_path()
        # Пытаемся записать в .env (только для локальной разработки) (Try to write to .env — local dev only)
        try:
            with open(env_path, 'a') as f:
                f.write(f'\n{KEY_ENV_VAR}={key}\n')
        except (OSError, PermissionError) as e:
            logger.warning("Не удалось записать ключ Fernet в .env: %s", e)
        os.environ[KEY_ENV_VAR] = key
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
