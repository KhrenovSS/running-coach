"""
Совместимость: реэкспорт логгера из src.utils.logger
Compatibility: re-export logger from src.utils.logger

Старый код использует: from src.logger import get_logger
Новый код должен использовать: from src.utils.logger import get_logger

Этот файл оставлен для обратной совместимости.
"""

from src.utils.logger import get_logger, logger

__all__ = ["get_logger", "logger"]
