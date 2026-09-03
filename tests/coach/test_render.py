# Тесты детерминированного рендера (Deterministic render tests) — DEV_PLAN §10
from src.coach.contracts import AthleteState, WorkoutProposal
from src.coach.rules.p1_safety import evaluate_safety
from src.coach.render import (
    render_prescription,
    render_prescription_short,
    render_state_card,
)
from src.coach.safety import clamp
from tests.coach.test_safety_clamp import AGGRESSIVE, _state


def test_render_numbers_match_prescription():
    """Числа карточки — из полей Prescription, не из прозы (numbers from fields)."""
    state = _state()
    verdict = evaluate_safety(state)
    p, _ = clamp(WorkoutProposal(workout_type="easy", target_zone=2,
                                 duration_min=45, distance_km=7.5), verdict, state)
    text = render_prescription(p)
    assert "Лёгкий бег" in text
    assert "Z2" in text
    assert "45 мин" in text
    assert "7.5 км" in text
    assert "Ограничение по безопасности" not in text  # не урезано — блока нет


def test_render_clamped_has_safety_block():
    """При clamped=True в карточке есть фиксированный не-LLM-блок ограничения."""
    state = _state(hrv_status="very_low")
    verdict = evaluate_safety(state)
    p, clamped = clamp(AGGRESSIVE, verdict, state)
    assert clamped
    text = render_prescription(p)
    assert "⚠️ *Ограничение по безопасности:*" in text
    assert "Интервалы" not in text  # агрессивный тип не просочился в карточку


def test_render_rest_has_no_volume():
    state = _state(pain_level=7)
    verdict = evaluate_safety(state)
    p, _ = clamp(AGGRESSIVE, verdict, state)
    text = render_prescription(p)
    assert "Отдых" in text
    assert "км" not in text and "мин" not in text.replace("Ограничение", "")


def test_render_prescription_with_max_hr_shows_bpm_ceiling():
    """Инцидент 26.08: карточка не содержала цифр пульса — «точный потолок
    увидишь в карточке» вёл в никуда. С max_hr потолок зоны в уд/мин обязателен."""
    state = _state()
    verdict = evaluate_safety(state)
    p, _ = clamp(WorkoutProposal(workout_type="easy", target_zone=2,
                                 duration_min=40, distance_km=5.5), verdict, state)
    text = render_prescription(p, max_hr=177)
    assert "пульс до 141 уд/мин" in text   # 177·0.80 = 141.6 → floor
    # без max_hr — прежний формат, строки пульса нет (backward-compatible)
    assert "пульс" not in render_prescription(p)


def test_render_prescription_z5_no_bpm_line():
    """Z5 — потолка в уд/мин нет: строка пульса не рендерится."""
    state = _state()
    verdict = evaluate_safety(state)
    p, _ = clamp(WorkoutProposal(workout_type="easy", target_zone=2), verdict, state)
    p.target["max_zone"] = 5
    assert "пульс" not in render_prescription(p, max_hr=177)


def test_render_prescription_short_reminder_line():
    """Короткое напоминание (решение владельца 26.08): тип · пульс до N · мин."""
    state = _state()
    verdict = evaluate_safety(state)
    p, _ = clamp(WorkoutProposal(workout_type="easy", target_zone=2,
                                 duration_min=40, distance_km=5.5), verdict, state)
    text = render_prescription_short(p, max_hr=177)
    assert text.startswith("План на сегодня без изменений:")
    assert "🟢 Лёгкий бег · пульс до 141 · 40 мин" in text
    # без max_hr — вместо пульса зона
    assert "Z2 и ниже" in render_prescription_short(p)


def test_render_predicted_estimate_replaces_llm_distance():
    """Пожелание 26.08: дистанция — расчётный ориентир из данных, не догадка LLM.

    С predicted: строка «Ориентир…» с темпом, км от LLM скрыт; в напоминании — то же.
    """
    state = _state()
    verdict = evaluate_safety(state)
    p, _ = clamp(WorkoutProposal(workout_type="easy", target_zone=2,
                                 duration_min=40, distance_km=5.5), verdict, state)
    p.predicted = {"pace_min_km": 7.5, "distance_km": 5.3, "hr_ceiling": 141}
    text = render_prescription(p, max_hr=177)
    assert "Ориентир по твоим пробежкам: ~7:30/км → ≈5.3 км" in text
    assert "~5.5 км" not in text            # догадка LLM скрыта
    short = render_prescription_short(p, max_hr=177)
    assert "~7:30/км ≈ 5.3 км" in short


