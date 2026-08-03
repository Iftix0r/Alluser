from database import SessionLocal
from models import ExcludedGroup, Keyword, User


def get_user(tg_user_id: int) -> User | None:
    db = SessionLocal()
    try:
        return db.query(User).filter_by(tg_user_id=tg_user_id).first()
    finally:
        db.close()


def get_or_create_user(tg_user_id: int) -> User:
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(tg_user_id=tg_user_id).first()
        if not user:
            user = User(tg_user_id=tg_user_id)
            db.add(user)
            db.commit()
            db.refresh(user)
        return user
    finally:
        db.close()


def save_session(tg_user_id: int, phone: str, session_string: str) -> None:
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(tg_user_id=tg_user_id).first()
        user.phone = phone
        user.session_string = session_string
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


def add_keyword(tg_user_id: int, word: str) -> bool:
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(tg_user_id=tg_user_id).first()
        if not user or not user.session_string:
            return False
        word = word.strip().lower()
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


def find_user_by_id(user_id: int) -> User | None:
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(id=user_id).first()
        if user:
            db.expunge(user)
        return user
    finally:
        db.close()
