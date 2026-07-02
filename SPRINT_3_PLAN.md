# Спринт 3 — Декомпозиция main.py + Jinja2 + pydantic-settings

## Цель
Сократить `main.py` с 2776 → ~50 строк, разложив код по пакетам.

## Перед началом работы
1. Прочитать `AGENTS.md` — правила кодирования, комментарии, коммиты
2. Прочитать `docs/CODE_GUIDELINES.md`
3. Прочитать `README.md` — актуальное состояние проекта

## Статус работ

- [x] **Шаг 0 — Подготовка**
  - [x] Создать директории: `src/web/templates/`, `src/web/static/`, `src/web/routes/`
  - [x] Установить `jinja2` если нет в зависимостях
  - [x] Проверить `git status` — рабочий репозиторий, ветка `main`

- [x] **Шаг 1 — Jinja2-шаблоны (HTML из main.py)**
  - [x] 1.1 Создать `src/web/templates/base.html` — базовый каркас (DOCTYPE, head, style, scripts)
  - [x] 1.2 Создать `src/web/templates/login.html` — из строк 1221–1261
  - [x] 1.3 Создать `src/web/templates/register.html` — из строк 1278–1321
  - [x] 1.4 Создать `src/web/templates/index.html` — из MAIN_HTML (строки 451–968)
  - [x] 1.5 Создать `src/web/templates/session.html` — из SESSION_HTML (строки 970–1082)
  - [x] 1.6 Создать `src/web/templates/settings.html` — из SETTINGS_PAGE (строки 1084–1139)
  - [ ] 1.7 Создать `src/web/static/styles.css` — собрать весь CSS из шаблонов
  - [x] 1.8 В main.py: подключить `Jinja2Templates`, заменить `HTMLResponse(f"""...""")` на `templates.TemplateResponse()`
  - [x] 1.9 Проверить: все страницы открываются, JS/графики работают
  - [x] 1.10 COMMIT: "Шаг 1: HTML вынесен в Jinja2-шаблоны"

- [x] **Шаг 2 — Выделение сервисов (бизнес-логика из main.py)**
  - [x] 2.1 Создать `src/services/telegram_notify.py` — `telegram_notify()` (бывш. `_telegram_notify`)
  - [x] 2.2 Создать `src/services/stats.py` — `calc_stats()`, `zone_ranges()`, `render_zone_bars()`, `render_type_row()`, `fmt_duration()`, `build_nav_html()`, `MONTHS_RU`, `MONTHS_RU_SHORT`, `ZONE_COLORS`
  - [x] 2.3 Создать `src/services/recovery_view.py` — `hrv_status()`, `tired_label()`, `readiness_label()`, `load_label()` (бывш. `_hrv_status`, `_tired_label`, `_readiness_label`, `_load_label`)
  - [x] 2.4 Создать `src/services/coros_sync_auto.py` — `_auto_sync_status`, `_auto_sync_status_lock`, `health_sync_interval`, `activity_sync_interval`, `update_last_health_sync()`, `save_dashboard_data()`, `auto_sync_health()`, `auto_sync_health_inner()`, `auto_sync_activities()`, `auto_sync_activities_inner()`
  - [x] 2.5 В main.py: заменить вызовы на импорты из сервисов; убраны префиксы `_` у глобальных переменных и функций
  - [x] 2.6 Проверить: `telegram_notify`, статистика, автосинхронизация работают (импорты без ошибок)
  - [x] 2.7 COMMIT: "Шаг 2: бизнес-логика вынесена в src/services/"

- [x] **Шаг 3 — Выделение роутов (API endpoints из main.py)**
  - [x] 3.1 Создать `src/web/routes/__init__.py` — `web_router = APIRouter()`
  - [x] 3.2 Создать `src/web/routes/pages.py` — `GET /`, `GET /session/{id}`, `GET /settings`, `POST /session/{id}/delete`, `POST /settings` + `render_page()` (её логика)
  - [x] 3.3 Создать `src/web/routes/uploads.py` — `POST /upload`, `POST /upload/confirm`, `POST /upload/confirm_deleted`
  - [x] 3.4 Создать `src/web/routes/coros.py` — `POST /coros/sync`, `POST /coros/sync/health`, `GET /coros/sync/status/{task_id}`
  - [x] 3.5 Создать `src/web/routes/logs.py` — `GET /logs`
  - [x] 3.6 В main.py: `app.include_router(web_router)` вместо декораторов
  - [x] 3.7 Перенести глобальное состояние `_pending`, `_sync_tasks`, `_AUTO_SYNC_LOCK`, `TRAINING_TYPES_RU` в `src/web/state.py`; `templates` в `src/deps.py`
  - [x] 3.8 Проверить: все 14 роутов загружаются (7 pages + 3 uploads + 3 coros + 1 logs)
  - [x] 3.9 COMMIT: "Шаг 3: роуты вынесены в src/web/routes/"

