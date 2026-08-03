# Классификация метрик здоровья для отображения (Health metrics display helpers)

def hrv_status(hrv: float | None, baseline: float | None, sd: float | None,
               intervals: list[float] | None = None) -> tuple[str | None, str]:
    if hrv is None:
        return None, ''
    if intervals and len(intervals) >= 4:
        if hrv < intervals[0]:
            return 'very_low', '🔴 Низкая ({:.0f})'.format(hrv)
        elif hrv < intervals[2]:
            return 'low', '🟡 Пониженная ({:.0f})'.format(hrv)
        elif hrv <= intervals[3]:
            return 'normal', '🟢 Норма ({:.0f})'.format(hrv)
        else:
            return 'elevated', '🟣 Повышенная ({:.0f})'.format(hrv)
    if baseline is None or baseline == 0:
        return None, '{:.0f}'.format(hrv)
    if sd is None or sd == 0:
        sd = baseline * 0.2
    if hrv > baseline + sd:
        return 'elevated', '🟣 Повышенная ({:.0f})'.format(hrv)
    elif hrv >= baseline - sd:
        return 'normal', '🟢 Норма ({:.0f})'.format(hrv)
    elif hrv >= baseline - 2 * sd:
        return 'low', '🟡 Пониженная ({:.0f})'.format(hrv)
    else:
        return 'very_low', '🔴 Низкая ({:.0f})'.format(hrv)


def tired_label(tired_rate: int | None) -> str:
    if tired_rate is None:
        return ''
    if tired_rate <= -5:
        return '🟢 Низкая'
    elif tired_rate <= 0:
        return '🟡 Умеренная'
    else:
        return '🔴 Высокая'


def readiness_label(performance: float | None, recovery_pct: float | None = None,
                    training_load_ratio: float | None = None) -> str:
    if recovery_pct is not None:
        if recovery_pct >= 70:
            return '🟢 Готов к тренировкам'
        elif recovery_pct >= 30:
            return '🟡 Умеренная готовность'
        else:
            return '🔴 Требуется отдых'
    if training_load_ratio is not None:
        if training_load_ratio < 0.8:
            return '🟢 Низкая нагрузка'
        elif training_load_ratio <= 1.2:
            return '🟡 Оптимальная нагрузка'
        else:
            return '🔴 Перегрузка'
    if performance is None:
        return ''
    if performance > 0.5:
        return '🟢 Готов к тренировкам'
    elif performance > -0.5:
        return '🟡 Умеренная готовность'
    else:
        return '🔴 Требуется отдых'


def load_label(training_load: float | None) -> str:
    if training_load is None:
        return ''
    if training_load < 50:
        return 'Лёгкая'
    elif training_load < 150:
        return 'Средняя'
    else:
        return 'Высокая'


# --- Структурированные функции для модуля аналитики ---

def hrv_status_structured(hrv: float | None, baseline: float | None, sd: float | None,
                           intervals: list[float] | None = None) -> dict:
    """Структурированный HRV-статус: status + value + confidence + evidence.
    (Structured HRV status for analytics module.)
    """
    if hrv is None:
        return {'status': 'unknown', 'value': None, 'confidence': 0.0, 'evidence': 'no HRV data'}
    status, _ = hrv_status(hrv, baseline, sd, intervals)
    confidence = 0.9 if intervals else (0.7 if baseline else 0.3)
    return {
        'status': status or 'unknown',
        'value': round(hrv, 1),
        'confidence': confidence,
        'evidence': f'HRV={hrv}, baseline={baseline}, sd={sd}',
    }


def load_status_structured(training_load: float | None, cti: float | None = None,
                            ati: float | None = None) -> dict:
    """Структурированный статус нагрузки: status + value + confidence + evidence.
    (Structured load status for analytics module.)
    """
    if training_load is None and cti is None:
        return {'status': 'unknown', 'value': None, 'confidence': 0.0, 'evidence': 'no load data'}
    if cti is not None and ati is not None:
        ratio = ati / cti if cti > 0 else 0
        if ratio > 1.5:
            load_status = 'high_anaerobic'
            confidence = 0.8
        elif ratio > 1.0:
            load_status = 'mixed'
            confidence = 0.7
        else:
            load_status = 'aerobic'
            confidence = 0.7
        evidence = f'ATI={ati}, CTI={cti}, ratio={ratio:.2f}'
        value = round(ratio, 2)
    else:
        value = training_load
        load_status = 'unknown'
        confidence = 0.3
        evidence = f'training_load={training_load}'
    return {
        'status': load_status,
        'value': value,
        'confidence': confidence,
        'evidence': evidence,
    }


