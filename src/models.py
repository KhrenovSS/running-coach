# Импорт библиотек SQLAlchemy и стандартных модулей (SQLAlchemy and standard library imports)
from sqlalchemy import create_engine, Column, Integer, Float, String, Text, DateTime, Date, JSON, BigInteger, Boolean, ForeignKey, UniqueConstraint
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime, timezone
import os

# Helper: текущее UTC время с tzinfo для TIMESTAMPTZ (Aware UTC helper for TIMESTAMPTZ)
def utcnow() -> datetime:
    return datetime.now(timezone.utc)

# Базовый класс для всех моделей SQLAlchemy (Base class for all SQLAlchemy models)
Base = declarative_base()


# Модель пользователя (User model — multi-user support)
class User(Base):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, nullable=True)   # email для входа (login email)
    password_hash = Column(String(255), nullable=True)        # bcrypt-хеш пароля (bcrypt password hash)
    telegram_chat_id = Column(BigInteger, unique=True, nullable=True)
    telegram_username = Column(String(255), nullable=True)
    name = Column(String(255), nullable=True)
    age = Column(Integer, nullable=True)
    height_cm = Column(Integer, nullable=True)
    weight_kg = Column(Float, nullable=True)
    sport_level = Column(String(50), nullable=True)  # beginner / intermediate / advanced
    goal_type = Column(String(50), nullable=True)  # lose_weight / 10k / half_marathon / marathon / general
    goal_target = Column(String(255), nullable=True)  # e.g. "sub 60 min 10k"
    last_health_sync_at = Column(DateTime(timezone=True), nullable=True)
    max_hr = Column(Integer, default=177)
    max_credible_pace = Column(Float, default=3.0)
    max_gps_jump_m = Column(Float, default=100.0)
    min_hr_for_fast_pace = Column(Integer, default=130)
    is_active = Column(Boolean, default=True)
    timezone = Column(String(50), nullable=True)  # Часовой пояс пользователя (User timezone, e.g. "Europe/Moscow")
    created_at = Column(DateTime(timezone=True), default=utcnow)
    registered_at = Column(DateTime(timezone=True), nullable=True)

    training_sessions = relationship("TrainingSession", back_populates="user")
    daily_metrics = relationship("DailyMetrics", back_populates="user")
    weight_measurements = relationship("WeightMeasurement", back_populates="user")
    deleted_trainings = relationship("DeletedTraining", back_populates="user")
    watch_credentials = relationship("WatchCredential", back_populates="user")


# Модель учётных данных часов (Watch credential model — multi-brand)
class WatchCredential(Base):
    __tablename__ = 'watch_credentials'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    brand = Column(String(50), nullable=False)  # e.g. 'coros', 'garmin', 'polar'
    encrypted_user = Column(String(255), nullable=True)   # encrypted email/username
    encrypted_password = Column(String(255), nullable=True)  # encrypted password
    access_token = Column(String(512), nullable=True)  # cached API token
    token_expires_at = Column(DateTime(timezone=True), nullable=True)
    last_activity_sync_at = Column(DateTime(timezone=True), nullable=True)
    last_health_sync_at = Column(DateTime(timezone=True), nullable=True)
    activity_sync_interval = Column(Integer, nullable=True)  # minutes, NULL = default 60
    health_sync_interval = Column(Integer, nullable=True)  # minutes, NULL = default 480
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    user = relationship("User", back_populates="watch_credentials")


# Модель тренировочной сессии (Training session model)
class TrainingSession(Base):
    __tablename__ = 'training_sessions'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=True, index=True)  # Для обратной совместимости nullable
    begin_ts = Column(DateTime(timezone=True), default=utcnow)
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
    timezone = Column(String(50), nullable=True)  # Часовой пояс тренировки (Training timezone, e.g. "Europe/Moscow")
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
    begin_ts = Column(DateTime(timezone=True), nullable=False)
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
    deleted_at = Column(DateTime(timezone=True), default=utcnow)

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
    synced_at = Column(DateTime(timezone=True), default=utcnow)
    recovery_pct = Column(Integer, nullable=True)  # Coros recovery % (0-100)
    form_score = Column(Float, nullable=True)  # Coros "Базовая форма"
    load_impact = Column(Float, nullable=True)  # Coros "Влияние нагрузки"
    intensity_trend = Column(Float, nullable=True)  # Coros "Тренд интенсивности"
    sleep_hrv_interval_list = Column(Text, nullable=True)  # Coros HRV intervals JSON [min, low, normal_start, normal_end]
    source_brand = Column(String(50), nullable=True)  # e.g. 'coros', 'garmin' (source of metric)

    user = relationship("User", back_populates="daily_metrics")


