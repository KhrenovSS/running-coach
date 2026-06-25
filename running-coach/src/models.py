from sqlalchemy import create_engine, Column, Integer, Float, String, DateTime, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import os

Base = declarative_base()

class TrainingSession(Base):
    __tablename__ = 'training_sessions'
    
    id = Column(Integer, primary_key=True)
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

class UserSettings(Base):
    __tablename__ = 'user_settings'
    id = Column(Integer, primary_key=True)
    max_hr = Column(Integer, default=177)
    weight = Column(Float, default=85.0)

class WeightMeasurement(Base):
    __tablename__ = 'weight_measurements'
    id = Column(Integer, primary_key=True)
    weight_kg = Column(Float, nullable=False)
    measured_at = Column(DateTime, default=datetime.utcnow)

DB_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DB_DIR}/running_coach.db")
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

def init_db():
    Base.metadata.create_all(bind=engine)

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
