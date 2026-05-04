from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings

engine = create_engine(
    settings.database_url,
    # SQLite 専用: マルチスレッドで同一接続を共有するための設定
    connect_args={"check_same_thread": False} if "sqlite" in settings.database_url else {},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI の Depends() で使う DB セッションジェネレーター"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
