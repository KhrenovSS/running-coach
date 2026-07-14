# Тесты health-check эндпоинта (Health check endpoint tests)

import os
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-pytest")

from fastapi.testclient import TestClient
from src.startup import create_app

app = create_app()
client = TestClient(app)


class TestHealthEndpoint:
    def test_health_returns_200(self):
        response = client.get("/health/")
        assert response.status_code == 200

    def test_health_contains_status(self):
        response = client.get("/health/")
        data = response.json()
        assert "status" in data

    def test_health_contains_database_check(self):
        response = client.get("/health/")
        data = response.json()
        assert "checks" in data
        assert "database" in data["checks"]

    def test_health_contains_application_info(self):
        response = client.get("/health/")
        data = response.json()
        assert "application" in data
        assert "name" in data["application"]
        assert data["application"]["name"] == "AI Running Coach"
