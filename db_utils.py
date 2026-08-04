from datetime import datetime, timedelta

from crypto_utils import encrypt_session
from database import SessionLocal
from default_keywords import DEFAULT_DRIVER_KEYWORDS, DEFAULT_PASSENGER_KEYWORDS
from models import AdSettings, AdTargetGroup, BlockedSender, DriverKeyword, ExcludedGroup, Keyword, User

MAX_KEYWORD_LENGTH = 200
TRIAL_DAYS = 3
MAX_AD_TEXT_LENGTH = 1000
MIN_AD_INTERVAL_MINUTES = 15
DEFAULT_AD_INTERVAL_MINUTES = 60


def get_user(tg_user_id: int) -> User | None:
    db = SessionLocal()
    try:
        return db.query(User).filter_by(tg_user_id=tg_user_id).first()
    finally:
        db.close()


def _add_default_keywords(db, user_id: int) -> None:
    db.bulk_save_objects([Keyword(user_id=user_id, word=w) for w in DEFAULT_PASSENGER_KEYWORDS])
    db.bulk_save_objects([DriverKeyword(user_id=user_id, word=w) for w in DEFAULT_DRIVER_KEYWORDS])


def get_or_create_user(tg_user_id: int) -> User:
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(tg_user_id=tg_user_id).first()
        if not user:
            user = User(tg_user_id=tg_user_id)
            db.add(user)
            db.commit()
            db.refresh(user)
            _add_default_keywords(db, user.id)
            user.default_keywords_seeded = True
            db.commit()
            db.refresh(user)
        return user
    finally:
        db.close()


def seed_default_keywords_for_existing_users() -> int:
    """Ilgari ro'yxatdan o'tgan, lekin hali hech qanday kalit so'z qo'shmagan
    foydalanuvchilarga dastlabki ro'yxatni beradi. Faqat bir marta ishlaydi
    (har bir foydalanuvchi uchun `default_keywords_seeded` bayrog'i bilan belgilanadi),
    shu sababli o'zi ataylab bo'shatib qo'ygan ro'yxatni qayta to'ldirmaydi."""
    db = SessionLocal()
    try:
        users = db.query(User).filter_by(default_keywords_seeded=False).all()
        seeded = 0
        for user in users:
            has_kw = db.query(Keyword).filter_by(user_id=user.id).first() is not None
            has_dkw = db.query(DriverKeyword).filter_by(user_id=user.id).first() is not None
            if not has_kw and not has_dkw:
                _add_default_keywords(db, user.id)
                seeded += 1
            user.default_keywords_seeded = True
        db.commit()
        return seeded
    finally:
        db.close()


def save_session(tg_user_id: int, phone: str, session_string: str) -> None:
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(tg_user_id=tg_user_id).first()
        user.phone = phone
        user.session_string = encrypt_session(session_string)
        user.is_active = True
        db.commit()
    finally:
        db.close()


def set_order_group(tg_user_id: int, group_id: int) -> bool:
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(tg_user_id=tg_user_id).first()
        if not user or not user.session_string:
            return False
        user.order_group_id = group_id
        db.commit()
        return True
    finally:
        db.close()


def clear_session(tg_user_id: int) -> None:
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(tg_user_id=tg_user_id).first()
        if user:
            user.session_string = None
            user.is_active = False
            db.commit()
    finally:
        db.close()


def clear_order_group(tg_user_id: int) -> bool:
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(tg_user_id=tg_user_id).first()
        if not user or not user.order_group_id:
            return False
        user.order_group_id = None
        db.commit()
        return True
    finally:
        db.close()


def start_trial(tg_user_id: int) -> None:
    """Sessiya birinchi marta ulanganda bepul sinov muddatini beradi."""
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(tg_user_id=tg_user_id).first()
        if user and user.subscription_expires_at is None:
            user.subscription_expires_at = datetime.utcnow() + timedelta(days=TRIAL_DAYS)
            db.commit()
    finally:
        db.close()


def extend_subscription(tg_user_id: int, days: int) -> User | None:
    """Obunani uzaytiradi (agar muddati o'tgan bo'lsa, bugundan boshlab hisoblaydi)."""
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(tg_user_id=tg_user_id).first()
        if not user:
            return None
        now = datetime.utcnow()
        base = user.subscription_expires_at if user.subscription_expires_at and user.subscription_expires_at > now else now
        user.subscription_expires_at = base + timedelta(days=days)
        user.is_active = True
        db.commit()
        db.refresh(user)
        db.expunge(user)
        return user
    finally:
        db.close()


def is_subscription_active(user) -> bool:
    return bool(user.subscription_expires_at and user.subscription_expires_at > datetime.utcnow())


def format_subscription_status(user) -> str:
    if not user.subscription_expires_at:
        return "obuna yo'q"
    delta = user.subscription_expires_at - datetime.utcnow()
    seconds_left = delta.total_seconds()
    if seconds_left <= 0:
        return "muddati tugagan"
    days = delta.days
    if days > 0:
        return f"{days} kun qoldi"
    hours = delta.seconds // 3600
    return f"{hours} soat qoldi"


