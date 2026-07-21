# Fixes Directory

Директория для отслеживания исправлений багов в рамках многоагентного workflow.

## Структура

```
fixes/
├── template/
│   ├── approach.md    — шаблон для архитектора
│   └── review.md      — шаблон для ревьювера
├── 001/
│   ├── approach.md    — анализ бага от @architect
│   └── review.md      — ревью от @reviewer
├── 002/
│   ├── approach.md
│   └── review.md
└── ...
```

## Workflow

1. **Создать директорию** для бага: `fixes/001/`
2. **@architect** анализирует баг → создает `approach.md`
3. **@coder** исправляет баг на основе `approach.md`
4. **@tester** пишет тесты для исправления
5. **@reviewer** проверяет изменения → создает `review.md`
6. **@devops** обеспечивает прохождение CI
7. **Commit + Push**

## Именование директорий

Используй порядковые номера или ID из BACKLOG.md:
- `fixes/001/` — первый баг
- `fixes/002/` — второй баг
- `fixes/BACKLOG-123/` — баг из BACKLOG.md с ID 123

## Шаблоны

Смотри `fixes/template/` для шаблонов approach.md и review.md.