def readiness_structured(performance: float | None, recovery_pct: float | None = None,
                          training_load_ratio: float | None = None) -> dict:
    """Структурированная готовность: status ready/moderate/rest (Structured readiness).

    Приоритет сигналов повторяет readiness_label: recovery_pct → training_load_ratio → performance.
    """
    if recovery_pct is not None:
        status = 'ready' if recovery_pct >= 70 else ('moderate' if recovery_pct >= 30 else 'rest')
        return {'status': status, 'value': round(recovery_pct, 1), 'confidence': 0.8,
                'evidence': f'recovery_pct={recovery_pct}'}
    if training_load_ratio is not None:
        status = 'ready' if training_load_ratio < 0.8 else ('moderate' if training_load_ratio <= 1.2 else 'rest')
        return {'status': status, 'value': round(training_load_ratio, 2), 'confidence': 0.6,
                'evidence': f'training_load_ratio={training_load_ratio}'}
    if performance is not None:
        status = 'ready' if performance > 0.5 else ('moderate' if performance > -0.5 else 'rest')
        return {'status': status, 'value': round(performance, 2), 'confidence': 0.5,
                'evidence': f'performance={performance}'}
    return {'status': 'unknown', 'value': None, 'confidence': 0.0, 'evidence': 'no readiness data'}


def tired_rate_structured(tired_rate: int | None) -> dict:
    """Структурированный уровень усталости: status low/moderate/high (Structured fatigue level)."""
    if tired_rate is None:
        return {'status': 'unknown', 'value': None, 'confidence': 0.0, 'evidence': 'no tired_rate data'}
    if tired_rate <= -5:
        status = 'low'
    elif tired_rate <= 0:
        status = 'moderate'
    else:
        status = 'high'
    return {'status': status, 'value': tired_rate, 'confidence': 0.7, 'evidence': f'tired_rate={tired_rate}'}


def recovery_pct_structured(recovery_pct: float | None) -> dict:
    """Структурированный процент восстановления: recovered/partial/needs_rest (Structured recovery %)."""
    if recovery_pct is None:
        return {'status': 'unknown', 'value': None, 'confidence': 0.0, 'evidence': 'no recovery_pct data'}
    if recovery_pct >= 70:
        status = 'recovered'
    elif recovery_pct >= 30:
        status = 'partial'
    else:
        status = 'needs_rest'
    return {'status': status, 'value': round(recovery_pct, 1), 'confidence': 0.8,
            'evidence': f'recovery_pct={recovery_pct}'}


# NB: READINESS_WEIGHTS содержит "sleep_quality", но выделенной колонки в DailyMetrics нет —
# структурированный sleep-вывод отложен до появления источника данных (решается в дизайне движка).


def rhr_anomaly(rhr: int | None, baseline_rhr: int | None = None) -> dict:
    """Детекция аномалии пульса покоя: +5 повышенный, +10 критический, -3 низкий.
    (RHR anomaly detection based on coros_health_metrics.md §6.)
    """
    if rhr is None:
        return {'status': 'unknown', 'value': None, 'confidence': 0.0, 'evidence': 'no RHR data'}
    if baseline_rhr is None:
        return {'status': 'normal', 'value': rhr, 'confidence': 0.3, 'evidence': 'no baseline'}
    diff = rhr - baseline_rhr
    if diff >= 10:
        status = 'critical_elevated'
        confidence = 0.9
    elif diff >= 5:
        status = 'elevated'
        confidence = 0.8
    elif diff <= -3:
        status = 'low'
        confidence = 0.7
    else:
        status = 'normal'
        confidence = 0.8
    return {
        'status': status,
        'value': rhr,
        'confidence': confidence,
        'evidence': f'RHR={rhr}, baseline={baseline_rhr}, diff={diff:+d}',
    }
