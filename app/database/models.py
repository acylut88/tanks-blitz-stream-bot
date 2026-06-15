"""
SQLAlchemy модели данных
"""
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship, declarative_base

Base = declarative_base()


class User(Base):
    """Модель пользователя (зрителя)"""
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    vk_id = Column(Integer, nullable=True, unique=True, index=True)  # Истинный VK ID
    nick = Column(String(100), nullable=False, unique=True, index=True)  # Текущий ник
    
    # Премиум статус
    premium_streams_left = Column(Integer, default=0)  # Жетоны ПА
    lifetime_streams_with_premium = Column(Integer, default=0)  # На скольких стримах использовал ПА
    
    # Статистика ящиков
    lifetime_boxes_opened = Column(Integer, default=0)
    pending_boxes = Column(Integer, default=0)
    
    # Lifetime статистика
    lifetime_tanks_lt = Column(Integer, default=0)
    lifetime_tanks_st = Column(Integer, default=0)
    lifetime_tanks_tt = Column(Integer, default=0)
    lifetime_tanks_pt = Column(Integer, default=0)
    
    # Временные метки (используем lambda для вызова функции при создании)
    first_seen = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    last_seen = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    # Relationships
    stream_stats = relationship("StreamStats", back_populates="user", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<User(id={self.id}, nick='{self.nick}', vk_id={self.vk_id})>"


class StreamSession(Base):
    """Модель сессии стрима"""
    __tablename__ = "stream_sessions"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    started_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    ended_at = Column(DateTime(timezone=True), nullable=True)
    
    # Победители
    winner_1_nick = Column(String(100), nullable=True)
    winner_2_nick = Column(String(100), nullable=True)
    winner_3_nick = Column(String(100), nullable=True)
    
    # Призы
    winner_1_prize = Column(String(200), default="2 ПА + Главный приз")
    winner_2_prize = Column(String(200), default="2 ПА")
    winner_3_prize = Column(String(200), default="1 ПА")
    
    # Relationships
    stream_stats = relationship("StreamStats", back_populates="session", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<StreamSession(id={self.id}, started_at={self.started_at})>"


class StreamStats(Base):
    """Модель статистики пользователя в текущем стриме"""
    __tablename__ = "stream_stats"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    session_id = Column(Integer, ForeignKey("stream_sessions.id"), nullable=False, index=True)
    
    # Текущая статистика
    current_bm = Column(Integer, default=0)  # Боевая Мощь
    activations_count = Column(Integer, default=0)  # Счётчик поставок 0-12
    last_activation_time = Column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    user = relationship("User", back_populates="stream_stats")
    session = relationship("StreamSession", back_populates="stream_stats")
    
    def __repr__(self):
        return f"<StreamStats(user_id={self.user_id}, bm={self.current_bm}, activations={self.activations_count})>"

class ProcessedMessage(Base):
    """Хранилище ID обработанных сообщений (для защиты от дублирования после перезапуска)"""
    __tablename__ = "processed_messages"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    msg_id = Column(String(50), nullable=False, unique=True, index=True)  # ID сообщения VK
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    
    def __repr__(self):
        return f"<ProcessedMessage(msg_id={self.msg_id})>"
    
class Setting(Base):
    """Хранилище настроек (key-value store)"""
    __tablename__ = "settings"
    
    key = Column(String(100), primary_key=True)
    value = Column(Text, nullable=False)  # Храним как JSON строку
    description = Column(String(255), nullable=True)
    category = Column(String(50), nullable=True)  # 'raffle', 'dispatcher', 'general'
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    def __repr__(self):
        return f"<Setting(key={self.key}, value={self.value})>"