# Чеклист нового API endpoint

Перед коммитом проверь каждый пункт (Check each item before commit):

## Структура (Structure)

- [ ] Роут создан в `src/api/routes/<domain>.py`
- [ ] Используется `APIRouter` с `prefix` и `tags`
- [ ] Функция имеет docstring (bilingual RU/EN)
- [ ] Путь endpoint логичен и соответствует REST

## Валидация (Validation)

- [ ] Входные данные валидируются через Pydantic модель
- [ ] Используется `response_model=` для типизации ответа
- [ ] Query параметры имеют типы и ограничения (`Field(ge=, le=)`)
- [ ] Path параметры валидируются (тип, диапазон)

## Бизнес-логика (Business logic)

- [ ] Логика вынесена в `src/services/<domain>/`
- [ ] Роут тонкий: валидация → вызов сервиса → возврат
- [ ] Нет SQL-запросов напрямую в роуте
- [ ] Нет hardcoded значений — используются `settings.*` / `constants.*`

## Безопасность (Security)

- [ ] Параметризованные запросы к БД (не f-strings в SQL)
- [ ] Проверка прав доступа (когда будет аутентификация)
- [ ] Нет утечки sensitive данных в ответе
- [ ] Валидация файлов (тип, размер) для upload endpoints

## Обработка ошибок (Error handling)

- [ ] Используются типизированные исключения из `src/exceptions.py`
- [ ] `HTTPException` с понятным `detail` для клиента
- [ ] Нет `except: pass` — указаны конкретные типы
- [ ] Ошибки логируются с контекстом

## Логирование (Logging)

- [ ] Ключевые операции логируются (sync, upload, delete)
- [ ] Логи содержат контекст (ID, количество, результат)
- [ ] Не логируются пароли, токены, персональные данные

## Тестирование (Testing)

- [ ] Написан unit-тест для бизнес-логики
- [ ] Написан integration-тест для endpoint (если применимо)
- [ ] Edge cases покрыты (пустые данные, невалидный ввод)

## Документация (Documentation)

- [ ] CHANGELOG.md обновлён
- [ ] README.md обновлён (если добавлена новая фича)
- [ ] Swagger docs автоматически сгенерируются (проверить `/docs`)

---

## Быстрая проверка (Quick check)

```bash
# Запустить тесты (Run tests)
pytest tests/ -v

# Проверить что сервер стартует (Check server starts)
python -c "from main import app; print('OK')"

# Проверить импорты (Check imports)
python -c "from src.config import settings; print(settings.http_timeout)"
```