- [x] **Шаг 4 — Выделение scheduler + startup**
  - [x] 4.1 Создать `src/scheduler.py` — `AutoSyncScheduler` (класс-одиночка с `_loop`, `start/stop`)
  - [x] 4.2 Создать `src/startup.py` — `create_app()` — factory-функция: инициализация Jinja2Templates, регистрация роутов, startup-событие, init_db, alembic, scheduler
  - [x] 4.3 Перенести `startup()` из main.py в `src/startup.py`
  - [x] 4.4 main.py сокращён до 7 строк
  - [x] 4.5 Проверить: `from main import app` работает
  - [x] 4.6 Проверить `run_telegram_bot.py` — не сломался
  - [x] 4.7 COMMIT: "Шаг 4: scheduler и startup выделены, main.py 7 строк"

- [ ] **Шаг 5 — pydantic-settings (единая конфигурация)**
  - [ ] 5.1 Создать `src/config/settings.py` — класс `Settings(BaseSettings)` с полями из `.env`
  - [ ] 5.2 Заменить `CONFIG` dataclass на `settings` из pydantic-settings
  - [ ] 5.3 Обновить `src/config/__init__.py` — экспортировать `settings`
  - [ ] 5.4 Все импорты `from src.config import CONFIG` → `from src.config import settings`
  - [ ] 5.5 Убрать автогенерацию ключа в `src/crypto.py` — падать с ошибкой если `COROS_CRED_KEY` не задан
  - [ ] 5.6 Проверить: `uvicorn main:app` стартует, переменные окружения читаются
  - [ ] 5.7 COMMIT: "Шаг 5: pydantic-settings вместо dataclass CONFIG"

- [ ] **Шаг 6 — Финальная уборка**
  - [ ] 6.1 Удалить `get_settings()` если остался (всё через `User`)
  - [ ] 6.2 Удалить `src/logger.py` (legacy-файл, всё через `src/utils/logger.py`)
  - [ ] 6.3 Проверить `src/exceptions.py` — все исключения используются
  - [ ] 6.4 `wc -l main.py` → < 60 строк
  - [ ] 6.5 `grep -rn "html\s*+=\s*f" main.py src/` → 0 (нет f-строк HTML)
  - [ ] 6.6 Обновить `CHANGELOG.md`
  - [ ] 6.7 Обновить `AGENTS.md` — секция «Текущее состояние»
  - [ ] 6.8 COMMIT: "Шаг 6: финальная уборка, main.py очищен"

## Критические проверки после каждого шага

- [ ] `GET /` — главная страница открывается, тренировки видны
- [ ] `GET /session/{id}` — детальная страница с графиком
- [ ] `GET /settings` — настройки открываются
- [ ] `GET /login` — страница входа
- [ ] `POST /upload` — загрузка TCX/FIT работает
- [ ] `POST /settings` — сохранение настроек
- [ ] `POST /session/{id}/delete` — удаление тренировки
- [ ] `GET /logs` — логи показываются
- [ ] `POST /coros/sync` — синхронизация запускается
- [ ] `POST /coros/sync/health` — health sync запускается
- [ ] Автосинхронизация работает (фоновый поток)
- [ ] Telegram-бот не сломан (`run_telegram_bot.py`)
- [ ] `git status` — нет лишних файлов

## Ошибки и их решения

| Проблема | Решение |
|----------|---------|
| Jinja2 `{{` конфликтует с JS `{{` | Использовать `{% raw %}...{% endraw %}` в JS-блоках |
| Chart.js не отображается | Проверить пути к CDN в base.html, проверить `safe` фильтр |
| `render_page()` использует глобальные переменные | Передать через параметры или контекст шаблона |
| `_pending`/`_sync_tasks` не доступны из роутов | Вынести в `src/web/state.py` как модульные переменные |
| Конфликт импортов после переноса | Использовать `from src.web.state import ...` |
| `alembic upgrade head` не видит модели | Проверить `target_metadata = Base.metadata` в `alembic/env.py` |

## После завершения спринта

```bash
# Проверка: main.py должен быть < 60 строк
wc -l main.py

# Проверка: нет inline HTML
grep -rn "html\s*+=\s*f" main.py src/ || echo "OK — нет inline HTML"

# Проверка: HTML только в .html файлах
find src/web/templates/ -name "*.html" | wc -l

# Финальный пуш
set -a && source .env && set +a && cd /home/nimda/projects/running-coach && git push "https://KhrenovSS:${GITHUB_TOKEN}@github.com/KhrenovSS/running-coach.git" main
```
