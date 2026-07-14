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
