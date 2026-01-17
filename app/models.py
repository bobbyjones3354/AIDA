from sqlalchemy import Column, Integer, String, DateTime, UniqueConstraint
from sqlalchemy.ext.declarative import declarative_base
import datetime

Base = declarative_base()

# 3. models.py ƒ?" Update schema with dual sentiment fields
class Article(Base):
    __tablename__ = "articles"
    __table_args__ = (UniqueConstraint("url", name="uq_articles_url"),)
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String)
    summary = Column(String)
    sentiment_emotional = Column(String)
    sentiment_contextual = Column(String)
    sentiment_confidence = Column(String)
    impact_level = Column(String)
    impact_reason = Column(String)
    image_url = Column(String)
    source = Column(String)
    url = Column(String)
    category = Column(String)
    country = Column(String)
    published_at = Column(DateTime, default=datetime.datetime.utcnow)


class UserStreak(Base):
    __tablename__ = "user_streaks"
    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String, unique=True, index=True, nullable=False)
    streak_count = Column(Integer, default=0)
    last_checkin_date = Column(String)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)


class UserRead(Base):
    __tablename__ = "user_reads"
    __table_args__ = (UniqueConstraint("device_id", "article_url", "read_date", name="uq_user_reads"),)
    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String, index=True, nullable=False)
    article_url = Column(String, nullable=False)
    read_date = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
