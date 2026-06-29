# Telegram-бот для Running Coach (Telegram bot for Running Coach)
import asyncio
import logging
import os
import threading
import tempfile
from datetime import datetime, timedelta, date, time as dt_time
from typing import Optional

from telegram import Update
from telegram.ext import (
    Application, CommandHandler, ConversationHandler,
    MessageHandler, filters, ContextTypes,
)

from src.models import (
    SessionLocal, User, UserSettings, TrainingSession,
    DailyMetrics, WeightMeasurement, DeletedTraining,
    get_user_by_telegram,
)
from src.crypto import encrypt, decrypt
from src.coros_client import CorosClient, CorosAuthError, CorosAPIError
from src.parsers.fit_parser import parse_fit
from src.logger import get_logger

logger = get_logger("telegram_bot")

EMAIL, PASSWORD = range(2)

TRAINING_TYPES_RU = {
    'interval': 'Интервальная',
    'long': 'Длинная',
    'recovery': 'Восстановительная',
    'tempo': 'Темповая',
}


def _send_message(token: str, chat_id: int, text: str):
    """Отправляет сообщение через Telegram Bot API напрямую (Send message via Telegram Bot API directly)"""
    import httpx
    try:
        with httpx.Client(timeout=10) as client:
            client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            )
    except Exception as e:
        logger.error("Failed to send Telegram message: %s", e)


def get_user(chat_id: int) -> Optional[User]:
    return get_user_by_telegram(chat_id)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    username = update.effective_user.username
    user = get_user(chat_id)
    if user and user.coros_email:
        await update.message.reply_text(
            f"👋 Привет, {user.name or username or 'бегун'}!\n"
            f"Твой Coros аккаунт уже привязан: {user.coros_email}\n\n"
            f"/sync — синхронизировать тренировки\n"
            f"/stats — статистика\n"
            f"/trainings — последние тренировки\n"
            f"/weight — ввести вес (или /weight 75.5)\n"
            f"/delete_me — удалить мои данные",
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
    except Exception:
        pass

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
        user.coros_email = email
        user.coros_password = encrypt(password)
        user.registered_at = datetime.utcnow()

        us = db.query(UserSettings).first()
        if not us:
            us = UserSettings()
            db.add(us)
        us.coros_email = email
        us.coros_password = encrypt(password)

        db.commit()
        logger.info("Пользователь %s (chat_id=%s) привязал Coros: %s", username, chat_id, email)
    except Exception as e:
        db.rollback()
        logger.error("Ошибка сохранения пользователя: %s", e)
        await update.message.reply_text("😔 Произошла ошибка. Попробуй позже.")
        return ConversationHandler.END
    finally:
        db.close()

    await update.message.reply_text(
        f"✅ *Готово!* Аккаунт Coros привязан.\n\n"
        f"Email: `{email}`\n"
        f"Пароль: 🔒 получен (сообщение удалено из чата)\n\n"
        f"/sync — синхронизировать тренировки\n"
        f"/stats — статистика\n"
        f"/trainings — последние тренировки",
        parse_mode="Markdown",
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
            if metrics_list:
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
                            synced_acts += 1
                            if max_act_ts is None or act['start_time'] > max_act_ts:
                                max_act_ts = act['start_time']
                        os.unlink(tmp.name)
                    except Exception as e:
                        logger.error("Bot sync: error processing %s: %s", act['name'], e)
                        try:
                            os.unlink(tmp.name)
                        except Exception:
                            pass

                if synced_acts:
                    user.last_coros_sync = max_act_ts
                    us = db.query(UserSettings).first()
                    if us:
                        us.last_coros_sync = max_act_ts
                    db.commit()

            msg_parts.append(f"тренировки: {synced_acts}")
        except Exception as e:
            logger.error("Bot sync activities error: %s", e)
            msg_parts.append("тренировки: ошибка")

        msg = f"✅ Синхронизация завершена:\n" + "\n".join(f"• {p}" for p in msg_parts)

    except CorosAuthError as e:
        msg = f"❌ Ошибка аутентификации Coros: {e}\nПроверь логин и пароль через /start"
    except Exception as e:
        logger.error("Bot sync error", exc_info=True)
        msg = f"❌ Ошибка: {e}"
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
    """Ежедневный опрос веса (Daily weight prompt at 9:00)"""
    db = SessionLocal()
    try:
        users = db.query(User).filter(
            User.telegram_chat_id.isnot(None),
            User.is_active == True,
        ).all()
        for user in users:
            try:
                await context.bot.send_message(
                    chat_id=user.telegram_chat_id,
                    text="⏰ *Доброе утро!* Введи свой сегодняшний вес (в кг):\n"
                         "например: 75.5",
                    parse_mode="Markdown",
                )
                _awaiting_weight[user.telegram_chat_id] = True
            except Exception as e:
                logger.warning("Failed to send weight prompt to %s: %s", user.telegram_chat_id, e)
    finally:
        db.close()


async def cmd_delete_me(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = get_user(chat_id)
    if not user:
        await update.message.reply_text("❌ Нет данных для удаления.")
        return

    db = SessionLocal()
    try:
        db.query(TrainingSession).filter(TrainingSession.user_id == user.id).delete()
        db.query(DailyMetrics).filter(DailyMetrics.user_id == user.id).delete()
        db.query(WeightMeasurement).filter(WeightMeasurement.user_id == user.id).delete()
        db.query(DeletedTraining).filter(DeletedTraining.user_id == user.id).delete()
        user.coros_email = None
        user.coros_password = None
        user.telegram_chat_id = None
        db.commit()
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
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_weight_message))

    # Планировщик ежедневного опроса веса в 9:00 (Daily weight prompt at 9:00)
    application.job_queue.run_daily(daily_weight_job, time=dt_time(hour=9, minute=0))
    logger.info("Ежедневный опрос веса запланирован на 9:00")

    logger.info("Telegram-obot polling started")
    application.run_polling(allowed_updates=Update.ALL_TYPES)