def test_render_no_predicted_keeps_llm_distance():
    """Без прогноза — прежний формат с `~N км` из proposal."""
    state = _state()
    verdict = evaluate_safety(state)
    p, _ = clamp(WorkoutProposal(workout_type="easy", target_zone=2,
                                 duration_min=40, distance_km=5.5), verdict, state)
    p.predicted = {}
    text = render_prescription(p, max_hr=177)
    assert "~5.5 км" in text
    assert "Ориентир" not in text


def test_render_prescription_short_rest():
    """Отдых в напоминании — без пульса и объёма."""
    state = _state(pain_level=7)
    verdict = evaluate_safety(state)
    p, _ = clamp(AGGRESSIVE, verdict, state)
    text = render_prescription_short(p, max_hr=177)
    assert "Отдых" in text
    assert "пульс" not in text and "мин" not in text


def test_render_state_card_low_confidence_warns():
    state = AthleteState(user_id=1, data_confidence=0.2)
    text = render_state_card(state)
    assert "Данных мало" in text


def test_render_no_unbalanced_markdown():
    """Инцидент 23.08: одиночный `_` (tired_rate) ломал legacy-Markdown Telegram.

    Вне backticks в карточках не должно быть `_`; `*` — парные.
    """
    import re

    from src.coach.contracts import SkillResult
    from src.coach.render import render_state_card

    state = AthleteState(user_id=1, data_confidence=0.9, skills={
        "fatigue": SkillResult(key="fatigue", status="warning", value=-26,
                               unit="tired_rate", confidence=0.8),
        "load": SkillResult(key="load", status="danger", value=1.68, unit="ratio"),
    })
    text = render_state_card(state)
    outside_code = re.sub(r"`[^`]*`", "", text)   # вырезать code-entities
    assert "_" not in outside_code, f"голый _ вне backticks: {outside_code!r}"
    assert outside_code.count("*") % 2 == 0, "непарные * в карточке"


def test_render_earliest_in_local_timezone(monkeypatch):
    """Инцидент 23.08: earliest показывался в UTC (17:59 вместо 20:59 мск)."""
    from datetime import datetime

    from src.config import settings

    monkeypatch.setattr(settings, "timezone", "Europe/Moscow")
    state = _state()
    state.recovery_hours_left = 1.0
    verdict = evaluate_safety(state, now=datetime(2026, 8, 23, 16, 59))
    p, _ = clamp(WorkoutProposal(workout_type="easy", target_zone=2), verdict, state,
                 now=datetime(2026, 8, 23, 16, 59))
    text = render_prescription(p)
    assert "20:59" in text     # 17:59 UTC → 20:59 MSK
    assert "17:59" not in text


def test_render_earliest_prefers_user_timezone(monkeypatch):
    """BACKLOG #260: пояс пользователя приоритетнее settings.timezone (user tz wins)."""
    from datetime import datetime
    from types import SimpleNamespace

    from src.config import settings

    monkeypatch.setattr(settings, "timezone", "Europe/Moscow")
    state = _state()
    state.recovery_hours_left = 1.0
    verdict = evaluate_safety(state, now=datetime(2026, 8, 23, 16, 59))
    p, _ = clamp(WorkoutProposal(workout_type="easy", target_zone=2), verdict, state,
                 now=datetime(2026, 8, 23, 16, 59))
    user = SimpleNamespace(timezone="Europe/Berlin")
    text = render_prescription(p, user=user)
    assert "19:59" in text     # 17:59 UTC → 19:59 Berlin (не 20:59 MSK)
    assert "20:59" not in text


# --- Pace-режим: цель — темп+время, пульс справочно (pace-lead cards) ---

