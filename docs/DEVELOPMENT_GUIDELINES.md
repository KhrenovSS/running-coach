# Development Guidelines — AI Running Coach

> Единая точка входа для стандартов разработки.  
> Если вы ИИ-агент — прочитайте этот файл целиком, прежде чем писать код.

## Обязательно к прочтению

| Задача | Читать |
|--------|--------|
| Начать работу с проектом | [`AGENTS.md`](../AGENTS.md) |
| Общие правила написания кода | [`CODE_GUIDELINES.md`](CODE_GUIDELINES.md) |
| Архитектура и структура проекта | [`ARCHITECTURE.md`](ARCHITECTURE.md) |
| Как писать API endpoints | [`API_ROUTES_GUIDE.md`](API_ROUTES_GUIDE.md) |
| Обработка ошибок и исключения | [`ERROR_HANDLING.md`](ERROR_HANDLING.md) |
| Соглашения об именовании | [`NAMING_CONVENTIONS.md`](NAMING_CONVENTIONS.md) |
| Как писать тесты | [`TESTING.md`](TESTING.md) |
| База данных и миграции | Раздел "База данных" в [`CODE_GUIDELINES.md`](CODE_GUIDELINES.md) + [`CHECKLIST_MIGRATION.md`](CHECKLIST_MIGRATION.md) |
| Code review / самопроверка | [`CHECKLIST_FEATURE.md`](CHECKLIST_FEATURE.md) |
| Code review API endpoint | [`CHECKLIST_API.md`](CHECKLIST_API.md) |

## Золотые правила (кратко)

1. **DRY** — не дублируй код. Ищи существующие функции/константы.
2. **Константы** — используй `from src.config import CONFIG`. Никаких magic numbers.
3. **Исключения** — используй `src/exceptions.py`. Запрещён `except: pass`.
4. **API** — тонкие роуты: валидация → сервис → ответ.
5. **База данных** — миграции только через Alembic; параметризованные запросы.
6. **Логирование** — `logger.info()`/`logger.error()` вместо `print()`.
7. **Комментарии** — bilingual (RU/EN), пиши сразу.
8. **Тесты** — unit для логики, integration для endpoint.
9. **CHANGELOG** — обновляй сразу в том же коммите.

## Быстрые ссылки

- Запуск сервера: `uvicorn main:app --host 0.0.0.0 --port 8000`
- Тесты: `pytest tests/ -v`
- Миграции: `alembic revision --autogenerate -m "..."`
- Проверка синтаксиса: `python -m py_compile main.py src/**/*.py`

---

**Последнее обновление:** 30.06.2026
