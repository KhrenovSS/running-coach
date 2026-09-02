# Карточка СОХРАНЁННОГО плана недели (week_view) — инцидент 02.09.2026:
# вопрос «какой план на неделю» в чате получал прозу без чисел.
from datetime import timedelta

from src.coach.week_view import NO_PLAN_TEXT, render_stored_week_plan
from src.models import Recommendation, UserModel
from src.utils.timeutils import user_now


def _monday(d):
    return d - timedelta(days=d.weekday())


def _rec(db, user_id, for_date, wtype="easy", zone=2, minutes=40.0,
         status="planned", km=None):
    row = Recommendation(user_id=user_id, for_date=for_date, workout_type=wtype,
                         target_json={"max_zone": zone},
                         volume_json={"duration_min": minutes, "distance_km": km},
                         status=status, source="llm", clamped=False)
    db.add(row)
    db.commit()
    return row


def test_empty_week_hints_plan_command(empty_user, db_session):
    """Строк на неделю нет → подсказка составить план, без падения."""
    assert render_stored_week_plan(empty_user.id, db=db_session) == NO_PLAN_TEXT


def test_latest_row_per_date_wins_and_today_marked(empty_user, db_session):
    """Последняя строка на дату (proposed поверх planned) побеждает; сегодня — «▶»;
    без меты мезоцикла заголовок сводки опускается; строки другой недели не попадают."""
    today = user_now(empty_user).date()
    monday = _monday(today)
    sunday = monday + timedelta(days=6)
    _rec(db_session, empty_user.id, sunday, "long", 2, 75.0, "planned", km=8.4)
    _rec(db_session, empty_user.id, sunday, "long", 2, 80.0, "proposed", km=9.0)
    _rec(db_session, empty_user.id, today, "easy", 2, 35.0, "confirmed")
    _rec(db_session, empty_user.id, monday + timedelta(days=7), "tempo", 3, 45.0)

    text = render_stored_week_plan(empty_user.id, db=db_session)

    assert f"План на неделю ({monday:%d.%m}–{sunday:%d.%m})" in text
    assert "80 мин" in text and "≈9.0 км" in text       # свежая строка воскресенья
    assert "75 мин" not in text                          # старая — вытеснена
    assert f"▶ " in text and f"{today:%d.%m}" in text    # маркер сегодняшнего дня
    assert "мезоцикла" not in text                       # меты недели нет
    assert "Темповая" not in text                        # следующая неделя — мимо
    assert "/plan" in text                               # футер «перепланировать»


def test_week_meta_from_user_model_renders_header(empty_user, db_session):
    """Мета недели из params_json.week_plan (advance_mesocycle) — в заголовке."""
    today = user_now(empty_user).date()
    monday = _monday(today)
    _rec(db_session, empty_user.id, today, "easy", 2, 30.0)
    db_session.add(UserModel(user_id=empty_user.id, params_json={"week_plan": {
        "week_start": monday.isoformat(), "mesocycle_week": 2,
        "phase": "build", "target_km": 28.0, "last_build_km": 28.0}}))
    db_session.commit()

    text = render_stored_week_plan(empty_user.id, db=db_session)
    assert "Неделя 2/4 мезоцикла (рост) · цель ~28 км" in text


def test_week_meta_of_other_week_is_ignored(empty_user, db_session):
    """Мета другой недели (устаревшая) не подставляется в заголовок."""
    today = user_now(empty_user).date()
    _rec(db_session, empty_user.id, today, "easy", 2, 30.0)
    db_session.add(UserModel(user_id=empty_user.id, params_json={"week_plan": {
        "week_start": (_monday(today) - timedelta(days=7)).isoformat(),
        "mesocycle_week": 1, "mesocycle_length": 4, "phase": "build",
        "target_km": 20.0}}))
    db_session.commit()
    assert "мезоцикла" not in render_stored_week_plan(empty_user.id, db=db_session)


def test_superseded_rows_are_invisible(empty_user, db_session):
    """Строка, погашенная перепланированием, не попадает в карточку недели."""
    today = user_now(empty_user).date()
    saturday = _monday(today) + timedelta(days=5)
    _rec(db_session, empty_user.id, today, "easy", 2, 30.0)
    _rec(db_session, empty_user.id, saturday, "tempo", 3, 45.0, status="superseded")
    text = render_stored_week_plan(empty_user.id, db=db_session)
    assert "Темповая" not in text and "45 мин" not in text


def test_past_days_render_as_facts(empty_user, db_session):
    """Прошедшие дни — факт связанной тренировки (✓) или пропуск (✗); потолок пульса
    плана для них не печатается (он дрейфует со сменой якоря зон — жалоба 02.09.2026)."""
    from datetime import datetime, timedelta as td, timezone

    from tests.helpers import build_training_session

    today = user_now(empty_user).date()
    if today.weekday() < 2:                      # нужны два прошедших дня недели
        import pytest
        pytest.skip("понедельник/вторник — в текущей неделе мало прошедших дней")
    monday = _monday(today)
    done_row = _rec(db_session, empty_user.id, monday, "easy", 2, 38.0, "confirmed")
    _rec(db_session, empty_user.id, monday + timedelta(days=1), "easy", 2, 35.0, "confirmed")
    _rec(db_session, empty_user.id, today, "easy", 2, 35.0, "confirmed")
    s = build_training_session(
        db_session, empty_user.id, total_distance_km=5.4, duration_minutes=38.2,
        avg_heart_rate=137, training_type="tempo",     # классификатор — не наш ярлык
        begin_ts=datetime.combine(monday, datetime.min.time(), tzinfo=timezone.utc) + td(hours=9))
    done_row.linked_session_id = s.id
    db_session.commit()

    text = render_stored_week_plan(empty_user.id, db=db_session)
    lines = text.splitlines()
    mon = next(l for l in lines if f" {monday:%d.%m} — " in l)            # не заголовок
    tue = next(l for l in lines if f" {monday + timedelta(days=1):%d.%m} — " in l)
    assert mon.startswith("✓") and "факт 38 мин" in mon and "5.4 км" in mon \
        and "7:04/км" in mon and "ср. пульс 137" in mon              # фактический темп
    assert "Лёгкий бег" in mon and "Темповая" not in mon     # плановый ярлык, не классификатор
    assert "пульс до" not in mon
    assert tue.startswith("✗") and "пропущен" in tue and "35 мин" in tue
    assert any(l.startswith("▶") and "пульс до" in l for l in lines)   # сегодня — план
    assert "✓ факт · ✗ пропущен" in lines[-1]
