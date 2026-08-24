# Константы LLM-слоя (LLM layer constants) — DEV_PLAN §8

COACH_MAX_TOKENS = 4000          # нестриминг, далеко от HTTP-таймаута
COACH_MAX_TOOL_ITERATIONS = 6    # потолок tool-циклов за ход
COACH_HISTORY_TURNS = 8          # окно истории диалога в промпте
COACH_MAX_TURNS_PER_DAY = 40     # дневной бюджет LLM-ходов
COACH_EFFORT_CHAT = "low"
COACH_EFFORT_PLAN = "medium"

# Обогащение today-блока (context enrichment) — DEV_PLAN §5
COACH_ENRICH_RECENT_LIMIT = 5    # последних тренировок в контексте хода
COACH_ENRICH_WEEKS = 4           # недель сводки в контексте хода
COACH_WEEKLY_REPORT_WEEKS = 8    # горизонт недельного отчёта (C8)
COACH_WEEKLY_REPORT_RECENT = 10  # тренировок в контексте недельного отчёта (C8)

# Цены claude-opus-5 за 1M токенов (prices per 1M tokens, USD)
PRICE_INPUT_PER_M = 5.0
PRICE_OUTPUT_PER_M = 25.0
PRICE_CACHE_READ_PER_M = 0.5     # ~0.1× входа
PRICE_CACHE_WRITE_PER_M = 6.25   # ~1.25× входа
