# Work Plan: Оценка тренировки через веб-форму

## Цель
1. Оценка (0–10) всегда видна на странице детального просмотра тренировки (сейчас скрыта, если нет оценки)
2. Возможность создать/изменить оценку через веб-форму (сейчас — только через Telegram)

## План

### Шаг 1 — `src/web/routes/pages.py`: новый endpoint `POST /session/{session_id}/feedback`
- [x] Импортировать `AuditService` (уже импортирован)
- [x] Upsert `TrainingFeedback` (создать если нет, обновить если есть)
- [x] Аудит через `AuditService`
- [x] Редирект обратно на `/session/{session_id}`

### Шаг 2 — `src/web/templates/session.html`: блок оценки
- [x] Заменить `{% if rating_display %}` на безусловный блок
- [x] Если оценки нет: «📝 Оценить тренировку» + select 0–10 + кнопка «Сохранить»
- [x] Если оценка есть: «✏️ Изменить оценку» + select (текущее значение) + кнопка «Сохранить»
- [x] Форма отправляется `POST` на `/session/{session_id}/feedback`

### Шаг 3 — `src/web/routes/pages.py`: передать `session_id` и `rating` в шаблон
- [x] В `session_detail()` передать `session_id` и `rating` (int или None) в контекст шаблона

### Шаг 4 — `AGENTS.md`: обновить статус
- [x] Добавлена запись о выполненной работе

### Шаг 5 — `CHANGELOG.md`: запись о доработке
- [x] Добавлена запись

### Шаг 6 — git commit
- [ ] git add + commit + push
