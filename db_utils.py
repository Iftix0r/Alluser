from datetime import datetime, timedelta

from sqlalchemy import func

from crypto_utils import encrypt_session
from database import SessionLocal
from default_keywords import DEFAULT_DRIVER_KEYWORDS, DEFAULT_PASSENGER_KEYWORDS
from models import (
    AdLog,
    AdSettings,
    AdTargetGroup,
    BlockedSender,
    DriverKeyword,
    ExcludedGroup,
    ExtraAccount,
    ExtraOrderGroup,
    GreetingLog,
    AllowedGroup,
    Keyword,
    OrderCard,
    OrderCardMessage,
    OrderLog,
    SenderCooldown,
    TeamAdmin,
    User,
)

MAX_KEYWORD_LENGTH = 200
TRIAL_DAYS = 3
MAX_AD_TEXT_LENGTH = 1000
MIN_AD_INTERVAL_MINUTES = 15
DEFAULT_AD_INTERVAL_MINUTES = 60
MAX_EXTRA_ORDER_GROUPS = 5
UNLIMITED_SUBSCRIPTION_DAYS = 3650
UNLIMITED_DISPLAY_THRESHOLD_DAYS = 3000
_STALE_DRIVER_KEYWORDS = {"taksi"}

MAX_GREETING_TEXT_LENGTH = 2000
GREETING_COOLDOWN_DAYS = 2


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


def remove_stale_driver_keywords() -> int:
    """"taksi" so'zi ilgari xato ravishda ham yo'lovchi, ham haydovchi kalit so'zi
    sifatida default ro'yxatga qo'shilgan edi — natijada "taksi" so'zi bor deyarli
    barcha haqiqiy buyurtmalar haydovchi xabari deb chiqarib tashlanardi. Bu allaqachon
    bazaga yozilgan eski yozuvlarni tozalaydi (o'chirilgan qatorlar sonini qaytaradi)."""
    db = SessionLocal()
    try:
        rows = db.query(DriverKeyword).filter(DriverKeyword.word.in_(_STALE_DRIVER_KEYWORDS)).all()
        count = len(rows)
        for row in rows:
            db.delete(row)
        db.commit()
        return count
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
        user.renewal_notice_sent_at = None
        db.commit()
        db.refresh(user)
        db.expunge(user)
        return user
    finally:
        db.close()


def is_subscription_active(user) -> bool:
    return bool(user.subscription_expires_at and user.subscription_expires_at > datetime.utcnow())


def set_unlimited_subscription(tg_user_id: int) -> User | None:
    """Foydalanuvchiga muddatsiz (amalda ~10 yillik) obuna beradi."""
    return extend_subscription(tg_user_id, UNLIMITED_SUBSCRIPTION_DAYS)


def revoke_subscription(tg_user_id: int) -> User | None:
    """Obunani darhol bekor qiladi (muddatini hozirgi vaqtga o'rnatadi)."""
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(tg_user_id=tg_user_id).first()
        if not user:
            return None
        user.subscription_expires_at = datetime.utcnow()
        db.commit()
        db.refresh(user)
        db.expunge(user)
        return user
    finally:
        db.close()


def delete_user(user_id: int) -> bool:
    """Foydalanuvchini va unga tegishli barcha ma'lumotlarni (kalit so'zlar, guruhlar,
    qo'shimcha akkauntlar va h.k.) butunlay o'chiradi. Qaytarib bo'lmaydi."""
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(id=user_id).first()
        if not user:
            return False
        db.delete(user)
        db.commit()
        return True
    finally:
        db.close()


def format_subscription_status(user) -> str:
    if not user.subscription_expires_at:
        return "obuna yo'q"
    delta = user.subscription_expires_at - datetime.utcnow()
    seconds_left = delta.total_seconds()
    if seconds_left <= 0:
        return "muddati tugagan"
    days = delta.days
    if days >= UNLIMITED_DISPLAY_THRESHOLD_DAYS:
        return "♾ cheksiz"
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


def toggle_whitelist_only_groups(tg_user_id: int, value: bool) -> None:
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(tg_user_id=tg_user_id).first()
        if user:
            user.whitelist_only_groups = value
            db.commit()
    finally:
        db.close()


