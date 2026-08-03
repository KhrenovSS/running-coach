# Coach orchestrator (точки входа)
# Этап 0 — скелет модуля коуча (Coach module skeleton). Реализация — на последующих этапах.

def on_workout_completed(user_id: int, session_id: int, db=None):
    """После загрузки/синка тренировки: анализ + калибровка + обновление рекомендаций."""
    raise NotImplementedError("Этап 4")


def morning_check(user_id: int, db=None):
    """Утренняя проверка готовности → рекомендация на день."""
    raise NotImplementedError("Этап 2")


def handle_chat(user_id: int, message: str, db=None):
    """Свободный чат с коучем (LLM как интерфейс)."""
    raise NotImplementedError("Этап 5")
