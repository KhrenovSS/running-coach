# Ручной tool-loop агента (Manual agent tool loop) — DEV_PLAN §5/§8
#
# Не client.beta.messages.tool_runner: runner'у некуда прокинуть request-scoped
# Session (глобал/contextvar нарушают §8 CLAUDE.md). Ручной цикл даёт лимит
# итераций, DI сессии и тривиальный мок. (Manual loop: session DI + iteration cap.)

from __future__ import annotations

import json

from pydantic import ValidationError
from sqlalchemy.orm import Session

from src.coach.llm.client import CoachLLM, LLMResponse
from src.coach.llm.config import COACH_MAX_TOKENS, COACH_MAX_TOOL_ITERATIONS
from src.coach.llm.schemas import CoachTurn, coach_turn_json_schema
from src.coach.tools.registry import anthropic_tools, run_tool
from src.exceptions import CoachError, NotFoundError, ToolExecutionError
from src.utils.logger import get_logger

logger = get_logger("coach.agent")


def _tool_results_block(resp: LLMResponse, *, user_id: int, db: Session) -> list[dict]:
    """Выполнить все tool-вызовы ответа, вернуть tool_result-блоки (run tool calls)."""
    results = []
    for call in resp.tool_calls:
        try:
            payload = run_tool(call.name, call.args, user_id=user_id, db=db)
            results.append({"type": "tool_result", "tool_use_id": call.id,
                            "content": json.dumps(payload, ensure_ascii=False)})
        except (ToolExecutionError, NotFoundError) as e:
            # Ошибка tool'а — данные для модели, не крах хода (tool error is data)
            results.append({"type": "tool_result", "tool_use_id": call.id,
                            "content": str(e), "is_error": True})
    return results


def run_turn(llm: CoachLLM, *, user_id: int, db: Session,
             system: list[dict], messages: list[dict],
             effort: str = "low") -> tuple[CoachTurn, dict]:
    """Один ход агента: цикл tool_use → tool_result → структурированный CoachTurn.

    Возвращает (turn, usage_total). Бросает CoachError при превышении лимита
    итераций или невалидном выходе — вызывающий уходит в fallback.
    """
    usage_total = {"input_tokens": 0, "output_tokens": 0,
                   "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0,
                   "tool_calls": []}
    convo = list(messages)
    for _ in range(COACH_MAX_TOOL_ITERATIONS):
        resp = llm.complete(system=system, messages=convo,
                            tools=anthropic_tools(),
                            output_schema=coach_turn_json_schema(),
                            effort=effort, max_tokens=COACH_MAX_TOKENS)
        for k in ("input_tokens", "output_tokens",
                  "cache_read_input_tokens", "cache_creation_input_tokens"):
            usage_total[k] += resp.usage.get(k, 0)

        if resp.stop_reason == "tool_use" and resp.tool_calls:
            usage_total["tool_calls"] += [c.name for c in resp.tool_calls]
            # Эхо блоков ответа как есть (incl. thinking) + все результаты одним
            # user-сообщением — иначе модель отучится от параллельных вызовов.
            convo.append({"role": "assistant", "content": resp.raw_content})
            convo.append({"role": "user",
                          "content": _tool_results_block(resp, user_id=user_id, db=db)})
            continue

        parsed = resp.parsed
        if parsed is None and resp.text:
            try:
                parsed = json.loads(resp.text)
            except json.JSONDecodeError as e:
                raise CoachError(f"невалидный JSON от LLM: {e}") from e
        if parsed is None:
            raise CoachError(f"пустой ответ LLM (stop_reason={resp.stop_reason})")
        try:
            return CoachTurn.model_validate(parsed), usage_total
        except ValidationError as e:
            raise CoachError(f"CoachTurn не прошёл валидацию: {e}") from e

    raise CoachError(
        f"превышен лимит tool-итераций ({COACH_MAX_TOOL_ITERATIONS})")