def _pace_prescription(expected_hr: int | None = 166):
    """Заклэмпленное pace-назначение: темп 5.5 (5:30/км), 40 мин → ≈7.3 км."""
    state = _state()
    verdict = evaluate_safety(state)
    p, _ = clamp(WorkoutProposal(workout_type="tempo", target_zone=4,
                                 duration_min=40, target_pace_min_km=5.5),
                 verdict, state)
    if expected_hr is not None:
        p.predicted = {"expected_hr": expected_hr, "pace_min_km": 5.5,
                       "based_on": {"n_points": 8, "window_days": 120}}
    return p


def test_render_pace_lead_full_card():
    """Все параметры: цель — темп+время, дистанция расчётная, пульс справочно."""
    text = render_prescription(_pace_prescription(), max_hr=177)
    assert "Темп 5:30/км" in text
    assert "40 мин" in text
    assert "≈7.3 км" in text                       # 40 / 5.5
    assert "на пульс сегодня не смотрим" in text
    assert "~166 уд/мин" in text
    assert "ориентировочно" in text
    assert "пульс до" not in text                  # HR-цели в pace-режиме нет
    assert "и ниже" not in text                    # строки зоны нет


def test_render_pace_lead_no_hr_estimate():
    """Мало данных для прогноза пульса → пометка вместо цифры."""
    text = render_prescription(_pace_prescription(expected_hr=None), max_hr=177)
    assert "Темп 5:30/км" in text
    assert "мало данных" in text
    assert "уд/мин" not in text


def test_render_pace_lead_short():
    """Short-напоминание pace-режима: тип · темп · время · дистанция."""
    text = render_prescription_short(_pace_prescription(), max_hr=177)
    assert text.startswith("План на сегодня без изменений:")
    assert "темп 5:30/км" in text
    assert "40 мин" in text
    assert "≈7.3 км" in text
    assert "пульс до" not in text


def test_render_future_day_card_and_short():
    """Инцидент 29.08: план на воскресенье подписывался «на сегодня».

    Будущий день: заголовок с днём недели и датой + пометка «предварительно»;
    short — «План на <день> (dd.mm) без изменений:». Сегодня — байт-в-байт прежнее.
    """
    from datetime import date, timedelta

    from src.coach.render import _WEEKDAYS_RU

    state = _state()
    verdict = evaluate_safety(state)
    p, _ = clamp(WorkoutProposal(workout_type="long", target_zone=2,
                                 duration_min=60, for_days_ahead=2), verdict, state)
    today = p.when - timedelta(days=2)
    day_name = _WEEKDAYS_RU[p.when.weekday()]

    card = render_prescription(p, max_hr=177, today=today)
    assert f"*🟦 Длительный бег — {day_name} {p.when:%d.%m}*" in card
    assert "Предварительно — утром сверимся по состоянию." in card

    short = render_prescription_short(p, max_hr=177, today=today)
    assert short.startswith(f"План на {day_name} ({p.when:%d.%m}) без изменений:")

    # Сегодняшнее назначение — прежние строки без метки дня
    p_today, _ = clamp(WorkoutProposal(workout_type="long", target_zone=2,
                                       duration_min=60), verdict, state)
    assert render_prescription(p_today, max_hr=177,
                               today=p_today.when).startswith("*🟦 Длительный бег*")
    assert render_prescription_short(p_today, max_hr=177, today=p_today.when
                                     ).startswith("План на сегодня без изменений:")


