# Конфигурация модуля аналитики и коучинга (Coach module configuration)
#
# ЕДИНСТВЕННЫЙ исполняемый источник порогов (BACKLOG #230, Этап 5).
# Человекочитаемый источник — docs/coros_health_metrics.md; числа здесь зеркалят его
# и потребляются recovery_view + будущими skills. НЕ дублировать значения inline.
# (Single executable source of thresholds; mirrors docs/coros_health_metrics.md.)

# --- Пороги метрик (Metric thresholds — см. §§ в docs/coros_health_metrics.md) ---
RECOVERY_PCT_READY = 70        # §5: recovery_pct ≥ 70 → готов (ready)
RECOVERY_PCT_MODERATE = 30     # §5: ≥ 30 → умеренная готовность (moderate), ниже — отдых (rest)
LOAD_RATIO_LOW = 0.8           # §7: ratio < 0.8 → низкая нагрузка (low load)
LOAD_RATIO_HIGH = 1.2          # §7: ratio > 1.2 → перегрузка (overload)
PERFORMANCE_READY = 0.5        # §4: performance > 0.5 → готов (float −2..+2)
PERFORMANCE_MODERATE = -0.5    # §4: > −0.5 → умеренная, ниже — отдых
TIRED_LOW_MAX = -5             # §3: tired_rate ≤ −5 → низкая усталость
TIRED_MODERATE_MAX = 0         # §3: ≤ 0 → умеренная, выше — высокая
TRAINING_LOAD_LIGHT_MAX = 50   # §7: training_load < 50 → лёгкая
TRAINING_LOAD_MEDIUM_MAX = 150 # §7: < 150 → средняя, выше — высокая
RHR_ELEVATED_DIFF = 5          # §6: RHR − baseline ≥ +5 → повышенный
RHR_CRITICAL_DIFF = 10         # §6: ≥ +10 → критический
RHR_LOW_DIFF = -3              # §6: ≤ −3 → аномально низкий
HRV_SD_FALLBACK_FACTOR = 0.2   # §2: sd ≈ baseline·0.2, когда API не отдаёт sleepHrvSd

# Веса readiness. NB: sleep_quality удалён 05.08.2026 — источника данных сна в DailyMetrics
# нет, вес по несуществующей метрике опаснее его отсутствия; веса перенормированы к 1.0.
# Вернуть sleep при появлении данных (re-add sleep when a data source exists).
READINESS_WEIGHTS = {
    "hrv_status": 0.35,
    "rhr_deviation": 0.24,
    "tired_rate": 0.18,
    "recovery_pct": 0.23,
}

FATIGUE_WEIGHTS = {
    "training_load_ratio": 0.35,
    "hrv_deviation": 0.25,
    "ati_cti_ratio": 0.20,
    "consecutive_hard_days": 0.20,
}

INJURY_RISK_THRESHOLDS = {
    "hrv_very_low_days": 3,
    "load_ratio_high": 1.5,
    "consecutive_hard_days": 4,
}

CALIBRATION_EWMA_ALPHA = 0.2
CALIBRATION_MIN_SAMPLES = 5
CALIBRATION_MAX_CHANGE_PCT = 0.10

CONFIDENCE_MIN_DAYS = 14
CONFIDENCE_MIN_SESSIONS = 10
CONFIDENCE_LOW_THRESHOLD = 0.5

# Часы восстановления по типу тренировки. Ключи ДОЛЖНЫ совпадать с выходом классификатора
# (src/analysis/classify.py: easy/recovery/tempo/long/interval); `race` — для ручного/будущего типа.
# Recovery hours by training type — keys must match classifier output.
RECOVERY_HOURS_BY_TYPE = {
    "recovery": 12,
    "easy": 18,
    "long": 30,
    "tempo": 36,
    "interval": 48,
    "race": 72,
}
RECOVERY_HOURS_DEFAULT = 24  # безопасный дефолт для неизвестного типа (safe default)


def recovery_hours_for(training_type: str | None) -> int:
    """Часы восстановления по типу тренировки с безопасным дефолтом — без KeyError.

    Recovery hours for a training type, with a safe default (never raises KeyError).
    """
    return RECOVERY_HOURS_BY_TYPE.get(training_type or "", RECOVERY_HOURS_DEFAULT)

# --- Безопасность и боль (Safety & pain — DEV_PLAN §4) ---
PAIN_SCALE_MAX = 10            # шкала боли 0..10 (pain scale)
PAIN_CAUTION_LEVEL = 3         # боль ≥ 3 → осторожный режим (caution mode)
PAIN_STOP_LEVEL = 5            # боль ≥ 5 → тренировка запрещена (no training)
PAIN_PERSIST_DAYS = 3          # боль N дней подряд → осторожный режим даже при низком уровне
SAFETY_MAX_ZONE_DEFAULT = 5    # потолок зоны по умолчанию (нет ограничений)
SAFETY_MAX_DURATION_CAUTION_MIN = 40  # потолок длительности в осторожном режиме, мин

# Лестница интенсивности — порядок = порядок опасности; clamp() двигает только ВНИЗ.
# (Intensity ladder — order equals danger order; clamp() only moves DOWN.)
TYPE_INTENSITY_ORDER = ("rest", "recovery", "easy", "long", "tempo", "interval", "race")
HARD_TYPES = ("tempo", "interval", "race")
EASY_TYPES = ("recovery", "easy")

# --- ACWR / baseline RHR (skills/load, skills/fatigue) ---
ACWR_ACUTE_DAYS = 7            # острое окно ACWR (acute window)
ACWR_CHRONIC_DAYS = 28         # хроническое окно ACWR (chronic window)
ACWR_CHRONIC_MIN_DAYS = 14     # меньше данных в хроническом окне → ratio=None (не 0.0!)
RHR_BASELINE_DAYS = 30         # окно медианы для baseline RHR
RHR_BASELINE_MIN_POINTS = 7    # меньше точек → baseline нет (None)

DISTRIBUTION_80_20 = {
    "easy_share_target": 0.80,
    "hard_share_target": 0.20,
    "tolerance": 0.10,
}

CYCLE_3_1 = {
    "build_weeks": 3,
    "deload_week": 1,
    "deload_volume_pct": 0.60,
}

LOAD_PROGRESSION = {
    "max_weekly_increase_pct": 10,
    "max_monthly_increase_pct": 30,
}
