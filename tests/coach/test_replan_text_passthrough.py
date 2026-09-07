# Текст-триггер перепланирования доезжает до плана (инцидент 07.09.2026): реплика
# «переделай план, сегодня не смогу» раньше отбрасывалась в handle_text → cmd_plan.
import asyncio
from types import SimpleNamespace

from src.telegram.handlers import coach as coach_handlers


def test_plan_blocking_passes_athlete_text(monkeypatch):
    from src.coach import weekly_plan

    seen = {}

    def fake_plan(user_id, *, db, athlete_text=None, **_):
        seen["user_id"], seen["text"] = user_id, athlete_text
        return "ok"

    monkeypatch.setattr(weekly_plan, "generate_weekly_plan", fake_plan)
    assert coach_handlers._plan_blocking(7, "переделай план, сегодня не смогу") == "ok"
    assert seen == {"user_id": 7, "text": "переделай план, сегодня не смогу"}


def test_handle_text_replan_trigger_forwards_message(monkeypatch):
    seen = {}

    async def fake_cmd_plan(update, context, *, athlete_text=None):
        seen["text"] = athlete_text

    monkeypatch.setattr(coach_handlers, "cmd_plan", fake_cmd_plan)
    monkeypatch.setattr(coach_handlers, "_is_awaiting_weight", lambda chat_id: False)
    monkeypatch.setattr(coach_handlers, "get_user", lambda chat_id: SimpleNamespace(id=1))
    text = "Нужно переделать план: сегодня побегать не смогу"
    update = SimpleNamespace(effective_chat=SimpleNamespace(id=1),
                             message=SimpleNamespace(text=text))
    asyncio.run(coach_handlers.handle_text(update, None))
    assert seen["text"] == text
