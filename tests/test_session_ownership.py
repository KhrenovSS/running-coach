# Гвард владения БД-сессией (Session ownership guard — BACKLOG #231, Этап 6)
#
# SessionLocal() разрешён ТОЛЬКО в композиционных корнях. Сервисы/репозитории
# получают db параметром — свои сессии не открывают (detached-объекты, рваные
# транзакции). Новый вызов SessionLocal() вне списка = осознанное решение:
# добавь файл сюда ТОЛЬКО если это действительно новый композиционный корень.
# (SessionLocal() is allowed only in composition roots; services take db as a param.)

from pathlib import Path

SRC = Path(__file__).parent.parent / "src"

# Композиционные корни (Composition roots)
ALLOWED = {
    "domain/models/base.py",        # канонический get_db + инфраструктура
    "startup.py",                   # bootstrap приложения
    "services/sync/orchestrator.py",  # корень цикла синхронизации (web + auto)
    "services/telegram_notify.py",  # fire-and-forget из фоновых контекстов (документированное исключение)
    "telegram/utils.py",            # корень telegram-хендлеров (get_user)
    "telegram/sync_runner.py",      # корень синка из бота
}
ALLOWED_PREFIXES = (
    "telegram/handlers/",  # хендлеры бота — каждый владеет своей сессией
    "telegram/jobs/",      # фоновые джобы бота
)


def test_sessionlocal_only_in_composition_roots():
    violations = []
    for path in SRC.rglob("*.py"):
        rel = str(path.relative_to(SRC))
        if "SessionLocal()" not in path.read_text(encoding="utf-8"):
            continue
        if rel in ALLOWED or rel.startswith(ALLOWED_PREFIXES):
            continue
        violations.append(rel)
    assert not violations, (
        f"SessionLocal() вне композиционных корней: {violations}. "
        f"Передай db параметром или осознанно расширь allowlist в этом тесте."
    )
