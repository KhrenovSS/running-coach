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
