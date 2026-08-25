#!/usr/bin/env python3
# Дистилляция книги в гайды базы знаний коуча (Book → guides distillation) — E1 (#245)
#
# Офлайн-инструмент, по одной книге за прогон. LLM — через мост подписки
# (bin/coach_llm_bridge.py, :8765). Черновики пишутся в books/_distilled/<книга>/
# для РУЧНОГО РЕВЬЮ (стоп-поинт E1) — в src/coach/knowledge/guides/ переносить
# только после ревью. Конспект — своими словами, НЕ цитаты (копирайт).
#
# Запуск (с хоста, зависимости: pip install -e ".[distill]"):
#   COACH_LLM_BRIDGE_TOKEN=... python bin/distill_books.py books/<файл> [--windows N]
#   (токен и модель подхватываются из .env.bridge автоматически)

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
BRIDGE_URL = "http://127.0.0.1:8765"
WINDOW_WORDS = 12_000        # окно map-прохода (words per map window)
MAX_TOKENS_MAP = 2_000
MAX_TOKENS_REDUCE = 8_000
FILE_MARKER = re.compile(r"^===FILE:\s*(\S+)\s*===\s*$", re.MULTILINE)

GUIDE_FORMAT = """Формат guide-файла (СТРОГО):
---
topic: <короткий slug темы>
title: <заголовок по-русски>
source: конспект книги «{book}»
status: distilled
tags: <5-8 тегов через запятую, по-русски, в нижнем регистре>
key_rules:
  <snake_case_имя>: <число или простое значение>
  (3-5 числовых правил, применимых в тренировках: проценты, дни, пороги)
---

## <Тема раздела>

<проза СВОИМИ СЛОВАМИ, максимум 350 слов на раздел, 3-6 разделов на файл>
"""

MAP_PROMPT = """Ты помогаешь ИИ-тренеру по бегу для ЛЮБИТЕЛЯ (цель: здоровье,
медленный устойчивый прогресс, возврат после травмы колена). Ниже фрагмент книги
«{book}» ({idx}/{total}). Выпиши КОНСПЕКТ-ЗАМЕТКИ: практические принципы, числовые
правила (проценты объёмов, схемы недель, пороги, темпы относительно порогового),
структуры готовых тренировочных планов (если есть — с числами по неделям).
Пропускай воду, истории и элитную специфику. Своими словами, НЕ цитируй.
Формат: маркированный список, ≤40 пунктов.

ФРАГМЕНТ:
{text}"""

REDUCE_PROMPT = """Ты собираешь базу знаний ИИ-тренера по бегу для любителя
(здоровье, медленный прогресс, колено после травмы). Ниже — конспект-заметки
всей книги «{book}». Сгенерируй 2-4 guide-файла в заданном формате: сгруппируй
заметки по темам (например: методика интенсивности, структура недели/плана,
восстановление, техника/травмы). Если в книге есть ГОТОВЫЕ тренировочные планы —
отдельный файл с именем 60_plans_*: недельные структуры таблицей, объёмы в
ПРОЦЕНТАХ от текущего недельного объёма бегуна (не абсолютные км).

Уже есть гайды (темы НЕ дублировать, только дополнять новым): аэробная база
(Лидьярд), правило 80/20, прогрессия 10% и цикл 3:1, светофор боли в колене.

{format}

Раздели файлы строками-маркерами вида:
===FILE: 4x_<slug>.md===
(имя: 40-59 — методика, 60-69 — планы; slug латиницей)

ЗАМЕТКИ:
{notes}"""


def _extract_text(path: Path) -> str:
    """Извлечь текст книги по расширению (extract text by extension)."""
    suffix = path.suffix.lower()
    if suffix in (".txt", ".md"):
        return path.read_text(encoding="utf-8", errors="ignore")
    if suffix == ".epub":
        try:
            from bs4 import BeautifulSoup
            from ebooklib import ITEM_DOCUMENT, epub
        except ImportError:
            sys.exit('Нужны зависимости: pip install -e ".[distill]"')
        book = epub.read_epub(str(path))
        parts = []
        for item in book.get_items_of_type(ITEM_DOCUMENT):
            parts.append(BeautifulSoup(item.get_content(), "html.parser")
                         .get_text(" ", strip=True))
        return "\n\n".join(parts)
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError:
            sys.exit('Нужны зависимости: pip install -e ".[distill]"')
        reader = PdfReader(str(path))
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
        if len(text.split()) < 500:
            sys.exit("PDF почти без текстового слоя (скан?) — нужен OCR, файл не годится")
        return text
    if suffix == ".fb2":
        import xml.etree.ElementTree as ET
        root = ET.parse(str(path)).getroot()
        # FB2 хранит картинки как base64 в <binary> (до ~90% «объёма»!).
        # Берём текст ТОЛЬКО из <body>; <binary>/<description> исключаем —
        # иначе окна забиваются мусором, и модель отклоняет их по AUP ([bio]).
        # (FB2 keeps images as base64 in <binary>; extract <body> text only.)
        def _localname(tag: str) -> str:
            return tag.rsplit("}", 1)[-1]
        bodies = [el for el in root if _localname(el.tag) == "body"]
        if not bodies:
            sys.exit("FB2 без <body> — структура не распознана")
        return "\n".join(" ".join(b.itertext()) for b in bodies)
    sys.exit(f"Неизвестный формат: {suffix} (поддержаны: epub, fb2, pdf, txt, md)")


def _load_bridge_token() -> str:
    import os
    token = os.getenv("COACH_LLM_BRIDGE_TOKEN", "")
    if token:
        return token
    env_bridge = ROOT / ".env.bridge"
    if env_bridge.exists():
        for line in env_bridge.read_text().splitlines():
            if line.startswith("COACH_LLM_BRIDGE_TOKEN="):
                return line.split("=", 1)[1].strip()
    sys.exit("Нет COACH_LLM_BRIDGE_TOKEN (env или .env.bridge)")