def get_all_users() -> list[User]:
    db = SessionLocal()
    try:
        users = db.query(User).order_by(User.created_at.desc()).all()
        db.expunge_all()
        return users
    finally:
        db.close()


def get_expired_active_users() -> list[User]:
    """Obunasi tugagan, lekin hali faol/ulangan foydalanuvchilar (sweep uchun)."""
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        users = (
            db.query(User)
            .filter(User.is_active.is_(True), User.session_string.isnot(None))
            .filter((User.subscription_expires_at.is_(None)) | (User.subscription_expires_at <= now))
            .all()
        )
        db.expunge_all()
        return users
    finally:
        db.close()


def add_keyword(tg_user_id: int, word: str) -> bool:
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(tg_user_id=tg_user_id).first()
        if not user or not user.session_string:
            return False
        word = word.strip().lower()
        if not word or len(word) > MAX_KEYWORD_LENGTH:
            return False
        exists = db.query(Keyword).filter_by(user_id=user.id, word=word).first()
        if exists:
            return False
        db.add(Keyword(user_id=user.id, word=word))
        db.commit()
        return True
    finally:
        db.close()


def remove_keyword(tg_user_id: int, word: str) -> bool:
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(tg_user_id=tg_user_id).first()
        if not user:
            return False
        word = word.strip().lower()
        kw = db.query(Keyword).filter_by(user_id=user.id, word=word).first()
        if not kw:
            return False
        db.delete(kw)
        db.commit()
        return True
    finally:
        db.close()


def list_keywords(tg_user_id: int) -> list[str]:
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(tg_user_id=tg_user_id).first()
        if not user:
            return []
        return [k.word for k in user.keywords]
    finally:
        db.close()


def add_driver_keyword(tg_user_id: int, word: str) -> bool:
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(tg_user_id=tg_user_id).first()
        if not user or not user.session_string:
            return False
        word = word.strip().lower()
        if not word or len(word) > MAX_KEYWORD_LENGTH:
            return False
        exists = db.query(DriverKeyword).filter_by(user_id=user.id, word=word).first()
        if exists:
            return False
        db.add(DriverKeyword(user_id=user.id, word=word))
        db.commit()
        return True
    finally:
        db.close()


def remove_driver_keyword(tg_user_id: int, word: str) -> bool:
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(tg_user_id=tg_user_id).first()
        if not user:
            return False
        word = word.strip().lower()
        kw = db.query(DriverKeyword).filter_by(user_id=user.id, word=word).first()
        if not kw:
            return False
        db.delete(kw)
        db.commit()
        return True
    finally:
        db.close()


def list_driver_keywords(tg_user_id: int) -> list[str]:
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(tg_user_id=tg_user_id).first()
        if not user:
            return []
        return [k.word for k in user.driver_keywords]
    finally:
        db.close()


def get_active_users() -> list[User]:
    db = SessionLocal()
    try:
        users = (
            db.query(User)
            .filter(User.is_active.is_(True), User.session_string.isnot(None))
            .all()
        )
        db.expunge_all()
        return users
    finally:
        db.close()


def toggle_active(tg_user_id: int, active: bool) -> None:
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(tg_user_id=tg_user_id).first()
        if user:
            user.is_active = active
            db.commit()
    finally:
        db.close()


def toggle_assume_passenger(tg_user_id: int, value: bool) -> None:
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(tg_user_id=tg_user_id).first()
        if user:
            user.assume_passenger_if_unmatched = value
            db.commit()
    finally:
        db.close()


def toggle_excluded_group(user_id: int, chat_id: int) -> bool:
    """Guruh holatini almashtiradi. True = endi istisno qilindi, False = endi kuzatiladi."""
    db = SessionLocal()
    try:
        existing = db.query(ExcludedGroup).filter_by(user_id=user_id, chat_id=chat_id).first()
        if existing:
            db.delete(existing)
            db.commit()
            return False
        db.add(ExcludedGroup(user_id=user_id, chat_id=chat_id))
        db.commit()
        return True
    finally:
        db.close()


def get_excluded_group_ids(user_id: int) -> set[int]:
    db = SessionLocal()
    try:
        rows = db.query(ExcludedGroup.chat_id).filter_by(user_id=user_id).all()
        return {row[0] for row in rows}
    finally:
        db.close()


def search_users(query: str) -> list[User]:
    query = query.strip().lower()
    db = SessionLocal()
    try:
        users = (
            db.query(User)
            .filter(User.session_string.isnot(None))
            .order_by(User.created_at.desc())
            .all()
        )
        db.expunge_all()
        return [
            u for u in users
            if query in str(u.tg_user_id) or (u.phone and query in u.phone.lower())
        ]
    finally:
        db.close()


def get_expiring_soon_users(days: int = 3) -> list[User]:
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        soon = now + timedelta(days=days)
        users = (
            db.query(User)
            .filter(User.session_string.isnot(None))
            .filter(User.subscription_expires_at.isnot(None))
            .filter(User.subscription_expires_at > now, User.subscription_expires_at <= soon)
            .order_by(User.subscription_expires_at.asc())
            .all()
        )
        db.expunge_all()
        return users
    finally:
        db.close()


