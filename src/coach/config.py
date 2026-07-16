# Конфигурация модуля аналитики и коучинга (Coach module configuration)

READINESS_WEIGHTS = {
    "hrv_status": 0.30,
    "rhr_deviation": 0.20,
    "tired_rate": 0.15,
    "recovery_pct": 0.20,
    "sleep_quality": 0.15,
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

RECOVERY_HOURS_BY_TYPE = {
    "interval": 48,
    "tempo": 36,
    "long": 30,
    "recovery": 12,
    "race": 72,
}

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
