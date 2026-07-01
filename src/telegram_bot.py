# Telegram-бот для Running Coach (Telegram bot for Running Coach)
import asyncio
import logging
import os
import threading
import tempfile
from datetime import datetime, timedelta, date, time as dt_time
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, ConversationHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes,
)

from src.models import (
    SessionLocal, User, TrainingSession,
    DailyMetrics, WeightMeasurement, DeletedTraining, TrainingFeedback,
    get_user_by_telegram,
)
from src.crypto import encrypt, decrypt
from src.coros_client import CorosClient, CorosAuthError, CorosAPIError
from src.parsers.fit_parser import parse_fit
from src.logger import get_logger
from src.services.audit import AuditService
from src.services.auth import generate_telegram_login_token, hash_password

logger = get_logger("telegram_bot")


def _get_web_app_url() -> str:
    """Базовый URL веб-приложения (Web app base URL)"""
    return os.getenv("WEB_APP_URL", "http://localhost:8000").rstrip("/")


def _generate_login_link(db, user: User) -> str:
    """
    Сгенерировать одноразовую ссылку для входа/регистрации
    Generate single-use link for login or registration

    Если у пользователя нет password_hash — ссылка ведёт на /register.
    If user has no password_hash — link goes to /register.
    """
    token = generate_telegram_login_token(db, user)
    if user.password_hash:
        return f"{_get_web_app_url()}/auth/telegram?token={token}"
    return f"{_get_web_app_url()}/register?token={token}"

EMAIL, PASSWORD = range(2)
NEW_PASSWORD = 10  # состояние для /reset_password (state for /reset_password conversation)

TRAINING_TYPES_RU = {
    'interval': 'Интервальная',
    'long': 'Длинная',
    'recovery': 'Восстановительная',
    'tempo': 'Темповая',
}


def _send_message(token: str, chat_id: int, text: str, reply_markup: dict = None,
                  db=None, user_id: int = None):
    """Отправляет сообщение через Telegram Bot API напрямую (Send message via Telegram Bot API directly)"""
    import httpx
    audit = AuditService(db) if db else None
    try:
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        with httpx.Client(timeout=10) as client:
            response = client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json=payload,
            )
            if response.status_code == 400:
                # Markdown parsing error — retry without parse_mode (Markdown parsing error — retry without parse_mode)
                logger.warning("Retry sendMessage without Markdown (400 error)")
                payload.pop("parse_mode")
                response = client.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json=payload,
                )
            response.raise_for_status()
        if audit:
            audit.log_telegram_sent(
                user_id=user_id,
                chat_id=chat_id,
                message_preview=text[:100],
            )
    except Exception as e:
        logger.error("Failed to send Telegram message: %s", e)
        if audit:
            audit.log_telegram_failed(
                user_id=user_id,
                chat_id=chat_id,
                error=str(e),
                message_preview=text[:100],
            )


def get_user(chat_id: int) -> Optional[User]:
    return get_user_by_telegram(chat_id)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    username = update.effective_user.username
    user = get_user(chat_id)
    if user and user.coros_email:
        # Генерируем ссылку для входа в веб (Generate web login link)
        db = SessionLocal()
        try:
            login_link = _generate_login_link(db, user)
        finally:
            db.close()
        await update.message.reply_text(
            f"👋 Привет, {user.name or username or 'бегун'}!\n"
            f"Твой Coros аккаунт уже привязан: {user.coros_email}\n\n"
            f"🔗 Ссылка для входа в веб-интерфейс:\n"
            f"{login_link}\n\n"
            f"/sync — синхронизировать тренировки\n"
            f"/stats — статистика\n"
            f"/trainings — последние тренировки\n"
            f"/weight — ввести вес (или /weight 75.5)\n"
            f"/login_info — показать email для входа\n"
            f"/reset_password — сменить пароль\n"
            f"/delete_me — удалить мои данные",
            disable_web_page_preview=True,
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "🏃 *Добро пожаловать в Running Coach!*\n\n"
        "Для начала мне нужен доступ к твоим данным Coros.\n"
        "Введи *email* от аккаунта Coros Training Hub:",
        parse_mode="Markdown",
    )
    return EMAIL


async def get_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    email = update.message.text.strip()
    if "@" not in email:
        await update.message.reply_text("Похоже, это не email. Попробуй ещё раз (example@mail.com):")
        return EMAIL
    context.user_data["coros_email"] = email
    await update.message.reply_text(
        "Отлично! Теперь введи *пароль* от Coros Training Hub:\n\n"
        "🔒 Пароль будет зашифрован и сохранён только локально.",
        parse_mode="Markdown",
    )
    return PASSWORD


