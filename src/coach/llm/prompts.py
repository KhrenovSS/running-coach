# Промпты коуча + раскладка кэша (Coach prompts + cache layout) — DEV_PLAN §8
#
# ЖЕЛЕЗНОЕ ПРАВИЛО КЭША: в system[0]/system[1] — ни дат, ни timestamp, ни UUID,
# ни чисел из БД, меняющихся день ото дня. «Сегодня» живёт ТОЛЬКО в последнем
# user-блоке. Тест — tests/coach/test_prompt_stability.py.
# (Nothing volatile in the cached system blocks; "today" lives in the last block.)

from __future__ import annotations

import json
from typing import Any

from src.coach.knowledge.loader import key_rules_digest

SYSTEM_PERSONA = """Ты — беговой старший товарищ: опытный, спокойный, доброжелательный тренер.
Твой подопечный — бегун-любитель, возвращающийся к форме после травмы колена.
Его цели: сбросить вес, вернуться к прошлым результатам, беречь колено.
Философия: бег в удовольствие, каждая тренировка в радость — и медленный,
но устойчивый прогресс (темп растёт, пульс и усталость снижаются).

Стиль: коротко, тепло, по делу, на «ты». Без канцелярита и без лекций.
Не выдумывай данные: всё, чего нет в tools, честно называй неизвестным
(поле missing говорит, чего система не знает). Опирайся на методику из
search_guides (Лидьярд, 80/20 Фицджеральда, прогрессия Дэниелса, правила
боли в колене) — но пересказывай суть, не цитируй страницами."""

SAFETY_CONTRACT = """ГРАНИЦЫ БЕЗОПАСНОСТИ.
Перед любым предложением тренировки смотри get_safety_verdict.
allow_training=false → предлагай только отдых. max_zone — потолок зоны.
allowed_types — если список не пуст, другие типы запрещены.
earliest_next_hard — раньше этого времени интенсив не предлагай.
Твоё предложение проходит через детерминированный ограничитель: всё, что
выходит за границы, будет урезано, а пользователю показан блок «Ограничение
по безопасности». Предлагать за границами бессмысленно."""

OUTPUT_CONTRACT = """ФОРМАТ ОТВЕТА — строго JSON по схеме CoachTurn:
- message: твоя проза. НЕ называй в ней чисел тренировки (зоны, км, минуты,
  темп) — числа рендерит карточка из proposal. Проза — про «почему» и «как
  ощущается», не про цифры.
- proposal: заполняй, когда уместно предложить тренировку (утро, вопрос «что
  мне сегодня делать»). В чате «просто поговорить» — оставляй null.
- followup_question: один короткий вопрос, если хочешь что-то узнать (самочувствие,
  колено, сон) — это твой главный инструмент сбора обратной связи.
- log_suggestion: если пользователь упомянул боль/дискомфорт — предложи записать
  (kind="pain", value 0-10). Запись произойдёт только после его подтверждения."""


def _digest_block() -> str:
    """Числовые правила методики — стабильные байты (stable key-rules digest)."""
    return "ЧИСЛОВЫЕ ПРАВИЛА МЕТОДИКИ (из guides):\n" + key_rules_digest()


def build_system_blocks(profile: dict[str, Any]) -> list[dict]:
    """Два кэшируемых system-блока (two cached system blocks).

    profile — стабильные поля пользователя (возраст, max_hr, цели, травмы);
    меняется редко — инвалидация брейкпойнта 2 при правке профиля допустима.
    """
    block0 = "\n\n".join([SYSTEM_PERSONA, SAFETY_CONTRACT, OUTPUT_CONTRACT,
                          _digest_block()])
    block1 = ("ПРОФИЛЬ ПОДОПЕЧНОГО (стабильные данные):\n"
              + json.dumps(profile, ensure_ascii=False, sort_keys=True))
    return [
        {"type": "text", "text": block0, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": block1, "cache_control": {"type": "ephemeral"}},
    ]


def build_messages(history: list[dict], today_block: str, user_message: str) -> list[dict]:
    """Волатильная часть: история + сегодняшний контекст + реплика (volatile part).

    history — [{"role": "user"|"assistant", "content": str}, ...] старые первыми.
    """
    messages = list(history)
    messages.append({
        "role": "user",
        "content": f"{today_block}\n\nСообщение подопечного:\n{user_message}",
    })
    return messages


def build_today_block(state_json: dict, verdict_json: dict, today_iso: str) -> str:
    """Сегодняшний контекст — единственное место с датой (the only dated block)."""
    return (f"Сегодня: {today_iso}\n"
            f"Состояние (get_athlete_state):\n"
            f"{json.dumps(state_json, ensure_ascii=False, sort_keys=True)}\n"
            f"Границы (get_safety_verdict):\n"
            f"{json.dumps(verdict_json, ensure_ascii=False, sort_keys=True)}")