# Модель измерения веса (Weight measurement model)
class WeightMeasurement(Base):
    __tablename__ = 'weight_measurements'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=True, index=True)
    weight_kg = Column(Float, nullable=False)
    measured_at = Column(DateTime(timezone=True), default=utcnow)

    user = relationship("User", back_populates="weight_measurements")


# Модель обратной связи по тренировке (Training feedback model)
class TrainingFeedback(Base):
    __tablename__ = 'training_feedback'
    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey('training_sessions.id'), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=True, index=True)
    rating = Column(Integer, nullable=False)  # 0–10 (тяжесть тренировки)
    notes = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    session = relationship("TrainingSession")
    user = relationship("User")


# Модель события аудита (Audit event model)
class AuditEvent(Base):
    __tablename__ = 'audit_events'
    
    id = Column(Integer, primary_key=True)
    event_type = Column(String(100), nullable=False, index=True)
    severity = Column(String(20), nullable=False, default='info')  # info, warning, error, critical
    message = Column(Text, nullable=False)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=True, index=True)
    ip_address = Column(String(45), nullable=True)
    metadata_json = Column(Text, nullable=True)  # JSON string
    created_at = Column(DateTime(timezone=True), default=utcnow, index=True)
    
    user = relationship("User")


# Модель токена для Telegram-входа в веб (Telegram web login token model)
class AuthToken(Base):
    __tablename__ = 'auth_tokens'
    
    id = Column(Integer, primary_key=True)
    token = Column(String(64), unique=True, nullable=False, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    used_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    user = relationship("User")


# Определение пути к БД и создание подключения (Database path and connection setup)
DB_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError(
        "DATABASE_URL environment variable is required. "
        "Set it to a PostgreSQL connection string, e.g. "
        "postgresql://running_coach:PASSWORD@localhost:5432/running_coach"
    )


# Lazy engine creation — engine is built on first access, not at module import time.
# This allows tests to override DATABASE_URL before any code calls get_db()/init_db().
_engine = None


def get_engine():
    global _engine
    if _engine is not None:
        return _engine
    if DATABASE_URL.startswith("postgresql"):
        _engine = create_engine(
            DATABASE_URL,
            pool_pre_ping=True,
            pool_size=10,
            max_overflow=20,
        )
    elif DATABASE_URL.startswith("sqlite"):
        _engine = create_engine(
            DATABASE_URL,
            connect_args={"check_same_thread": False, "timeout": 30},
            pool_pre_ping=True,
        )
    else:
        raise ValueError(f"Unsupported DATABASE_URL scheme: {DATABASE_URL.split(':')[0]}")
    return _engine


# Alias for backward compatibility


# Lazy SessionLocal — creates sessionmaker on first call, bound to lazy engine
class _SessionLocal:
    """Lazy sessionmaker: engine is resolved via get_engine() on first call, not at import time."""
    _maker = None

    def __call__(self):
        if self._maker is None:
            self._maker = sessionmaker(bind=get_engine())
        return self._maker()

    def __init__(self):
        pass

    def configure(self, **kwargs):
        if self._maker is None:
            self._maker = sessionmaker(bind=get_engine(), **kwargs)
        else:
            self._maker.configure(**kwargs)


SessionLocal = _SessionLocal()


# Зависимость для FastAPI: выдаёт сессию БД и закрывает её после запроса (FastAPI DB session dependency)
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Инициализация БД: создание таблиц (Initialize DB: create all tables)
def init_db():
    Base.metadata.create_all(bind=get_engine())


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