def add_allowed_group(user_id: int, chat_id: int, username: str | None, title: str | None) -> bool:
    """Ruxsat berilgan guruhlar ro'yxatiga qo'shadi. True = yangi qo'shildi."""
    db = SessionLocal()
    try:
        existing = db.query(AllowedGroup).filter_by(user_id=user_id, chat_id=chat_id).first()
        if existing:
            return False
        db.add(AllowedGroup(user_id=user_id, chat_id=chat_id, username=username, title=title))
        db.commit()
        return True
    finally:
        db.close()


def remove_allowed_group(user_id: int, chat_id: int) -> bool:
    db = SessionLocal()
    try:
        existing = db.query(AllowedGroup).filter_by(user_id=user_id, chat_id=chat_id).first()
        if not existing:
            return False
        db.delete(existing)
        db.commit()
        return True
    finally:
        db.close()


def list_allowed_groups(user_id: int) -> list[AllowedGroup]:
    db = SessionLocal()
    try:
        rows = db.query(AllowedGroup).filter_by(user_id=user_id).all()
        db.expunge_all()
        return rows
    finally:
        db.close()


def get_allowed_group_ids(user_id: int) -> set[int]:
    db = SessionLocal()
    try:
        rows = db.query(AllowedGroup.chat_id).filter_by(user_id=user_id).all()
        return {row[0] for row in rows}
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


def exclude_group(user_id: int, chat_id: int) -> bool:
    """Guruhni istisno (bloklangan) ro'yxatiga qo'shadi - allaqachon bo'lsa qayta qo'shmaydi.
    True = yangi bloklandi, False = allaqachon bloklangan edi."""
    db = SessionLocal()
    try:
        existing = db.query(ExcludedGroup).filter_by(user_id=user_id, chat_id=chat_id).first()
        if existing:
            return False
        db.add(ExcludedGroup(user_id=user_id, chat_id=chat_id))
        db.commit()
        return True
    finally:
        db.close()


def seconds_since_last_order(user_id: int, sender_id: int) -> float | None:
    """Shu yuboruvchidan (sender) shu foydalanuvchi (user) uchun oxirgi marta
    qachon buyurtma yuborilganini soniyada qaytaradi. Hali bo'lmagan bo'lsa - None."""
    db = SessionLocal()
    try:
        row = db.query(SenderCooldown).filter_by(user_id=user_id, sender_id=sender_id).first()
        if not row:
            return None
        return (datetime.utcnow() - row.last_order_at).total_seconds()
    finally:
        db.close()


def mark_sender_order_sent(user_id: int, sender_id: int) -> None:
    """Shu yuboruvchidan hozir buyurtma yuborilganini belgilaydi (cooldown uchun)."""
    db = SessionLocal()
    try:
        row = db.query(SenderCooldown).filter_by(user_id=user_id, sender_id=sender_id).first()
        if row:
            row.last_order_at = datetime.utcnow()
        else:
            db.add(SenderCooldown(user_id=user_id, sender_id=sender_id, last_order_at=datetime.utcnow()))
        db.commit()
    finally:
        db.close()


def add_team_admin(user_id: int, admin_tg_id: int, admin_name: str | None = None) -> bool:
    """Foydalanuvchiga qo'shimcha admin qo'shadi. True = yangi qo'shildi."""
    db = SessionLocal()
    try:
        existing = db.query(TeamAdmin).filter_by(user_id=user_id, admin_tg_id=admin_tg_id).first()
        if existing:
            return False
        db.add(TeamAdmin(user_id=user_id, admin_tg_id=admin_tg_id, admin_name=admin_name))
        db.commit()
        return True
    finally:
        db.close()


def remove_team_admin(user_id: int, admin_tg_id: int) -> bool:
    db = SessionLocal()
    try:
        existing = db.query(TeamAdmin).filter_by(user_id=user_id, admin_tg_id=admin_tg_id).first()
        if not existing:
            return False
        db.delete(existing)
        db.commit()
        return True
    finally:
        db.close()


def list_team_admins(user_id: int) -> list[TeamAdmin]:
    db = SessionLocal()
    try:
        return db.query(TeamAdmin).filter_by(user_id=user_id).all()
    finally:
        db.close()


def is_team_admin(user_id: int, tg_id: int) -> bool:
    db = SessionLocal()
    try:
        return db.query(TeamAdmin).filter_by(user_id=user_id, admin_tg_id=tg_id).first() is not None
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


