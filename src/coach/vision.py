# Извлечение данных сна из скриншота (Sleep-screenshot vision) — #257, подход 29.08.2026
#
# Пользователь присылает скрин экрана сна Coros → мост читает картинку через
# Read-tool (endpoint /vision, bin/coach_llm_bridge.py) → строгий JSON.
# Отдельный узкий путь: основной текстовый коуч (мост /complete) не затронут.
# (Owner sends a Coros sleep screenshot; the bridge reads it and returns strict JSON.)

from __future__ import annotations

import base64

import httpx
from pydantic import BaseModel, Field, ValidationError, field_validator

from src.coach.llm.bridge_client import extract_json
from src.config import settings
from src.utils.logger import get_logger

logger = get_logger("coach.vision")

_SYSTEM = ("Ты извлекаешь данные из скриншота экрана сна приложения Coros. "
           "Отвечай СТРОГО одним JSON-объектом, без markdown и пояснений.")

# Промпт под реальный экран Coros (подписи смешанные RU/EN):
# «Всего сна», «Deep Sleep %», «REM %», «Бдение» (время / прерывания),
# «Bedtime Consistency» (сдвиг vs 30-дн. среднего), «Sleep Stress», текст-резюме.
_PROMPT = (
    "Прочитай изображение (Read tool) — это экран сна Coros — и верни JSON строго:\n"
    '{"is_sleep_screen": true|false,\n'
    ' "duration_min": минут общего сна («Всего сна» 5h 52min → 352) или null,\n'
    ' "deep_pct": процент глубокого сна («Deep Sleep %» → целое 0-100) или null,\n'
    ' "rem_pct": процент REM («REM %») или null,\n'
    ' "awake_min": минут бодрствования («Бдение» total time) или null,\n'
    ' "awake_interruptions": число прерываний («/ N раз») или null,\n'
    ' "bedtime_offset_min": «Bedtime Consistency vs среднего»: целое со знаком, '
    'позже среднего = плюс (49мин later → 49), раньше = минус, или null,\n'
    ' "sleep_stress": число «Sleep Stress» или null,\n'
    ' "deep_min": минуты глубокого, если показаны отдельно, иначе null,\n'
    ' "rem_min": минуты REM, если показаны, иначе null,\n'
    ' "score": оценка/балл сна, если есть, иначе null,\n'
    ' "note": короткое текстовое резюме сна с экрана (одна строка) или null,\n'
    ' "date": "YYYY-MM-DD" если дата видна, иначе null}\n'
    "Время «7ч 42м»/«7h 42m» переводи в минуты. Если это НЕ экран сна — "
    '{"is_sleep_screen": false} и остальное null. Чего нет на экране — null, '
    "не выдумывай."
)


class SleepShot(BaseModel):
    """Данные сна, извлечённые из скриншота Coros (parsed sleep screenshot)."""
    is_sleep_screen: bool = False
    duration_min: int | None = Field(default=None, ge=0, le=1440)
    awake_min: int | None = Field(default=None, ge=0, le=1440)
    deep_pct: int | None = Field(default=None, ge=0, le=100)
    rem_pct: int | None = Field(default=None, ge=0, le=100)
    awake_interruptions: int | None = Field(default=None, ge=0, le=200)
    bedtime_offset_min: int | None = Field(default=None, ge=-720, le=720)
    sleep_stress: int | None = Field(default=None, ge=0, le=100)
    # опционально — если конкретный экран показывает минуты фаз / балл:
    deep_min: int | None = Field(default=None, ge=0, le=1440)
    rem_min: int | None = Field(default=None, ge=0, le=1440)
    score: int | None = Field(default=None, ge=0, le=100)
    note: str | None = Field(default=None, max_length=500)
    date: str | None = None

    @field_validator("duration_min", "awake_min", "deep_pct", "rem_pct",
                     "awake_interruptions", "bedtime_offset_min", "sleep_stress",
                     "deep_min", "rem_min", "score", mode="before")
    @classmethod
    def _empty_to_none(cls, v):
        return None if v in ("", "null", "-") else v

    def has_data(self) -> bool:
        """Есть ли что сохранять (минимум общая длительность)."""
        return self.is_sleep_screen and self.duration_min is not None

    def extra(self) -> dict | None:
        """Гибкие метрики → JSON-колонка sleep_extra (flexible metrics blob)."""
        keys = ("deep_pct", "rem_pct", "awake_interruptions", "bedtime_offset_min",
                "sleep_stress", "deep_min", "rem_min", "score", "note")
        d = {k: getattr(self, k) for k in keys if getattr(self, k) is not None}
        return d or None


def extract_sleep(image_bytes: bytes, *, timeout: int = 150) -> SleepShot | None:
    """Скрин → SleepShot через мост /vision. None — мост недоступен/ошибка/мусор.

    Никогда не бросает наружу: фото пользователя не должно ронять хендлер.
    """
    base_url = (settings.coach_llm_bridge_url or "").rstrip("/")
    if not base_url:
        logger.warning("Vision: мост не настроен (coach_llm_bridge_url пуст)")
        return None
    payload = {
        "image_b64": base64.b64encode(image_bytes).decode("ascii"),
        "prompt": _PROMPT,
        "system_text": _SYSTEM,
    }
    try:
        resp = httpx.post(f"{base_url}/vision", json=payload,
                          headers={"X-Bridge-Token": settings.coach_llm_bridge_token},
                          timeout=timeout)
    except httpx.HTTPError as e:
        logger.warning("Vision: мост недоступен: %s", e)
        return None
    if resp.status_code != 200:
        logger.warning("Vision: мост HTTP %s: %s", resp.status_code, resp.text[:200])
        return None
    parsed = extract_json(resp.json().get("text", ""))
    if parsed is None:
        logger.warning("Vision: не удалось распарсить JSON из ответа модели")
        return None
    try:
        return SleepShot.model_validate(parsed)
    except ValidationError as e:
        logger.warning("Vision: ответ не прошёл валидацию: %s", e)
        return None
