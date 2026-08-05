# Чеклист миграции базы данных

Перед коммитом проверь каждый пункт (Check each item before commit):

## Создание миграции (Creating migration)

- [ ] Миграция создана через `alembic revision --autogenerate -m "description"`
- [ ] Файл миграции имеет понятное имя (snake_case, описательное)
- [ ] Миграция содержит только ОДНО логическое изменение

## Структура миграции (Migration structure)

- [ ] Функция `upgrade()` реализована (применение изменений)
- [ ] Функция `downgrade()` реализована (откат изменений)
- [ ] `downgrade()` действительно отменяет `upgrade()` (не пустая)
- [ ] Добавлены комментарии на русском и английском

## Идемпотентность (Idempotency)

- [ ] `CREATE INDEX IF NOT EXISTS` для индексов
- [ ] Проверка существования таблицы перед `CREATE TABLE`
- [ ] Проверка существования колонки перед `ADD COLUMN`
- [ ] Миграцию можно запустить несколько раз без ошибок

## Индексы (Indexes)

- [ ] Добавлены индексы для часто запрашиваемых полей
- [ ] Добавлены индексы для полей в `WHERE` и `JOIN`
- [ ] Unique constraint где нужно (email, date+user_id)
- [ ] Составные индексы для частых комбинаций фильтров

## Тестирование (Testing)

- [ ] `alembic upgrade head` проходит без ошибок
- [ ] `alembic downgrade -1` проходит без ошибок
- [ ] После downgrade + upgrade схема идентична
- [ ] Существующие данные не теряются при миграции
- [ ] Тесты проходят после миграции: `pytest tests/`

## Безопасность (Safety)

- [ ] Миграция не удаляет данные без подтверждения
- [ ] `DROP TABLE` / `DROP COLUMN` — только если точно нужно
- [ ] Для больших таблиц — учтено время блокировки
- [ ] Есть backup план (как откатить в production)

## Деплой миграции в прод (Production deploy) — урок инцидента 05.08.2026

Миграции применяются автоматически на старте `app`. Порядок:

- [ ] `bin/backup_db.sh` — ВСЕГДА перед деплоем
- [ ] Миграция проверена в PG-режиме тестов (`TEST_PG_URL`, CI это делает автоматически)
- [ ] **Если миграция содержит `ALTER TABLE`/DDL по «живым» таблицам — СНАЧАЛА `docker compose stop bot`**,
      потом `docker compose up -d app`, потом `up -d bot`. Бот держит транзакции
      (sync-цикл) → `ALTER` ждёт лока, прерванная попытка может оставить
      полупримененную схему без штампа версии → crash-loop app (BACKLOG #234)
- [ ] После старта: `curl localhost:8000/health/` — блок `migrations.current_revision` = новый head
- [ ] Если app в crash-loop на миграции: `docker compose stop app bot` →
      `docker compose run --rm --no-deps app python -m alembic upgrade head` —
      покажет реальный traceback (в логах контейнера его НЕТ — BACKLOG #235)

## Документация (Documentation)

- [ ] CHANGELOG.md обновлён (секция `### Added` или `### Changed`)
- [ ] Описание миграции понятно (что добавлено/изменено/удалено)

---

## Команды Alembic (Alembic commands)

```bash
# Создать миграцию (Create migration)
alembic revision --autogenerate -m "add recovery_pct to daily_metrics"

# Применить все миграции (Apply all migrations)
alembic upgrade head

# Откатить последнюю (Rollback last)
alembic downgrade -1

# Показать статус (Show status)
alembic current
alembic history

# Проверить pending миграции (Check pending migrations)
alembic heads
```

## Частые ошибки (Common mistakes)

- ❌ Не заполнена `downgrade()` — невозможно откатить
- ❌ Несколько изменений в одной миграции — сложно откатить
- ❌ Нет `IF NOT EXISTS` — падает при повторном запуске
- ❌ Удаление колонки с данными — потеря данных!
- ❌ Изменение типа колонки без cast — может упасть на данных