async def get_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    password = update.message.text.strip()
    if len(password) < 2:
        await update.message.reply_text("Слишком короткий пароль. Попробуй ещё раз:")
        return PASSWORD

    email = context.user_data["coros_email"]
    chat_id = update.effective_chat.id
    username = update.effective_user.username
    name = update.effective_user.full_name

    # Удаляем сообщение с паролем из чата (Delete password message from chat)
    try:
        await update.message.delete()
    except Exception as e:
        logger.debug("Не удалось удалить сообщение с паролем: %s", e)

    db = SessionLocal()
    try:
        user = get_user(chat_id)
        if not user:
            admin = db.query(User).filter(User.id == 1).first()
            if admin and not admin.telegram_chat_id:
                user = admin
                user.telegram_chat_id = chat_id
            else:
                user = User(
                    telegram_chat_id=chat_id,
                    telegram_username=username,
                    name=name,
                )
                db.add(user)
                db.flush()

        user.telegram_username = username
        user.name = name
        old_coros_email = user.coros_email
        user.coros_email = email
        user.coros_password = encrypt(password)
        user.registered_at = datetime.utcnow()

        db.commit()
        logger.info("Пользователь %s (chat_id=%s) привязал Coros: %s", username, chat_id, email)
        
        # Аудит изменения настроек (Audit settings change)
        audit = AuditService(db)
        changes = {}
        if old_coros_email != email:
            changes['coros_email'] = {'old': old_coros_email, 'new': email}
        if changes:
            audit.log_settings_changed(
                user_id=user.id,
                changes=changes,
                source="telegram_start",
            )
        
        # Генерируем ссылку для входа в веб (Generate web login link)
        login_link = _generate_login_link(db, user)
    except Exception as e:
        db.rollback()
        logger.error("Ошибка сохранения пользователя: %s", e)
        await update.message.reply_text("😔 Произошла ошибка. Попробуй позже.")
        return ConversationHandler.END
    finally:
        db.close()

    await update.message.reply_text(
        f"✅ Готово! Аккаунт Coros привязан.\n\n"
        f"Email: {email}\n"
        f"Пароль: 🔒 получен (сообщение удалено из чата)\n\n"
        f"🔗 Ссылка для входа в веб-интерфейс:\n"
        f"{login_link}\n\n"
        f"/sync — синхронизировать тренировки\n"
        f"/stats — статистика\n"
        f"/trainings — последние тренировки\n"
        f"/login_info — показать email для входа\n"
        f"/reset_password — сменить пароль",
        disable_web_page_preview=True,
    )
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Диалог отменён.")
    return ConversationHandler.END


