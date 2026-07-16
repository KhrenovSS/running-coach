# Рекомендации по написанию кода (Code Guidelines)

> Практическое руководство: как писать код, чтобы даже слабая модель делала качественно.  
> Много примеров "❌ До" → "✅ После".

## Содержание

1. [Константы — никаких magic numbers](#1-константы--никаких-magic-numbers)
2. [Архитектура: где писать код](#2-архитектура-где-писать-код)
3. [API endpoints: тонкие роуты](#3-api-endpoints-тонкие-роуты)
4. [База данных и миграции](#4-база-данных-и-миграции)
5. [Валидация через Pydantic](#5-валидация-через-pydantic)
6. [Обработка ошибок](#6-обработка-ошибок)
7. [Логирование](#7-логирование)
8. [Комментарии и докстринги](#8-комментарии-и-докстринги)
9. [Импорты](#9-импорты)
10. [Чеклисты перед коммитом](#10-чеклисты-перед-коммитом)

---

## 1. Константы — никаких magic numbers

### Правило

**Все** числа, строки, URL, пороги — через `from src.config import settings` (env-настройки) или `from src.config.constants import NAME` (фиксированные константы).

### ❌ До

```python
def classify_hr(hr: int) -> str:
    if hr < 106:
        return "Z1"
    elif hr < 124:
        return "Z2"
    elif hr < 142:
        return "Z3"
    elif hr < 154:
        return "Z4"
    else:
        return "Z5"

# Где-то в коде:
resp = httpx.get(url, timeout=15)
```

### ✅ После

```python
from src.config import settings
from src.config.constants import HR_ZONE_1_MAX_PCT, HR_ZONE_2_MAX_PCT

def classify_hr(hr: int, max_hr: int) -> str:
    return get_hr_zone(hr, max_hr)  # пороги из constants.py

resp = httpx.get(url, timeout=settings.http_timeout)
```

### Где брать константы

| Вместо | Используй |
|--------|-----------|
| `177` | `settings.default_max_hr` |
| `15` (timeout) | `settings.http_timeout` |
| `3.0` (мин/км) | `MAX_CREDIBLE_PACE` (constants.py) |
| `0.2` (км) | `MIN_SEGMENT_DISTANCE_KM` (constants.py) |
| `1.0` (вариативность) | `VARIABILITY_THRESHOLD` (constants.py) |
| `21600` (health sync) | `SYNC_HEALTH_INTERVAL` (constants.py) |
| `180` (дней) | `HEALTH_SYNC_DAYS` (constants.py) |
| `7` (TTL сессии) | `settings.session_ttl_days` |
| `"UTC"` | `settings.timezone` |

### Когда добавлять новую константу

Если значение:
1. Используется больше 1 раза
2. Может меняться (настройка, env)
3. Неочевидно без контекста

→ добавляй в `src/config/constants.py` (фиксированные) или `src/config/settings.py` (env).

---

## 2. Архитектура: где писать код

### Золотое правило

| Что | Где |
|-----|-----|
| HTTP endpoint | `src/api/routes/<domain>.py` |
| Бизнес-логика | `src/services/<domain>/` |
| SQLAlchemy модели | `src/domain/models/<domain>.py` |
| Константы | `src/config/constants.py` |
| Настройки из env | `src/config/settings.py` |
| Исключения | `src/exceptions.py` |
| Утилиты общего назначения | `src/utils/` |

### ❌ До — всё в main.py

```python
# main.py — 300+ строк
@app.post("/upload")
async def upload(file: UploadFile, db: Session = Depends(get_db)):
    # 1. Парсинг XML
    tree = ET.parse(file.file)
    # 2. Очистка GPS
    # 3. Сегментация
    # 4. Сохранение в БД
    # 5. Возврат
```

### ✅ После — разделение ответственности

```python
# src/api/routes/training.py
from src.services.training.upload import TrainingUploadService

@router.post("/upload")
async def upload(file: UploadFile, db: Session = Depends(get_db)):
    """Загрузить тренировку (Upload training)"""
    service = TrainingUploadService(db)
    training = await service.process(file)
    return {"status": "ok", "training_id": training.id}

# src/services/training/upload.py
class TrainingUploadService:
    """Сервис загрузки тренировок (Training upload service)"""
    
    def __init__(self, db: Session):
        self.db = db
    
    async def process(self, file: UploadFile) -> TrainingSession:
        """Обработать загруженный файл (Process uploaded file)"""
        parser = get_parser_for_file(file.filename)
        trackpoints = parser.parse(file.file)
        cleaned = clean_trackpoints(trackpoints)
        segments = segment_training(cleaned)
        return self.save(cleaned, segments)
```

### Размер файла

- **Максимум ~400 строк**. Если больше — разбивай на модули.
- **Роут — максимум ~80 строк**. Если больше — логика уходит в сервис.

---

## 3. API endpoints: тонкие роуты

### Шаблон роута

```python
# src/api/routes/training.py
from fastapi import APIRouter, Depends, UploadFile, status
from sqlalchemy.orm import Session

from src.api.deps import get_db
from src.schemas.training import TrainingUploadResponse
from src.services.training.upload import TrainingUploadService

router = APIRouter(prefix="/training", tags=["training"])

@router.post(
    "/upload",
    response_model=TrainingUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_training(
    file: UploadFile,
    db: Session = Depends(get_db),
):
    """
    Загрузить тренировку из TCX/FIT файла
    Upload training from TCX/FIT file
    """
    service = TrainingUploadService(db)
    training = await service.process(file)
    return TrainingUploadResponse(
        status="ok",
        training_id=training.id,
    )
```

### Что должен делать роут

1. Принять запрос
2. Валидировать вход (Pydantic / FastAPI автоматически)
3. Вызвать сервис
4. Вернуть ответ

### Что роут НЕ должен делать

- Парсить XML / FIT напрямую
- Строить SQL
- Ходить во внешние API
- Содержать бизнес-правила
- Содержать длинные if/else цепочки

### Статус-коды

```python
from fastapi import status

# GET — 200 (default)
# POST create — 201
# DELETE — 204
# Validation error — 400
# Not found — 404
# Server error — 500

@router.delete("/{training_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_training(training_id: int, db: Session = Depends(get_db)):
    """Удалить тренировку (Delete training)"""
    service = TrainingService(db)
    await service.delete(training_id)
    return None
```

### Зависимости

```python
# src/api/deps.py
from typing import Generator
from fastapi import Depends
from sqlalchemy.orm import Session
from src.domain.models.base import SessionLocal

def get_db() -> Generator[Session, None, None]:
    """Сессия БД (DB session)"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

---

## 4. База данных и миграции

### Правила работы с БД

1. **Только Alembic** для изменения схемы
2. **Параметризованные запросы** — никаких f-string в SQL
3. **Модели в `src/domain/models/`** (по доменам: user.py, training.py, health.py и т.д.)
4. **Индексы** для частых `WHERE`/`JOIN`

### ❌ До

```python
# НЕПРАВИЛЬНО — SQL injection!
result = db.execute(f"SELECT * FROM training_sessions WHERE user_id = {user_id}")

# НЕПРАВИЛЬНО — ALTER TABLE в коде
@app.on_event("startup")
def startup():
    db.execute("ALTER TABLE daily_metrics ADD COLUMN recovery_pct INTEGER")
```

### ✅ После

```python
# Правильно — ORM
sessions = db.query(TrainingSession).filter(
    TrainingSession.user_id == user_id
).all()

# Правильно — Alembic миграция
# alembic/versions/xxxx_add_recovery_pct.py
op.add_column('daily_metrics', sa.Column('recovery_pct', sa.Integer(), nullable=True))
```

### Создание миграции

```bash
alembic revision --autogenerate -m "add recovery_pct to daily_metrics"
alembic upgrade head
```

### Идемпотентность (safe to rerun)

```python
# alembic/versions/xxxx_add_index.py
from alembic import op
import sqlalchemy as sa

def upgrade():
    # CREATE INDEX IF NOT EXISTS
    op.create_index(
        'ix_training_sessions_user_id',
        'training_sessions',
        ['user_id'],
        if_not_exists=True,
    )

def downgrade():
    op.drop_index(
        'ix_training_sessions_user_id',
        'training_sessions',
        if_exists=True,
    )
```

---

## 5. Валидация через Pydantic

### Правило

Все входные данные API — Pydantic модели.

### ❌ До

```python
@app.post("/settings")
async def save_settings(request: Request, db: Session = Depends(get_db)):
    data = await request.json()
    max_hr = data.get("max_hr")
    if not isinstance(max_hr, int) or max_hr < 100 or max_hr > 220:
        return {"error": "invalid max_hr"}
```

### ✅ После

```python
# src/schemas/settings.py
from pydantic import BaseModel, Field, field_validator

class SettingsUpdate(BaseModel):
    """Обновление настроек (Settings update)"""
    max_hr: int = Field(ge=100, le=220)
    weight_kg: float = Field(ge=30, le=300)
    max_credible_pace: float = Field(ge=2.0, le=10.0)

# src/api/routes/settings.py
@router.post("/")
async def save_settings(
    settings: SettingsUpdate,
    db: Session = Depends(get_db),
):
    """Сохранить настройки (Save settings)"""
    service = SettingsService(db)
    service.update(settings)
    return {"status": "ok"}
```

### Правила Pydantic

- `Field(ge=, le=, min_length=, max_length=, pattern=)` для ограничений
- `@field_validator` для кросс-полевой логики
- `response_model=` для типизации ответов

---

## 6. Обработка ошибок

### Главное правило

**Запрещён `except: pass`. Всегда указывай тип исключения и логируй.**

### ❌ До

```python
try:
    result = requests.get(url, timeout=15)
except:
    pass
```

### ✅ После

```python
import httpx
from src.config import settings
from src.exceptions import WatchAPIError
from src.utils.logger import logger

try:
    result = await httpx.AsyncClient().get(url, timeout=settings.http_timeout)
    result.raise_for_status()
except httpx.HTTPStatusError as e:
    logger.error(f"Watch API error: {url} → {e.response.status_code}")
    raise WatchAPIError(str(e), brand="coros", status=e.response.status_code)
except httpx.RequestError as e:
    logger.error(f"Watch API network error: {url} → {e}")
    raise WatchAPIError(str(e), brand="coros")
```

### Исключения проекта

```python
from src.exceptions import (
    NotFoundError,      # 404
    ValidationError,    # 400
    WatchAPIError,      # 502
    WatchAuthError,     # 401
    AuthenticationError,# 401
    DatabaseError,      # 500
    FileProcessingError,# 422
)

# Примеры использования:
raise NotFoundError("training", training_id)
raise ValidationError("max_hr", "must be between 100 and 220")
raise WatchAPIError("Not authenticated", brand="coros")
```

### Обработка в сервисах

```python
# src/services/training/detail.py
from src.exceptions import NotFoundError

class TrainingDetailService:
    def get(self, training_id: int) -> TrainingSession:
        training = self.db.query(TrainingSession).get(training_id)
        if not training:
            raise NotFoundError("training", training_id)
        return training
```

---

## 7. Логирование

### Правило

Используй `logger` из `src.utils.logger`. Никакого `print()`.

### ❌ До

```python
print("Sync started")
print(f"Found {count} activities")
```

### ✅ После

```python
from src.utils.logger import logger

logger.info("Coros sync started")
logger.info(f"Coros sync completed: {count} activities processed")
logger.warning(f"Slow query detected: {duration_ms}ms")
logger.error(f"Failed to parse file {filename}: {error}")
```

### Что логировать

| Уровень | Когда |
|---------|-------|
| DEBUG | Детали разработки, дампы данных |
| INFO | Ключевые операции (sync, upload, delete) |
| WARNING | Аномалии, fallback'ы, медленные запросы |
| ERROR | Сбои, исключения |

### Что НЕ логировать

- Пароли
- API токены
- Refresh tokens
- Персональные данные пользователя

---

## 8. Комментарии и докстринги

### Правило

**Комментарии писать СРАЗУ, не позже.** Каждая функция/класс — докстринг. Сложные блоки — комментарий. Язык: русский + английский в скобках.

### Обязательно

```python
# Расчёт среднего темпа по сегменту (Calculate average pace for segment)
def calc_avg_pace(distance_km: float, duration_min: float) -> float:
    """
    Рассчитать средний темп в мин/км
    Calculate average pace in min/km
    
    Args:
        distance_km: дистанция в км (distance in km)
        duration_min: длительность в минутах (duration in minutes)
    
    Returns:
        Темп в мин/км (pace in min/km)
    """
    return duration_min / distance_km
```

### Необязательно

```python
# ✅ Не нужен комментарий
x = x + 1

# ✅ Не нужен комментарий
return result
```

---

## 9. Импорты

### Порядок

```python
# 1. Стандартная библиотека
import os
import json
from datetime import datetime

# 2. Сторонние библиотеки
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel

# 3. Внутренние модули
from src.config import settings
from src.config.constants import HEALTH_SYNC_DAYS
from src.domain.models.training import TrainingSession
from src.domain.models.base import get_db
from src.utils.logger import logger
```

### Импорт настроек и констант

```python
# ✅ Правильно (env-настройки)
from src.config import settings

timeout = settings.http_timeout

# ✅ Правильно (фиксированные константы)
from src.config.constants import HEALTH_SYNC_DAYS, MAX_CREDIBLE_PACE

days = HEALTH_SYNC_DAYS

# ❌ Неправильно — старый способ, используйте settings / constants
timeout = 15
max_hr = 177
```

---

## 10. Чеклисты перед коммитом

### Любой код

- [ ] Нет `except: pass`
- [ ] Нет `print()` — используется `logger`
- [ ] Нет hardcoded значений — используются `settings.*` / `constants.*`
- [ ] Комментарии bilingual (RU/EN)
- [ ] Типизация (type hints)
- [ ] Тесты проходят: `pytest tests/ -v`

### API endpoint

- [ ] Роут в `src/api/routes/<domain>.py`
- [ ] `response_model` указан
- [ ] Бизнес-логика в `src/services/<domain>/`
- [ ] Обработка ошибок через `src/exceptions.py`

### Миграция

- [ ] Создана через `alembic revision --autogenerate`
- [ ] Есть `downgrade()`
- [ ] Идемпотентна
- [ ] Тестирован `upgrade`/`downgrade`

### Безопасность данных

- [ ] Правка не удаляет и не переименовывает колонки без миграции
- [ ] Изменение сигнатуры функции, вызываемой в `startup.py`, проверено на всех местах вызова
- [ ] Если правка затрагивает `startup.py`, `models.py` (shim), `src/domain/models/base.py` — проверен сценарий первого запуска на пустой БД
- [ ] Есть fallback / возможность отката для пользовательских данных

### Action-проверка перед опасным рефакторингом

Если изменение может затронуть существующие данные в БД (переименование функции, смена аргументов, удаление колонки, рефакторинг startup):

1. **Остановись** — не применяй автоматически
2. **Опиши пользователю**: какие данные под угрозой, что будет после рефакторинга, есть ли миграция
3. **Получи подтверждение** — только после явного `да» применяй
4. **Пример:** рефакторинг `get_settings()` без параметра → `get_settings(user_id)` в PREP-11 потребовал обновления `startup.py:45` и `uploads.py:79`. Без этого при рестарте контейнера `TypeError` в startup приводил к потере пользователя и всех его данных.

---

**Последнее обновление:** 16.07.2026 (Sprint 20c)
