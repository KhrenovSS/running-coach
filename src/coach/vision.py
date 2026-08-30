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

_SYSTEM = ("Ты извлекаешь данные из скриншота экрана сна фитнес-приложения. "
           "Отвечай СТРОГО одним JSON-объектом, без markdown и пояснений.")

_PROMPT = (
    "Прочитай изображение (Read tool) и верни JSON строго с этими полями:\n"
    '{"is_sleep_screen": true|false,\n'
    ' "duration_min": целое минут общего сна или null,\n'
    ' "deep_min": минут глубокого сна или null,\n'
    ' "light_min": минут лёгкого сна или null,\n'
    ' "rem_min": минут REM или null,\n'
    ' "awake_min": минут бодрствования или null,\n'
    ' "score": оценка сна 0-100 или null,\n'
    ' "date": "YYYY-MM-DD" если дата видна, иначе null}\n'
    "Время вида «7ч 42м» / «7h 42m» переводи в минуты (462). "
    "Если это НЕ экран сна — верни {\"is_sleep_screen\": false} и остальные null. "
    "Не выдумывай: чего нет на экране — null."
)


class SleepShot(BaseModel):
    """Данные сна, извлечённые из скриншота (parsed sleep screenshot)."""
    is_sleep_screen: bool = False
    duration_min: int | None = Field(default=None, ge=0, le=1440)
    deep_min: int | None = Field(default=None, ge=0, le=1440)
    light_min: int | None = Field(default=None, ge=0, le=1440)
    rem_min: int | None = Field(default=None, ge=0, le=1440)
    awake_min: int | None = Field(default=None, ge=0, le=1440)
    score: int | None = Field(default=None, ge=0, le=100)
    date: str | None = None

    @field_validator("duration_min", "deep_min", "light_min", "rem_min",
                     "awake_min", "score", mode="before")
    @classmethod
    def _empty_to_none(cls, v):
        return None if v in ("", "null", "-") else v

    def has_data(self) -> bool:
        """Есть ли что сохранять (минимум длительность или скор)."""
        return self.is_sleep_screen and (self.duration_min is not None
                                         or self.score is not None)


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
