# Стабильность промпта — ключ к prompt cache (Prompt stability) — DEV_PLAN §8
import json
import re

from src.coach.llm.prompts import build_messages, build_system_blocks, build_today_block
from src.coach.tools.registry import anthropic_tools

PROFILE = {"age": 40, "max_hr": 177, "goal_type": "general", "goal_target": None,
           "sport_level": "intermediate", "weight_kg": 75.0}


def test_system_blocks_byte_stable():
    """Два вызова → побайтно одинаковые system-блоки (byte-stable cached blocks)."""
    a = build_system_blocks(PROFILE)
    b = build_system_blocks(PROFILE)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_cache_control_placement():
    """cache_control ровно на двух блоках, оба ДО волатильной части."""
    blocks = build_system_blocks(PROFILE)
    assert len(blocks) == 2
    assert all(b["cache_control"] == {"type": "ephemeral"} for b in blocks)


def test_no_volatile_content_in_system():
    """В system — ни дат, ни времени, ни UUID (no dates/times/uuids in system)."""
    text = " ".join(b["text"] for b in build_system_blocks(PROFILE))
    assert not re.search(r"\d{4}-\d{2}-\d{2}", text)      # ISO-даты
    assert not re.search(r"\d{2}:\d{2}:\d{2}", text)      # время
    assert not re.search(r"[0-9a-f]{8}-[0-9a-f]{4}", text)  # UUID


def test_today_lives_only_in_last_message():
    """Дата — только в последнем user-блоке (the date only in the last block)."""
    today = build_today_block({"x": 1}, {"y": 2}, "2026-08-23 21:40 (Europe/Moscow)")
    messages = build_messages([{"role": "user", "content": "старое"},
                               {"role": "assistant", "content": "ответ"}],
                              today, "вопрос")
    assert "2026-08-23" in messages[-1]["content"]
    assert all("2026-08-23" not in m["content"] for m in messages[:-1])


def test_tool_definitions_stable():
    """Определения tools стабильны между вызовами (stable tool definitions)."""
    a = json.dumps(anthropic_tools(), sort_keys=True)
    b = json.dumps(anthropic_tools(), sort_keys=True)
    assert a == b
    # и не содержат волатильного
    assert not re.search(r"\d{4}-\d{2}-\d{2}", a)
