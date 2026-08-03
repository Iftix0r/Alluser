from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker

from config import DATABASE_URL
from models import Base

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = scoped_session(sessionmaker(bind=engine))


def init_db():
    Base.metadata.create_all(engine)
