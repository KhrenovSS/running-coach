FROM python:3.13-slim

WORKDIR /app

# Системные зависимости для psycopg2 и timezonefinder (System deps for psycopg2 and timezonefinder)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc && \
    rm -rf /var/lib/apt/lists/*

# Установка зависимостей (Install dependencies)
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# Копирование исходного кода (Copy source code)
COPY . .

# Создание директорий для runtime (Create runtime directories)
RUN mkdir -p uploads logs

# Точка входа определяется в docker-compose (Entrypoint defined in docker-compose)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]