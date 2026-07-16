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
from src.services.<service> import <SomeService>
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
# src/api/routes/<domain>.py
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import Annotated

from src.api.deps import get_db
from src.services.<service> import <SomeService>

router = APIRouter(prefix="/<domain>", tags=["<domain>"])


@router.get("/", response_model=list)
async def list_items(
    year: Annotated[int | None, Query(ge=2000, le=2100)] = None,
    month: Annotated[int | None, Query(ge=1, le=12)] = None,
    db: Session = Depends(get_db),
):
    """
    Список ... с фильтром по году/месяцу
    List ... filtered by year/month
    """
    service = <SomeService>(db)
    return service.list(year=year, month=month)
```

### Сервис

```python
# src/services/<domain>.py
from sqlalchemy.orm import Session
from src.models import SomeModel

class SomeService:
    """Сервис ... (Service description)"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def list(self, year: int | None = None, month: int | None = None) -> list:
        """
        Получить список ... (Get list)
        """
        query = self.db.query(SomeModel).order_by(SomeModel.id.desc())
        return query.all()
```

---

## 3. GET — детальная информация

```python
# src/api/routes/<domain>.py
from fastapi import APIRouter, Depends, Path
from sqlalchemy.orm import Session

from src.api.deps import get_db
from src.services.<service> import <SomeService>

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
# src/api/routes/<domain>.py
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from src.api.deps import get_db
from src.services.<service> import <SomeService>


class UpdateSchema(BaseModel):
    """Схема обновления (Update schema)"""
    value: int = Field(ge=0, le=100)


router = APIRouter(prefix="/<domain>", tags=["<domain>"])


@router.post("/", response_model=dict, status_code=status.HTTP_200_OK)
async def update(
    data: UpdateSchema,
    db: Session = Depends(get_db),
):
    """
    Обновить ... (Update ...)
    """
    service = <SomeService>(db)
    service.update(data)
    return {"status": "ok"}
```

### Pydantic схема (внутри файла роута или в `src/models.py`)

```python
from pydantic import BaseModel, Field

class UpdateSchema(BaseModel):
    """Обновление ... (Update schema)"""
    value: int = Field(ge=100, le=220)
```

---

## 5. POST — upload файла

```python
# src/api/routes/uploads.py
from fastapi import APIRouter, Depends, UploadFile, File, status, Form
from sqlalchemy.orm import Session

from src.api.deps import get_db
from src.models import TrainingSession

router = APIRouter(tags=["uploads"])


@router.post("/upload")
async def upload_training(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """
    Загрузить тренировку из TCX/FIT файла
    Upload training from TCX/FIT file
    """
    # Логика загрузки (парсинг, анализ, сохранение)
    return {"status": "ok", "training_id": training.id}
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
# src/api/routes/<domain>.py
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from src.api.deps import get_db
from src.services.<service> import <SomeService>


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(
    id: int,
    db: Session = Depends(get_db),
):
    """
    Удалить ... (Delete ...)
    """
    service = <SomeService>(db)
    service.delete(id)
    return None
```

---

## 7. Подключение роутера к приложению

```python
# src/startup.py (внутри create_app())
def create_app():
    app = FastAPI(title="AI Running Coach")
    register_middleware(app)
    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(web_router)
    return app
```

Роуты группируются в `src/web/routes/__init__.py`:
```python
# src/web/routes/__init__.py
from src.web.routes.pages import router as pages_router
from src.web.routes.uploads import router as uploads_router
from src.web.routes.sync import router as sync_router
from src.web.routes.logs import router as logs_router

web_router = APIRouter()
web_router.include_router(pages_router)
web_router.include_router(uploads_router)
web_router.include_router(sync_router)
web_router.include_router(logs_router)
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

**Последнее обновление:** 16.07.2026