def test_render_week_plan_shows_distance():
    """Недельная карточка: у каждого бегового дня есть примерная дистанция ≈X км.

    Пожелание владельца 31.08.2026: раньше в плане выводились только темп/пульс +
    время, без пройденного расстояния. Дистанцию берём из уже клэмпленного объёма.
    """
    from datetime import date

    from src.coach.render_week import render_week_plan

    state = _state()
    verdict = evaluate_safety(state)
    tempo, _ = clamp(WorkoutProposal(workout_type="tempo", target_zone=4,
                                     duration_min=40, target_pace_min_km=5.5),
                     verdict, state)               # pace-режим → volume km 7.3
    easy, _ = clamp(WorkoutProposal(workout_type="easy", target_zone=2,
                                    duration_min=45, distance_km=7.5),
                    verdict, state)                # HR-режим → volume km 7.5
    tempo.when = date(2026, 9, 2)
    easy.when = date(2026, 9, 4)
    targets = {"week_start": "2026-08-31", "mesocycle_week": 2,
               "mesocycle_length": 4, "phase": "build", "target_km": 40}

    text = render_week_plan([tempo, easy], targets, max_hr=177)
    assert "План на неделю" in text
    assert "≈7.3 км" in text                       # темп-день: 40 / 5.5
    assert "≈7.5 км" in text                       # лёгкий день: объём из proposal


def test_render_gps_warning_with_cadence_estimate():
    """GPS недостоверен + оценка по шагам → числа из детерминированного рендера:
    длительность сбоя, оценка в км и число, которое пользователь видел на часах."""
    from src.coach.render import render_gps_warning

    text = render_gps_warning({
        "unreliable": True,
        "bad_first_min": 0.0, "bad_last_min": 15.0,
        "device_distance_km": 15.65,
        "gps_distance_km": 4.35,
        "distance": {"source": "cadence_estimate", "quality": "estimate",
                     "estimated_km": 6.52},
    })
    assert text is not None
    assert "GPS сбоил" in text
    assert "оценка по шагам" in text
    assert "6.5 км" in text          # число из estimated_km, не из прозы LLM
    assert "часы намерили 15.7" in text  # контраст с числом на часах, не пост-очистка
    assert "15 мин" in text          # длительность сбоя из bad_first/last


def test_render_gps_warning_without_estimate_degrades_honestly():
    """Оценки нет → предупреждение без чисел дистанции-оценки."""
    from src.coach.render import render_gps_warning

    text = render_gps_warning({"unreliable": True, "gps_distance_km": 4.35,
                               "distance": {"source": "gps", "quality": "unknown"}})
    assert "ненадёжны" in text
    assert "оценка по шагам" not in text


def test_render_gps_warning_none_when_reliable():
    """GPS в порядке (или блока нет) → предупреждения нет."""
    from src.coach.render import render_gps_warning

    assert render_gps_warning(None) is None
    assert render_gps_warning({"unreliable": False}) is None


def test_render_week_plan_facts_mode_and_backward_compat():
    """facts= → прошедшие дни как факт/пропуск, будущее — план; без facts всё как раньше."""
    from datetime import date

    from src.coach.render_week import render_week_plan

    state = _state()
    verdict = evaluate_safety(state)
    past, _ = clamp(WorkoutProposal(workout_type="easy", target_zone=2, duration_min=40),
                    verdict, state)
    missed, _ = clamp(WorkoutProposal(workout_type="easy", target_zone=2, duration_min=30),
                      verdict, state)
    future, _ = clamp(WorkoutProposal(workout_type="long", target_zone=2, duration_min=70),
                      verdict, state)
    past.when, missed.when, future.when = date(2026, 8, 31), date(2026, 9, 1), date(2026, 9, 6)
    targets = {"week_start": "2026-08-31"}
    facts = {date(2026, 8, 31): {"duration_min": 41.0, "distance_km": 5.9, "avg_hr": 139},
             date(2026, 9, 1): None}

    text = render_week_plan([past, missed, future], targets, max_hr=177,
                            today=date(2026, 9, 2), facts=facts)
    assert "✓ Пн 31.08 — 🟢 Лёгкий бег · факт 41 мин · 5.9 км · ср. пульс 139" in text
    assert "✗ Вт 01.09 — 🟢 Лёгкий бег · 30 мин · пропущен" in text
    assert "Вс 06.09 — 🟦 Длительный бег · пульс до" in text
    assert "✓ факт · ✗ пропущен" in text

    plain = render_week_plan([past, missed, future], targets, max_hr=177)
    assert "✓" not in plain and "✗" not in plain and "пульс до" in plain


