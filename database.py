from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import scoped_session, sessionmaker

from config import DATABASE_URL
from models import Base

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = scoped_session(sessionmaker(bind=engine))


USERS_TABLE_MIGRATIONS = [
    ("assume_passenger_if_unmatched", "ALTER TABLE users ADD COLUMN assume_passenger_if_unmatched BOOLEAN DEFAULT 0 NOT NULL"),
    ("default_keywords_seeded", "ALTER TABLE users ADD COLUMN default_keywords_seeded BOOLEAN DEFAULT 0 NOT NULL"),
    ("greeting_text", "ALTER TABLE users ADD COLUMN greeting_text TEXT"),
    ("greeting_enabled", "ALTER TABLE users ADD COLUMN greeting_enabled BOOLEAN DEFAULT 1 NOT NULL"),
    ("customer_greeting_text", "ALTER TABLE users ADD COLUMN customer_greeting_text TEXT"),
    (
        "customer_greeting_enabled",
        "ALTER TABLE users ADD COLUMN customer_greeting_enabled BOOLEAN DEFAULT 0 NOT NULL",
    ),
    ("renewal_notice_sent_at", "ALTER TABLE users ADD COLUMN renewal_notice_sent_at DATETIME"),
    ("rich_order_format", "ALTER TABLE users ADD COLUMN rich_order_format BOOLEAN DEFAULT 0 NOT NULL"),
    ("whitelist_only_groups", "ALTER TABLE users ADD COLUMN whitelist_only_groups BOOLEAN DEFAULT 0 NOT NULL"),
    (
        "new_member_notifications_enabled",
        "ALTER TABLE users ADD COLUMN new_member_notifications_enabled BOOLEAN DEFAULT 1 NOT NULL",
    ),
]

# Ko'p ishlatiladigan filter va statistika so'rovlarini katta bazada ham tez saqlaydi.
# IF NOT EXISTS sababli har ishga tushishda xavfsiz tekshiriladi.
INDEX_MIGRATIONS = [
    "CREATE INDEX IF NOT EXISTS ix_keywords_user_id ON keywords (user_id)",
    "CREATE INDEX IF NOT EXISTS ix_driver_keywords_user_id ON driver_keywords (user_id)",
    "CREATE INDEX IF NOT EXISTS ix_excluded_groups_user_chat ON excluded_groups (user_id, chat_id)",
    "CREATE INDEX IF NOT EXISTS ix_order_logs_user_created ON order_logs (user_id, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_ad_logs_user_created ON ad_logs (user_id, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_order_card_messages_card ON order_card_messages (order_card_id)",
]

# customer_greeting_enabled ustuni bir necha marta standart qiymati o'zgargan:
# boshida o'chirilgan, keyin "hammada yoqilgan" qilingan, endi yana o'chirilganga qaytarildi
# (har bir foydalanuvchi panel orqali o'zi yoqadi) — mavjud qatorlar uchun bir martalik tuzatish.
_ONE_TIME_DATA_FIXES = [
    ("customer_greeting_enabled_default_on", "UPDATE users SET customer_greeting_enabled = 1"),
    ("customer_greeting_enabled_default_off_again", "UPDATE users SET customer_greeting_enabled = 0"),
]


def _migrate_add_missing_columns():
    """Base.metadata.create_all mavjud jadvallarga yangi ustun qo'shmaydi,
    shu sababli eski bazalarni qo'lda moslashtiramiz."""
    inspector = inspect(engine)
    if "users" not in inspector.get_table_names():
        return
    existing_columns = {col["name"] for col in inspector.get_columns("users")}
    with engine.begin() as conn:
        for column_name, ddl in USERS_TABLE_MIGRATIONS:
            if column_name not in existing_columns:
                conn.execute(text(ddl))


def _apply_one_time_data_fixes():
    """Har biri faqat bir marta ishga tushadigan ma'lumot tuzatishlari (masalan,
    ustun standart qiymati keyinchalik o'zgartirilganda, eski qatorlarni yangilash)."""
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE IF NOT EXISTS applied_data_fixes (name TEXT PRIMARY KEY)"))
        applied = {row[0] for row in conn.execute(text("SELECT name FROM applied_data_fixes"))}
        for name, sql in _ONE_TIME_DATA_FIXES:
            if name in applied:
                continue
            conn.execute(text(sql))
            conn.execute(text("INSERT INTO applied_data_fixes (name) VALUES (:name)"), {"name": name})


def _create_performance_indexes():
    with engine.begin() as conn:
        for sql in INDEX_MIGRATIONS:
            conn.execute(text(sql))


def init_db():
    Base.metadata.create_all(engine)
    _migrate_add_missing_columns()
    _apply_one_time_data_fixes()
    _create_performance_indexes()
