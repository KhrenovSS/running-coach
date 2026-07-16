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
