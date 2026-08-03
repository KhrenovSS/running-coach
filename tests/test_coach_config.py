# Тесты конфигурации коуча и structured-выводов (Coach config + structured outputs) — Трек 2
from src.coach.config import recovery_hours_for, RECOVERY_HOURS_BY_TYPE, RECOVERY_HOURS_DEFAULT
from src.services.recovery_view import (
    readiness_structured, tired_rate_structured, recovery_pct_structured,
)


def test_recovery_hours_taxonomy_matches_classifier():
    # Все типы, которые выдаёт classify.py, должны присутствовать
    for t in ("easy", "recovery", "tempo", "long", "interval"):
        assert t in RECOVERY_HOURS_BY_TYPE, f"нет ключа {t}"


def test_recovery_hours_for_known_and_unknown():
    assert recovery_hours_for("easy") == RECOVERY_HOURS_BY_TYPE["easy"]
    assert recovery_hours_for("interval") == 48
    # неизвестный тип и None → безопасный дефолт, без KeyError
    assert recovery_hours_for("marathon") == RECOVERY_HOURS_DEFAULT
    assert recovery_hours_for(None) == RECOVERY_HOURS_DEFAULT


def test_readiness_structured_priority():
    # recovery_pct имеет приоритет
    r = readiness_structured(performance=0.9, recovery_pct=80, training_load_ratio=2.0)
    assert r["status"] == "ready" and r["evidence"].startswith("recovery_pct")
    assert readiness_structured(None, recovery_pct=10)["status"] == "rest"
    assert readiness_structured(None, None, training_load_ratio=1.5)["status"] == "rest"
    assert readiness_structured(None)["status"] == "unknown"


def test_tired_and_recovery_structured():
    assert tired_rate_structured(-6)["status"] == "low"
    assert tired_rate_structured(0)["status"] == "moderate"
    assert tired_rate_structured(5)["status"] == "high"
    assert tired_rate_structured(None)["status"] == "unknown"

    assert recovery_pct_structured(85)["status"] == "recovered"
    assert recovery_pct_structured(50)["status"] == "partial"
    assert recovery_pct_structured(10)["status"] == "needs_rest"
    assert recovery_pct_structured(None)["confidence"] == 0.0
