# Импорт библиотек SQLAlchemy и стандартных модулей (SQLAlchemy and standard library imports)
from sqlalchemy import create_engine, event, Column, Integer, Float, String, Text, DateTime, Date, JSON, BigInteger, Boolean, ForeignKey, UniqueConstraint
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime
import os

# Базовый класс для всех моделей SQLAlchemy (Base class for all SQLAlchemy models)
Base = declarative_base()


# Модель пользователя (User model — multi-user support)
class User(Base):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True)
    telegram_chat_id = Column(BigInteger, unique=True, nullable=True)
    telegram_username = Column(String(255), nullable=True)
    name = Column(String(255), nullable=True)
    age = Column(Integer, nullable=True)
    height_cm = Column(Integer, nullable=True)
    weight_kg = Column(Float, nullable=True)
    sport_level = Column(String(50), nullable=True)  # beginner / intermediate / advanced
    goal_type = Column(String(50), nullable=True)  # lose_weight / 10k / half_marathon / marathon / general
    goal_target = Column(String(255), nullable=True)  # e.g. "sub 60 min 10k"
    coros_email = Column(String(255), nullable=True)
    coros_password = Column(String(255), nullable=True)  # encrypted
    last_coros_sync = Column(DateTime, nullable=True)
    last_health_sync_at = Column(DateTime, nullable=True)
    max_hr = Column(Integer, default=177)
    max_credible_pace = Column(Float, default=3.0)
    max_gps_jump_m = Column(Float, default=100.0)
    min_hr_for_fast_pace = Column(Integer, default=130)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    registered_at = Column(DateTime, nullable=True)

    training_sessions = relationship("TrainingSession", back_populates="user")
    daily_metrics = relationship("DailyMetrics", back_populates="user")
    weight_measurements = relationship("WeightMeasurement", back_populates="user")
    deleted_trainings = relationship("DeletedTraining", back_populates="user")


# Модель тренировочной сессии (Training session model)
class TrainingSession(Base):
    __tablename__ = 'training_sessions'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=True, index=True)  # Для обратной совместимости nullable
    begin_ts = Column(DateTime, default=datetime.utcnow)
    total_distance_km = Column(Float)
    avg_heart_rate = Column(Integer)
    max_heart_rate = Column(Integer)
    training_type = Column(String(50))
    segments_count = Column(Integer, default=1)
    duration_minutes = Column(Float, default=0)
    segments_json = Column(JSON, default=list)
    hr_pace_series = Column(JSON, default=list)
    avg_temperature = Column(Integer, nullable=True)
    weather_code = Column(Integer, nullable=True)
    elevation_gain = Column(Integer, nullable=True)
    elevation_loss = Column(Integer, nullable=True)
    suspect_flags = Column(JSON, default=list)
    cleaning_log = Column(JSON, default=list)
    avg_cadence = Column(Integer, nullable=True)
    training_effect = Column(Float, nullable=True)
    anaerobic_training_effect = Column(Float, nullable=True)
    vo2max = Column(Float, nullable=True)
    calories = Column(Integer, nullable=True)

    user = relationship("User", back_populates="training_sessions")


# Модель удалённой тренировки (Deleted training model)
class DeletedTraining(Base):
    __tablename__ = 'deleted_trainings'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=True, index=True)
    begin_ts = Column(DateTime, nullable=False)
    total_distance_km = Column(Float, nullable=True)
    avg_heart_rate = Column(Integer, nullable=True)
    max_heart_rate = Column(Integer, nullable=True)
    training_type = Column(String(50), nullable=True)
    duration_minutes = Column(Float, nullable=True)
    avg_temperature = Column(Integer, nullable=True)
    elevation_gain = Column(Integer, nullable=True)
    avg_cadence = Column(Integer, nullable=True)
    training_effect = Column(Float, nullable=True)
    vo2max = Column(Float, nullable=True)
    calories = Column(Integer, nullable=True)
    avg_pace = Column(Float, nullable=True)
    deleted_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="deleted_trainings")