async def cmd_sync(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = get_user(chat_id)
    if not user or not user.coros_email:
        await update.message.reply_text(
            "❌ Coros аккаунт не привязан. Используй /start чтобы настроить."
        )
        return

    await update.message.reply_text("⏳ Синхронизация запущена. Это может занять до минуты...")
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")

    def _run():
        _sync_for_user(user, chat_id, token)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()


def _sync_for_user(user: User, chat_id: int, token: str):
    """Синхронизирует тренировки и метрики здоровья для пользователя (Sync trainings and health metrics for a user)"""
    db = SessionLocal()
    audit = AuditService(db)
    audit.log_coros_sync_started(
        user_id=user.id,
        email=user.coros_email,
        source="telegram_sync",
    )
    try:
        try:
            plain_password = decrypt(user.coros_password)
        except Exception:
            plain_password = user.coros_password

        client = CorosClient(user.coros_email, plain_password, timeout=15)
        client.authenticate()
        logger.info("Bot sync: Coros auth OK for user %s", user.id)

        synced_health = 0
        synced_acts = 0
        msg_parts = []

        # === Health sync ===
        try:
            existing_dates = {
                r[0] for r in db.query(DailyMetrics.date)
                .filter(DailyMetrics.user_id == user.id).all()
            }
            today = date.today()
            start_day = (today - timedelta(days=120)).strftime("%Y%m%d")
            end_day = today.strftime("%Y%m%d")
            metrics_list = client.get_daily_metrics(start_day, end_day)
            if not metrics_list:
                msg_parts.append("🟡 здоровье: нет данных — проверьте синхронизацию часов с Coros")
                logger.info("Bot sync health: empty response for user %s — watch may not be synced", user.id)
                msg_parts.append(f"здоровье: нет данных")
            else:
                analytics_by_date = {}
                try:
                    analytics_list = client.get_analytics()
                    for a in analytics_list:
                        ad = a.get('happenDay')
                        if ad:
                            try:
                                d = datetime.strptime(str(ad), "%Y%m%d").date()
                                analytics_by_date[d] = a
                            except (ValueError, TypeError):
                                pass
                except Exception as e:
                    logger.warning("Bot sync: analytics fetch error: %s", e)

                for entry in metrics_list:
                    happen_day = entry.get('happenDay')
                    if not happen_day:
                        continue
                    try:
                        entry_date = datetime.strptime(str(happen_day), "%Y%m%d").date()
                    except (ValueError, TypeError):
                        continue
                    if entry_date in existing_dates:
                        continue
                    ana = analytics_by_date.get(entry_date, {})
                    dm = DailyMetrics(
                        user_id=user.id,
                        date=entry_date,
                        avg_sleep_hrv=entry.get('avgSleepHrv'),
                        sleep_hrv_baseline=entry.get('sleepHrvBase'),
                        sleep_hrv_sd=entry.get('sleepHrvSd'),
                        rhr=entry.get('rhr'),
                        tired_rate=entry.get('tiredRateNew'),
                        training_load=entry.get('trainingLoad'),
                        training_load_ratio=entry.get('trainingLoadRatio'),
                        performance=entry.get('performance'),
                        ati=entry.get('ati'),
                        cti=entry.get('cti'),
                        vo2max=entry.get('vo2max') or ana.get('vo2max'),
                        lthr=entry.get('lthr') or ana.get('lthr'),
                        stamina_level=entry.get('staminaLevel') or ana.get('staminaLevel'),
                        ltsp=ana.get('ltsp'),
                        stamina_level_7d=ana.get('staminaLevel7d'),
                    )
                    db.add(dm)
                    synced_health += 1

                if synced_health:
                    db.commit()

                if analytics_by_date:
                    updated = 0
                    for entry_date, ana in analytics_by_date.items():
                        existing = db.query(DailyMetrics).filter(
                            DailyMetrics.user_id == user.id,
                            DailyMetrics.date == entry_date,
                        ).first()
                        if not existing:
                            continue
                        changed = False
                        for field in ('vo2max', 'lthr', 'stamina_level', 'ltsp', 'stamina_level_7d'):
                            if getattr(existing, field) is None and ana.get(field) is not None:
                                setattr(existing, field, ana.get(field))
                                changed = True
                        if changed:
                            updated += 1
                    if updated:
                        db.commit()

                msg_parts.append(f"здоровье: {synced_health}")

            # Сохраняем время последней синхронизации здоровья (Save last health sync time)
            user.last_health_sync_at = datetime.utcnow()
            # Сохраняем dashboard данные (Save dashboard data)
            try:
                dashboard = client.get_dashboard()
                if dashboard:
                    today = date.today()
                    dm = db.query(DailyMetrics).filter(
                        DailyMetrics.user_id == user.id,
                        DailyMetrics.date == today
                    ).first()
                    if not dm:
                        dm = DailyMetrics(user_id=user.id, date=today)
                        db.add(dm)
                        db.flush()
                    dm.recovery_pct = dashboard.get('recovery') or dashboard.get('recoveryPercent')
                    dm.load_impact = dashboard.get('loadImpact')
                    dm.intensity_trend = dashboard.get('intensityTrend')
            except Exception as e:
                logger.warning("Bot sync: dashboard error: %s", e)
            db.commit()
        except Exception as e:
            logger.error("Bot sync health error: %s", e)
            msg_parts.append(f"здоровье: ошибка")

        # === Activity sync ===
        try:
            activities = client.list_activities(limit=50, since=user.last_coros_sync)
            if activities:
                existing_times = {
                    r[0] for r in db.query(TrainingSession.begin_ts)
                    .filter(TrainingSession.user_id == user.id).all()
                }

                def already_imported(ts):
                    for et in existing_times:
                        if et is not None and abs((et - ts).total_seconds()) < 120:
                            return True
                    return False

                new_acts = [a for a in activities if not already_imported(a['start_time'])]
                max_act_ts = user.last_coros_sync
                new_session_ids = []
                for act in new_acts:
                    tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.fit')
                    tmp.close()
                    try:
                        ok = client.download_fit(act['id'], act['sport_type'], tmp.name)
                        if not ok:
                            os.unlink(tmp.name)
                            continue
                        data = parse_fit(
                            tmp.name,
                            max_hr=user.max_hr or 177,
                            max_credible_pace=user.max_credible_pace or 3.0,
                            max_gps_jump_m=user.max_gps_jump_m or 100.0,
                            min_hr_for_fast_pace=user.min_hr_for_fast_pace or 130,
                        )
                        if data and data.get('begin_ts'):
                            session = TrainingSession(**data)
                            session.user_id = user.id
                            db.add(session)
                            db.flush()
                            new_session_ids.append((act, session.id, data))
                            synced_acts += 1
                            if max_act_ts is None or act['start_time'] > max_act_ts:
                                max_act_ts = act['start_time']
                        os.unlink(tmp.name)
                    except Exception as e:
                        logger.error("Bot sync: error processing %s: %s", act['name'], e)
                        try:
                            os.unlink(tmp.name)
                        except OSError as unlink_err:
                            logger.debug("Bot sync: не удалось удалить temp-файл %s: %s", tmp.name, unlink_err)

                if synced_acts:
                    user.last_coros_sync = max_act_ts
                    db.commit()
                    # Уведомление + запрос оценки для каждой новой тренировки (Notify + rating prompt)
                    token_bot = os.getenv("TELEGRAM_BOT_TOKEN", "")
                    for act, sid, data in new_session_ids:
                        row1 = [{"text": str(i), "callback_data": f"feedback:{sid}:{i}"} for i in range(0, 6)]
                        row2 = [{"text": str(i), "callback_data": f"feedback:{sid}:{i}"} for i in range(6, 11)]
                        _send_message(
                            token_bot, chat_id,
                            f"🏃 *Новая тренировка!*\n"
                            f"▫️ {act['name']}\n"
                            f"▫️ {data.get('total_distance_km', 0):.1f} км\n\n"
                            f"Насколько тяжёлой была тренировка?\n"
                            f"`0` — вообще легко\n"
                            f"`10` — почти умер",
                            reply_markup={"inline_keyboard": [row1, row2]},
                            db=db,
                            user_id=user.id,
                        )

            msg_parts.append(f"тренировки: {synced_acts}")
        except Exception as e:
            logger.error("Bot sync activities error: %s", e)
            msg_parts.append("тренировки: ошибка")

        msg = f"✅ Синхронизация завершена:\n" + "\n".join(f"• {p}" for p in msg_parts)
        audit.log_coros_sync_completed(
            user_id=user.id,
            email=user.coros_email,
            trainings_synced=synced_acts,
            health_synced=synced_health,
            source="telegram_sync",
        )

    except CorosAuthError as e:
        logger.error("Bot sync auth error: %s", e)
        msg = f"❌ Ошибка аутентификации Coros: {e}\nПроверь логин и пароль через /start"
        audit.log_coros_sync_failed(
            user_id=user.id,
            email=user.coros_email,
            error=str(e),
            source="telegram_sync",
        )
    except Exception as e:
        logger.error("Bot sync error", exc_info=True)
        msg = f"❌ Ошибка: {e}"
        audit.log_coros_sync_failed(
            user_id=user.id,
            email=user.coros_email,
            error=str(e),
            source="telegram_sync",
        )
    finally:
        db.close()

    _send_message(token, chat_id, msg)


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = get_user(chat_id)
    if not user:
        await update.message.reply_text("❌ Сначала используй /start чтобы зарегистрироваться.")
        return

    db = SessionLocal()
    try:
        sessions = db.query(TrainingSession).filter(
            TrainingSession.user_id == user.id
        ).order_by(TrainingSession.begin_ts.desc()).all()
        metrics_count = db.query(DailyMetrics).filter(
            DailyMetrics.user_id == user.id
        ).count()
    finally:
        db.close()

    if not sessions:
        await update.message.reply_text("Тренировок пока нет. Используй /sync чтобы загрузить.")
        return

    total_km = sum(s.total_distance_km or 0 for s in sessions)
    total_dur = sum(s.duration_minutes or 0 for s in sessions)
    h = int(total_dur // 60)
    m = int(total_dur % 60)
    dur_str = f"{h}ч {m}мин" if h else f"{m}мин"

    # За последние 7 дней (Last 7 days)
    week_ago = datetime.utcnow() - timedelta(days=7)
    week_sessions = [s for s in sessions if s.begin_ts and s.begin_ts >= week_ago]
    week_km = sum(s.total_distance_km or 0 for s in week_sessions)

    text = (
        f"📊 *Статистика*\n\n"
        f"Всего тренировок: {len(sessions)}\n"
        f"Общая дистанция: {total_km:.1f} км\n"
        f"Общее время: {dur_str}\n"
        f"Записей здоровья: {metrics_count}\n\n"
        f"За 7 дней: {len(week_sessions)} тренировок, {week_km:.1f} км"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_trainings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = get_user(chat_id)
    if not user:
        await update.message.reply_text("❌ Сначала используй /start чтобы зарегистрироваться.")
        return

    db = SessionLocal()
    try:
        sessions = db.query(TrainingSession).filter(
            TrainingSession.user_id == user.id
        ).order_by(TrainingSession.begin_ts.desc()).limit(5).all()
    finally:
        db.close()

    if not sessions:
        await update.message.reply_text("Тренировок пока нет. Используй /sync чтобы загрузить.")
        return

    lines = ["📋 *Последние тренировки*:\n"]
    for s in sessions:
        ttype = TRAINING_TYPES_RU.get(s.training_type, s.training_type or "—")
        date_str = s.begin_ts.strftime("%d.%m.%Y") if s.begin_ts else "—"
        dist = f"{s.total_distance_km:.1f} км" if s.total_distance_km else "—"
        dur = f"{int(s.duration_minutes)} мин" if s.duration_minutes else "—"
        lines.append(f"▫️ *{date_str}* — {ttype}")
        lines.append(f"   {dist}, {dur}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# === Ежедневный учёт веса (Daily weight tracking) ===

_awaiting_weight: dict[int, bool] = {}


async def handle_weight_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает ответ на запрос веса (Handle weight reply from daily prompt)"""
    chat_id = update.effective_chat.id
    if not _awaiting_weight.get(chat_id):
        return

    text = update.message.text.strip().replace(",", ".")
    try:
        weight = float(text)
        if weight < 20 or weight > 300:
            await update.message.reply_text(
                "Похоже, это не похоже на вес в кг. Попробуй ещё раз (например: 75.5):"
            )
            return
    except ValueError:
        await update.message.reply_text("Пожалуйста, введи число (например: 75.5):")
        return

    db = SessionLocal()
    try:
        user = get_user(chat_id)
        if not user:
            await update.message.reply_text("❌ Пользователь не найден. Используй /start.")
            return
        wm = WeightMeasurement(weight_kg=weight, measured_at=datetime.utcnow(), user_id=user.id)
        db.add(wm)
        db.commit()
        await update.message.reply_text(f"✅ Вес {weight} кг сохранён!")
    except Exception as e:
        db.rollback()
        logger.error("Weight save error: %s", e)
        await update.message.reply_text("😔 Ошибка при сохранении веса.")
    finally:
        db.close()

    _awaiting_weight.pop(chat_id, None)


async def cmd_weight(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ручной ввод веса (/weight 75.5)"""
    chat_id = update.effective_chat.id
    user = get_user(chat_id)
    if not user:
        await update.message.reply_text("❌ Сначала используй /start чтобы зарегистрироваться.")
        return

    args = context.args
    if not args:
        await update.message.reply_text("Использование: /weight 75.5")
        return

    try:
        w = float(args[0].replace(",", "."))
        if w < 20 or w > 300:
            await update.message.reply_text("Похоже, это не похоже на вес в кг.")
            return
    except ValueError:
        await update.message.reply_text("Введи число, например: /weight 75.5")
        return

    db = SessionLocal()
    try:
        wm = WeightMeasurement(weight_kg=w, measured_at=datetime.utcnow(), user_id=user.id)
        db.add(wm)
        db.commit()
        await update.message.reply_text(f"✅ Вес {w} кг сохранён!")
    except Exception as e:
        db.rollback()
        logger.error("Weight save error: %s", e)
        await update.message.reply_text("😔 Ошибка при сохранении.")
    finally:
        db.close()


async def daily_weight_job(context: ContextTypes.DEFAULT_TYPE):
    """Ежедневный опрос/напоминание о весе (Daily weight prompt/reminder — runs at 9:00, 12:00, 15:00, 18:00 if no weight logged today)"""
    logger.info("daily_weight_job fired at %s", datetime.utcnow().isoformat())
    db = SessionLocal()
    audit = AuditService(db)
    try:
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        hour = datetime.utcnow().hour
        users = db.query(User).filter(
            User.telegram_chat_id.isnot(None),
            User.is_active == True,
        ).all()
        for user in users:
            # Проверяем, был ли уже введён вес сегодня (Check if weight already logged today)
            existing = db.query(WeightMeasurement).filter(
                WeightMeasurement.user_id == user.id,
                WeightMeasurement.measured_at >= today_start,
            ).first()
            if existing:
                continue

            # Выбираем текст в зависимости от времени (Pick message text by hour)
            if hour < 10:
                text = "⏰ *Доброе утро!* Введи свой сегодняшний вес (в кг):\nнапример: 75.5"
            else:
                text = "🔔 *Напоминание:* вес за сегодня ещё не введён.\nВведи свой вес (в кг):\nнапример: 75.5"

            try:
                await context.bot.send_message(
                    chat_id=user.telegram_chat_id,
                    text=text,
                    parse_mode="Markdown",
                )
                _awaiting_weight[user.telegram_chat_id] = True
                audit.log_telegram_sent(
                    user_id=user.id,
                    chat_id=user.telegram_chat_id,
                    message_preview="Daily weight prompt",
                    source="daily_weight_job",
                )
            except Exception as e:
                logger.warning("Failed to send weight prompt to %s: %s", user.telegram_chat_id, e)
                audit.log_telegram_failed(
                    user_id=user.id,
                    chat_id=user.telegram_chat_id,
                    error=str(e),
                    message_preview="Daily weight prompt",
                    source="daily_weight_job",
                )
    finally:
        db.close()


async def daily_recovery_check_job(context: ContextTypes.DEFAULT_TYPE):
    """Проверка данных сна: старт в 10:00, повтор каждые 2 часа. Если данные есть — следующая проверка вечером (18:00). Если нет — продолжаем каждые 2 часа до 18:00 (Recovery data check: start at 10:00, repeat every 2 hours. If data found — next check at 18:00. If not — continue every 2 hours until 18:00)"""
    db = SessionLocal()
    audit = AuditService(db)
    try:
        now = datetime.utcnow()
        hour = now.hour

        # За пределами активного времени (0:00–8:00 и после 19:00) — пропускаем (Outside active hours — skip)
        if hour < 8 or hour >= 20:
            next_run = now.replace(hour=10, minute=0, second=0, microsecond=0)
            if next_run <= now:
                next_run += timedelta(days=1)
            context.job_queue.run_once(daily_recovery_check_job, int((next_run - now).total_seconds()))
            return

        cutoff = now - timedelta(hours=12)
        users = db.query(User).filter(
            User.telegram_chat_id.isnot(None),
            User.is_active == True,
        ).all()

        any_missing = False
        for user in users:
            # Проверяем, есть ли данные о сне за последние 12 часов (Check if recovery data exists for last 12 hours)
            latest_metrics = db.query(DailyMetrics).filter(
                DailyMetrics.user_id == user.id,
                DailyMetrics.date >= cutoff.date(),
            ).order_by(DailyMetrics.date.desc()).first()

            if not latest_metrics:
                any_missing = True
                # Проверяем, была ли недавно попытка синхронизации здоровья (Check if health sync was recently attempted)
                sync_recently = (
                    user.last_health_sync_at is not None
                    and (now - user.last_health_sync_at).total_seconds() < 14400  # 4 часа (4 hours)
                )
                if sync_recently:
                    msg = ("🌙 *Нет свежих данных о восстановлении*\n\n"
                           "Синхронизация с Coros выполнялась недавно, но данные о сне и HRV за последние 12 часов не найдены.\n"
                           "Возможно, часы не синхронизированы с приложением Coros.\n"
                           "Попробуй открыть Coros app, потянуть экран вниз для синхронизации, "
                           "затем используй /sync.")
                else:
                    msg = ("🌙 *Нет данных о восстановлении*\n\n"
                           "У тебя нет свежих данных о сне и HRV за последние 12 часов.\n"
                           "Используй /sync чтобы синхронизировать данные с Coros.")
                try:
                    await context.bot.send_message(
                        chat_id=user.telegram_chat_id,
                        text=msg,
                        parse_mode="Markdown",
                    )
                    logger.info("Sent recovery reminder to user %s (chat_id=%s)", user.id, user.telegram_chat_id)
                    audit.log_telegram_sent(
                        user_id=user.id,
                        chat_id=user.telegram_chat_id,
                        message_preview="Recovery reminder",
                        source="daily_recovery_check_job",
                    )
                except Exception as e:
                    logger.warning("Failed to send recovery reminder to %s: %s", user.telegram_chat_id, e)
                    audit.log_telegram_failed(
                        user_id=user.id,
                        chat_id=user.telegram_chat_id,
                        error=str(e),
                        message_preview="Recovery reminder",
                        source="daily_recovery_check_job",
                    )

        # Планируем следующую проверку (Schedule next check)
        if any_missing:
            # Данные не получены — проверяем через 2 часа (Data not found — check again in 2 hours)
            next_run = now + timedelta(hours=2)
        else:
            # Данные получены — следующая проверка вечером (18:00) (Data found — next check at 18:00)
            evening_run = now.replace(hour=18, minute=0, second=0, microsecond=0)
            if evening_run <= now:
                evening_run += timedelta(days=1)
            next_run = evening_run

        context.job_queue.run_once(daily_recovery_check_job, int((next_run - now).total_seconds()))
    finally:
        db.close()


async def cmd_delete_me(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = get_user(chat_id)
    if not user:
        await update.message.reply_text("❌ Нет данных для удаления.")
        return

    db = SessionLocal()
    audit = AuditService(db)
    try:
        db.query(TrainingSession).filter(TrainingSession.user_id == user.id).delete()
        db.query(DailyMetrics).filter(DailyMetrics.user_id == user.id).delete()
        db.query(WeightMeasurement).filter(WeightMeasurement.user_id == user.id).delete()
        db.query(DeletedTraining).filter(DeletedTraining.user_id == user.id).delete()
        user.coros_email = None
        user.coros_password = None
        user.telegram_chat_id = None
        db.commit()
        audit.log_settings_changed(
            user_id=user.id,
            changes={"account": {"action": "delete_all_data"}},
            source="telegram_delete_me",
        )
        await update.message.reply_text(
            "🗑 Все твои данные удалены.\n"
            "Если захочешь начать заново — используй /start."
        )
    except Exception as e:
        db.rollback()
        logger.error("Delete error: %s", e)
        await update.message.reply_text("😔 Ошибка при удалении данных.")
    finally:
        db.close()


# === Команды управления аккаунтом (Account management commands) ===

async def cmd_login_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать email для входа в веб (Show login email)"""
    chat_id = update.effective_chat.id
    user = get_user(chat_id)
    if not user:
        await update.message.reply_text("❌ Сначала используй /start чтобы зарегистрироваться.")
        return
    if not user.email:
        await update.message.reply_text(
            "У вас ещё не установлен email для входа.\n"
            "Используйте /start чтобы получить ссылку на регистрацию."
        )
        return
    await update.message.reply_text(
        f"📧 Ваш email для входа: {user.email}\n\n"
        f"Форма входа: {_get_web_app_url()}/login\n"
        f"Сменить пароль: /reset_password"
    )


async def cmd_reset_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сброс пароля — запросить новый пароль (Reset password — prompt for new password)"""
    chat_id = update.effective_chat.id
    user = get_user(chat_id)
    if not user:
        await update.message.reply_text("❌ Сначала используй /start чтобы зарегистрироваться.")
        return
    if not user.email:
        await update.message.reply_text(
            "❌ У вас ещё не установлен email. Сначала зарегистрируйтесь через /start."
        )
        return ConversationHandler.END
    from src.config import CONFIG
    await update.message.reply_text(
        f"🔑 Введите новый пароль (минимум {CONFIG.AUTH.PASSWORD_MIN_LENGTH} символов).\n"
        f"🔒 Пароль будет показан 2 секунды, затем сообщение удалится (как при вводе пароля Coros)."
    )
    return NEW_PASSWORD


async def get_new_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получить новый пароль, сохранить хеш, показать и удалить (Receive new password, save hash, show and delete)"""
    from src.config import CONFIG
    chat_id = update.effective_chat.id
    user = get_user(chat_id)
    if not user:
        await update.message.reply_text("❌ Пользователь не найден.")
        return ConversationHandler.END

    password = update.message.text.strip()
    if len(password) < CONFIG.AUTH.PASSWORD_MIN_LENGTH:
        await update.message.reply_text(
            f"Слишком короткий пароль (минимум {CONFIG.AUTH.PASSWORD_MIN_LENGTH} символов). Попробуйте ещё раз:"
        )
        return NEW_PASSWORD

    # Сохраняем хеш пароля (Save password hash)
    db = SessionLocal()
    audit = AuditService(db)
    try:
        user_db = db.query(User).filter(User.id == user.id).first()
        user_db.password_hash = hash_password(password)
        db.commit()
        # Удаляем сообщение с паролем (Delete password message)
        try:
            await update.message.delete()
        except Exception:
            pass
        # Показываем пароль 2 секунды затем удаляем (Show password for 2 sec then delete)
        # Используем reply_text, ждём 2 сек, затем удаляем (Reply, wait 2s, then delete)
        confirmation = await update.message.reply_text(
            f"✅ Пароль установлен: {password}\n"
            f"🔒 Это сообщение будет удалено через 2 секунды."
        )
        await asyncio.sleep(2)
        try:
            await confirmation.delete()
        except Exception:
            pass
        audit.log_settings_changed(
            user_id=user.id,
            changes={"password": {"action": "reset"}},
            source="telegram_reset_password",
        )
        await update.message.reply_text(
            "✅ Пароль изменён. Теперь вы можете войти через /login_info или /start."
        )
    except Exception as e:
        db.rollback()
        logger.error("Password reset error: %s", e)
        await update.message.reply_text("😔 Ошибка при смене пароля.")
    finally:
        db.close()
    return ConversationHandler.END


async def cancel_reset_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена сброса пароля (Cancel password reset)"""
    await update.message.reply_text("Смена пароля отменена.")
    return ConversationHandler.END


# === Обратная связь по тренировке (Training feedback) ===

async def feedback_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает нажатие кнопки оценки тренировки (Handle training rating button press)"""
    query = update.callback_query
    await query.answer()
    data = query.data
    if not data or not data.startswith("feedback:"):
        return
    parts = data.split(":")
    if len(parts) != 3:
        return
    _, session_id_str, rating_str = parts
    try:
        session_id = int(session_id_str)
        rating = int(rating_str)
    except ValueError:
        return
    if rating < 0 or rating > 10:
        return

    chat_id = update.effective_chat.id
    user = get_user(chat_id)
    if not user:
        await query.edit_message_text(
            "❌ Пользователь не найден. Используй /start чтобы зарегистрироваться."
        )
        return

    db = SessionLocal()
    try:
        fb = db.query(TrainingFeedback).filter(
            TrainingFeedback.session_id == session_id,
            TrainingFeedback.user_id == user.id,
        ).first()
        if fb:
            await query.edit_message_text(
                f"✅ Оценка уже была сохранена ранее: {fb.rating}/10"
            )
            return

        fb = TrainingFeedback(
            session_id=session_id,
            user_id=user.id,
            rating=rating,
        )
        db.add(fb)
        db.commit()
        labels = {0: "😴", 1: "😌", 2: "🙂", 3: "😐", 4: "😅", 5: "💪",
                  6: "😤", 7: "🥵", 8: "😵", 9: "💀", 10: "⚰️"}
        await query.edit_message_text(
            f"✅ Спасибо! Оценка {rating}/10 {labels.get(rating, '')} сохранена."
        )
    except Exception as e:
        db.rollback()
        logger.error("Feedback save error: %s", e)
        await query.edit_message_text("😔 Ошибка при сохранении оценки.")
    finally:
        db.close()


def run_bot():
    """Запускает Telegram бота (блокирующий вызов — запускать в отдельном процессе)"""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.warning("TELEGRAM_BOT_TOKEN не задан — бот не запущен")
        return

    from telegram.ext import JobQueue
    application = (
        Application.builder()
        .token(token)
        .job_queue(JobQueue())
        .build()
    )

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_email)],
            PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_password)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("sync", cmd_sync))
    application.add_handler(CommandHandler("stats", cmd_stats))
    application.add_handler(CommandHandler("trainings", cmd_trainings))
    application.add_handler(CommandHandler("weight", cmd_weight))
    application.add_handler(CommandHandler("delete_me", cmd_delete_me))
    application.add_handler(CommandHandler("login_info", cmd_login_info))

    # Обработчик сброса пароля — отдельная conversation (Password reset conversation handler)
    reset_pw_handler = ConversationHandler(
        entry_points=[CommandHandler("reset_password", cmd_reset_password)],
        states={
            NEW_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_new_password)],
        },
        fallbacks=[CommandHandler("cancel", cancel_reset_password)],
    )
    application.add_handler(reset_pw_handler)

    application.add_handler(CallbackQueryHandler(feedback_callback, pattern="^feedback:"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_weight_message))

    # Планировщик опроса веса: 9:00, 12:00, 15:00, 18:00 (Weight prompt schedule: 9:00, 12:00, 15:00, 18:00)
    for hour in [9, 12, 15, 18]:
        application.job_queue.run_daily(daily_weight_job, time=dt_time(hour=hour, minute=0))
    logger.info("Ежедневный опрос веса запланирован на 9:00, 12:00, 15:00, 18:00")

    # Если текущее время после 9:00 — запускаем проверку веса сразу (If past 9:00 — run weight check immediately)
    now = datetime.utcnow()
    if now.hour >= 9 and not (now.hour == 9 and now.minute == 0 and now.second < 5):
        db = SessionLocal()
        try:
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            any_weight_today = db.query(WeightMeasurement).filter(
                WeightMeasurement.measured_at >= today_start,
            ).first()
            if not any_weight_today:
                logger.info("Вес ещё не введён сегодня — запускаем напоминание через 30 секунд")
                application.job_queue.run_once(daily_weight_job, when=datetime.utcnow() + timedelta(seconds=30))
        finally:
            db.close()

    # Проверка данных сна — старт в 10:00, дальше функция сама планирует (Recovery check starts at 10:00, then schedules itself)
    application.job_queue.run_daily(daily_recovery_check_job, time=dt_time(hour=10, minute=0))
    logger.info("Проверка данных сна запланирована на 10:00")

    logger.info("Telegram-obot polling started")
    application.run_polling(allowed_updates=Update.ALL_TYPES)
