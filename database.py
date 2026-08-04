from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import scoped_session, sessionmaker

from config import DATABASE_URL
from models import Base

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = scoped_session(sessionmaker(bind=engine))


def _migrate_add_missing_columns():
    """Base.metadata.create_all mavjud jadvallarga yangi ustun qo'shmaydi,
    shu sababli eski bazalarni qo'lda moslashtiramiz."""
    inspector = inspect(engine)
    if "users" not in inspector.get_table_names():
        return
    existing_columns = {col["name"] for col in inspector.get_columns("users")}
    if "assume_passenger_if_unmatched" not in existing_columns:
        with engine.begin() as conn:
            conn.execute(
                text("ALTER TABLE users ADD COLUMN assume_passenger_if_unmatched BOOLEAN DEFAULT 0 NOT NULL")
            )


def init_db():
    Base.metadata.create_all(engine)
    _migrate_add_missing_columns()
