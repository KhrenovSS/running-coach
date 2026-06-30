# Обработка ошибок (Error Handling)

> Как правильно обрабатывать исключения в running-coach.

## Главные правила

1. **Запрещён `except: pass`** — всегда указывай тип исключения.
2. **Логируй ошибки** с контекстом.
3. **Используй типизированные исключения** из `src/exceptions.py`.
4. **Возвращай user-friendly сообщения**, не stack traces.
5. **Не лови Exception без причины** — лови только то, что можешь обработать.

## Иерархия исключений

```
Exception
  └── AppError (наше базовое)
        ├── NotFoundError          # 404
        ├── ValidationError        # 400
        ├── AuthenticationError    # 401
        ├── CorosAPIError          # 502
        ├── FileProcessingError    # 422
        ├── DatabaseError          # 500
        └── RateLimitError         # 429
```

## Исключения проекта

| Исключение | Статус | Когда использовать |
|------------|--------|-------------------|
| `NotFoundError(resource, id)` | 404 | Ресурс не найден в БД |
| `ValidationError(field, reason)` | 400 | Невалидные входные данные |
| `AuthenticationError(reason)` | 401 | Проблема аутентификации |
| `CorosAPIError(endpoint, status)` | 502 | Ошибка Coros API |
| `FileProcessingError(filename, reason)` | 422 | Ошибка парсинга файла |
| `DatabaseError(operation, details)` | 500 | Ошибка базы данных |
| `RateLimitError(message, retry_after)` | 429 | Превышен лимит запросов |

## Примеры

### 1. Ресурс не найден

```python
from src.exceptions import NotFoundError

def get_training(db: Session, training_id: int) -> TrainingSession:
    """Получить тренировку (Get training)"""
    training = db.query(TrainingSession).get(training_id)
    if not training:
        raise NotFoundError("training", training_id)
    return training
```

Клиент получит:
```json
{
  "message": "training 42 not found",
  "resource": "training",
  "id": 42
}
```

### 2. Внешний API

```python
import httpx
from src.config import CONFIG
from src.exceptions import CorosAPIError
from src.utils.logger import logger

async def fetch_activities(access_token: str):
    """Загрузить список активностей (Fetch activities)"""
    url = f"{CONFIG.COROS.BASE_URL}{CONFIG.COROS.ACTIVITIES_ENDPOINT}"
    
    try:
        async with httpx.AsyncClient(timeout=CONFIG.TIMING.HTTP_TIMEOUT) as client:
            response = await client.get(url, headers={"Authorization": access_token})
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as e:
        logger.error(f"Coros API HTTP error: {url} → {e.response.status_code}")
        raise CorosAPIError(CONFIG.COROS.ACTIVITIES_ENDPOINT, e.response.status_code)
    except httpx.RequestError as e:
        logger.error(f"Coros API network error: {url} → {e}")
        raise CorosAPIError(CONFIG.COROS.ACTIVITIES_ENDPOINT, 0)
```

### 3. Обработка файла

```python
from src.exceptions import FileProcessingError

def parse_tcx(file_path: str) -> list[TrackPoint]:
    """Парсинг TCX файла (Parse TCX file)"""
    try:
        tree = ET.parse(file_path)
        return _extract_trackpoints(tree)
    except ET.ParseError as e:
        logger.error(f"Failed to parse TCX {file_path}: {e}")
        raise FileProcessingError(file_path, f"Invalid XML: {e}")
    except FileNotFoundError:
        raise FileProcessingError(file_path, "File not found")
```

### 4. База данных

```python
from src.exceptions import DatabaseError

def save_training(db: Session, training: TrainingSession) -> None:
    """Сохранить тренировку (Save training)"""
    try:
        db.add(training)
        db.commit()
    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Failed to save training: {e}")
        raise DatabaseError("save training", str(e))
```

## Антипаттерны

### ❌ `except: pass`

```python
# ПЛОХО — ошибка проглатывается
try:
    result = await fetch_data()
except:
    pass
```

```python
# ХОРОШО — тип + лог + fallback
try:
    result = await fetch_data()
except httpx.RequestError as e:
    logger.error(f"Network error: {e}")
    raise CorosAPIError("/endpoint", 0)
```

### ❌ Голый `raise Exception`

```python
# ПЛОХО
if not training:
    raise Exception("Training not found")
```

```python
# ХОРОШО
if not training:
    raise NotFoundError("training", training_id)
```

### ❌ Широкий `except Exception`

```python
# ПЛОХО — ловит всё подряд
try:
    parse_file()
except Exception as e:
    logger.error(e)
```

```python
# ХОРОШО — конкретные типы
try:
    parse_file()
except ET.ParseError as e:
    logger.error(f"XML parse error: {e}")
    raise FileProcessingError(filename, str(e))
except FileNotFoundError:
    logger.error(f"File not found: {filename}")
    raise FileProcessingError(filename, "File not found")
```

## Middleware

Централизованная обработка уже настроена в `src/api/middleware.py`:

- `AppError` → JSON с `message` и `details`
- `HTTPException` → JSON с `message`
- `Exception` → JSON `"Internal server error"`, логируется

Не нужно добавлять try/except в каждый роут — middleware поймает.

---

**Последнее обновление:** 30.06.2026
