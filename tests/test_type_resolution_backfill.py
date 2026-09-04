# Переразметка истории по резолверу (relabel backfill) — 04.09.2026
from datetime import timedelta

from src.domain.models.base import utcnow
from src.models import Recommendation
from src.services.repositories_insights import InsightRepository
from src.services.type_resolution_backfill import relabel_sessions
from tests.helpers import build_training_session, make_user


def test_relabel_sessions_changes_only_what_resolver_says(db_session):
    user = make_user(db_session, chat_id=987654321, email="relabel-backfill@example.com")   # max_hr 177
    d0 = utcnow() - timedelta(days=3)
    # A: план long, час спокойно, классификатор easy → long
    a = build_training_session(db_session, user.id, training_type="easy", avg_heart_rate=130,
                               duration_minutes=60, begin_ts=d0)
    db_session.add(Recommendation(user_id=user.id, for_date=d0.date(), workout_type="long",
                                  volume_json={"duration_min": 60.0}, status="planned"))
    # B: без плана, catch-all tempo при спокойном пульсе → easy
    b = build_training_session(db_session, user.id, training_type="tempo", avg_heart_rate=137,
                               duration_minutes=38, begin_ts=d0 + timedelta(days=1))
    # C: ручной override — не трогаем
    c = build_training_session(db_session, user.id, training_type="easy", avg_heart_rate=137,
                               duration_minutes=38, training_type_override="tempo",
                               begin_ts=d0 + timedelta(days=2))
    db_session.commit()

    result = relabel_sessions(db_session, user_id=user.id)
    assert result["checked"] == 2 and result["changed"] == 2
    for s in (a, b, c):
        db_session.refresh(s)
    assert (a.training_type, a.training_type_auto, a.training_type_source) == ("long", "easy", "plan")
    assert (b.training_type, b.training_type_auto, b.training_type_source) == ("easy", "tempo", "auto")
    assert c.training_type == "easy" and c.training_type_source is None      # override: не в выборке
    assert {ch["after"] for ch in result["changes"]} == {"long", "easy"}
    assert InsightRepository.for_session(user.id, a.id, db=db_session) is not None
    # повторный прогон ничего не меняет
    assert relabel_sessions(db_session, user_id=user.id)["changed"] == 0
