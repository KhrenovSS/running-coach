#!/usr/bin/env python3
# Разовый backfill avg_pace для исторических тренировок (One-off avg_pace backfill).
#
# Новые тренировки (upload + sync) уже получают avg_pace из process_trackpoints.
# Старые строки (созданные до появления колонки avg_pace) имеют avg_pace=NULL —
# этот скрипт заполняет их производным значением duration_minutes / total_distance_km.
#
# БЕЗОПАСНОСТЬ: только дописывает NULL-значения (не перезаписывает существующие,
# не удаляет данные). Идемпотентно — повторный запуск ничего не меняет.
#
# Запуск (в контейнере app или с заданным DATABASE_URL):
#   docker compose exec app python bin/backfill_avg_pace.py
#   # или локально:
#   DATABASE_URL=postgresql://... python bin/backfill_avg_pace.py

import sys
from pathlib import Path

# Скрипт запускается как `python bin/backfill_avg_pace.py` → sys.path[0] = bin/, а не корень.
# Добавляем корень проекта, чтобы `src` импортировался при любом cwd.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.models import SessionLocal, TrainingSession  # noqa: E402


def backfill_avg_pace() -> int:
    db = SessionLocal()
    updated = 0
    try:
        rows = db.query(TrainingSession).filter(
            TrainingSession.avg_pace.is_(None),
            TrainingSession.total_distance_km.isnot(None),
            TrainingSession.total_distance_km > 0,
            TrainingSession.duration_minutes.isnot(None),
        ).all()
        for s in rows:
            s.avg_pace = round(s.duration_minutes / s.total_distance_km, 2)
            updated += 1
        db.commit()
        return updated
    finally:
        db.close()


if __name__ == "__main__":
    n = backfill_avg_pace()
    print(f"avg_pace backfill: обновлено строк / rows updated = {n}")
