# Руководство по созданию API endpoints

> Шаблоны и примеры для FastAPI роутов.  
> Если нужен новый endpoint — скопируй подходящий шаблон и адаптируй.

## Содержание

1. [Базовый шаблон](#1-базовый-шаблон)
2. [GET — список](#2-get--список)
3. [GET — детальная информация](#3-get--детальная-информация)
4. [POST — создание](#4-post--создание)
5. [POST — upload файла](#5-post--upload-файла)
6. [DELETE — удаление](#6-delete--удаление)
7. [Подключение роутера к main.py](#7-подключение-роутера-к-mainpy)
8. [Частые ошибки](#8-частые-ошибки)

---

## 1. Базовый шаблон

```python
# src/api/routes/<domain>.py
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from src.api.deps import get_db
from src.schemas.<domain> import <SomeSchema>
from src.services.<domain>.<service> import <SomeService>
from src.exceptions import NotFoundError

router = APIRouter(
    prefix="/<domain>",
    tags=["<domain>"],
)


@router.get("/", response_model=list[<SomeSchema>])
async def list_items(
    db: Session = Depends(get_db),
):
    """
    Список ... (List ...)
    """
    service = <SomeService>(db)
    return service.list()
```

### Обязательные элементы

- `APIRouter(prefix="...", tags=["..."])`
- `response_model=` для GET/POST
- `status_code=` для POST/DELETE
- `db: Session = Depends(get_db)`
- Докстринг на русском и английском
- Вызов сервиса, не прямая логика

---

## 2. GET — список

```python
# src/api/routes/training.py
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import Annotated

from src.api.deps import get_db
from src.schemas.training import TrainingSummary
from src.services.training.list import TrainingListService

router = APIRouter(prefix="/training", tags=["training"])


@router.get("/", response_model=list[TrainingSummary])
async def list_trainings(
    year: Annotated[int | None, Query(ge=2000, le=2100)] = None,
    month: Annotated[int | None, Query(ge=1, le=12)] = None,
    db: Session = Depends(get_db),
):
    """
    Список тренировок с фильтром по году/месяцу
    List trainings filtered by year/month
    """
    service = TrainingListService(db)
    return service.list_trainings(year=year, month=month)
```

### Сервис

```python
# src/services/training/list.py
from sqlalchemy.orm import Session
from src.models import TrainingSession

class TrainingListService:
    """Сервис списка тренировок (Training list service)"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def list_trainings(
        self,
        year: int | None = None,
        month: int | None = None,
    ) -> list[TrainingSession]:
        """
        Получить список тренировок (Get trainings list)
        """
        query = self.db.query(TrainingSession).order_by(TrainingSession.begin_ts.desc())
        
        if year is not None:
            query = query.filter(self.db.extract('year', TrainingSession.begin_ts) == year)
        if month is not None:
            query = query.filter(self.db.extract('month', TrainingSession.begin_ts) == month)
        
        return query.all()
```

---

## 3. GET — детальная информация

```python
# src/api/routes/training.py
from fastapi import APIRouter, Depends, Path
from sqlalchemy.orm import Session

from src.api.deps import get_db
from src.schemas.training import TrainingDetail
from src.services.training.detail import TrainingDetailService

router = APIRouter(prefix="/training", tags=["training"])


@router.get("/{training_id}", response_model=TrainingDetail)
async def get_training(
    training_id: int,
    db: Session = Depends(get_db),
):
    """
    Детальная информация о тренировке
    Get training details
    """
    service = TrainingDetailService(db)
    return service.get(training_id)
```

### Сервис с обработкой 404

```python
# src/services/training/detail.py
from sqlalchemy.orm import Session
from src.models import TrainingSession
from src.exceptions import NotFoundError

class TrainingDetailService:
    """Сервис деталей тренировки (Training detail service)"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def get(self, training_id: int) -> TrainingSession:
        """
        Получить тренировку по ID (Get training by ID)
        """
        training = self.db.query(TrainingSession).get(training_id)
        if not training:
            raise NotFoundError("training", training_id)
        return training
```

---

## 4. POST — создание

```python
# src/api/routes/settings.py
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from src.api.deps import get_db
from src.schemas.settings import SettingsUpdate
from src.services.settings import SettingsService

router = APIRouter(prefix="/settings", tags=["settings"])


@router.post("/", response_model=dict, status_code=status.HTTP_200_OK)
async def save_settings(
    settings: SettingsUpdate,
    db: Session = Depends(get_db),
):
    """
    Сохранить настройки пользователя
    Save user settings
    """
    service = SettingsService(db)
    service.update(settings)
    return {"status": "ok"}
```

### Pydantic схема

```python
# src/schemas/settings.py
from pydantic import BaseModel, Field

class SettingsUpdate(BaseModel):
    """Обновление настроек (Settings update)"""
    max_hr: int = Field(ge=100, le=220)
    weight_kg: float = Field(ge=30, le=300)
    max_credible_pace: float = Field(ge=2.0, le=10.0)
```

---

## 5. POST — upload файла

```python
# src/api/routes/training.py
from fastapi import APIRouter, Depends, UploadFile, File, status
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
    file: UploadFile = File(...),
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

### Сервис upload

```python
# src/services/training/upload.py
from fastapi import UploadFile
from sqlalchemy.orm import Session

from src.models import TrainingSession
from src.parsers.tcx_parser import TcxParser
from src.parsers.fit_parser import FitParser
from src.exceptions import FileProcessingError

class TrainingUploadService:
    """Сервис загрузки тренировок (Training upload service)"""
    
    def __init__(self, db: Session):
        self.db = db
    
    async def process(self, file: UploadFile) -> TrainingSession:
        """
        Обработать загруженный файл (Process uploaded file)
        """
        parser = self._get_parser(file.filename)
        try:
            training = parser.parse(file.file)
        except Exception as e:
            raise FileProcessingError(file.filename, str(e))
        
        self.db.add(training)
        self.db.commit()
        return training
    
    def _get_parser(self, filename: str):
        """Выбрать парсер по расширению (Select parser by extension)"""
        if filename.endswith('.tcx'):
            return TcxParser()
        elif filename.endswith('.fit'):
            return FitParser()
        raise FileProcessingError(filename, "Unsupported file format")
```

---

## 6. DELETE — удаление

```python
# src/api/routes/training.py
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from src.api.deps import get_db
from src.services.training.delete import TrainingDeleteService

router = APIRouter(prefix="/training", tags=["training"])


@router.delete("/{training_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_training(
    training_id: int,
    db: Session = Depends(get_db),
):
    """
    Удалить тренировку
    Delete training
    """
    service = TrainingDeleteService(db)
    service.delete(training_id)
    return None
```

---

## 7. Подключение роутера к main.py

```python
# main.py
from fastapi import FastAPI
from src.api.middleware import register_middleware
from src.api.routes import training, settings, coros, health

app = FastAPI(title="AI Running Coach")

# Middleware
register_middleware(app)

# Роуты
app.include_router(training.router)
app.include_router(settings.router)
app.include_router(coros.router)
app.include_router(health.router)
```

### Файл `src/api/routes/__init__.py`

```python
"""
API routes package
"""
from src.api.routes import training, settings, coros, health

__all__ = ["training", "settings", "coros", "health"]
```

---

## 8. Частые ошибки

| ❌ Ошибка | ✅ Правильно |
|-----------|-------------|
| Бизнес-логика в роуте | Вынести в `services/` |
| `response_model` не указан | Всегда указывать |
| `return {"error": "..."}` | `raise HTTPException` или исключение |
| `db = SessionLocal()` в роуте | `db: Session = Depends(get_db)` |
| Отсутствует docstring | Добавить bilingual docstring |
| Множество `if/else` в роуте | Вынести в сервис |

---

**Последнее обновление:** 30.06.2026