# Модель ежедневных метрик здоровья (Daily health metrics)
class DailyMetrics(Base):
    __tablename__ = 'daily_metrics'
    __table_args__ = (
        UniqueConstraint('user_id', 'date', name='uq_user_date'),
    )
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=True, index=True)
    date = Column(Date, nullable=False)
    avg_sleep_hrv = Column(Float, nullable=True)
    sleep_hrv_baseline = Column(Float, nullable=True)
    sleep_hrv_sd = Column(Float, nullable=True)
    rhr = Column(Integer, nullable=True)
    tired_rate = Column(Integer, nullable=True)
    training_load = Column(Float, nullable=True)
    training_load_ratio = Column(Float, nullable=True)
    performance = Column(Integer, nullable=True)
    ati = Column(Float, nullable=True)
    cti = Column(Float, nullable=True)
    vo2max = Column(Float, nullable=True)
    lthr = Column(Integer, nullable=True)
    stamina_level = Column(Float, nullable=True)
    ltsp = Column(Float, nullable=True)
    stamina_level_7d = Column(Float, nullable=True)
    synced_at = Column(DateTime, default=datetime.utcnow)
    recovery_pct = Column(Integer, nullable=True)  # Coros recovery % (0-100)
    form_score = Column(Float, nullable=True)  # Coros "Базовая форма"
    load_impact = Column(Float, nullable=True)  # Coros "Влияние нагрузки"
    intensity_trend = Column(Float, nullable=True)  # Coros "Тренд интенсивности"
    sleep_hrv_interval_list = Column(Text, nullable=True)  # Coros HRV intervals JSON [min, low, normal_start, normal_end]

    user = relationship("User", back_populates="daily_metrics")


# Модель измерения веса (Weight measurement model)
class WeightMeasurement(Base):
    __tablename__ = 'weight_measurements'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=True, index=True)
    weight_kg = Column(Float, nullable=False)
    measured_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="weight_measurements")


# Модель обратной связи по тренировке (Training feedback model)
class TrainingFeedback(Base):
    __tablename__ = 'training_feedback'
    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey('training_sessions.id'), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=True, index=True)
    rating = Column(Integer, nullable=False)  # 0–10 (тяжесть тренировки)
    notes = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    session = relationship("TrainingSession")
    user = relationship("User")


# Определение пути к БД и создание подключения (Database path and connection setup)
DB_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DB_DIR}/running_coach.db")
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 30},
    pool_pre_ping=True,
)


# Включение WAL-режима для SQLite при подключении (Enable WAL mode for SQLite on connect)
@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_conn, connection_record):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.execute("PRAGMA busy_timeout=5000")
    cur.close()


SessionLocal = sessionmaker(bind=engine)


# Зависимость для FastAPI: выдаёт сессию БД и закрывает её после запроса (FastAPI DB session dependency)
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Инициализация БД: создание таблиц (Initialize DB: create all tables)
def init_db():
    Base.metadata.create_all(bind=engine)


# Получение настроек пользователя из User (Get user settings from User model)
def get_settings():
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == 1).first()
        if not user:
            # Создаём пользователя со значениями по умолчанию (Create user with defaults)
            user = User(
                id=1, max_hr=177, weight_kg=85.0,
                max_credible_pace=3.0, max_gps_jump_m=100.0, min_hr_for_fast_pace=130,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        # Прокси для совместимости — User.weight_kg маппится на .weight (Proxy for backward compat)
        user.weight = user.weight_kg
        return user
    finally:
        db.close()


# Получить пользователя по telegram chat_id (Get user by telegram chat ID)
def get_user_by_telegram(chat_id: int) -> User:
    db = SessionLocal()
    try:
        return db.query(User).filter(User.telegram_chat_id == chat_id).first()
    finally:
        db.close()


# Создать или получить пользователя по telegram chat_id (Get or create user by telegram)
def get_or_create_user_by_telegram(chat_id: int, username: str = None) -> User:
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.telegram_chat_id == chat_id).first()
        if not user:
            user = User(telegram_chat_id=chat_id, telegram_username=username)
            db.add(user)
            db.commit()
            db.refresh(user)
        return user
    finally:
        db.close()


# Получить пользователя по ID (Get user by ID)
def get_user(user_id: int) -> User:
    db = SessionLocal()
    try:
        return db.query(User).filter(User.id == user_id).first()
    finally:
        db.close()
