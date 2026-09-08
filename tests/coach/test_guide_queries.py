# Тесты запросов к базе знаний (guide queries) — E2.1: гайды Швеца 47–50 (07.09.2026)
# Проверяем, что новые темы находятся поиском, а старые гварды (боль → колено) не сдвинулись.

from src.coach.knowledge.loader import (
    key_rules_digest,
    plan_guides_queries,
    review_guides_queries,
    search,
)
from src.coach.turn_context import _as_queries

DIGEST_LINES_MAX = 64  # ориентир DEV_PLAN E2.1: 16 гайдов × ≤4 правила в среднем (≤5 на гайд), кэшируемый system[0];
                       # 60 → 64 08.09.2026: два правила зимы в гайде 49


def _top_guide(query: str) -> str:
    return search(query, top_k=1)[0].guide


def test_shvets_guides_found_by_topic():
    """Каждый новый гайд — первый по своему запросу (each new guide wins its query)."""
    assert _top_guide("ходьба бег новичок").startswith("47_")
    assert _top_guide("соревнование гонка раскладка").startswith("48_")
    assert _top_guide("жара погода условия").startswith("49_")
    assert _top_guide("грипп перерыв болезнь").startswith("50_")


def test_knee_guide_still_wins_pain_query():
    """Регресс: боль → первым чанк гайда про колено, новые гайды его не вытесняют."""
    assert _top_guide("боль колено дискомфорт") == "30_knee_and_pain.md"


def test_key_rules_digest_within_budget():
    lines = key_rules_digest().splitlines()
    assert len(lines) <= DIGEST_LINES_MAX
    assert any(line.startswith("47_") and "walk_run_stage_weeks" in line for line in lines)
    assert any(line.startswith("50_") and "illness_pause" in line for line in lines)


def test_review_queries_add_heat_last():
    """Жара — третьим запросом: боль и тип тренировки при лимите чанков важнее."""
    queries = review_guides_queries({"type": "easy", "pain_level": 2},
                                    {"heat": {"heat_flag": True}})
    assert queries[0] == "боль колено дискомфорт"
    assert queries[-1] == "жара погода условия"
    assert len(queries) == 3
    # без флага жары — запроса нет (no heat flag → no heat query)
    assert "жара погода условия" not in review_guides_queries({"type": "easy"},
                                                             {"heat": {"heat_flag": False}})
    assert review_guides_queries({"type": "race"}, None) == ["соревнование гонка раскладка"]


def test_review_queries_add_cold_when_frost():
    """Зима (08.09.2026): cold_flag → запрос про мороз/ветер/снег/гололёд → гайд 49 Швеца;
    при одновременной жаре (невозможно, но) приоритет у heat; без флагов запроса нет."""
    queries = review_guides_queries({"type": "easy"}, {"heat": {"cold_flag": True, "heat_flag": False}})
    assert queries[-1] == "мороз ветер снег гололёд покрытие погода"
    assert _top_guide(queries[-1]).startswith("49_")
    assert len(review_guides_queries({"type": "easy"}, {"heat": {"cold_flag": False}})) == 1
    digest = key_rules_digest()
    assert "wind_below_zero_more_dangerous_than_frost" in digest


def test_plan_queries_switch_on_detraining_return():
    default = plan_guides_queries({"detraining_return": False})
    assert len(default) == 1 and "мезоцикл" in default[0]
    ret = plan_guides_queries({"detraining_return": True})
    assert len(ret) == 2
    # первый запрос → гайд 47 (ходьба→бег), второй → гайд 61 (план возврата в % от пика)
    assert _top_guide(ret[0]).startswith("47_")
    assert _top_guide(ret[1]).startswith("61_")
    assert plan_guides_queries(None) == default


def test_as_queries_accepts_str_or_list():
    assert _as_queries(None) == []
    assert _as_queries("") == []
    assert _as_queries("один") == ["один"]
    assert _as_queries(["a", "b"]) == ["a", "b"]
