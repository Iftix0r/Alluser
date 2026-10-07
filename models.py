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
    default_keywords_seeded = Column(Boolean, default=False, nullable=False)
    subscription_expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    greeting_text = Column(Text, nullable=True)
    greeting_enabled = Column(Boolean, default=True, nullable=False)
    customer_greeting_text = Column(Text, nullable=True)
    customer_greeting_enabled = Column(Boolean, default=False, nullable=False)
    renewal_notice_sent_at = Column(DateTime, nullable=True)
    rich_order_format = Column(Boolean, default=False, nullable=False)
    whitelist_only_groups = Column(Boolean, default=False, nullable=False)

    keywords = relationship("Keyword", back_populates="user", cascade="all, delete-orphan")
    driver_keywords = relationship("DriverKeyword", back_populates="user", cascade="all, delete-orphan")
    excluded_groups = relationship("ExcludedGroup", back_populates="user", cascade="all, delete-orphan")
    blocked_senders = relationship("BlockedSender", back_populates="user", cascade="all, delete-orphan")
    sender_cooldowns = relationship("SenderCooldown", back_populates="user", cascade="all, delete-orphan")
    team_admins = relationship("TeamAdmin", back_populates="user", cascade="all, delete-orphan")
    allowed_groups = relationship("AllowedGroup", back_populates="user", cascade="all, delete-orphan")
    ad_settings = relationship(
        "AdSettings", back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    ad_target_groups = relationship("AdTargetGroup", back_populates="user", cascade="all, delete-orphan")
    extra_accounts = relationship("ExtraAccount", back_populates="user", cascade="all, delete-orphan")
    extra_order_groups = relationship("ExtraOrderGroup", back_populates="user", cascade="all, delete-orphan")
    order_logs = relationship("OrderLog", back_populates="user", cascade="all, delete-orphan")
    ad_logs = relationship("AdLog", back_populates="user", cascade="all, delete-orphan")
    greeting_logs = relationship("GreetingLog", back_populates="user", cascade="all, delete-orphan")
    order_cards = relationship("OrderCard", back_populates="user", cascade="all, delete-orphan")


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


class SenderCooldown(Base):
    """Bitta yuboruvchidan oxirgi marta qachon buyurtma yuborilganini saqlaydi -
    bir vaqtning o'zida ko'plab zakaz kelib tushmasligi uchun (cooldown)."""

    __tablename__ = "sender_cooldowns"
    __table_args__ = (UniqueConstraint("user_id", "sender_id", name="uq_cooldown_user_sender"),)

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    sender_id = Column(BigInteger, nullable=False)
    last_order_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="sender_cooldowns")


class TeamAdmin(Base):
    """Foydalanuvchi (bot operatori) o'ziga qo'shgan qo'shimcha adminlar - ular ham
    buyurtma kartasidagi \"⚙️ Amallar\" menyusidan (bloklash va h.k.) foydalana oladi."""

    __tablename__ = "team_admins"
    __table_args__ = (UniqueConstraint("user_id", "admin_tg_id", name="uq_team_admin_user_admin"),)

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    admin_tg_id = Column(BigInteger, nullable=False)
    admin_name = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="team_admins")


class AllowedGroup(Base):
    """\"Faqat ruxsat berilgan guruhlar\" rejimi (whitelist_only_groups) yoqilganda -
    hisob a'zo bo'lgan ko'plab guruhdan faqat shu ro'yxatdagilaridan buyurtma qidiriladi,
    qolganlari (a'zo bo'lsa ham) e'tiborsiz qoldiriladi."""

    __tablename__ = "allowed_groups"
    __table_args__ = (UniqueConstraint("user_id", "chat_id", name="uq_allowed_user_chat"),)

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    chat_id = Column(BigInteger, nullable=False)
    username = Column(String, nullable=True)
    title = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="allowed_groups")


class AdSettings(Base):
    __tablename__ = "ad_settings"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True)
    text = Column(Text, nullable=True)
    interval_minutes = Column(Integer, default=60, nullable=False)
    is_active = Column(Boolean, default=False, nullable=False)
    last_sent_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="ad_settings")


class AdTargetGroup(Base):
    __tablename__ = "ad_target_groups"
    __table_args__ = (UniqueConstraint("user_id", "chat_id", name="uq_ad_target_user_chat"),)

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    chat_id = Column(BigInteger, nullable=False)

    user = relationship("User", back_populates="ad_target_groups")


class ExtraOrderGroup(Base):
    __tablename__ = "extra_order_groups"
    __table_args__ = (UniqueConstraint("user_id", "chat_id", name="uq_extra_order_user_chat"),)

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    chat_id = Column(BigInteger, nullable=False)
    title = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="extra_order_groups")


class OrderLog(Base):
    """Har bir muvaffaqiyatli yuborilgan buyurtma uchun bitta yozuv — statistika uchun."""

    __tablename__ = "order_logs"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="order_logs")


class AdLog(Base):
    """Har bir muvaffaqiyatli yuborilgan reklama xabari uchun bitta yozuv — statistika uchun."""

    __tablename__ = "ad_logs"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="ad_logs")


class GreetingLog(Base):
    """Har bir shaxsiy suhbatdoshga oxirgi marta qachon avtomatik salomlashuv
    xabari yuborilganini saqlaydi (bir necha kunda bir marta yuborish uchun)."""

    __tablename__ = "greeting_logs"
    __table_args__ = (UniqueConstraint("user_id", "sender_id", name="uq_greeting_user_sender"),)

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    sender_id = Column(BigInteger, nullable=False)
    last_sent_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="greeting_logs")


class OrderCard(Base):
    """\"Boy\" formatdagi buyurtma xabari — \"Zakazni yopish\" tugmasi bilan kuzatiladi
    (bir nechta guruhga yuborilgan bo'lsa, yopilganda barcha nusxalar yangilanadi)."""

    __tablename__ = "order_cards"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    sender_tg_id = Column(BigInteger, nullable=True)
    sender_name = Column(String, nullable=True)
    status = Column(String, nullable=False, default="open")
    created_at = Column(DateTime, default=datetime.utcnow)
    closed_at = Column(DateTime, nullable=True)
    closed_by = Column(String, nullable=True)

    user = relationship("User", back_populates="order_cards")
    messages = relationship("OrderCardMessage", back_populates="order_card", cascade="all, delete-orphan")


class OrderCardMessage(Base):
    """Bitta OrderCard bir nechta guruhga yuborilgan bo'lsa, har bir nusxaning
    chat_id/message_id juftligi — yopilganda hammasini tahrirlash uchun."""

    __tablename__ = "order_card_messages"

    id = Column(Integer, primary_key=True)
    order_card_id = Column(Integer, ForeignKey("order_cards.id"), nullable=False)
    chat_id = Column(BigInteger, nullable=False)
    message_id = Column(Integer, nullable=False)

    order_card = relationship("OrderCard", back_populates="messages")


class ExtraAccount(Base):
    __tablename__ = "extra_accounts"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    phone = Column(String, nullable=False)
    session_string = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="extra_accounts")