def test_render_week_plan_rest_of_week_summary():
    """plan_scope=rest_of_week → в шапке «сделано X км, осталось ~Y км»."""
    from datetime import date

    from src.coach.render_week import render_week_plan

    state = _state()
    easy, _ = clamp(WorkoutProposal(workout_type="easy", target_zone=2, duration_min=40),
                    evaluate_safety(state), state)
    easy.when = date(2026, 9, 4)
    targets = {"week_start": "2026-08-31", "mesocycle_week": 1, "mesocycle_length": 4,
               "phase": "build", "target_km": 28.0, "plan_scope": "rest_of_week",
               "done_km": 12.1, "remaining_km": 15.9}
    text = render_week_plan([easy], targets, max_hr=177, today=date(2026, 9, 2))
    assert "цель ~28 км · сделано 12.1 км, осталось ~15.9 км" in text


def test_render_week_plan_shows_pace_hint_and_predicted_km():
    """Строка недели: ~темп из прогноза; ≈км — из прогноза, а не из числа LLM (02.09.2026);
    fallback темпа — подсказка основного сегмента; без данных темпа нет."""
    from datetime import date

    from src.coach.render_week import render_week_plan

    state = _state()
    verdict = evaluate_safety(state)
    long, _ = clamp(WorkoutProposal(workout_type="long", target_zone=2, duration_min=80,
                                    distance_km=9.0), verdict, state)
    long.when = date(2026, 9, 6)
    long.predicted = {"pace_min_km": 7.06, "distance_km": 11.3}
    seg, _ = clamp(WorkoutProposal(workout_type="easy", target_zone=2, duration_min=35),
                   verdict, state)
    seg.when = date(2026, 9, 4)
    seg.predicted = {}
    seg.target["segments"] = [
        {"role": "warmup", "amount_kind": "min", "amount_value": 5.0, "pace_hint_min_km": None},
        {"role": "steady", "amount_kind": "min", "amount_value": 25.0, "pace_hint_min_km": 6.87}]
    nodata, _ = clamp(WorkoutProposal(workout_type="easy", target_zone=1, duration_min=30,
                                      distance_km=4.0), verdict, state)
    nodata.when = date(2026, 9, 3)
    nodata.predicted = {}

    text = render_week_plan([long, seg, nodata], {"week_start": "2026-08-31"}, max_hr=177)
    lines = {l.split(" — ")[0][-5:]: l for l in text.splitlines() if " — " in l}
    assert "~7:04/км" in lines["06.09"] and "≈11.3 км" in lines["06.09"]   # прогноз, не 9.0
    assert "≈9.0 км" not in text
    assert "~6:52/км" in lines["04.09"]                                    # подсказка сегмента
    assert "/км" not in lines["03.09"] and "≈4.0 км" in lines["03.09"]     # нет данных → без темпа


def test_render_week_plan_fact_line_has_pace():
    """Факт прошедшего дня печатает фактический темп."""
    from datetime import date

    from src.coach.render_week import render_week_plan

    state = _state()
    p, _ = clamp(WorkoutProposal(workout_type="easy", target_zone=2, duration_min=40),
                 evaluate_safety(state), state)
    p.when = date(2026, 8, 31)
    text = render_week_plan([p], {"week_start": "2026-08-31"}, max_hr=177,
                            today=date(2026, 9, 2),
                            facts={date(2026, 8, 31): {"duration_min": 38.2, "distance_km": 5.4,
                                                       "pace_min_km": 38.2 / 5.4, "avg_hr": 137}})
    assert "факт 38 мин · 5.4 км · 7:04/км · ср. пульс 137" in text


