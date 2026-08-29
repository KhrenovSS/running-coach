# Конфигурация модуля коуча (Coach module configuration)
#
# ЕДИНСТВЕННЫЙ исполняемый источник порогов (BACKLOG #230). ДВА человекочитаемых
# источника: метрики здоровья — docs/coros_health_metrics.md; safety/pain и лестница
# интенсивности — docs/coach/DEV_PLAN.md §4. Потребители: recovery_view + skills + safety.
# НЕ дублировать значения inline. (Single executable source; two human-readable sources.)

# --- Пороги метрик (Metric thresholds — см. §§ в docs/coros_health_metrics.md) ---
RECOVERY_PCT_READY = 70        # §12 coros-дока: recovery_pct ≥ 70 → готов (ready)
RECOVERY_PCT_MODERATE = 30     # исторический порог display-слоя; шкала Coros §12 — 20/70/90 (приведение — BACKLOG #249)
LOAD_RATIO_LOW = 0.8           # display-ярлык нагрузки (UI); травмоопасные пороги ACWR — INJURY_RISK_THRESHOLDS
LOAD_RATIO_HIGH = 1.2          # display-ярлык нагрузки (UI)
PERFORMANCE_READY = 0.5        # §4: performance > 0.5 → готов (float −2..+2)
PERFORMANCE_MODERATE = -0.5    # §4: > −0.5 → умеренная, ниже — отдых
TIRED_LOW_MAX = -5             # §3: tired_rate ≤ −5 → низкая усталость
TIRED_MODERATE_MAX = 0         # §3: ≤ 0 → умеренная, выше — высокая
TRAINING_LOAD_LIGHT_MAX = 50   # §5 coros-дока: training_load < 50 → лёгкая
TRAINING_LOAD_MEDIUM_MAX = 150 # §5: < 150 → средняя, выше — высокая
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
# Минимальная зона, в которой тип имеет смысл: потолок зоны ниже → тип даунгрейдится.
# (Minimal zone a type makes sense in; a lower zone cap downgrades the type.)
TYPE_MIN_ZONE = {"rest": 1, "recovery": 1, "easy": 2, "long": 2, "tempo": 4, "interval": 5, "race": 4}
# Абсолютные санити-границы целевого темпа назначения — единый источник для clamp
# и pydantic-схемы LLM. (Target pace sanity bounds — shared by clamp and LLM schema.)
PACE_TARGET_MIN_PER_KM = 2.5   # быстрее — нереально для любителя (faster is unrealistic)
PACE_TARGET_MAX_PER_KM = 12.0  # медленнее — это уже ходьба (slower is walking)
ATI_CTI_HIGH = 1.5             # §7 coros-дока: ATI/CTI > 1.5 → перекос в анаэробную нагрузку

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
    # 0.75 — выравнено по guide 60_plans_fitzgerald (mesocycle_recovery_volume_percent=75);
    # key_rules digest уже показывает LLM 75% — конфиг не должен противоречить
    "deload_volume_pct": 0.75,
}

LOAD_PROGRESSION = {
    "max_weekly_increase_pct": 10,
    "max_monthly_increase_pct": 30,
}

# --- Метрики сессии M1 (Session metrics) — docs/coach/METRICS_GUIDE.md §4 ---
# Пороги применяет src/services/workout_insights.py; чистые формулы в
# src/analysis/session_metrics.py принимают их параметрами (без импорта coach→analysis).

# M1.1: дисциплина лёгкого дня (гайды 00/10 — «лёгкие бегают слишком быстро»)
EASY_RUN_Z3_TOLERANCE_PCT = 0.10   # доля moving-time в Z3+ у easy/recovery/long → флаг

# M1.4: баллы нагрузки за минуту по зонам (Дэниелс, гайд 44: Л 0.2 … Пв 1.5–2.0;
# коэффициенты — первое приближение для %max_hr-зон, уточняются после M3/ПАНО)
POINTS_PER_MIN = {"z1": 0.2, "z2": 0.25, "z3": 0.5, "z4": 1.0, "z5": 1.5}

# M1.5: потолки качественного объёма (Дэниелс, гайд 44)
INTERVAL_MAX_PCT_WEEK = 0.08       # км в Z4+ ≤ 8% недельного км…
INTERVAL_MAX_KM = 10.0             # …или 10 км — что меньше
THRESHOLD_MAX_PCT_WEEK = 0.10      # км в Z3 ≤ 10% недельного км…
THRESHOLD_MAX_KM = 24.0            # …или 24 км
INTERVAL_SEGMENT_MAX_MIN = 5.0     # непрерывный отрезок в Z4+ не дольше 5 мин

# M1.6: длительная (Дэниелс, гайд 45: ≤25–30% недели или 150 мин)
LONG_RUN_MAX_PCT_WEEK = 0.30
LONG_RUN_MAX_MIN = 150.0

# M1.7: каденс (Дэниелс, гайд 46 — профилактика колена; цель ~180 spm)
CADENCE_TARGET_SPM = 180
CADENCE_LOW_SPM = 170              # медиана ниже → флаг low_cadence
CADENCE_SANITY_MIN_SPM = 120       # ниже — подозрение на «одну ногу» → available=false

# M1.8: RPE-триангуляция «плохого дня» (Фицджеральд, гайд 40)
RPE_ELEVATED_DELTA = 2             # RPE выше медианы того же типа на ≥2 → флаг
RPE_HISTORY_DAYS = 90
RPE_MIN_SAMPLES = 5                # меньше оценок того же типа → available=false
RPE_BASELINE_Z_MAX = 1.0           # гейт «объективный фон в норме»: |z| hr_vs_baseline

# M1.9: разминка перед качественной (Фицджеральд, гайд 41)
WARMUP_WINDOW_MIN = 10.0           # окно проверки, минуты от старта
WARMUP_EASY_SHARE_MIN = 0.5        # меньше половины окна в Z1–2 → флаг no_warmup

# M2.2: план vs факт (METRICS_GUIDE §5) — соответствие назначению
PLAN_VOLUME_TOLERANCE_PCT = 0.15   # объём выше плана более чем на 15% → флаг
PLAN_INTENSITY_TOLERANCE_PCT = 0.10  # доля времени выше плановой зоны → флаг

# --- Недельный план (Weekly plan) — решения владельца 29.08.2026 ---
# Качественных дней в плане недели: возврат после травмы колена — один
# (guide 41 допускает 3; потолок поднимает владелец осознанно)
PLAN_QUALITY_DAYS_MAX = 1
