# Запуск Telegram-бота как отдельного процесса (Run Telegram bot as standalone process)
import os
import sys

# Добавляем корень проекта в путь (Add project root to path)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.telegram_bot import run_bot

if __name__ == "__main__":
    run_bot()
