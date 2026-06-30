"""
API Middleware — централизованная обработка ошибок и логирование
API Middleware — centralized error handling and logging

Регистрация в main.py (Registration in main.py):
    from src.api.middleware import register_middleware
    register_middleware(app)
"""

import time
import logging
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse

from src.exceptions import AppError
from src.utils.logger import get_requests_logger, get_logger

logger = get_logger("app")
requests_logger = get_requests_logger()

# Порог медленного запроса в мс (Slow request threshold in ms)
SLOW_REQUEST_THRESHOLD_MS = 1000


async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Глобальный обработчик необработанных исключений
    Global handler for unhandled exceptions
    """
    logger.exception(
        f"Unhandled error: {request.method} {request.url.path}",
        extra={"context": "GlobalException", "path": request.url.path},
    )
    return JSONResponse(
        status_code=500,
        content={"message": "Internal server error"},
    )


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    """
    Обработчик типизированных исключений приложения
    Handler for typed application exceptions
    """
    logger.warning(
        f"App error: {request.method} {request.url.path} — {exc.status_code} {exc.message}",
        extra={
            "context": "AppError",
            "status_code": exc.status_code,
            "path": request.url.path,
            **exc.details,
        },
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "message": exc.message,
            **(exc.details if exc.details else {}),
        },
    )


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """
    Обработчик HTTP исключений FastAPI
    Handler for FastAPI HTTP exceptions
    """
    return JSONResponse(
        status_code=exc.status_code,
        content={"message": exc.detail},
    )


class RequestLoggingMiddleware:
    """
    Middleware для логирования запросов и замера времени
    Middleware for request logging and timing
    """
    
    def __init__(self, app: FastAPI):
        self.app = app
    
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        
        start_time = time.time()
        request = Request(scope, receive)
        
        # Извлекаем IP (Extract IP)
        forwarded_for = request.headers.get("x-forwarded-for")
        real_ip = request.headers.get("x-real-ip")
        ip_address = (forwarded_for.split(",")[0].strip() if forwarded_for 
                      else real_ip or "unknown")
        
        request_info = {
            "method": scope["method"],
            "path": scope["path"],
            "ip": ip_address,
            "user_agent": request.headers.get("user-agent", "unknown"),
        }
        
        async def send_with_logging(message):
            if message["type"] == "http.response.start":
                duration_ms = (time.time() - start_time) * 1000
                status_code = message.get("status", 0)
                
                # Добавляем заголовок X-Process-Time (Add X-Process-Time header)
                headers = list(message.get("headers", []))
                headers.append((b"x-process-time", f"{duration_ms:.3f}ms".encode()))
                message["headers"] = headers
                
                log_data = {
                    **request_info,
                    "status_code": status_code,
                    "duration_ms": round(duration_ms, 2),
                }
                
                # Slow request — warning (Slow request warning)
                if duration_ms > SLOW_REQUEST_THRESHOLD_MS:
                    requests_logger.warning(
                        f"Slow request: {scope['method']} {scope['path']} — {duration_ms:.0f}ms",
                        extra={**log_data, "context": "SlowRequest"},
                    )
                # Ошибки — warning/error (Errors)
                elif status_code >= 500:
                    requests_logger.error(
                        f"Server error: {scope['method']} {scope['path']} — {status_code}",
                        extra={**log_data, "context": "ServerError"},
                    )
                elif status_code >= 400:
                    requests_logger.warning(
                        f"Client error: {scope['method']} {scope['path']} — {status_code}",
                        extra={**log_data, "context": "ClientError"},
                    )
                else:
                    requests_logger.info(
                        f"{scope['method']} {scope['path']} — {status_code} ({duration_ms:.0f}ms)",
                        extra={**log_data, "context": "Request"},
                    )
            
            await send(message)
        
        try:
            await self.app(scope, receive, send_with_logging)
        except Exception:
            duration_ms = (time.time() - start_time) * 1000
            requests_logger.error(
                f"Unhandled exception in {scope['method']} {scope['path']}",
                extra={**request_info, "duration_ms": round(duration_ms, 2), "context": "UnhandledException"},
            )
            raise


def register_middleware(app: FastAPI) -> None:
    """
    Зарегистрировать все middleware и обработчики ошибок
    Register all middleware and error handlers
    """
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(Exception, global_exception_handler)
    
    app.add_middleware(RequestLoggingMiddleware)
    
    logger.info("Middleware registered: error handlers + request logging")