def get_users_needing_renewal_reminder(days: int = 3) -> list[User]:
    """get_expiring_soon_users bilan bir xil, lekin shu muddat uchun eslatma hali
    yuborilmagan foydalanuvchilarni qaytaradi (bir marta yuboriladi, har tekshiruvda emas)."""
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        soon = now + timedelta(days=days)
        users = (
            db.query(User)
            .filter(User.session_string.isnot(None))
            .filter(User.is_active.is_(True))
            .filter(User.subscription_expires_at.isnot(None))
            .filter(User.subscription_expires_at > now, User.subscription_expires_at <= soon)
            .filter(User.renewal_notice_sent_at.is_(None))
            .order_by(User.subscription_expires_at.asc())
            .all()
        )
        db.expunge_all()
        return users
    finally:
        db.close()


def mark_renewal_reminder_sent(user_id: int) -> None:
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(id=user_id).first()
        if user:
            user.renewal_notice_sent_at = datetime.utcnow()
            db.commit()
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


def remove_ad_target_group(user_id: int, chat_id: int) -> bool:
    """Reklama nishon guruhini ro'yxatdan olib tashlaydi (masalan, doimiy yetib
    bo'lmaydigan/tark etilgan guruh uchun avtomatik tozalashda ishlatiladi)."""
    db = SessionLocal()
    try:
        existing = db.query(AdTargetGroup).filter_by(user_id=user_id, chat_id=chat_id).first()
        if not existing:
            return False
        db.delete(existing)
        db.commit()
        return True
    finally:
        db.close()


def set_greeting_text(tg_user_id: int, text: str) -> bool:
    text = text.strip()
    if not text or len(text) > MAX_GREETING_TEXT_LENGTH:
        return False
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(tg_user_id=tg_user_id).first()
        if not user:
            return False
        user.greeting_text = text
        db.commit()
        return True
    finally:
        db.close()


def clear_greeting_text(tg_user_id: int) -> None:
    """Sozlangan matnni tozalaydi, standart (platforma) matniga qaytaradi."""
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(tg_user_id=tg_user_id).first()
        if user:
            user.greeting_text = None
            db.commit()
    finally:
        db.close()


def toggle_greeting_enabled(tg_user_id: int) -> bool:
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(tg_user_id=tg_user_id).first()
        if not user:
            return True
        user.greeting_enabled = not user.greeting_enabled
        db.commit()
        return user.greeting_enabled
    finally:
        db.close()


def set_customer_greeting_text(tg_user_id: int, text: str) -> bool:
    text = text.strip()
    if not text or len(text) > MAX_GREETING_TEXT_LENGTH:
        return False
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(tg_user_id=tg_user_id).first()
        if not user:
            return False
        user.customer_greeting_text = text
        db.commit()
        return True
    finally:
        db.close()


def clear_customer_greeting_text(tg_user_id: int) -> None:
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(tg_user_id=tg_user_id).first()
        if user:
            user.customer_greeting_text = None
            db.commit()
    finally:
        db.close()


def toggle_customer_greeting_enabled(tg_user_id: int) -> bool:
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(tg_user_id=tg_user_id).first()
        if not user:
            return False
        user.customer_greeting_enabled = not user.customer_greeting_enabled
        db.commit()
        return user.customer_greeting_enabled
    finally:
        db.close()


def should_send_greeting(user_id: int, sender_id: int) -> bool:
    """True bo'lsa, shu jo'natuvchiga oxirgi GREETING_COOLDOWN_DAYS kun ichida
    salomlashuv yuborilmagan (yoki umuman yuborilmagan)."""
    db = SessionLocal()
    try:
        row = db.query(GreetingLog).filter_by(user_id=user_id, sender_id=sender_id).first()
        if not row:
            return True
        return datetime.utcnow() - row.last_sent_at >= timedelta(days=GREETING_COOLDOWN_DAYS)
    finally:
        db.close()


def record_greeting_sent(user_id: int, sender_id: int) -> None:
    db = SessionLocal()
    try:
        row = db.query(GreetingLog).filter_by(user_id=user_id, sender_id=sender_id).first()
        if row:
            row.last_sent_at = datetime.utcnow()
        else:
            db.add(GreetingLog(user_id=user_id, sender_id=sender_id, last_sent_at=datetime.utcnow()))
        db.commit()
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


