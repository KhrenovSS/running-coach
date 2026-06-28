import os
import re
from cryptography.fernet import Fernet

KEY_ENV_VAR = 'COROS_CRED_KEY'
_fernet_cache = None


def _get_env_path():
    return os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), '.env')


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


def _get_fernet():
    global _fernet_cache
    if _fernet_cache is not None:
        return _fernet_cache
    key = os.environ.get(KEY_ENV_VAR)
    if not key:
        key = _read_key_from_env_file()
    if not key:
        key = Fernet.generate_key().decode()
        env_path = _get_env_path()
        try:
            with open(env_path, 'a') as f:
                f.write(f'\n{KEY_ENV_VAR}={key}\n')
        except Exception:
            pass
        os.environ[KEY_ENV_VAR] = key
    _fernet_cache = Fernet(key.encode())
    return _fernet_cache


def encrypt(plaintext: str) -> str:
    if not plaintext:
        return ''
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    if not ciphertext:
        return ''
    return _get_fernet().decrypt(ciphertext.encode()).decode()
