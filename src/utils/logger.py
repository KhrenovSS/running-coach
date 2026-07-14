"""
Унифицированная система логирования (Unified logging system)

Features:
- Structured logging с контекстом
- JSON формат в production (LOG_FORMAT=json)
- Human-readable формат в development
- Ежедневная ротация файлов
- Отдельные логгеры: app, requests, audit
- Управление уровнем через env LOG_LEVEL

Usage:
    from src.utils.logger import get_logger
    logger = get_logger("app")
    logger.info("Message")
    logger.warning("Slow request", extra={"duration_ms": 1500})
"""

import json
import logging
import os
import sys
import threading
from datetime import datetime, timezone
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Any


# Настройки из окружения (Settings from environment)
LOG_LEVEL = os.getenv("LOG_LEVEL", "info").upper()
LOG_FORMAT = os.getenv("LOG_FORMAT", "text").lower()
LOGS_DIR = Path(os.getenv("LOGS_DIR", "logs"))

# Убедимся, что директория существует (Ensure logs directory exists)
LOGS_DIR.mkdir(parents=True, exist_ok=True)


class JSONFormatter(logging.Formatter):
    """JSON форматтер для production (JSON formatter for production)"""
    
    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        
        # Добавляем extra поля (Add extra fields)
        for key, value in record.__dict__.items():
            if key not in {
                "name", "msg", "args", "levelname", "levelno", "pathname",
                "filename", "module", "exc_info", "exc_text", "stack_info",
                "lineno", "funcName", "created", "msecs", "relativeCreated",
                "thread", "threadName", "processName", "process", "message",
                "asctime", "getMessage",
            }:
                log_entry[key] = value
        
        # Добавляем исключение если есть (Add exception if present)
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        
        return json.dumps(log_entry, ensure_ascii=False, default=str)


class TextFormatter(logging.Formatter):
    """Текстовый форматтер для development (Text formatter for development)"""
    
    def format(self, record: logging.LogRecord) -> str:
        # Базовая часть
        base = f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} | {record.levelname:8} | {record.name}"
        
        # Добавляем context если есть (Add context if present)
        context = getattr(record, "context", None)
        if context:
            base += f" | [{context}]"
        
        base += f" | {record.getMessage()}"
        
        # Добавляем extra данные (Add extra data)
        extra = {}
        for key, value in record.__dict__.items():
            if key not in {
                "name", "msg", "args", "levelname", "levelno", "pathname",
                "filename", "module", "exc_info", "exc_text", "stack_info",
                "lineno", "funcName", "created", "msecs", "relativeCreated",
                "thread", "threadName", "processName", "process", "message",
                "asctime", "context", "getMessage",
            }:
                extra[key] = value
        
        if extra:
            base += f" | {json.dumps(extra, ensure_ascii=False, default=str)}"
        
        if record.exc_info:
            base += f"\n{self.formatException(record.exc_info)}"
        
        return base


def _create_file_handler(filename: str) -> TimedRotatingFileHandler:
    """Создать файловый handler с ежедневной ротацией (Create daily rotating file handler)"""
    handler = TimedRotatingFileHandler(
        filename=LOGS_DIR / filename,
        when="midnight",
        interval=1,
        backupCount=30,  # Хранить 30 дней (Keep 30 days)
        encoding="utf-8",
        utc=True,
    )
    handler.suffix = "%Y-%m-%d"
    
    if LOG_FORMAT == "json":
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(TextFormatter())
    
    return handler


def _create_console_handler() -> logging.StreamHandler:
    """Создать консольный handler (Create console handler)"""
    handler = logging.StreamHandler(sys.stdout)
    if LOG_FORMAT == "json":
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(TextFormatter())
    return handler


def _setup_logger(name: str, filename: str, level: str = LOG_LEVEL) -> logging.Logger:
    """Настроить логгер (Setup logger)"""
    logger = logging.getLogger(name)
    
    # Избегаем дублирования handlers (Avoid duplicate handlers)
    if logger.handlers:
        return logger
    
    logger.setLevel(getattr(logging, level, logging.INFO))
    logger.propagate = False
    
    # Файловый handler (File handler)
    logger.addHandler(_create_file_handler(filename))
    
    # Консольный handler (Console handler)
    logger.addHandler(_create_console_handler())
    
    return logger


# Готовые логгеры (Ready-to-use loggers)
_app_logger: logging.Logger | None = None
_requests_logger: logging.Logger | None = None
_audit_file_logger: logging.Logger | None = None
_logger_cache_lock = threading.Lock()


def get_logger(name: str = "app") -> logging.Logger:
    """
    Получить логгер приложения (Get application logger)
    
    Args:
        name: имя логгера. Рекомендуется "app" или имя модуля
    
    Returns:
        Настроенный логгер
    """
    global _app_logger
    if name == "app" and _app_logger is not None:
        return _app_logger
    
    logger = _setup_logger(name, "app.log")
    if name == "app":
        with _logger_cache_lock:
            if _app_logger is None:
                _app_logger = logger
    return logger


def get_requests_logger() -> logging.Logger:
    """Получить логгер API запросов (Get API requests logger)"""
    global _requests_logger
    if _requests_logger is not None:
        return _requests_logger
    
    with _logger_cache_lock:
        if _requests_logger is None:
            _requests_logger = _setup_logger("requests", "requests.log")
    return _requests_logger


def get_audit_file_logger() -> logging.Logger:
    """Получить логгер аудита в файл (Get audit file logger)"""
    global _audit_file_logger
    if _audit_file_logger is not None:
        return _audit_file_logger
    
    with _logger_cache_lock:
        if _audit_file_logger is None:
            _audit_file_logger = _setup_logger("audit_file", "audit.log")
    return _audit_file_logger


def log_with_context(
    logger: logging.Logger,
    level: str,
    message: str,
    context: str | None = None,
    **extra: Any,
) -> None:
    """
    Логировать с контекстом и extra-полями (Log with context and extra fields)
    
    Example:
        log_with_context(logger, "info", "Sync completed", context="Coros", count=5)
    """
    extra_dict = {}
    if context:
        extra_dict["context"] = context
    extra_dict.update(extra)
    
    log_func = getattr(logger, level.lower(), logger.info)
    log_func(message, extra=extra_dict)


def _fix_single_logger(name: str, filename: str) -> None:
    log = logging.getLogger(name)
    log.disabled = False
    log._cache.clear()
    new_handlers = []
    for h in log.handlers[:]:
        stream = getattr(h, 'stream', None)
        if stream is None and getattr(h, '_closed', False):
            log.removeHandler(h)
            if isinstance(h, TimedRotatingFileHandler):
                new_handlers.append(_create_file_handler(filename))
            elif isinstance(h, logging.StreamHandler):
                new_handlers.append(_create_console_handler())
    for h in new_handlers:
        log.addHandler(h)


def fix_logger_after_uvicorn() -> None:
    """
    Восстановить все логгеры после uvicorn dictConfig (Python 3.13+).
    uvicorn вызывает logging.config.dictConfig() при старте, что:
    1. Закрывает все существующие handlers (FileHandler.stream = None)
    2. Отключает существующие логгеры (logger.disabled = True)
    
    Эта функция должна вызываться из startup() приложения.
    """
    _fix_single_logger("app", "app.log")
    _fix_single_logger("requests", "requests.log")
    _fix_single_logger("audit_file", "audit.log")


# Удобный доступ к app-логгеру (Convenient app logger access)
logger = get_logger("app")