def add_extra_account(tg_user_id: int, phone: str, session_string: str) -> "ExtraAccount":
    from crypto_utils import encrypt_session
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(tg_user_id=tg_user_id).first()
        acc = ExtraAccount(user_id=user.id, phone=phone, session_string=encrypt_session(session_string))
        db.add(acc)
        db.commit()
        db.refresh(acc)
        db.expunge(acc)
        return acc
    finally:
        db.close()


def list_extra_accounts(tg_user_id: int) -> list:
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(tg_user_id=tg_user_id).first()
        if not user:
            return []
        accs = db.query(ExtraAccount).filter_by(user_id=user.id).all()
        db.expunge_all()
        return accs
    finally:
        db.close()


def remove_extra_account(account_id: int, tg_user_id: int) -> bool:
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(tg_user_id=tg_user_id).first()
        if not user:
            return False
        acc = db.query(ExtraAccount).filter_by(id=account_id, user_id=user.id).first()
        if not acc:
            return False
        db.delete(acc)
        db.commit()
        return True
    finally:
        db.close()


def get_all_extra_accounts() -> list:
    db = SessionLocal()
    try:
        accs = db.query(ExtraAccount).all()
        db.expunge_all()
        return accs
    finally:
        db.close()


def add_extra_order_group(user_id: int, chat_id: int, title: str | None = None) -> bool:
    """Asosiy buyurtma guruhiga qo'shimcha ravishda buyurtma yuboriladigan guruh qo'shadi.
    Ko'pi bilan MAX_EXTRA_ORDER_GROUPS ta guruh qo'shish mumkin."""
    db = SessionLocal()
    try:
        count = db.query(ExtraOrderGroup).filter_by(user_id=user_id).count()
        if count >= MAX_EXTRA_ORDER_GROUPS:
            return False
        exists = db.query(ExtraOrderGroup).filter_by(user_id=user_id, chat_id=chat_id).first()
        if exists:
            return False
        db.add(ExtraOrderGroup(user_id=user_id, chat_id=chat_id, title=title))
        db.commit()
        return True
    finally:
        db.close()


def remove_extra_order_group(user_id: int, group_id: int) -> bool:
    db = SessionLocal()
    try:
        row = db.query(ExtraOrderGroup).filter_by(id=group_id, user_id=user_id).first()
        if not row:
            return False
        db.delete(row)
        db.commit()
        return True
    finally:
        db.close()


def list_extra_order_groups(user_id: int) -> list[ExtraOrderGroup]:
    db = SessionLocal()
    try:
        rows = db.query(ExtraOrderGroup).filter_by(user_id=user_id).all()
        db.expunge_all()
        return rows
    finally:
        db.close()


def get_extra_order_group_ids(user_id: int) -> list[int]:
    db = SessionLocal()
    try:
        rows = db.query(ExtraOrderGroup.chat_id).filter_by(user_id=user_id).all()
        return [row[0] for row in rows]
    finally:
        db.close()


def create_order_card(user_id: int, sender_tg_id: int | None, sender_name: str | None) -> int:
    """Yangi \"boy\" formatdagi buyurtma kartasi yozuvini yaratadi va uning id'sini qaytaradi."""
    db = SessionLocal()
    try:
        card = OrderCard(user_id=user_id, sender_tg_id=sender_tg_id, sender_name=sender_name)
        db.add(card)
        db.commit()
        return card.id
    finally:
        db.close()


def add_order_card_message(order_card_id: int, chat_id: int, message_id: int) -> None:
    db = SessionLocal()
    try:
        db.add(OrderCardMessage(order_card_id=order_card_id, chat_id=chat_id, message_id=message_id))
        db.commit()
    finally:
        db.close()


def get_order_card_messages(order_card_id: int) -> list[tuple[int, int]]:
    db = SessionLocal()
    try:
        rows = db.query(OrderCardMessage.chat_id, OrderCardMessage.message_id).filter_by(
            order_card_id=order_card_id
        ).all()
        return [(row[0], row[1]) for row in rows]
    finally:
        db.close()


