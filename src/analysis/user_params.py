# Параметры анализа из профиля пользователя (Per-user analysis parameters) — #274/#327, 11.09.2026
#
# Единый резолвер «поле User → kw process_trackpoints» с дефолтами из config/constants: им пользуются
# reanalyze, live-синк (parse_fit) и web-загрузка (parse_fit/parse_tcx) — раньше live-путь не передавал
# interval_*-настройки, и ярлык тренировки после кнопки «пересчитать» мог отличаться от синка.
# (One resolver for user-tunable analysis kwargs; live and reanalyze paths agree.)

from __future__ import annotations

from typing import Any

from src.config.constants import (
    DEFAULT_HR_LAG_SEC,
    DEFAULT_MIN_OSCILLATIONS,
    DEFAULT_MIN_PHASE_DISTANCE_M,
    DEFAULT_MIN_PHASE_DURATION_SEC,
    DEFAULT_PACE_THRESHOLD,
    MAX_CREDIBLE_PACE,
    MAX_GPS_JUMP_M,
    MIN_HR_FOR_FAST_PACE,
)


def gps_kwargs(user: Any | None) -> dict:
    """Пороги GPS-очистки из профиля (None/пусто → дефолты констант). (GPS cleaning kwargs.)"""
    return {
        "max_credible_pace": getattr(user, "max_credible_pace", None) or MAX_CREDIBLE_PACE,
        "max_gps_jump_m": getattr(user, "max_gps_jump_m", None) or MAX_GPS_JUMP_M,
        "min_hr_for_fast_pace": getattr(user, "min_hr_for_fast_pace", None) or MIN_HR_FOR_FAST_PACE,
    }


def interval_kwargs(user: Any | None) -> dict:
    """Настройки детекции интервалов из профиля — имена как у process_trackpoints
    (`pace_gap` = interval_pace_threshold, мин/км). (Interval-detection kwargs.)"""
    return {
        "pace_gap": getattr(user, "interval_pace_threshold", None) or DEFAULT_PACE_THRESHOLD,
        "interval_min_phase_duration": (getattr(user, "interval_min_phase_duration", None)
                                        or DEFAULT_MIN_PHASE_DURATION_SEC),
        "interval_min_phase_distance_m": (getattr(user, "interval_min_phase_distance_m", None)
                                          or DEFAULT_MIN_PHASE_DISTANCE_M),
        "interval_hr_lag_sec": getattr(user, "interval_hr_lag_sec", None) or DEFAULT_HR_LAG_SEC,
        "interval_min_oscillations": (getattr(user, "interval_min_oscillations", None)
                                      or DEFAULT_MIN_OSCILLATIONS),
    }


def analysis_kwargs(user: Any | None) -> dict:
    """GPS + интервалы одним словарём — для parse_fit/parse_tcx/process_trackpoints."""
    return {**gps_kwargs(user), **interval_kwargs(user)}
