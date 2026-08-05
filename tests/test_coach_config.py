# Тесты конфигурации коуча и structured-выводов (Coach config + structured outputs) — Трек 2
from src.coach import config as coach_config
from src.coach.config import (
    recovery_hours_for, RECOVERY_HOURS_BY_TYPE, RECOVERY_HOURS_DEFAULT,
    READINESS_WEIGHTS, FATIGUE_WEIGHTS,
    RECOVERY_PCT_READY, RECOVERY_PCT_MODERATE,
    PERFORMANCE_READY, PERFORMANCE_MODERATE,
)
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


# --- Анти-дрейф (BACKLOG #230, Этап 5): пороги и веса — единый источник ---

def test_readiness_weights_sum_to_one_and_have_data_sources():
    """Веса нормированы; веса по метрикам без источника данных запрещены
    (sleep_quality был удалён — данных сна в DailyMetrics нет)."""
    assert abs(sum(READINESS_WEIGHTS.values()) - 1.0) < 1e-9
    assert "sleep_quality" not in READINESS_WEIGHTS, \
        "вес по несуществующей метрике: сначала добавь источник данных сна"
    assert abs(sum(FATIGUE_WEIGHTS.values()) - 1.0) < 1e-9


def test_thresholds_are_ordered():
    """Санити: границы не перепутаны местами."""
    assert RECOVERY_PCT_READY > RECOVERY_PCT_MODERATE
    assert PERFORMANCE_READY > PERFORMANCE_MODERATE
    assert coach_config.LOAD_RATIO_HIGH > coach_config.LOAD_RATIO_LOW
    assert coach_config.RHR_CRITICAL_DIFF > coach_config.RHR_ELEVATED_DIFF > 0 > coach_config.RHR_LOW_DIFF
    assert coach_config.TRAINING_LOAD_MEDIUM_MAX > coach_config.TRAINING_LOAD_LIGHT_MAX


def test_recovery_view_uses_config_thresholds():
    """recovery_view обязан читать пороги из coach.config — проверяем на границах.
    (recovery_view must consume config thresholds — verified at the boundaries.)"""
    assert readiness_structured(None, recovery_pct=RECOVERY_PCT_READY)["status"] == "ready"
    assert readiness_structured(None, recovery_pct=RECOVERY_PCT_READY - 1)["status"] == "moderate"
    assert readiness_structured(None, recovery_pct=RECOVERY_PCT_MODERATE - 1)["status"] == "rest"
    assert readiness_structured(PERFORMANCE_READY + 0.01)["status"] == "ready"
    assert readiness_structured(PERFORMANCE_READY)["status"] == "moderate"