def test_week_card_and_short_card_show_compact_structure():
    """Строка недели и короткая карточка печатают структуру сегментов компактно;
    у прошедшего дня — плановая структура рядом с фактом (жалоба владельца 02.09)."""
    from datetime import date

    from src.coach.render import render_prescription_short
    from src.coach.render_week import render_week_plan

    state = _state()
    verdict = evaluate_safety(state)
    strides = [{"role": "steady", "amount_kind": "min", "amount_value": 25.0, "target_zone": 2},
               {"role": "work", "repeat": 7, "amount_kind": "sec", "amount_value": 18.0,
                "target_zone": 3},
               {"role": "cooldown", "amount_kind": "min", "amount_value": 5.0, "target_zone": 1}]
    past, _ = clamp(WorkoutProposal(workout_type="easy", target_zone=3, duration_min=35),
                    verdict, state)
    past.when = date(2026, 9, 1)
    past.target["segments"] = strides
    today_p, _ = clamp(WorkoutProposal(workout_type="easy", target_zone=2, duration_min=35),
                       verdict, state)
    today_p.when = date(2026, 9, 2)
    today_p.target["segments"] = [
        {"role": "warmup", "amount_kind": "min", "amount_value": 5.0, "target_zone": 1},
        {"role": "steady", "amount_kind": "min", "amount_value": 25.0, "target_zone": 2},
        {"role": "cooldown", "amount_kind": "min", "amount_value": 5.0, "target_zone": 1}]

    text = render_week_plan([past, today_p], {"week_start": "2026-08-31"}, max_hr=177,
                            today=date(2026, 9, 2),
                            facts={date(2026, 9, 1): {"duration_min": 46.2, "distance_km": 6.7,
                                                      "pace_min_km": 46.2 / 6.7, "avg_hr": 140}})
    assert "детали в дне" not in text
    # ускорения — структура в уд/мин (177: Z2→141, Z3→153, Z1→123)
    assert ("✓ Вт 01.09 — 🟢 Лёгкий бег · 25 мин до 141 + 7×18 сек до 153 + зам 5 мин до 123"
            " · факт 46 мин") in text
    # ровная пробежка (разм/бег/зам) — без структуры и без зон (решение владельца 02.09)
    wed = next(l for l in text.splitlines() if l.startswith("▶ Ср 02.09"))
    assert "разм" not in wed and "Z" not in wed and "пульс до 141" in wed

    short = render_prescription_short(today_p, max_hr=177, today=date(2026, 9, 2))
    assert "разм" not in short and short.endswith("пульс до 141 · 35 мин")   # без структуры
    short_strides = render_prescription_short(past, max_hr=177, today=date(2026, 9, 1))
    assert short_strides.endswith("25 мин до 141 + 7×18 сек до 153 + зам 5 мин до 123")


def test_hr_lead_line_is_bpm_first():
    """Полная карточка: «пульс до N уд/мин» без ярлыка зоны; зона — только без max_hr."""
    state = _state()
    p, _ = clamp(WorkoutProposal(workout_type="easy", target_zone=2, duration_min=45),
                 evaluate_safety(state), state)
    with_hr = render_prescription(p, max_hr=177)
    assert "пульс до 141 уд/мин" in with_hr and "Z2 и ниже" not in with_hr
    assert "Z2 и ниже" in render_prescription(p)


def test_plan_change_line_formats():
    """«Изменил план на Вс 06.09: 🛌 Отдых (было: 🟦 Длительный бег · 80 мин)»; без прежней
    строки — «Поставил на …»; у отдыха минут нет (решение владельца 03.09.2026)."""
    from datetime import date
    from types import SimpleNamespace

    from src.coach.render_week import plan_change_line

    state = _state()
    verdict = evaluate_safety(state)
    rest, _ = clamp(WorkoutProposal(workout_type="rest", target_zone=1), verdict, state)
    tempo, _ = clamp(WorkoutProposal(workout_type="easy", target_zone=2, duration_min=45),
                     verdict, state)
    old = SimpleNamespace(workout_type="long", volume_json={"duration_min": 80.0})
    when = date(2026, 9, 6)
    assert plan_change_line(when, rest, old) == \
        "Изменил план на Вс 06.09: 🛌 Отдых (было: 🟦 Длительный бег · 80 мин)"
    assert plan_change_line(when, rest, None) == "Поставил на Вс 06.09: 🛌 Отдых"
    line = plan_change_line(date(2026, 9, 2), tempo, SimpleNamespace(
        workout_type="rest", volume_json={}))
    assert line.startswith("Изменил план на Ср 02.09: 🟢 Лёгкий бег · 45 мин (было: 🛌 Отдых)")
