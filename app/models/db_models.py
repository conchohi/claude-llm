"""
SQLAlchemy 데이터베이스 모델.
API 키와 대화 세션을 관계형 데이터베이스에 저장합니다.
"""

from datetime import datetime
from typing import Optional
from sqlalchemy import Column, String, Integer, DateTime, Boolean, Text, ForeignKey, JSON
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func

Base = declarative_base()


class APIKeyModel(Base):
    """API 키 테이블 모델."""

    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key_hash = Column(String(64), unique=True, nullable=False, index=True)
    user_id = Column(String(255), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    created_at = Column(DateTime, nullable=False, default=func.now())
    last_used = Column(DateTime, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    rate_limit = Column(Integer, nullable=True)


class ConversationSessionModel(Base):
    """대화 세션 테이블 모델."""

    __tablename__ = "conversation_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(64), unique=True, nullable=False, index=True)
    user_id = Column(String(255), nullable=False, index=True)
    created_at = Column(DateTime, nullable=False, default=func.now())
    updated_at = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now())
    # 관계
    messages = relationship("ConversationMessageModel", back_populates="session", cascade="all, delete-orphan", order_by="ConversationMessageModel.timestamp")


class ConversationMessageModel(Base):
    """대화 메시지 테이블 모델."""

    __tablename__ = "conversation_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(64), nullable=False, index=True)
    session_id = Column(String(64), ForeignKey("conversation_sessions.session_id", ondelete="SET NULL"), nullable=True, index=True)
    role = Column(String(50), nullable=False)  # 'user' or 'assistant'
    content = Column(Text, nullable=False)
    timestamp = Column(DateTime, nullable=False, default=func.now())
    mcp_context = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)
    process_time_ms = Column(Integer, nullable=True)

    # 관계
    session = relationship("ConversationSessionModel", back_populates="messages")
