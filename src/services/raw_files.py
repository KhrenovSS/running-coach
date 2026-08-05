# Хранилище исходных FIT/TCX-файлов (Raw FIT/TCX file storage — BACKLOG #229, Этап 4)
#
# Content-addressed: uploads/raw/<user_id>/<sha256>.<ext> — одинаковый контент
# не дублируется, имя файла само является ключом дедупа (file_sha256).
# Ошибка записи НЕ должна ронять импорт — сырьё желательно, но не обязательно.
# (Content-addressed storage; a write failure must never fail the import itself.)

import hashlib
from pathlib import Path
from typing import Optional

from src.config import settings
from src.utils.logger import get_logger

logger = get_logger("raw_files")


def sha256_hex(content: bytes) -> str:
    """SHA256 контента (Content SHA256)."""
    return hashlib.sha256(content).hexdigest()


def save_raw_file(user_id: int, content: bytes, ext: str) -> Optional[str]:
    """Сохранить исходный файл; вернуть путь (str) или None при ошибке записи.
    (Save the raw file; return its path or None on write failure.)
    Идемпотентно: существующий файл не перезаписывается (content-addressed).
    """
    try:
        sha = sha256_hex(content)
        ext = (ext or '').lstrip('.').lower() or 'bin'
        path = Path(settings.raw_files_dir) / str(user_id) / f"{sha}.{ext}"
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + '.tmp')
            tmp.write_bytes(content)
            tmp.rename(path)  # атомарная публикация (atomic publish)
        return str(path)
    except OSError:
        logger.warning("Raw file save failed for user=%s (import continues)", user_id, exc_info=True)
        return None


def resolve_raw_file(raw_file_path: Optional[str]) -> Optional[Path]:
    """Проверить, что сырой файл существует на диске (Resolve raw file if it exists on disk)."""
    if not raw_file_path:
        return None
    path = Path(raw_file_path)
    return path if path.is_file() else None