# Транзиентные сбои моста (мост шеллит headless Claude Code — редкие 502/таймауты).
# Retry с бэкоффом, чтобы одиночный сбой не ронял многочасовой прогон.
# (Transient bridge failures — retry with backoff so one blip won't kill a long run.)
_RETRYABLE_STATUS = {429, 502, 503, 504}
# Подписка троттлит бёрст тяжёлых вызовов. КЛЮЧЕВОЕ: повторять тяжёлый вызов
# в горячем окне бесполезно — это ПРОДЛЕВАЕТ троттлинг; окну нужна ТИШИНА.
# Поэтому в скрипте — один короткий ретрай (на редкий сетевой блип), а реальное
# восстановление даёт ТИХИЙ кулдаун во внешнем драйвере + чекпойнт _notes/.
# (Retrying a heavy call in a hot window keeps the throttle alive — the window
#  needs quiet. One short in-script retry; the driver's quiet cooldown recovers.)
_RETRY_BACKOFFS = (20,)  # секунды (seconds)
MAP_PACE_SECONDS = 12    # пауза между map-вызовами, сглаживает бёрст (inter-call pacing)


def _bridge_complete(token: str, system_text: str, user_text: str,
                     max_tokens: int) -> str:
    last_err: Exception | None = None
    for attempt in range(len(_RETRY_BACKOFFS) + 1):
        try:
            resp = httpx.post(f"{BRIDGE_URL}/complete",
                              json={"system_text": system_text,
                                    "messages": [{"role": "user", "content": user_text}],
                                    "effort": "medium", "max_tokens": max_tokens},
                              headers={"X-Bridge-Token": token}, timeout=300)
            resp.raise_for_status()
            return resp.json().get("text", "")
        except (httpx.HTTPStatusError, httpx.TransportError) as e:
            # Не ретраим неретраибельные HTTP-статусы (напр. 401/400).
            # (Do not retry non-retryable statuses like 401/400.)
            if (isinstance(e, httpx.HTTPStatusError)
                    and e.response.status_code not in _RETRYABLE_STATUS):
                raise
            last_err = e
            if attempt < len(_RETRY_BACKOFFS):
                delay = _RETRY_BACKOFFS[attempt]
                print(f"    ⏳ мост: {type(e).__name__}, повтор через {delay}s "
                      f"(попытка {attempt + 1}/{len(_RETRY_BACKOFFS)})...")
                time.sleep(delay)
    raise RuntimeError(f"Мост недоступен после ретраев: {last_err}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Дистилляция книги в гайды коуча")
    parser.add_argument("book", type=Path, help="файл книги в books/")
    parser.add_argument("--window-words", type=int, default=WINDOW_WORDS)
    args = parser.parse_args()

    text = _extract_text(args.book)
    words = text.split()
    print(f"Книга: {args.book.name}, слов: {len(words)}")
    token = _load_bridge_token()
    book_name = args.book.stem

    out_dir = ROOT / "books" / "_distilled" / book_name
    notes_dir = out_dir / "_notes"
    notes_dir.mkdir(parents=True, exist_ok=True)

    # Map: окна → конспект-заметки, с чекпойнтом на диск (map pass w/ checkpoint).
    # Каждое окно кэшируется в _notes/NNN.md → повторный прогон возобновляет
    # с места обрыва, а не теряет часы работы при троттлинге подписки.
    windows = [words[i:i + args.window_words]
               for i in range(0, len(words), args.window_words)]
    notes: list[str] = []
    for i, win in enumerate(windows, 1):
        cache = notes_dir / f"{i:03d}.md"
        if cache.exists() and cache.read_text(encoding="utf-8").strip():
            print(f"  map {i}/{len(windows)} — из кэша (cached)")
            notes.append(cache.read_text(encoding="utf-8"))
            continue
        print(f"  map {i}/{len(windows)} ({len(win)} слов)...")
        note = _bridge_complete(
            token, "Ты аккуратный конспектист спортивной литературы.",
            MAP_PROMPT.format(book=book_name, idx=i, total=len(windows),
                              text=" ".join(win)),
            MAX_TOKENS_MAP)
        cache.write_text(note, encoding="utf-8")
        notes.append(note)
        if i < len(windows):
            time.sleep(MAP_PACE_SECONDS)

    # Reduce: заметки → guide-файлы (reduce pass: notes → guide files)
    print("  reduce → guide-файлы...")
    result = _bridge_complete(
        token, "Ты редактор базы знаний бегового тренера.",
        REDUCE_PROMPT.format(book=book_name, notes="\n\n".join(notes),
                             format=GUIDE_FORMAT.format(book=book_name)),
        MAX_TOKENS_REDUCE)

    parts = FILE_MARKER.split(result)
    # parts: [преамбула, имя1, тело1, имя2, тело2, ...]
    written = []
    for name, body in zip(parts[1::2], parts[2::2]):
        out = out_dir / name.strip()
        out.write_text(body.strip() + "\n", encoding="utf-8")
        written.append(out)
    (out_dir / "_raw_notes.md").write_text("\n\n".join(notes), encoding="utf-8")
    if not written:
        print("⚠️ Маркеры файлов не найдены — сырой ответ в _raw_reduce.md")
        (out_dir / "_raw_reduce.md").write_text(result, encoding="utf-8")
        return
    print(f"Готово: {len(written)} черновиков в {out_dir} — РЕВЬЮ перед переносом "
          f"в src/coach/knowledge/guides/ (стоп-поинт E1).")
    for p in written:
        print("  -", p.name)


if __name__ == "__main__":
    main()
