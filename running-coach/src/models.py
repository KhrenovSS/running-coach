# Импорт библиотек SQLAlchemy и стандартных модулей (SQLAlchemy and standard library imports)
from sqlalchemy import create_engine, Column, Integer, Float, String, DateTime, Date, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import os

# Базовый класс для всех моделей SQLAlchemy (Base class for all SQLAlchemy models)
Base = declarative_base()

# Модель тренировочной сессии (Training session model)
class TrainingSession(Base):
    __tablename__ = 'training_sessions'
    
    id = Column(Integer, primary_key=True)  # Уникальный идентификатор (Unique ID)
    begin_ts = Column(DateTime, default=datetime.utcnow)  # Дата и время начала тренировки (Start timestamp)
    total_distance_km = Column(Float)  # Общая дистанция в км (Total distance in km)
    avg_heart_rate = Column(Integer)  # Средний пульс (Average heart rate)
    max_heart_rate = Column(Integer)  # Максимальный пульс (Max heart rate)
    training_type = Column(String(50))  # Тип тренировки: interval/tempo/long/recovery (Training type)
    segments_count = Column(Integer, default=1)  # Количество сегментов (Number of segments)
    duration_minutes = Column(Float, default=0)  # Продолжительность в минутах (Duration in minutes)
    segments_json = Column(JSON, default=list)  # Детальные сегменты в JSON (Segments detail as JSON)
    hr_pace_series = Column(JSON, default=list)  # Временной ряд пульса и темпа (HR/pace time series as JSON)
    avg_temperature = Column(Integer, nullable=True)  # Средняя температура за тренировку (Average temperature)
    weather_code = Column(Integer, nullable=True)  # WMO код погоды (WMO weather code)
    elevation_gain = Column(Integer, nullable=True)  # Суммарный набор высоты в метрах (Total elevation gain)
    elevation_loss = Column(Integer, nullable=True)  # Суммарный спуск в метрах (Total elevation loss)
    suspect_flags = Column(JSON, default=list)  # Флаги подозрительности: pace_impossible, gps_spike, hr_pace_mismatch, too_short (Suspicion flags)
    cleaning_log = Column(JSON, default=list)  # Лог удалённых ошибочных участков тренировки (Cleaning log — removed bad segments)
    avg_cadence = Column(Integer, nullable=True)  # Средний каденс за тренировку в spm (Average cadence in steps per minute)
    training_effect = Column(Float, nullable=True)  # Аэробный тренировочный эффект 0.0-5.0 (Aerobic training effect)
    anaerobic_training_effect = Column(Float, nullable=True)  # Анаэробный тренировочный эффект (Anaerobic training effect)
    vo2max = Column(Float, nullable=True)  # Оценка VO2max за тренировку (Estimated VO2max for the session)
    calories = Column(Integer, nullable=True)  # Сожжённые калории (Total calories burned)

# Модель настроек пользователя (User settings model)
class UserSettings(Base):
    __tablename__ = 'user_settings'
    id = Column(Integer, primary_key=True)  # Уникальный идентификатор (Unique ID)
    max_hr = Column(Integer, default=177)  # Максимальная ЧСС пользователя (User max heart rate)
    weight = Column(Float, default=85.0)  # Вес пользователя в кг (User weight in kg)
    max_credible_pace = Column(Float, default=3.0)  # Минимальный реальный темп мин/км (Minimum credible pace min/km)
    max_gps_jump_m = Column(Float, default=100.0)  # Максимальный GPS-скачок в метрах (Max GPS jump in meters)
    min_hr_for_fast_pace = Column(Integer, default=130)  # Минимальный пульс для быстрого темпа (Min HR for fast pace)
    coros_email = Column(String(255), nullable=True)  # Email для входа в Coros Training Hub (Coros account email)
    coros_password = Column(String(255), nullable=True)  # Пароль Coros (Coros account password)
    last_coros_sync = Column(DateTime, nullable=True)  # Дата последней синхронизации с Coros (Last Coros sync timestamp)

