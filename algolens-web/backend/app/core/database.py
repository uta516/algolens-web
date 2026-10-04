from sqlalchemy import create_engine, inspect, text
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


def add_missing_columns(bind=engine) -> list[str]:
    """create_all は既存テーブルに列を足さないため、モデルにあって DB にない列を ALTER TABLE で足す。

    足すのは NULL 可の列だけ（既存の行は NULL になる）。足した "テーブル.列" の一覧を返す。
    """
    added = []
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())
    with bind.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue
            present = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in present or not column.nullable:
                    continue
                col_type = column.type.compile(dialect=bind.dialect)
                conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {col_type}'))
                added.append(f"{table.name}.{column.name}")
    return added


def get_db():
    """FastAPI の Depends() で使う DB セッションジェネレーター"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
