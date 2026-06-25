# Импорт библиотек SQLAlchemy и стандартных модулей (SQLAlchemy and standard library imports)
from sqlalchemy import create_engine, Column, Integer, Float, String, DateTime, JSON
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

# Модель настроек пользователя (User settings model)
class UserSettings(Base):
    __tablename__ = 'user_settings'
    id = Column(Integer, primary_key=True)  # Уникальный идентификатор (Unique ID)
    max_hr = Column(Integer, default=177)  # Максимальная ЧСС пользователя (User max heart rate)
    weight = Column(Float, default=85.0)  # Вес пользователя в кг (User weight in kg)

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
            settings = UserSettings(max_hr=177, weight=85.0)
            db.add(settings)
            db.commit()
            db.refresh(settings)
        return settings
    finally:
        db.close()