# Модель удалённой тренировки (Deleted training model — used to ask confirmation on re-upload / повторный импорт)
class DeletedTraining(Base):
    __tablename__ = 'deleted_trainings'
    id = Column(Integer, primary_key=True)
    begin_ts = Column(DateTime, nullable=False)  # Начало тренировки (Training start time)
    total_distance_km = Column(Float, nullable=True)  # Дистанция км (Distance in km)
    avg_heart_rate = Column(Integer, nullable=True)  # Средний пульс (Average HR)
    max_heart_rate = Column(Integer, nullable=True)  # Максимальный пульс (Max HR)
    training_type = Column(String(50), nullable=True)  # Тип тренировки (Training type)
    duration_minutes = Column(Float, nullable=True)  # Длительность мин (Duration in minutes)
    avg_temperature = Column(Integer, nullable=True)  # Температура (Temperature)
    elevation_gain = Column(Integer, nullable=True)  # Набор высоты (Elevation gain)
    avg_cadence = Column(Integer, nullable=True)  # Каденс (Cadence)
    training_effect = Column(Float, nullable=True)  # Тренировочный эффект (Training effect)
    vo2max = Column(Float, nullable=True)  # VO2max
    calories = Column(Integer, nullable=True)  # Калории (Calories)
    avg_pace = Column(Float, nullable=True)  # Средний темп мин/км (Average pace min/km)
    deleted_at = Column(DateTime, default=datetime.utcnow)  # Когда удалён (When deleted)

# Модель ежедневных метрик здоровья — сон, HRV, восстановление (Daily health metrics — sleep, HRV, recovery)
class DailyMetrics(Base):
    __tablename__ = 'daily_metrics'
    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False, unique=True)  # Дата метрик (Metrics date)
    avg_sleep_hrv = Column(Float, nullable=True)  # Средний HRV во сне (Average HRV during sleep)
    sleep_hrv_baseline = Column(Float, nullable=True)  # Базовая линия HRV (HRV baseline)
    sleep_hrv_sd = Column(Float, nullable=True)  # SDNN HRV (HRV standard deviation)
    rhr = Column(Integer, nullable=True)  # Пульс покоя (Resting heart rate)
    tired_rate = Column(Integer, nullable=True)  # Уровень усталости (Tiredness rate)
    training_load = Column(Float, nullable=True)  # Тренировочная нагрузка (Training load)
    training_load_ratio = Column(Float, nullable=True)  # Соотношение нагрузки (Acute:Chronic load ratio)
    performance = Column(Integer, nullable=True)  # Производительность / готовность (Performance / readiness)
    ati = Column(Float, nullable=True)  # Острая тренировочная нагрузка (Acute Training Impulse)
    cti = Column(Float, nullable=True)  # Хроническая тренировочная нагрузка (Chronic Training Impulse)
    vo2max = Column(Float, nullable=True)  # VO2max (Estimated VO2max)
    lthr = Column(Integer, nullable=True)  # Пульс лактатного порога (Lactate threshold HR)
    stamina_level = Column(Float, nullable=True)  # Уровень выносливости (Stamina level)
    ltsp = Column(Float, nullable=True)  # Темп лактатного порога, с/км (Lactate threshold pace s/km)
    stamina_level_7d = Column(Float, nullable=True)  # Тренд выносливости за 7 дней (Stamina 7-day trend)
    synced_at = Column(DateTime, default=datetime.utcnow)  # Когда данные получены (When synced)

# Модель измерения веса (Weight measurement model)
class WeightMeasurement(Base):
    __tablename__ = 'weight_measurements'
    id = Column(Integer, primary_key=True)  # Уникальный идентификатор (Unique ID)
    weight_kg = Column(Float, nullable=False)  # Вес в кг (Weight in kg)
    measured_at = Column(DateTime, default=datetime.utcnow)  # Дата измерения (Measurement date)

# Определение пути к БД и создание подключения (Database path and connection setup)
DB_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DB_DIR}/running_coach.db")
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

# Инициализация БД: создание таблиц (Initialize DB: create all tables)
def init_db():
    Base.metadata.create_all(bind=engine)

# Получение настроек пользователя из БД (Get user settings from DB)
def get_settings():
    db = SessionLocal()
    try:
        settings = db.query(UserSettings).first()
        if not settings:
            settings = UserSettings(max_hr=177, weight=85.0, max_credible_pace=3.0, max_gps_jump_m=100.0, min_hr_for_fast_pace=130)
            db.add(settings)
            db.commit()
            db.refresh(settings)
        return settings
    finally:
        db.close()
