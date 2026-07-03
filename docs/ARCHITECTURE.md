# Архитектура проекта (Project Architecture)

> Где размещать код? Как организован проект? Читай перед созданием новых файлов.

## Текущий стек (Current stack)

- **Backend:** Python 3.11+, FastAPI
- **База данных:** SQLite + SQLAlchemy ORM
- **Миграции:** Alembic
- **Тесты:** pytest, pytest-asyncio, freezegun, factory-boy
- **Логирование:** стандартный `logging` + `RotatingFileHandler`
- **Frontend внутри FastAPI:** Jinja2 templates + HTMX/vanilla JS

## Целевая структура (Target structure)

```
running-coach/
├── alembic/                    # Миграции Alembic
│   ├── versions/               # Файлы миграций
│   └── env.py                  # Конфигурация Alembic
├── docs/                       # Документация
│   ├── DEVELOPMENT_GUIDELINES.md
│   ├── CODE_GUIDELINES.md
│   ├── ARCHITECTURE.md
│   ├── API_ROUTES_GUIDE.md
│   ├── ERROR_HANDLING.md
│   ├── NAMING_CONVENTIONS.md
│   ├── TESTING.md
│   ├── CHECKLIST_API.md
│   ├── CHECKLIST_MIGRATION.md
│   ├── CHECKLIST_FEATURE.md
│   └── coros_health_metrics.md
├── scripts/                    # Вспомогательные скрипты
│   ├── version.py              # Управление версиями
│   ├── changelog.py            # Автоматизация CHANGELOG
│   └── tmp/                    # Одноразовые скрипты
├── src/                        # Исходный код
│   ├── __init__.py
│   ├── api/                    # FastAPI роуты и middleware
│   │   ├── __init__.py
│   │   ├── deps.py             # Зависимости FastAPI
│   │   ├── middleware.py       # Error handlers + timing
│   │   └── routes/             # Роуты по доменам
│   │       ├── __init__.py
│   │       ├── training.py     # Тренировки
│   │       ├── coros.py        # Coros sync
│   │       ├── settings.py     # Настройки пользователя
│   │       └── health.py       # Health check
│   ├── config/                 # Конфигурация
│   │   ├── __init__.py
│   │   └── constants.py        # CONFIG объект
│   ├── exceptions.py           # Типизированные исключения
│   ├── models.py               # SQLAlchemy модели
│   ├── parsers/                # Парсеры файлов
│   │   ├── __init__.py
│   │   ├── common.py           # Общая обработка trackpoints
│   │   ├── tcx_parser.py       # TCX парсер
│   │   └── fit_parser.py       # FIT парсер
│   ├── services/               # Бизнес-логика по доменам
│   │   ├── __init__.py
│   │   ├── training/           # Анализ тренировок
│   │   │   ├── __init__.py
│   │   │   ├── segmentation.py
│   │   │   ├── classification.py
│   │   │   ├── zones.py
│   │   │   └── statistics.py
│   │   ├── coros/              # Coros API интеграция
│   │   │   ├── __init__.py
│   │   │   ├── client.py
│   │   │   ├── sync.py
│   │   │   └── dto.py          # Pydantic DTO
│   │   └── analytics/          # AI-аналитика и рекомендации
│   │       ├── __init__.py
│   │       └── readiness.py
│   ├── schemas/                # Pydantic схемы для API
│   │   ├── __init__.py
│   │   ├── training.py
│   │   └── settings.py
│   ├── utils/                  # Общие утилиты
│   │   ├── __init__.py
│   │   ├── date_format.py
│   │   ├── logger.py
│   │   └── validators.py
│   ├── crypto.py               # Шифрование паролей
│   ├── logger.py               # Legacy: logger (перенести в utils/logger.py)
│   ├── telegram_bot.py         # Telegram бот
│   └── ...
├── tests/                      # Тесты
│   ├── conftest.py             # Фикстуры pytest
│   ├── unit/                   # Unit тесты
│   ├── integration/            # Integration тесты
│   └── e2e/                    # E2E тесты
├── uploads/                    # Загруженные файлы
├── screenshots/                # Скриншоты для README
├── main.py                     # Точка входа FastAPI
├── run_telegram_bot.py         # Запуск только Telegram бота
├── pyproject.toml              # Зависимости
├── alembic.ini                 # Конфиг Alembic
├── CHANGELOG.md                # История изменений
├── README.md                   # Описание проекта
├── AGENTS.md                   # Контекст для ИИ-агентов
└── PROJECT_AUDIT.md            # Аудит проекта и план рефакторинга
```

## Правила размещения кода

### Где писать новый код?

| Что делаешь | Куда класть | Пример |
|-------------|-------------|--------|
| Новый endpoint | `src/api/routes/<domain>.py` | `src/api/routes/training.py` |
| Бизнес-логика | `src/services/<domain>/` | `src/services/training/classification.py` |
| Pydantic схемы | `src/schemas/<domain>.py` | `src/schemas/training.py` |
| SQLAlchemy модели | `src/models.py` | `class TrainingSession` |
| Новая константа | `src/config/constants.py` | `CONFIG.PACE.MAX_CREDIBLE_PACE` |
| Новое исключение | `src/exceptions.py` | `class CorosAPIError` |
| Утилита общего назначения | `src/utils/` | `src/utils/date_format.py` |
| Тест | `tests/unit/`, `tests/integration/` | `tests/unit/test_classification.py` |
| Миграция БД | `alembic/versions/` | `c3f51ae84837_baseline.py` |

### Принцип тонких роутов

**API endpoint должен быть коротким:**

```python
# src/api/routes/training.py — ПРАВИЛЬНО
@router.post("/upload")
async def upload_training(
    file: UploadFile,
    db: Session = Depends(get_db),
):
    """Загрузить тренировку (Upload training)"""
    service = TrainingService(db)
    result = await service.process_upload(file)
    return {"status": "ok", "training_id": result.id}
```

**Неправильно** — весь SQL, парсинг и бизнес-логика внутри роута.

### Принцип DRY

Перед созданием нового файла/функции спроси себя:

1. Существует ли похожая функция?
2. Можно ли параметризовать существующую?
3. Эта логика используется больше чем в одном месте?

Если ответ "да" хотя бы на один вопрос — не создавай дубликат.

### Legacy-код

Некоторые файлы ещё не перенесены в новую структуру:
- `src/logger.py` → переносится в `src/utils/logger.py`
- `src/telegram_bot.py` → часть логики переносится в `src/services/telegram/`

**Правило:** не добавляй новый код в legacy-файлы. Рефактори постепенно.

## Потоки данных (Data flow)

### Загрузка тренировки

```
HTTP POST /training/upload
  ↓
src/api/routes/training.py (валидация)
  ↓
TrainingService.process_upload(file)
  ↓
Parser (tcx/fit) → process_trackpoints() → segments
  ↓
SQLAlchemy → SQLite
  ↓
HTTP JSON response
```

### Coros sync

```
HTTP POST /coros/sync
  ↓
src/api/routes/coros.py
  ↓
CorosSyncService.sync_activities(user)
  ↓
CorosClient.list_activities() + download FIT
  ↓
FIT parser → process_trackpoints()
  ↓
SQLAlchemy → SQLite
```

## Важные ограничения

- **Single-user mode:** сейчас `_current_user_id = 1`. Аутентификация в планах.
- **SQLite:** не делай тяжёлых миграций с переименованием таблиц — медленно.
- **Telegram bot:** запускается в фоновом потоке в `startup()`.

---

**Последнее обновление:** 30.06.2026
