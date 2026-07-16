# Чеклист новой фичи

Перед коммитом проверь каждый пункт (Check each item before commit):

## Архитектура (Architecture)

- [ ] DRY — нет дублирования кода
- [ ] Код организован по доменам (`src/services/<domain>/`)
- [ ] Файл не больше ~400 строк (если больше — вынести)
- [ ] Нет циклических импортов

## Константы (Constants)

- [ ] Нет hardcoded значений — используются `settings.*` (env) / `constants.*` (фикс)
- [ ] Новые настройки добавлены в `src/config/constants.py` (фиксированные) или `src/config/settings.py` (env)
- [ ] Магические числа заменены на именованные константы

## Код (Code)

- [ ] Комментарии bilingual (RU/EN), написаны сразу
- [ ] Docstring для каждой функции/класса
- [ ] Типизация (type hints) для аргументов и return
- [ ] Нет `print()` — используется `logger`
- [ ] Нет `except: pass` — указаны конкретные типы

## Обработка ошибок (Error handling)

- [ ] Используются исключения из `src/exceptions.py`
- [ ] Ошибки логируются с контекстом
- [ ] User-friendly сообщения (не stack traces)

## Безопасность данных (Data safety)

- [ ] Если фича меняет структуру БД — есть Alembic миграция с `upgrade`/`downgrade`
- [ ] Рефакторинг сервисных функций не ломает `startup.py` и другие точки входа
- [ ] Изменение сигнатуры функции проверено на всех местах вызова (grep)
- [ ] При риске потери данных — предупреждение пользователю перед применением
- [ ] Есть fallback / возможность отката для пользовательских данных

## Тесты (Tests)

- [ ] Unit-тесты для бизнес-логики
- [ ] Edge cases покрыты
- [ ] Тесты проходят: `pytest tests/ -v`

## Документация (Documentation)

- [ ] CHANGELOG.md обновлён
- [ ] README.md обновлён (если фича пользовательская)
- [ ] Скриншоты обновлены (если изменился UI)

## Git (Git)

- [ ] Коммит атомарный (одна фича = один коммит)
- [ ] Сообщение коммита понятное (что сделано)
- [ ] Нет лишних файлов в коммите (.env, __pycache__, .db)

---

## Быстрая проверка (Quick check)

```bash
# Тесты (Tests)
pytest tests/ -v

# Проверка импортов (Import check)
python -c "from src.startup import create_app; print('OK')"

# Сервер стартует (Server starts)
python -c "from main import app; print('OK')"

# Константы доступны (Constants available)
python -c "from src.config import settings; print(settings.http_timeout)"
```

## Антипаттерны — НЕ ДЕЛАЙ (Anti-patterns — DON'T)

| ❌ Нельзя | ✅ Правильно |
|-----------|-------------|
| `except: pass` | `except ValueError as e: logger.error(...)` |
| `max_hr = 177` | `settings.default_max_hr` |
| `f"SELECT * WHERE id={id}"` | `db.query().filter(User.id == id)` |
| `print("debug")` | `logger.debug("message")` |
| Бизнес-логика в роуте | Бизнес-логика в `services/` |
| Один файл 1000+ строк | Разбить на модули (≤400 строк) |
| Глобальные мутабельные | Dependency injection |
