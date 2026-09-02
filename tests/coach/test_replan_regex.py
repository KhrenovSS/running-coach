# Триггер составления плана недели в тексте (compose-plan regex) — 02.09.2026:
# «сформируй план пробежек на эту неделю» уходило в показ сохранённого плана, а не в /plan.
import pytest

from src.telegram.handlers.coach import _REPLAN_RE


@pytest.mark.parametrize("text", [
    "перепланируй",
    "Давай перепланируем неделю",
    "составь план на неделю",
    "сформируй план пробежек на эту неделю",
    "пересобери план",
    "нужен новый план на неделю",
    "план на следующую неделю",
])
def test_compose_requests_match(text):
    assert _REPLAN_RE.search(text)


@pytest.mark.parametrize("text", [
    "какой план на неделю?",
    "покажи план",
    "что у меня в плане на пятницу",
    "план на неделю не нравится",
])
def test_show_requests_do_not_match(text):
    assert not _REPLAN_RE.search(text)
