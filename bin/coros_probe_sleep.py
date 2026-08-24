#!/usr/bin/env python3
# Разведка сна в Coros API (Sleep field recon) — DEV_PLAN §9 D8, стоп-поинт.
#
# READ-ONLY: дёргает те же endpoint'ы, что и штатный синк (dashboard/query,
# analyse/dayDetail/query), и печатает ПОЛНЫЙ JSON — чтобы увидеть, отдаёт ли
# API длительность/фазы/оценку сна (штатный синк берёт только whitelist-ключи).
# В БД НЕ пишет. Запуск — из контейнера бота или с хоста с DATABASE_URL:
#   docker compose exec bot python bin/coros_probe_sleep.py
# (Read-only probe of the endpoints the regular sync already calls.)

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, ".")

from src.models import SessionLocal, WatchCredential  # noqa: E402
from src.services.sync.utils import _make_client  # noqa: E402


async def main() -> None:
    db = SessionLocal()
    try:
        cred = db.query(WatchCredential).filter(
            WatchCredential.brand == "coros").first()
        if cred is None:
            print("Нет coros-креденшела в БД (no coros credential)")
            return
        client = await _make_client(cred)
        if client is None:
            print("Не удалось создать клиента (client init failed)")
            return

        today = datetime.now(timezone.utc).date()
        start = (today - timedelta(days=2)).strftime("%Y%m%d")
        end = today.strftime("%Y%m%d")

        print("=== dashboard/query (полный ответ) ===")
        dashboard = await client.get_dashboard()
        print(json.dumps(dashboard, ensure_ascii=False, indent=1)[:8000])

        print("\n=== analyse/dayDetail/query", start, "-", end, "(полный ответ) ===")
        days = await client.get_daily_metrics(start, end)
        print(json.dumps(days, ensure_ascii=False, indent=1)[:12000])

        print("\n=== ключи с упоминанием sleep (sleep-related keys) ===")
        def walk(obj, path=""):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    p = f"{path}.{k}"
                    if "sleep" in k.lower():
                        print(p, "=", json.dumps(v, ensure_ascii=False)[:200])
                    walk(v, p)
            elif isinstance(obj, list):
                for i, v in enumerate(obj[:3]):
                    walk(v, f"{path}[{i}]")
        walk({"dashboard": dashboard, "days": days})
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
