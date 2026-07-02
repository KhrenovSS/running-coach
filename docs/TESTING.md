# Руководство по тестированию (Testing Guide)

> Как писать и запускать тесты в running-coach.

## Три уровня тестов

```
tests/
├── conftest.py              # Фикстуры pytest
├── unit/                    # Быстрые, с моками
│   ├── test_parsers.py
│   ├── test_classification.py
│   ├── test_zones.py
│   └── test_watch_client.py
├── integration/             # С реальной БД
│   ├── test_api_training.py
│   ├── test_api_settings.py
│   └── test_coros_sync.py
└── e2e/                     # Полные сценарии (Playwright/Selenium)
    └── test_upload_flow.py
```

| Тип | Скорость | БД | HTTP | Браузер |
|-----|----------|----|----|---------|
| Unit | быстро (< 1 сек) | мок | мок | нет |
| Integration | средне (5-30 сек) | in-memory SQLite | реальный FastAPI | нет |
| E2E | медленно | SQLite | реальный | да |

## Запуск тестов

```bash
# Все тесты
pytest

# Unit только
pytest tests/unit/ -v

# Integration только
pytest tests/integration/ -v

# С coverage
pytest --cov=src --cov-report=html

# Конкретный файл
pytest tests/unit/test_classification.py -v

# Конкретный тест
pytest tests/unit/test_classification.py::TestTrainingClassification::test_interval_detection -v
```

## Конфигурация

```ini
# pytest.ini
[pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
addopts = -v --tb=short
asyncio_mode = auto
```

## Unit тесты

### Пример: классификация тренировок

```python
# tests/unit/test_classification.py
import pytest
from src.services.training.classification import classify_training


class TestTrainingClassification:
    """Тесты классификации тренировок (Training classification tests)"""
    
    def test_interval_detection(self):
        """3+ вариативных км → Интервальная"""
        km_variability = [True, True, True, False]
        result = classify_training(km_variability)
        assert result == "interval"
    
    def test_tempo_detection(self):
        """1-2 вариативных км → Темповая"""
        km_variability = [True, False, False]
        result = classify_training(km_variability)
        assert result == "tempo"
    
    def test_long_recovery_detection(self):
        """0 вариативных км → Long/Recovery"""
        km_variability = [False, False, False]
        result = classify_training(km_variability)
        assert result in ("long", "recovery")
    
    def test_empty_input(self):
        """Пустой список → Recovery"""
        result = classify_training([])
        assert result == "recovery"
```

### Пример: пульсовые зоны

```python
# tests/unit/test_zones.py
import pytest
from src.config import calculate_hr_zones, get_hr_zone


class TestHRZones:
    """Тесты пульсовых зон (Heart rate zones tests)"""
    
    def test_calculate_zones_for_max_hr_177(self):
        """Расчёт зон для max_hr=177"""
        zones = calculate_hr_zones(177)
        assert zones["Z1"] == (106, 123)
        assert zones["Z5"] == (164, 177)
    
    def test_get_hr_zone(self):
        """Определение зоны по HR"""
        assert get_hr_zone(150, 177) == "Z4"
        assert get_hr_zone(130, 177) == "Z2"
        assert get_hr_zone(90, 177) == "below"
```

## Integration тесты

### Фикстуры

```python
# tests/conftest.py
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from main import app
from src.models import Base, get_db

# In-memory SQLite для тестов
TEST_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    """Подмена get_db для тестов (Override get_db for tests)"""
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(scope="function")
def db_session():
    """Свежая БД для каждого теста (Fresh DB for each test)"""
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    yield db
    db.close()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client(db_session):
    """TestClient с тестовой БД (TestClient with test DB)"""
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
```

### Пример integration теста

```python
# tests/integration/test_api_training.py
import io

class TestTrainingUpload:
    """Integration tests for training upload"""
    
    def test_upload_valid_tcx(self, client):
        """Загрузка валидного TCX"""
        file = io.BytesIO(b'<TrainingCenterDatabase>...</TrainingCenterDatabase>')
        file.name = "test.tcx"
        
        response = client.post(
            "/training/upload",
            files={"file": ("test.tcx", file, "application/tcx+xml")},
        )
        
        assert response.status_code == 201
        assert response.json()["status"] == "ok"
    
    def test_upload_invalid_format(self, client):
        """Отклонение неподдерживаемого формата"""
        file = io.BytesIO(b"not a training file")
        file.name = "test.txt"
        
        response = client.post(
            "/training/upload",
            files={"file": ("test.txt", file, "text/plain")},
        )
        
        assert response.status_code == 422
```

## Что покрывать тестами

### Обязательно

- Бизнес-логика (классификация, сегментация, зоны)
- Парсеры (TCX, FIT)
- API endpoints (happy path + ошибки)
- Работа с БД (CRUD)

### Хорошая практика

- Edge cases (пустые данные, нули, None)
- Error paths (404, 400, 500)
- Граничные значения (max_hr=100, max_hr=220)

## Чеклист теста

- [ ] Имя теста описывает поведение
- [ ] Тест проверяет одну вещь
- [ ] Дано/когда/тогда структура понятна
- [ ] Нет зависимости от внешних сервисов в unit-тестах
- [ ] Интеграционные тесты используют `TestClient` и in-memory БД

---

**Последнее обновление:** 30.06.2026
