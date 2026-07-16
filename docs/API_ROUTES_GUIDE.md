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
# src/services/training_service.py
from sqlalchemy.orm import Session
from src.models import TrainingSession, TrainingFeedback
from src.exceptions import NotFoundError


def delete_training(db: Session, user_id: int, session_id: int) -> None:
    """Удалить тренировку пользователя (Delete user's training session)."""
    session = db.query(TrainingSession).filter(
        TrainingSession.id == session_id,
        TrainingSession.user_id == user_id,
    ).first()
    if not session:
        raise NotFoundError("training", session_id)
    db.delete(session)
    db.commit()


def upsert_feedback(
    db: Session,
    user_id: int,
    session_id: int,
    rating: int,
    notes: str | None = None,
) -> TrainingFeedback:
    """Сохранить или обновить оценку тренировки (Upsert training feedback)."""
    feedback = db.query(TrainingFeedback).filter(
        TrainingFeedback.session_id == session_id,
        TrainingFeedback.user_id == user_id,
    ).first()
    if feedback:
        feedback.rating = rating
        feedback.notes = notes
    else:
        feedback = TrainingFeedback(
            session_id=session_id,
            user_id=user_id,
            rating=rating,
            notes=notes,
        )
        db.add(feedback)
    db.commit()
    db.refresh(feedback)
    return feedback
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

### Pydantic схема (внутри файла роута или в отдельном модуле `src/schemas/`)

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
# src/web/routes/uploads.py (логика в роуте + analysis/__init__.py)
from fastapi import UploadFile
from sqlalchemy.orm import Session

from src.models import TrainingSession
from src.analysis import process_trackpoints
from src.parsers.tcx_parser import TcxParser
from src.parsers.fit_parser import FitParser
from src.exceptions import FileProcessingError

def _parse_file(file: UploadFile):
    """Выбрать парсер по расширению (Select parser by extension)"""
    if file.filename.endswith('.tcx'):
        return TcxParser().parse(file.file)
    elif file.filename.endswith('.fit'):
        return FitParser().parse(file.file)
    raise FileProcessingError(file.filename, "Unsupported file format")
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
