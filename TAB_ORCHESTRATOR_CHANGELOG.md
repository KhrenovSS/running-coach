# TAB Orchestrator — Tracer изменений

## Цель
Реализовать 3 TAB-оркестратора в opencode: Build, Plan, Orchestrator.

## Что должно работать
- Клавиша **TAB** переключает между Build → Plan → Orchestrator
- Build: `opencode/big-pickle`, все инструменты
- Plan: `opencode/big-pickle`, только чтение (edit=bash=deny)
- Orchestrator: `opencode/deepseek-v4-pro`, координация (task/bash/git)

## Структура файлов для работы TAB

```
.opencode/agents/
  orchestrator.md   — mode: primary (третий TAB)
  architect.md      — mode: subagent
  coder.md          — mode: subagent
  tester.md         — mode: subagent
  reviewer.md       — mode: subagent
  devops.md         — mode: subagent

opencode.json       — переопределение build/plan (модели, permissions)
```

---

## Сессия 1 (21.07.2026)

### Что сделано
1. Создан этот CHANGELOG
2. Прочитаны все agent-файлы — orchestrator.md уже `mode: primary` ✅
3. Прочитаны architect.md, coder.md, tester.md — `mode: subagent` ✅
4. opencode.json текущий — **ПУСТОЙ** (только schema)

### Ключевое открытие
**orchestrator.md уже имеет `mode: primary`** — это значит он уже должен быть доступен как TAB в opencode. Проблема НЕ в markdown-файлах агентов.

### Проблема
opencode.json пустой — Build и Plan используются как встроенные с дефолтными настройками.
Нужно: переопределить `build` и `plan` в opencode.json для настройки моделей и permissions.

### Следующий шаг
Обновить opencode.json с agent-секцией.

---

## Сессия 2 (21.07.2026) — ПРИМЕНЕНИЕ ✅

### Изменения
- [x] opencode.json: добавлены `agent.build` и `agent.plan` с моделями и permissions

### Верификация
- [x] python -c "import json; json.load(open('opencode.json'))" — JSON валиден ✅
- [x] Все markdown-агенты на месте (6 файлов) ✅
- [x] orchestrator.md: `mode: primary` ✅
- [x] Все subagent-файлы: `mode: subagent` ✅

### Итоговая структура TAB

| TAB | Источник | Модель | Роль |
|-----|----------|--------|------|
| **Build** | opencode.json | `opencode/big-pickle` | Разработка (все инструменты) |
| **Plan** | opencode.json | `opencode/big-pickle` | Анализ (read-only) |
| **Orchestrator** | `.opencode/agents/orchestrator.md` | `opencode/deepseek-v4-pro` | Координация (task + git bash) |

### Субагенты (вызываются через @mention или task)

| Агент | Модель | Права |
|-------|--------|-------|
| @architect | `opencode/deepseek-v4-pro` | read, grep, glob |
| @coder | `opencode/deepseek-v4-pro` | read, edit, bash, grep, glob |
| @tester | `opencode/big-pickle` | read, edit, bash, grep, glob |
| @reviewer | `opencode/deepseek-v4-pro` | read, grep, glob |
| @devops | `opencode/deepseek-v4-pro` | read, edit, bash, grep, glob |

### Что нужно для проверки
**Перезапустить opencode** в директории проекта (`cd /home/nimda/projects/running-coach && opencode`), затем нажать TAB и убедиться что появятся 3 агента: Build, Plan, Orchestrator.

### Почему раньше не работало (анализ)
1. opencode.json был пустой — Build/Plan работали с дефолтными настройками
2. orchestrator.md уже имел `mode: primary` — но без переопределения Build/Plan в opencode.json TAB мог не показывать третий агент
3. Предыдущие сессии могли не записывать изменения в файл (ошибка инструмента write)

### Результат
Запись в opencode.json применена. Для активации — **перезапуск opencode в терминале**.
