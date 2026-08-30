# LLM-мост через подписку Claude Code (Subscription LLM bridge) — DEV_PLAN §8 (bridge mode)
#
# Мини-сервис на ХОСТЕ (вне контейнеров): принимает запрос коуча и вызывает
# headless Claude Code (`claude -p`), авторизованный подпиской владельца.
# Инструменты Claude Code отключены (--tools ""), один ход (--max-turns 1) —
# это чистый вызов модели, не агент. Tool-цикл коуча в этом режиме неактивен;
# контекст компенсирован обогащением (orchestrator инлайнит историю/сводки).
#
# Запуск: systemd-юнит running-coach-llm-bridge.service (порт 8765).
# Авторизация: заголовок X-Bridge-Token == env COACH_LLM_BRIDGE_TOKEN.
# (Host-side bridge: coach requests → headless Claude Code under the owner's
# subscription. No tools, single turn — a plain model call, not an agent.)

from __future__ import annotations

import base64
import binascii
import json
import os
import shutil
import subprocess
import tempfile

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

BRIDGE_MODEL = os.getenv("BRIDGE_MODEL", "sonnet")   # sonnet бережёт лимиты подписки
BRIDGE_TIMEOUT = int(os.getenv("BRIDGE_TIMEOUT", "120"))
BRIDGE_TOKEN = os.getenv("COACH_LLM_BRIDGE_TOKEN", "")
MAX_PROMPT_CHARS = 120_000   # защита от раздутого входа (input size guard)
MAX_IMAGE_B64_CHARS = 20_000_000   # ~15 МБ картинки после base64 (image size guard)

app = FastAPI(title="coach-llm-bridge", docs_url=None, redoc_url=None)


class CompleteRequest(BaseModel):
    system_text: str = Field(max_length=MAX_PROMPT_CHARS)
    messages: list[dict] = Field(default_factory=list)   # [{"role","content"}]
    effort: str = "low"          # принимается для совместимости; CLI сам решает
    max_tokens: int = 4000       # то же (accepted for interface compat)


class VisionRequest(BaseModel):
    # Картинка (base64) читается через Read-tool из временного файла на хосте:
    # headless Claude Code мультимодален, но по стандартному пути видит файл.
    # (Image is read via the Read tool from a host temp file — the bridge can't
    #  pass raw bytes to `claude -p` otherwise.)
    image_b64: str = Field(max_length=MAX_IMAGE_B64_CHARS)
    prompt: str = Field(max_length=MAX_PROMPT_CHARS)
    system_text: str = Field(default="", max_length=MAX_PROMPT_CHARS)
    model: str = ""              # пусто → BRIDGE_MODEL
    max_turns: int = Field(default=3, ge=2, le=6)  # ≥2: ход на Read + ход на ответ


def _flatten(messages: list[dict]) -> str:
    """История → плоский текст для single-turn вызова (history → flat prompt)."""
    parts = []
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        if not isinstance(content, str):   # tool-блоков в мосте не бывает — страховка
            content = json.dumps(content, ensure_ascii=False)
        label = "Подопечный" if role == "user" else "Тренер (твой прошлый ответ)"
        parts.append(f"[{label}]\n{content}")
    return "\n\n".join(parts)[:MAX_PROMPT_CHARS]


@app.get("/health")
def health():
    return {"ok": True, "model": BRIDGE_MODEL}


@app.post("/complete")
def complete(req: CompleteRequest, x_bridge_token: str = Header(default="")):
    if not BRIDGE_TOKEN or x_bridge_token != BRIDGE_TOKEN:
        raise HTTPException(status_code=401, detail="bad bridge token")

    prompt = _flatten(req.messages)
    cmd = ["claude", "-p",
           "--output-format", "json",
           "--max-turns", "1",
           "--tools", "",
           "--model", BRIDGE_MODEL,
           "--system-prompt", req.system_text]
    try:
        proc = subprocess.run(cmd, input=prompt, capture_output=True,
                              text=True, timeout=BRIDGE_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="claude CLI timeout")
    if proc.returncode != 0:
        # stderr без содержимого запроса (no request content in logs/errors)
        raise HTTPException(status_code=502,
                            detail=f"claude CLI exit={proc.returncode}: "
                                   f"{(proc.stderr or '')[:200]}")
    try:
        envelope = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise HTTPException(status_code=502, detail="claude CLI: non-JSON envelope")
    if envelope.get("is_error"):
        raise HTTPException(status_code=502,
                            detail=f"claude CLI error: {str(envelope)[:200]}")

    return _envelope_to_response(envelope)


def _envelope_to_response(envelope: dict) -> dict:
    usage = envelope.get("usage", {}) or {}
    return {
        "text": envelope.get("result", ""),
        "usage": {
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
            "cache_read_input_tokens": usage.get("cache_read_input_tokens", 0),
            "cache_creation_input_tokens": usage.get("cache_creation_input_tokens", 0),
        },
        "cost_usd": envelope.get("total_cost_usd"),
    }


@app.post("/vision")
def vision(req: VisionRequest, x_bridge_token: str = Header(default="")):
    """Прочитать изображение и вернуть ответ модели (image → model via Read tool).

    Картинка кладётся во временный каталог (0700), Read-tool разрешён только на
    него (--add-dir), остальные инструменты выключены. Файл удаляется всегда.
    """
    if not BRIDGE_TOKEN or x_bridge_token != BRIDGE_TOKEN:
        raise HTTPException(status_code=401, detail="bad bridge token")
    try:
        raw = base64.b64decode(req.image_b64, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=400, detail="bad image_b64")

    tmpdir = tempfile.mkdtemp(prefix="coach_vision_")
    os.chmod(tmpdir, 0o700)
    img_path = os.path.join(tmpdir, "image.png")
    try:
        with open(img_path, "wb") as f:
            f.write(raw)
        prompt = f"Изображение находится по пути: {img_path}\n\n{req.prompt}"
        cmd = ["claude", "-p",
               "--output-format", "json",
               "--max-turns", str(req.max_turns),
               "--allowedTools", "Read",
               "--add-dir", tmpdir,
               "--model", req.model or BRIDGE_MODEL]
        if req.system_text:
            cmd += ["--system-prompt", req.system_text]
        try:
            proc = subprocess.run(cmd, input=prompt, capture_output=True,
                                  text=True, timeout=BRIDGE_TIMEOUT)
        except subprocess.TimeoutExpired:
            raise HTTPException(status_code=504, detail="claude CLI timeout")
        if proc.returncode != 0:
            raise HTTPException(status_code=502,
                                detail=f"claude CLI exit={proc.returncode}: "
                                       f"{(proc.stderr or '')[:200]}")
        try:
            envelope = json.loads(proc.stdout)
        except json.JSONDecodeError:
            raise HTTPException(status_code=502, detail="claude CLI: non-JSON envelope")
        if envelope.get("is_error"):
            raise HTTPException(status_code=502,
                                detail=f"claude CLI error: {str(envelope)[:200]}")
        return _envelope_to_response(envelope)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