def close_order_card(order_card_id: int, closed_by: str) -> bool:
    """Buyurtma kartasini yopilgan deb belgilaydi. Faqat hali ochiq bo'lsa True qaytaradi
    (ikki marta yopilishining oldini olish uchun)."""
    db = SessionLocal()
    try:
        card = db.query(OrderCard).filter_by(id=order_card_id).first()
        if not card or card.status == "closed":
            return False
        card.status = "closed"
        card.closed_at = datetime.utcnow()
        card.closed_by = closed_by
        db.commit()
        return True
    finally:
        db.close()


def is_order_card_open(order_card_id: int) -> bool:
    db = SessionLocal()
    try:
        card = db.query(OrderCard).filter_by(id=order_card_id).first()
        return bool(card and card.status != "closed")
    finally:
        db.close()


def log_order(user_id: int) -> None:
    db = SessionLocal()
    try:
        db.add(OrderLog(user_id=user_id))
        db.commit()
    finally:
        db.close()


def count_orders(user_id: int, since: datetime | None = None) -> int:
    db = SessionLocal()
    try:
        q = db.query(OrderLog).filter_by(user_id=user_id)
        if since:
            q = q.filter(OrderLog.created_at >= since)
        return q.count()
    finally:
        db.close()


def get_user_order_stats(user_id: int) -> dict:
    """Bitta foydalanuvchi uchun bugun/7 kunda/jami yuborilgan buyurtmalar sonini qaytaradi."""
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        today_start = datetime(now.year, now.month, now.day)
        week_start = now - timedelta(days=7)
        q = db.query(OrderLog).filter_by(user_id=user_id)
        return {
            "total": q.count(),
            "today": q.filter(OrderLog.created_at >= today_start).count(),
            "week": q.filter(OrderLog.created_at >= week_start).count(),
        }
    finally:
        db.close()


def log_ad_sent(user_id: int) -> None:
    db = SessionLocal()
    try:
        db.add(AdLog(user_id=user_id))
        db.commit()
    finally:
        db.close()


def get_user_ad_stats(user_id: int) -> dict:
    """Bitta foydalanuvchi uchun bugun/7 kunda/jami yuborilgan reklama xabarlari sonini qaytaradi."""
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        today_start = datetime(now.year, now.month, now.day)
        week_start = now - timedelta(days=7)
        q = db.query(AdLog).filter_by(user_id=user_id)
        return {
            "total": q.count(),
            "today": q.filter(AdLog.created_at >= today_start).count(),
            "week": q.filter(AdLog.created_at >= week_start).count(),
        }
    finally:
        db.close()


def get_global_ad_stats() -> dict:
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        today_start = datetime(now.year, now.month, now.day)
        week_start = now - timedelta(days=7)
        return {
            "total": db.query(AdLog).count(),
            "today": db.query(AdLog).filter(AdLog.created_at >= today_start).count(),
            "week": db.query(AdLog).filter(AdLog.created_at >= week_start).count(),
        }
    finally:
        db.close()


def get_global_order_stats() -> dict:
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        today_start = datetime(now.year, now.month, now.day)
        week_start = now - timedelta(days=7)
        return {
            "total": db.query(OrderLog).count(),
            "today": db.query(OrderLog).filter(OrderLog.created_at >= today_start).count(),
            "week": db.query(OrderLog).filter(OrderLog.created_at >= week_start).count(),
        }
    finally:
        db.close()


def get_top_order_users(limit: int = 5, since: datetime | None = None) -> list[tuple[int, int]]:
    """Eng ko'p buyurtma qabul qilgan foydalanuvchilarni (users.id, buyurtmalar soni)
    tartibida qaytaradi."""
    db = SessionLocal()
    try:
        q = db.query(OrderLog.user_id, func.count(OrderLog.id).label("cnt"))
        if since:
            q = q.filter(OrderLog.created_at >= since)
        rows = q.group_by(OrderLog.user_id).order_by(func.count(OrderLog.id).desc()).limit(limit).all()
        return [(row[0], row[1]) for row in rows]
    finally:
        db.close()


def list_extra_accounts_by_user_db_id(user_db_id: int) -> list:
    db = SessionLocal()
    try:
        accs = db.query(ExtraAccount).filter_by(user_id=user_db_id).all()
        db.expunge_all()
        return accs
    finally:
        db.close()
