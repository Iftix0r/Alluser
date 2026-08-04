from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    tg_user_id = Column(BigInteger, unique=True, nullable=False)
    phone = Column(String, nullable=True)
    session_string = Column(Text, nullable=True)
    order_group_id = Column(BigInteger, nullable=True)
    is_active = Column(Boolean, default=True)
    assume_passenger_if_unmatched = Column(Boolean, default=False, nullable=False)
    subscription_expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    keywords = relationship("Keyword", back_populates="user", cascade="all, delete-orphan")
    driver_keywords = relationship("DriverKeyword", back_populates="user", cascade="all, delete-orphan")
    excluded_groups = relationship("ExcludedGroup", back_populates="user", cascade="all, delete-orphan")
    blocked_senders = relationship("BlockedSender", back_populates="user", cascade="all, delete-orphan")


class Keyword(Base):
    __tablename__ = "keywords"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    word = Column(String, nullable=False)

    user = relationship("User", back_populates="keywords")


class DriverKeyword(Base):
    __tablename__ = "driver_keywords"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    word = Column(String, nullable=False)

    user = relationship("User", back_populates="driver_keywords")


class ExcludedGroup(Base):
    __tablename__ = "excluded_groups"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    chat_id = Column(BigInteger, nullable=False)

    user = relationship("User", back_populates="excluded_groups")


class BlockedSender(Base):
    __tablename__ = "blocked_senders"
    __table_args__ = (UniqueConstraint("user_id", "sender_id", name="uq_blocked_user_sender"),)

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    sender_id = Column(BigInteger, nullable=False)
    sender_name = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="blocked_senders")
