"""
Исключения приложения (Application exceptions)

Типизированные исключения для единообразной обработки ошибок.
Typed exceptions for consistent error handling.

Использование (Usage):
    from src.exceptions import NotFoundError, CorosAPIError
    
    raise NotFoundError("training", training_id)
    raise CorosAPIError("/activities/list", 503)
"""


class AppError(Exception):
    """
    Базовое исключение приложения (Base application exception)
    
    Все кастомные исключения наследуются от этого класса.
    All custom exceptions inherit from this class.
    """
    
    def __init__(self, message: str, status_code: int = 500, details: dict | None = None):
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        super().__init__(message)


class NotFoundError(AppError):
    """
    Ресурс не найден (Resource not found)
    
    Пример (Example):
        raise NotFoundError("training", 42)
        # → "training 42 not found", status 404
    """
    
    def __init__(self, resource: str, resource_id: int | str):
        super().__init__(
            message=f"{resource} {resource_id} not found",
            status_code=404,
            details={"resource": resource, "id": resource_id}
        )


class ValidationError(AppError):
    """
    Ошибка валидации входных данных (Input validation error)
    
    Пример (Example):
        raise ValidationError("max_hr", "must be between 100 and 220")
    """
    
    def __init__(self, field: str, reason: str):
        super().__init__(
            message=f"Invalid {field}: {reason}",
            status_code=400,
            details={"field": field, "reason": reason}
        )


class CorosAPIError(AppError):
    """
    Ошибка Coros API (Coros API error)
    
    Пример (Example):
        raise CorosAPIError("/activities/list", 503)
    """
    
    def __init__(self, endpoint: str, status: int, response_text: str = ""):
        super().__init__(
            message=f"Coros API {endpoint} failed with status {status}",
            status_code=502,
            details={"endpoint": endpoint, "status": status, "response": response_text[:500]}
        )


class AuthenticationError(AppError):
    """
    Ошибка аутентификации (Authentication error)
    
    Пример (Example):
        raise AuthenticationError("Invalid Coros credentials")
    """
    
    def __init__(self, reason: str = "Authentication failed"):
        super().__init__(
            message=reason,
            status_code=401,
            details={"reason": reason}
        )


class FileProcessingError(AppError):
    """
    Ошибка обработки файла (File processing error)
    
    Пример (Example):
        raise FileProcessingError("TCX parsing failed", "invalid XML structure")
    """
    
    def __init__(self, filename: str, reason: str):
        super().__init__(
            message=f"Failed to process file {filename}: {reason}",
            status_code=422,
            details={"filename": filename, "reason": reason}
        )


class DatabaseError(AppError):
    """
    Ошибка базы данных (Database error)
    
    Пример (Example):
        raise DatabaseError("Failed to save training session", str(original_error))
    """
    
    def __init__(self, operation: str, details: str = ""):
        super().__init__(
            message=f"Database error during {operation}",
            status_code=500,
            details={"operation": operation, "error": details}
        )


class RateLimitError(AppError):
    """
    Превышен лимит запросов (Rate limit exceeded)
    
    Пример (Example):
        raise RateLimitError("Too many sync requests", retry_after=60)
    """
    
    def __init__(self, message: str = "Rate limit exceeded", retry_after: int = 60):
        super().__init__(
            message=message,
            status_code=429,
            details={"retry_after": retry_after}
        )
