# BACKLOG — Running Coach

Парковка идей, фиксов и вопросов.  
**Правило:** заметил мелочь → строка сюда, обратно к задаче. Не чини «заодно».

| # | Тег | Описание | Файл / Источник | Статус |
|---|-----|----------|-----------------|--------|
| 1 | [Фикс] | AUDIT-006 Telegram TODO: `sync_runner.py` вызывает `sync_activities_for_user`/`sync_health_for_user` напрямую вместо `run_sync_for_user`. Миграция на `run_sync_for_user_all_brands(chat_id)`. | `src/telegram/sync_runner.py:8-12` | ⬜ Открыт |
| 2 | [Фикс] | AUDIT-003: Тестовое покрытие практически отсутствует (3 теста, 63 строки). Нужно ≥20 тестов. | `tests/` | ⬜ Sprint 10 |
| 3 | [Фикс] | AUDIT-004: `sync_service.py` God Object (702 строки). Разбить на sync_service + sync_health + sync_activities + sync_utils. | `src/services/sync_service.py` | ⬜ Sprint 11 |
| 4 | [Фикс] | AUDIT-005: `models.py` God Object (344 строки, 9+ моделей). Разделить по доменам в `src/domain/models/`. | `src/models.py` | ⬜ Sprint 11 |
| 5 | [Фикс] | AUDIT-008: Threading + asyncio anti-pattern. Scheduler — daemon thread, sync_service — `asyncio.run()` внутри синхронных функций. Планируется выделение sync в отдельный процесс. | `src/scheduler.py`, `src/services/sync_service.py` | ⬜ Отложено |
| 6 | [Фикс] | AUDIT-012: Type hints не везде. `mypy src/ --strict` не проходит. | Весь `src/` | ⬜ Отложено |
| 7 | [Фикс] | AUDIT-014: Сегментация привязана к км-блокам — `segment_by_km()` не работает для коротких интервалов (10×200м+600м). Замена на `segment_by_pace()`. | `src/parsers/segmentation.py` | ✅ Выполнено |
| 8 | [Идея] | Sprint 7: Admin panel — дашборд, управление пользователями, просмотр аудита, принудительный sync. Отложено до >1 пользователя. | PROJECT_AUDIT.md | ⬜ Отложено |
| 9 | [Идея] | Модуль аналитики — 8 этапов (Этап 0–7): каркас, аналитика, движок, база знаний, персонализация, LLM, планы, обратная связь. | `decision_module_design.md` | ⬜ Отложено |
| 10 | [Идея] | Sprint 13: Фильтр по типу тренировки на главной, общая дистанция/время за неделю/месяц. | PROJECT_AUDIT.md | ⬜ Отложен |
| 11 | [Идея] | Sprint 14: Multi-brand onboarding — выбор бренда при `/start`, заглушки для Polar/Garmin/Suunto. | PROJECT_AUDIT.md | ⬜ Отложен |
| 12 | [Идея] | Sprint 15: Факторы самочувствия — multi-select (ноги, дыхание, пульс, жара, недосып, стресс), адаптивные подсказки, хранение для аналитики. | PROJECT_AUDIT.md | ⬜ Отложен |
| 13 | [Идея] | Мобильное PWA (Progressive Web App). | README.md | ⬜ Идея |
| 14 | [Фикс] | `docs/ARCHITECTURE.md` устарел: описывает SQLite, `src/logger.py`, `src/telegram_bot.py`, не описывает `src/watch/`, `src/telegram/`, `src/services/`. | `docs/ARCHITECTURE.md` | ⬜ Открыт |
| 15 | [Вопрос] | AUDIT-008: выделять ли sync в отдельный процесс/контейнер или оставить `run_async_in_thread`? | `src/services/sync_service.py` | ⬜ Вопрос |
| 16 | [Фикс] | Telegram `sync_runner.py`: нужен `run_sync_for_user_all_brands(chat_id)` для объединения отчёта по всем брендам. | `src/telegram/sync_runner.py` | ⬜ Открыт |

---

*Создан: 13.07.2026 (Фаза D)*
