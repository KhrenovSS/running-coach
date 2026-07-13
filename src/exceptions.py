"""
Исключения приложения (Application exceptions)

Типизированные исключения для единообразной обработки ошибок.
Typed exceptions for consistent error handling.

Использование (Usage):
    from src.exceptions import NotFoundError, WatchAPIError
    
    raise NotFoundError("training", training_id)
    raise WatchAPIError("/activities/list", 503)
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


class WatchAPIError(AppError):
    """
    Ошибка API часов (Watch API error) — brand-agnostic, для всех брендов часов.
    Brand-agnostic watch API exception for all watch brands.

    Пример (Example):
        raise WatchAPIError("Not authenticated", brand="coros")
        raise WatchAPIError(f"API error: {msg}", brand="coros", status=503)
    """

    def __init__(self, message: str, brand: str = "", status: int = 0,
                 response_text: str = ""):
        prefix = f"{brand.capitalize()} API" if brand else "Watch API"
        super().__init__(
            message=f"{prefix}: {message}",
            status_code=502,
            details={"brand": brand, "message": message, "status": status,
                     "response": response_text[:500]}
        )


class WatchAuthError(AppError):
    """
    Ошибка аутентификации часов (Watch authentication error) — brand-agnostic.
    Brand-agnostic watch authentication error.

    Пример (Example):
        raise WatchAuthError("Invalid credentials", brand="coros")
    """

    def __init__(self, message: str = "Watch authentication failed", brand: str = ""):
        super().__init__(
            message=f"{brand.capitalize()}: {message}" if brand else message,
            status_code=401,
            details={"brand": brand, "reason": message}
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
