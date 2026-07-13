"""
Утилита для запуска корутин из синхронного контекста (Thread-safe async runner).

Используется в scheduler, web sync routes и Telegram sync_runner
для вызова async-функций из синхронных потоков (threading.Thread).
"""
import asyncio


def run_async_in_thread(coro):
    """Run a coroutine in a fresh event loop (thread-safe).
    Тред-безопасный запуск корутины в новом event loop.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
