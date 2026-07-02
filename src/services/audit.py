"""
Сервис аудита событий (Audit event service)

Создаёт события аудита в БД и дублирует их в лог-файл.
Creates audit events in DB and duplicates them to log file.

Usage:
    from src.services.audit import AuditService
    audit = AuditService(db)
    audit.log_event(
        event_type="training.uploaded",
        message="Training uploaded successfully",
        severity="info",
        user_id=1,
        metadata={"training_id": 42},
    )
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from src.models import AuditEvent
from src.utils.logger import get_audit_file_logger

audit_logger = get_audit_file_logger()


class AuditService:
    """Сервис для создания событий аудита (Audit event creation service)"""
    
    # Типы событий (Event types)
    TRAINING_UPLOADED = "training.uploaded"
    TRAINING_DELETED = "training.deleted"
    COROS_SYNC_STARTED = "coros.sync.started"
    COROS_SYNC_COMPLETED = "coros.sync.completed"
    COROS_SYNC_FAILED = "coros.sync.failed"
    TELEGRAM_NOTIFICATION_SENT = "telegram.notification.sent"
    TELEGRAM_NOTIFICATION_FAILED = "telegram.notification.failed"
    SETTINGS_CHANGED = "settings.changed"
    USER_LOGIN = "user.login"
    USER_LOGOUT = "user.logout"
    ERROR = "app.error"
    
    VALID_SEVERITIES = {"info", "warning", "error", "critical"}
    
    def __init__(self, db: Session):
        self.db = db
    
    def log_event(
        self,
        event_type: str,
        message: str,
        severity: str = "info",
        user_id: int | None = None,
        ip_address: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AuditEvent | None:
        """
        Создать событие аудита (Create audit event)
        
        В случае ошибки записи в БД событие всё равно пишется в лог-файл.
        On DB write error, event is still written to log file.
        """
        if severity not in self.VALID_SEVERITIES:
            severity = "info"
        
        metadata_str = json.dumps(metadata, ensure_ascii=False, default=str) if metadata else None
        
        # Всегда пишем в лог-файл (Always write to log file)
        self._log_to_file(event_type, severity, message, user_id, ip_address, metadata)
        
        try:
            event = AuditEvent(
                event_type=event_type,
                severity=severity,
                message=message,
                user_id=user_id,
                ip_address=ip_address,
                metadata_json=metadata_str,
                created_at=datetime.now(timezone.utc).replace(tzinfo=None),
            )
            self.db.add(event)
            self.db.commit()
            self.db.refresh(event)
            return event
        except Exception as e:
            # Не падаем если БД недоступна — лог-файл уже есть
            # Don't fail if DB is unavailable — log file already written
            logging.getLogger("app").error(
                f"Failed to write audit event to DB: {event_type}",
                exc_info=e,
            )
            return None
    
    def _log_to_file(
        self,
        event_type: str,
        severity: str,
        message: str,
        user_id: int | None,
        ip_address: str | None,
        metadata: dict[str, Any] | None,
    ) -> None:
        """Записать событие аудита в лог-файл (Write audit event to log file)"""
        audit_logger.info(
            message,
            extra={
                "context": "Audit",
                "event_type": event_type,
                "severity": severity,
                "user_id": user_id,
                "ip_address": ip_address,
                "metadata": metadata,
                "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            },
        )
    
    # Удобные методы для частых событий (Convenience methods)
    
    def log_training_uploaded(self, user_id: int, training_id: int, filename: str, **extra) -> None:
        """Аудит: тренировка загружена (Audit: training uploaded)"""
        self.log_event(
            event_type=self.TRAINING_UPLOADED,
            message=f"Training uploaded: {filename}",
            severity="info",
            user_id=user_id,
            metadata={"training_id": training_id, "filename": filename, **extra},
        )
    
    def log_training_deleted(self, user_id: int, training_id: int, **extra) -> None:
        """Аудит: тренировка удалена (Audit: training deleted)"""
        self.log_event(
            event_type=self.TRAINING_DELETED,
            message=f"Training deleted: id={training_id}",
            severity="warning",
            user_id=user_id,
            metadata={"training_id": training_id, **extra},
        )
    
    def log_coros_sync_started(self, user_id: int, **extra) -> None:
        """Аудит: начата синхронизация Coros (Audit: Coros sync started)"""
        self.log_event(
            event_type=self.COROS_SYNC_STARTED,
            message="Coros sync started",
            severity="info",
            user_id=user_id,
            metadata=extra,
        )
    
    def log_coros_sync_completed(self, user_id: int, found: int = 0, processed: int = 0, **extra) -> None:
        """Аудит: синхронизация Coros завершена (Audit: Coros sync completed)"""
        metadata = {"found": found, "processed": processed, **extra}
        self.log_event(
            event_type=self.COROS_SYNC_COMPLETED,
            message=f"Coros sync completed: found={found}, processed={processed}",
            severity="info",
            user_id=user_id,
            metadata=metadata,
        )
    
    def log_coros_sync_failed(self, user_id: int, error: str, **extra) -> None:
        """Аудит: синхронизация Coros не удалась (Audit: Coros sync failed)"""
        self.log_event(
            event_type=self.COROS_SYNC_FAILED,
            message=f"Coros sync failed: {error}",
            severity="error",
            user_id=user_id,
            metadata={"error": error, **extra},
        )
    
    def log_telegram_sent(self, user_id: int, chat_id: int, message_preview: str, **extra) -> None:
        """Аудит: Telegram уведомление отправлено (Audit: Telegram notification sent)"""
        self.log_event(
            event_type=self.TELEGRAM_NOTIFICATION_SENT,
            message=f"Telegram notification sent: {message_preview[:50]}",
            severity="info",
            user_id=user_id,
            metadata={"chat_id": chat_id, "preview": message_preview[:100], **extra},
        )
    
    def log_telegram_failed(self, user_id: int, error: str, **extra) -> None:
        """Аудит: Telegram уведомление не отправлено (Audit: Telegram notification failed)"""
        self.log_event(
            event_type=self.TELEGRAM_NOTIFICATION_FAILED,
            message=f"Telegram notification failed: {error}",
            severity="warning",
            user_id=user_id,
            metadata={"error": error, **extra},
        )
    
    def log_settings_changed(self, user_id: int, changes: dict[str, Any], **extra) -> None:
        """Аудит: настройки изменены (Audit: settings changed)"""
        self.log_event(
            event_type=self.SETTINGS_CHANGED,
            message="Settings changed",
            severity="info",
            user_id=user_id,
            metadata={"changes": changes, **extra},
        )
    
    def log_error(self, user_id: int | None, message: str, error: str, **extra) -> None:
        """Аудит: ошибка приложения (Audit: application error)"""
        self.log_event(
            event_type=self.ERROR,
            message=message,
            severity="error",
            user_id=user_id,
            metadata={"error": error, **extra},
        )
