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

Относительные даты («сегодня», «вчера», «позавчера») определяй ТОЛЬКО по полю
days_ago тренировки (0 = сегодня, 1 = вчера) — не вычисляй их из ISO-дат сам.

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

OUTPUT_CONTRACT = """ФОРМАТ ОТВЕТА — ровно один JSON-объект, без markdown-фенсов и пояснений,
СТРОГО с этими именами полей:
{
  "message": "твоя проза",
  "proposal": {
    "workout_type": "rest|recovery|easy|long|tempo|interval|race",
    "target_zone": 1,
    "duration_min": 40,
    "distance_km": 6.5,
    "structure": null,
    "rationale": ["короткие причины строками"]
  },
  "followup_question": "один короткий вопрос или null",
  "log_suggestion": {"kind": "pain", "value": 2}
}
Правила:
- message: НЕ называй в прозе чисел тренировки (зоны, км, минуты, темп) — числа
  рендерит карточка из proposal. Проза — про «почему» и «как ощущается».
- proposal: объект ИЛИ null. Заполняй, когда уместно предложить тренировку (утро,
  вопрос «что мне сегодня делать»); в разговоре «просто поговорить» — null.
  Имена полей ровно как выше: workout_type, target_zone (1-5), duration_min,
  distance_km, structure, rationale (список строк). Другие имена не принимаются.
  Для workout_type="rest": target_zone = 1, duration_min и distance_km = null.
- followup_question: один короткий вопрос (самочувствие, колено, сон) — твой
  главный инструмент сбора обратной связи; или null.
- log_suggestion: объект ИЛИ null. Если пользователь упомянул боль/дискомфорт —
  предложи записать (kind="pain", value 0-10); запись только после его тапа."""


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


def build_today_block(state_json: dict, verdict_json: dict, today_iso: str,
                      extras: dict[str, Any] | None = None) -> str:
    """Сегодняшний контекст — единственное место с датой (the only dated block).

    extras — предзагруженные данные (recent_workouts, weekly_summary): сокращают
    tool round-trip'ы в API-режиме и компенсируют неактивный tool-цикл в мосте.
    """
    parts = [f"Сегодня: {today_iso}",
             "Состояние (get_athlete_state):",
             json.dumps(state_json, ensure_ascii=False, sort_keys=True),
             "Границы (get_safety_verdict):",
             json.dumps(verdict_json, ensure_ascii=False, sort_keys=True)]
    for key, value in (extras or {}).items():
        parts.append(f"{key}:")
        parts.append(json.dumps(value, ensure_ascii=False, sort_keys=True))
    return "\n".join(parts)