def block_sender(tg_user_id: int, sender_id: int, sender_name: str | None = None) -> bool:
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(tg_user_id=tg_user_id).first()
        if not user:
            return False
        exists = db.query(BlockedSender).filter_by(user_id=user.id, sender_id=sender_id).first()
        if exists:
            return False
        db.add(BlockedSender(user_id=user.id, sender_id=sender_id, sender_name=sender_name))
        db.commit()
        return True
    finally:
        db.close()


def unblock_sender(tg_user_id: int, sender_id: int) -> bool:
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(tg_user_id=tg_user_id).first()
        if not user:
            return False
        row = db.query(BlockedSender).filter_by(user_id=user.id, sender_id=sender_id).first()
        if not row:
            return False
        db.delete(row)
        db.commit()
        return True
    finally:
        db.close()


def is_sender_blocked(user_id: int, sender_id: int) -> bool:
    """user_id — users.id (ichki id), sender_id — bloklangan Telegram foydalanuvchi ID."""
    db = SessionLocal()
    try:
        return (
            db.query(BlockedSender).filter_by(user_id=user_id, sender_id=sender_id).first()
            is not None
        )
    finally:
        db.close()


def list_blocked_senders(tg_user_id: int) -> list[BlockedSender]:
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(tg_user_id=tg_user_id).first()
        if not user:
            return []
        rows = (
            db.query(BlockedSender)
            .filter_by(user_id=user.id)
            .order_by(BlockedSender.created_at.desc())
            .all()
        )
        db.expunge_all()
        return rows
    finally:
        db.close()


def _get_or_create_ad_settings(db, user: User) -> AdSettings:
    settings = db.query(AdSettings).filter_by(user_id=user.id).first()
    if not settings:
        settings = AdSettings(user_id=user.id, interval_minutes=DEFAULT_AD_INTERVAL_MINUTES)
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings


def get_ad_settings(tg_user_id: int) -> AdSettings | None:
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(tg_user_id=tg_user_id).first()
        if not user:
            return None
        settings = _get_or_create_ad_settings(db, user)
        db.expunge(settings)
        return settings
    finally:
        db.close()


def set_ad_text(tg_user_id: int, text: str) -> bool:
    text = text.strip()
    if not text or len(text) > MAX_AD_TEXT_LENGTH:
        return False
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(tg_user_id=tg_user_id).first()
        if not user:
            return False
        settings = _get_or_create_ad_settings(db, user)
        settings.text = text
        db.commit()
        return True
    finally:
        db.close()


def set_ad_interval(tg_user_id: int, minutes: int) -> bool:
    if minutes < MIN_AD_INTERVAL_MINUTES:
        return False
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(tg_user_id=tg_user_id).first()
        if not user:
            return False
        settings = _get_or_create_ad_settings(db, user)
        settings.interval_minutes = minutes
        db.commit()
        return True
    finally:
        db.close()


def toggle_ad_active(tg_user_id: int, value: bool) -> bool:
    """Yoqish faqat matn va kamida bitta guruh belgilangan bo'lsa muvaffaqiyatli bo'ladi."""
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(tg_user_id=tg_user_id).first()
        if not user:
            return False
        settings = _get_or_create_ad_settings(db, user)
        if value:
            has_target = db.query(AdTargetGroup).filter_by(user_id=user.id).first() is not None
            if not settings.text or not has_target:
                return False
        settings.is_active = value
        db.commit()
        return True
    finally:
        db.close()


def toggle_ad_target_group(user_id: int, chat_id: int) -> bool:
    """True = endi tanlandi, False = endi olib tashlandi."""
    db = SessionLocal()
    try:
        existing = db.query(AdTargetGroup).filter_by(user_id=user_id, chat_id=chat_id).first()
        if existing:
            db.delete(existing)
            db.commit()
            return False
        db.add(AdTargetGroup(user_id=user_id, chat_id=chat_id))
        db.commit()
        return True
    finally:
        db.close()


def get_ad_target_group_ids(user_id: int) -> set[int]:
    db = SessionLocal()
    try:
        rows = db.query(AdTargetGroup.chat_id).filter_by(user_id=user_id).all()
        return {row[0] for row in rows}
    finally:
        db.close()


def update_ad_last_sent(user_id: int, when) -> None:
    db = SessionLocal()
    try:
        settings = db.query(AdSettings).filter_by(user_id=user_id).first()
        if settings:
            settings.last_sent_at = when
            db.commit()
    finally:
        db.close()


def get_users_with_active_ads() -> list[User]:
    db = SessionLocal()
    try:
        users = (
            db.query(User)
            .join(AdSettings)
            .filter(
                User.is_active.is_(True),
                User.session_string.isnot(None),
                AdSettings.is_active.is_(True),
            )
            .all()
        )
        db.expunge_all()
        return users
    finally:
        db.close()


def find_user_by_id(user_id: int) -> User | None:
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(id=user_id).first()
        if user:
            db.expunge(user)
        return user
    finally:
        db.close()
