# Рекомендации по написанию кода (Code Guidelines)

> Практическое руководство «как писать код в этом проекте». Правила-инварианты — в `CLAUDE.md`
> («Дисциплина», «Golden rules»); здесь — как их применять, с примерами **из реального кода**.
> Где писать код и как устроены модули — `docs/ARCHITECTURE.md`; ошибки — `docs/ERROR_HANDLING.md`;
> логи — `docs/LOGGING.md`; тесты — `docs/TESTING.md`; чеклист перед коммитом — `docs/CHECKLIST_FEATURE.md`.

## Содержание

1. [Константы — никаких magic numbers](#1-константы--никаких-magic-numbers)
2. [Тонкие роуты и сервисы-функции](#2-тонкие-роуты-и-сервисы-функции)
3. [Валидация входа](#3-валидация-входа)
4. [База данных и миграции](#4-база-данных-и-миграции)
5. [Ошибки и логирование — кратко](#5-ошибки-и-логирование--кратко)
6. [Комментарии и докстринги](#6-комментарии-и-докстринги)
7. [Импорты](#7-импорты)
8. [Именование](#8-именование)
9. [Action-проверка перед опасным рефакторингом](#9-action-проверка-перед-опасным-рефакторингом)

---

## 1. Константы — никаких magic numbers

**Все** числа, строки, URL, пороги — через `from src.config import settings` (env-настройки) или
`from src.config.constants import NAME` (фиксированные). Пороги коуча и readiness — **только**
`src/coach/config.py` (человекочитаемый источник — `docs/coros_health_metrics.md`, метрики разбора —
`docs/coach/METRICS_GUIDE.md`; согласованность констант проверяет `tests/test_coach_config.py`).

```python
# ❌
if hr < 142: ...
resp = httpx.get(url, timeout=15)

# ✅
from src.config import settings
from src.analysis.hr_zones import get_zone
zone = get_zone(hr, max_hr, lthr)          # границы зон — из constants / LTHR
resp = httpx.get(url, timeout=settings.http_timeout)
```

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

Новая константа нужна, если значение используется больше одного раза, может меняться или неочевидно
без контекста. Именованная константа с bilingual-комментарием рядом; для порогов коуча — плюс
строка в человекочитаемом документе (см. `CHECKLIST_FEATURE.md`).

---

## 2. Тонкие роуты и сервисы-функции

Роут: принять запрос → валидировать → вызвать сервис → вернуть ответ. Никакого парсинга файлов,
SQL, внешних API и бизнес-правил внутри. Роут ~80 строк максимум, файл ~400.

Приложение — **Jinja2-формы** (`Form(...)`) и редиректы, не JSON-REST. Реальный роут
(`src/web/routes/pages/session.py`):

```python
@router.post('/session/{session_id}/delete')
async def session_delete(session_id: int, db: Session = Depends(get_db),
                         current_user: User = Depends(get_current_user)):
    delete_training(db, current_user.id, session_id)
    return RedirectResponse(url='/', status_code=303)
```

Сервисы — **функции модульного уровня**, `db: Session` приходит параметром (владение сессией —
`CLAUDE.md` §8, гвард `tests/test_session_ownership.py`). Единственный класс-сервис — `AuditService`.
`src/services/training_service.py`:

```python
def delete_training(db: Session, user_id: int, session_id: int) -> bool:
    """Удалить тренировку: метаданные → DeletedTraining, сессию удалить.
    Delete training: move metadata to DeletedTraining, remove the session.
    Возвращает True если удалено, False если не найдено."""
```

`get_db` один — `src/domain/models/base.py` (`src/api/deps.py` только реэкспортирует).
Подключение роутеров — `docs/ARCHITECTURE.md` «Принцип тонких роутов».

---

## 3. Валидация входа

Формы валидируются типами параметров FastAPI (`max_hr: int | None = Form(None)`) и явными
проверками диапазонов в сервисе/роуте с понятным ответом пользователю
(`src/web/routes/pages/settings.py::settings_save` — 15 полей формы). Pydantic-моделей запроса в
проекте нет; вводить их ради одного роута не нужно. Границы значений — из `constants.py`
(например, `HR_MAX_SANITY_*`), не литералами.

Данные с часов/из файлов **не доверяем**: парсеры и `src/analysis/gps_quality.py` помечают
недостоверное (`suspect_flags`, `gps_quality.unreliable`), а не отбрасывают молча.

---

## 4. База данных и миграции

1. Схема меняется **только** через Alembic (`alembic revision --autogenerate -m "..."`), миграции
   применяются при старте `app`. Чеклист и прод-порядок (`stop bot` перед ALTER) —
   `docs/CHECKLIST_MIGRATION.md`; data-safety — `CLAUDE.md` §5–7.
2. Запросы — ORM или параметризованные; никаких f-string в SQL.
3. Модели — `src/domain/models/<domain>.py`; `src/models.py` — shim для обратной совместимости,
   новый код туда не добавлять.
4. Индексы для частых `WHERE`/`JOIN`; уникальность данных — через частичные UNIQUE в БД
   (`uq_training_user_brand_extid`), не через проверку в коде.

```python
# ❌ ALTER TABLE в startup, f-string SQL
db.execute(f"SELECT * FROM training_sessions WHERE user_id = {user_id}")

# ✅
db.query(TrainingSession).filter(TrainingSession.user_id == user_id).all()
op.add_column('daily_metrics', sa.Column('recovery_pct', sa.Integer(), nullable=True))  # в миграции
```

---

## 5. Ошибки и логирование — кратко

- `except: pass` запрещён (CI-гвард). Ловим конкретный тип, логируем, поднимаем исключение проекта
  из `src/exceptions.py` (иерархия, коды HTTP и примеры — `docs/ERROR_HANDLING.md`).
- Логгер — `get_logger("<module.path>")` из `src.utils.logger` (иерархические имена `coach.*`,
  `telegram.handlers.*`; см. `docs/LOGGING.md`). `print()` не используется. Не логировать пароли,
  токены, персональные данные.

---

## 6. Комментарии и докстринги

Комментарии писать **сразу**, bilingual (русский + английский), у каждой функции/класса — докстринг
с назначением и контрактом возврата; сложный блок — комментарий «почему», а не «что».

```python
def delete_training(db: Session, user_id: int, session_id: int) -> bool:
    """
    Удалить тренировку: переместить метаданные в DeletedTraining, удалить сессию.
    Delete training: move metadata to DeletedTraining, remove the session.

    Возвращает True если удалено, False если не найдено.
    Returns True if deleted, False if not found.
    """
```

Ссылки на документы в комментариях — по имени файла и §: `# DEV_PLAN §4`, `# METRICS_GUIDE §6`
(нумерация этих секций стабильна и не меняется при правках документов).

---

## 7. Импорты

```python
# 1. Стандартная библиотека
import os
from datetime import datetime

# 2. Сторонние библиотеки
from fastapi import APIRouter, Depends, Form
from sqlalchemy.orm import Session

# 3. Внутренние модули
from src.config import settings
from src.config.constants import HEALTH_SYNC_DAYS
from src.domain.models.base import get_db
from src.domain.models.training import TrainingSession
from src.utils.logger import get_logger
```

`from src.database import ...` запрещён (модуль удалён, CI-гвард). Константы и настройки — только
через `src.config` (§1).

---

## 8. Именование

Общее — PEP 8: `snake_case` функции/переменные/модули, `PascalCase` классы, `UPPER_SNAKE` константы,
`is_/has_/should_` для boolean, функция = глагол + объект (`save_daily_metrics`, `parse_tcx`).
Специфика проекта — единицы измерения в имени:

```python
# ✅                                  # ❌
hr_zone = "Z2"                       zone = "Z2"          # чья зона?
max_hr, avg_heart_rate               maximumHeartRate, avgHR
pace_min_per_km = 5.5                pace = 5.5           # единицы?
distance_km, duration_minutes        dist, dur
lthr_bpm, ltsp_s_per_km              lthr, ltsp           # в constants/config — с единицей
```

Исключения — `<Domain>Error` (`WatchAPIError`, `LLMUnavailableError`); модули часов —
`src/watch/<brand>.py`; тесты — `tests/test_<module>.py`, `tests/coach/test_<module>.py`.
Мульти-брендовость: не хардкодить «coros» в именах общих функций (`sync_activities_for_user`, не `sync_coros`).

---

## 9. Action-проверка перед опасным рефакторингом

Если изменение может затронуть данные в БД или старт приложения (переименование функции, смена
аргументов, удаление колонки, правка `startup.py`/`domain/models/base.py`/`alembic/`):

1. **Остановись** — не применяй автоматически.
2. **Опиши пользователю**: какие данные под угрозой, что будет после, есть ли миграция/откат.
3. **Получи подтверждение** — применяй только после явного «да» (`CLAUDE.md` §5, субагент `db-safety-reviewer`).
4. **Урок PREP-11:** рефакторинг `get_settings()` → `get_settings(user_id)` потребовал обновить
   `startup.py` и `uploads.py`. Без этого `TypeError` в startup при рестарте контейнера приводил
   к потере пользователя и всех его данных.
